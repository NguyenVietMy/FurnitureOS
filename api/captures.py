"""Authenticated Capture HTTP boundary; construction is offline and fail-closed."""
from __future__ import annotations
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID
from fastapi import APIRouter, Header, Request, Query
from fastapi.responses import Response
from .capture_auth import CaptureError, SupabaseAuth
from .capture_repository import configured_repository
from .capture_models import (CaptureConfig,CaptureView,CreateCapture,DraftUpdate,PhotoReservation,
    PhotoAssociation,CaptureRevision,CaptureReview,CaptureGenerationRequest,CaptureGenerationResult,
    CaptureBlocked,CaptureGenerated,CalibrationRecord,CaptureDeletionStatus)
from .capture_files import normalize_photo
from .capture_reference import ReferenceRequest,ReferenceResult,calibrate
from .capture_room import validate_capture_rectangle,room_hash,computational_support
from .capture_vision import analyze_photo
from .live_generation import LiveGenerationRequest,generate_bedroom_for_room
from .provider import provider_configuration_available
from .swaps import CapturedSessionBinding,CAPTURE_SESSION_ACCESS

class CaptureService:
    def __init__(self, source, sessions, *, repository=None, auth=None, vision_provider=None, generation_provider=None):
        self.source,self.sessions=source,sessions
        self.repository,self.auth=repository,auth
        self.vision_provider,self.generation_provider=vision_provider,generation_provider

    def dependencies(self, authorization):
        repository=self.repository or configured_repository()
        auth=self.auth or SupabaseAuth(repository.settings,repository.client)
        return repository,auth.verify(authorization)

    def config(self):
        try:
            repository=self.repository or configured_repository()
            return CaptureConfig(storageReady=True,analysisAvailable=self.vision_provider is not None or provider_configuration_available(),
                generationAvailable=self.generation_provider is not None or provider_configuration_available(),
                detail="Private canonical photos and Room drafts expire 24 hours after creation. Deletion stays pending until stored bytes are removed.",
                authUrl=repository.settings.url,publishableKey=repository.settings.public_key)
        except CaptureError:
            return CaptureConfig(storageReady=False,analysisAvailable=False,generationAvailable=False,
                detail="Private photo uploads are unavailable right now. Explore Room preview or try Capture again later.")

    def read(self, repository, principal, capture_id, expected=None):
        capture=repository.read(principal,capture_id)
        if capture.state=="deleting" or capture.expiresAt<=datetime.now(timezone.utc):
            raise CaptureError("not-found","This Capture is unavailable.",404)
        if expected is not None and capture.revision!=expected:
            raise CaptureError("stale-capture","The Capture changed. Reload before continuing.")
        return capture

    @contextmanager
    def session_access(self, session_id, authorization):
        binding=self.sessions.captured_binding(session_id)
        if binding is None:
            yield
            return
        owner_matched=False
        try:
            repository,principal=self.dependencies(authorization)
            if principal.owner_id!=binding.owner_id:
                raise CaptureError("not-found","This session is unavailable.",404)
            owner_matched=True
            capture=self.read(repository,principal,binding.capture_id,binding.confirmed_revision)
            if capture.state!="confirmed" or capture.roomHash!=binding.room_hash:
                raise CaptureError("not-found","This session is unavailable.",404)
            with repository.lease(principal,capture.id,capture.revision,"session") as lease:
                access=CAPTURE_SESSION_ACCESS.set(binding)
                try:
                    yield
                    repository.assert_lease(principal,capture.id,capture.revision,lease,binding.room_hash)
                finally:
                    CAPTURE_SESSION_ACCESS.reset(access)
        except CaptureError as failure:
            if owner_matched and failure.code in ("not-found","stale-capture","lease-expired"):
                self.sessions.revoke_capture(binding.capture_id)
            raise CaptureError("not-found","This session is unavailable.",404) from None

    def router(self):
        router=APIRouter()
        @router.get("/api/captures/config",response_model=CaptureConfig)
        def config(): return self.config()

        @router.post("/api/captures",response_model=CaptureView)
        def create(body:CreateCapture,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            return CaptureView.model_validate(repository.user(principal,"create",payload=body.model_dump(mode="json")))

        @router.get("/api/captures/{capture_id}",response_model=CaptureView)
        def read(capture_id:UUID,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            return self.read(repository,principal,str(capture_id))

        @router.patch("/api/captures/{capture_id}/draft",response_model=CaptureView)
        def draft(capture_id:UUID,body:DraftUpdate,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            self.read(repository,principal,str(capture_id),body.expectedRevision)
            updated=repository.user(principal,"draft",str(capture_id),body.expectedRevision,{"draft":body.draft.model_dump(mode="json")})
            self.sessions.revoke_capture(str(capture_id))
            return CaptureView.model_validate(updated)

        @router.delete("/api/captures/{capture_id}",response_model=CaptureView)
        def delete(capture_id:UUID,body:CaptureRevision,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            self.read(repository,principal,str(capture_id),body.expectedRevision)
            updated=repository.user(principal,"delete",str(capture_id),body.expectedRevision)
            self.sessions.revoke_capture(str(capture_id))
            return CaptureView.model_validate(updated)

        @router.get("/api/captures/{capture_id}/deletion",response_model=CaptureDeletionStatus)
        def deletion(capture_id:UUID,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            status=repository.user(principal,"delete-status",str(capture_id))
            if status.get("state")!="deleting" or status.get("id")!=str(capture_id):
                raise CaptureError("not-found","This Capture is unavailable.",404)
            return CaptureDeletionStatus(id=str(capture_id),cleanupStatus=status.get("cleanupStatus","pending"))

        @router.post("/api/captures/{capture_id}/photos",response_model=CaptureView)
        def reserve(capture_id:UUID,body:PhotoReservation,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            self.read(repository,principal,str(capture_id),body.expectedRevision)
            result=repository.user(principal,"reserve",str(capture_id),body.expectedRevision,body.model_dump(mode="json"))
            self.sessions.revoke_capture(str(capture_id))
            return CaptureView.model_validate(result)

        @router.patch("/api/captures/{capture_id}/photos/{photo_id}",response_model=CaptureView)
        def associate(capture_id:UUID,photo_id:UUID,body:PhotoAssociation,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            self.read(repository,principal,str(capture_id),body.expectedRevision)
            result=repository.user(principal,"associate",str(capture_id),body.expectedRevision,
                {**body.model_dump(mode="json"),"photoId":str(photo_id)})
            self.sessions.revoke_capture(str(capture_id))
            return CaptureView.model_validate(result)

        @router.delete("/api/captures/{capture_id}/photos/{photo_id}",response_model=CaptureView)
        def remove_photo(capture_id:UUID,photo_id:UUID,body:CaptureRevision,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            self.read(repository,principal,str(capture_id),body.expectedRevision)
            result=repository.user(principal,"remove-photo",str(capture_id),body.expectedRevision,{"photoId":str(photo_id)})
            self.sessions.revoke_capture(str(capture_id))
            return CaptureView.model_validate(result)

        @router.post("/api/captures/{capture_id}/photos/{photo_id}/content",response_model=CaptureView)
        async def content(capture_id:UUID,photo_id:UUID,request:Request,expectedRevision:int=Query(ge=1),
                          authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            cid,pid=str(capture_id),str(photo_id)
            capture=self.read(repository,principal,cid,expectedRevision)
            photo=next((p for p in capture.photos if p.id==pid and p.state=="reserved"),None)
            if photo is None: raise CaptureError("not-found","This photo reservation is unavailable.",404)
            declared=request.headers.get("content-length")
            if declared and (not declared.isdigit() or int(declared)>min(4_000_000,photo.declaredBytes)):
                raise CaptureError("file-size","Each photo must fit its reserved size and 4 MB limit.",413)
            media=request.headers.get("content-type","").split(";")[0]
            if media not in ("image/jpeg","image/png"):
                raise CaptureError("file-type","Choose JPEG or PNG.",415)
            with repository.lease(principal,cid,expectedRevision,"upload") as lease:
                async def collect():
                    data=bytearray()
                    async for chunk in request.stream():
                        data.extend(chunk)
                        if len(data)>min(4_000_000,photo.declaredBytes):
                            raise CaptureError("file-size","Photo exceeds its reserved size.",413)
                    return bytes(data)
                try:
                    async with asyncio.timeout(30):
                        raw=await collect()
                        canonical=await asyncio.to_thread(normalize_photo,raw,media)
                        repository.assert_lease(principal,cid,expectedRevision,lease)
                        repository.upload(principal,cid,pid,canonical.data)
                        result=repository.authority(principal,"finalize-photo",cid,expectedRevision,lease,{
                            "photoId":pid,"inputBytes":canonical.input_bytes,"canonicalBytes":len(canonical.data),
                            "sha256":canonical.sha256,"widthPx":canonical.width,"heightPx":canonical.height})
                        return CaptureView.model_validate(result)
                except (Exception,asyncio.CancelledError) as failure:
                    try: repository.authority(principal,"upload-failed",cid,expectedRevision,lease,{"photoId":pid})
                    except CaptureError: pass
                    if isinstance(failure,TimeoutError): raise CaptureError("upload-timeout","Photo upload expired. Retry explicitly.",408) from None
                    raise

        @router.get("/api/captures/{capture_id}/photos/{photo_id}/content")
        def photo(capture_id:UUID,photo_id:UUID,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            capture=self.read(repository,principal,str(capture_id))
            accepted=next((p for p in capture.photos if p.id==str(photo_id) and p.state=="accepted"),None)
            if accepted is None: raise CaptureError("not-found","This photo is unavailable.",404)
            with repository.lease(principal,capture.id,capture.revision,"photo-read") as lease:
                data=repository.download(principal,capture.id,accepted.id,revision=capture.revision,
                    lease=lease,expected_sha256=accepted.sha256)
                if sha256(data).hexdigest()!=accepted.sha256:
                    raise CaptureError("photo-unavailable","This photo no longer matches its accepted content.",409)
                try: repository.assert_lease(principal,capture.id,capture.revision,lease)
                except CaptureError: raise CaptureError("not-found","This photo is unavailable.",404) from None
                return Response(data,media_type="image/jpeg",headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

        @router.post("/api/captures/{capture_id}/photos/{photo_id}/analyze",response_model=CaptureView)
        def analyze(capture_id:UUID,photo_id:UUID,body:CaptureRevision,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            capture=self.read(repository,principal,str(capture_id),body.expectedRevision)
            selected=next((p for p in capture.photos if p.id==str(photo_id) and p.state=="accepted"),None)
            if selected is None: raise CaptureError("not-found","This photo is unavailable.",404)
            with repository.lease(principal,capture.id,capture.revision,"vision") as lease:
                repository.authority(principal,"begin-analysis",capture.id,capture.revision,lease,{"photoId":selected.id})
                try:
                    data=repository.download(principal,capture.id,selected.id,revision=capture.revision,
                        lease=lease,expected_sha256=selected.sha256)
                    if sha256(data).hexdigest()!=selected.sha256: raise CaptureError("photo-unavailable","Accepted photo changed.")
                    try: repository.assert_lease(principal,capture.id,capture.revision,lease)
                    except CaptureError: raise CaptureError("not-found","This photo is unavailable.",404) from None
                    semantics=analyze_photo(data,selected.primaryWallId,self.vision_provider)
                    result=repository.authority(principal,"semantics",capture.id,capture.revision,lease,
                        {"photoId":selected.id,"sha256":selected.sha256,"semantics":semantics.model_dump(mode="json")})
                    self.sessions.revoke_capture(capture.id)
                    return CaptureView.model_validate(result)
                except Exception:
                    try: repository.authority(principal,"analysis-failed",capture.id,capture.revision,lease,{"photoId":selected.id})
                    except CaptureError: pass
                    raise

        @router.post("/api/captures/{capture_id}/calibrate",response_model=ReferenceResult)
        def reference(capture_id:UUID,body:ReferenceRequest,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            capture=self.read(repository,principal,str(capture_id),body.expectedRevision)
            photo=next((p for p in capture.photos if p.id==body.photoId and p.sha256==body.photoHash and p.state=="accepted"),None)
            if photo is None: raise CaptureError("stale-calibration","Choose a current accepted canonical photo.")
            with repository.lease(principal,capture.id,capture.revision,"calibration") as lease:
                result=calibrate(body,photo.widthPx,photo.heightPx)
                record=CalibrationRecord(request=body,result=result)
                repository.authority(principal,"calibration",capture.id,capture.revision,lease,record.model_dump(mode="json"))
                return result

        @router.post("/api/captures/{capture_id}/confirm",response_model=CaptureReview)
        def confirm(capture_id:UUID,body:CaptureRevision,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            capture=self.read(repository,principal,str(capture_id),body.expectedRevision)
            with repository.lease(principal,capture.id,capture.revision,"confirm") as lease:
                room,issues=validate_capture_rectangle(capture)
                if issues: return CaptureReview(status="review",capture=capture,issues=issues)
                updated=repository.authority(principal,"confirm",capture.id,capture.revision,lease,
                                             {"room":room.model_dump(mode="json"),"roomHash":room_hash(room)})
                return CaptureReview(status="confirmed",capture=CaptureView.model_validate(updated),room=room)

        @router.post("/api/captures/{capture_id}/generate",response_model=CaptureGenerationResult)
        def generate(capture_id:UUID,body:CaptureGenerationRequest,authorization:str|None=Header(default=None)):
            repository,principal=self.dependencies(authorization)
            capture=self.read(repository,principal,str(capture_id),body.expectedRevision)
            room,issues=validate_capture_rectangle(capture)
            if issues: return CaptureGenerationResult(root=CaptureBlocked(code="invalid-room",detail="Review required Room details.",issues=issues))
            if capture.state!="confirmed" or capture.confirmedRevision!=capture.revision or capture.roomHash!=room_hash(room) or capture.room!=room:
                return CaptureGenerationResult(root=CaptureBlocked(code="confirmation-required",detail="Confirm the current Room before generation."))
            unsupported=computational_support(room)
            if unsupported: return CaptureGenerationResult(root=CaptureBlocked(code="room-computation-unsupported",detail=unsupported))
            with repository.lease(principal,capture.id,capture.revision,"generation",seconds=300) as lease:
                generated=generate_bedroom_for_room(self.source,LiveGenerationRequest(roomType="bedroom",referenceId=body.referenceId),
                                                   room=room,private_room=True,provider=self.generation_provider)
                repository.assert_lease(principal,capture.id,capture.revision,lease,capture.roomHash)
                if generated.status=="solved":
                    binding=CapturedSessionBinding(principal.owner_id,capture.id,capture.revision,capture.roomHash,capture.expiresAt.timestamp())
                    generated=generated.model_copy(update={"design":self.sessions.register(generated.design,"bedroom",binding=binding)},deep=True)
                try: repository.assert_lease(principal,capture.id,capture.revision,lease,capture.roomHash)
                except CaptureError:
                    self.sessions.revoke_capture(capture.id)
                    raise
                return CaptureGenerationResult(root=CaptureGenerated(captureId=capture.id,confirmedRevision=capture.revision,roomHash=capture.roomHash,result=generated))
        return router


class CaptureBodyLimit:
    """Pure ASGI guard before JSON buffering, including chunked requests."""
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope["type"]!="http" or not scope.get("path","").startswith("/api/captures"):
            return await self.app(scope,receive,send)
        headers=dict(scope.get("headers",[]))
        image=scope.get("path","").endswith("/content")
        cap=4_000_000 if image else 32768
        declared=headers.get(b"content-length",b"")
        from fastapi.responses import JSONResponse
        if declared and (not declared.isdigit() or int(declared)>cap):
            return await JSONResponse({"detail":{"code":"body-limit","detail":"Request body exceeds its supported limit."}},status_code=413)(scope,receive,send)
        size=0
        async def bounded_receive():
            nonlocal size
            message=await receive()
            size+=len(message.get("body",b""))
            if size>cap: raise CaptureError("body-limit","Request body exceeds its supported limit.",413)
            return message
        await self.app(scope,bounded_receive,send)
