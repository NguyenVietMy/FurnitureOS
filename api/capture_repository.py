"""Caller-JWT reads/RPCs and a narrow privileged Capture authority; never a mock fallback."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from time import monotonic
from urllib.parse import quote
from uuid import uuid4
import httpx
from pydantic import ValidationError
from .capture_auth import CaptureError, CapturePrincipal, SupabaseAuth, SupabaseSettings
from .capture_models import CaptureView

class SupabaseCaptureRepository:
    def __init__(self, settings: SupabaseSettings, client: httpx.Client):
        self.settings,self.client = settings,client

    def _request(self, method, path, *, token, payload=None, data=None, media=None, maximum=262144):
        headers = {"apikey":self.settings.secret_key if token==self.settings.secret_key else self.settings.public_key,
                   "Authorization":"Bearer "+token}
        if media:
            headers["Content-Type"] = media
        started = monotonic()
        try:
            with self.client.stream(method,self.settings.url+path,headers=headers,json=payload,content=data,
                                    timeout=5,follow_redirects=False) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body)>maximum or monotonic()-started>5:
                        raise ValueError("bounded response exceeded")
                if response.status_code >= 300:
                    error = {}
                    try:
                        error = json.loads(body)
                    except ValueError:
                        pass
                    message = error.get("message","") if isinstance(error,dict) else ""
                    if not isinstance(message,str):message = ""
                    known = ("not-found","stale-capture","busy","quota","lease-expired","attempt-limit")
                    code = next((item for item in known if item in message),"service-unavailable")
                    raise CaptureError(code,{"not-found":"This Capture is unavailable.","stale-capture":"The Capture changed. Reload before continuing.",
                        "busy":"Another operation is active. Retry shortly.","quota":"Capture quota reached. Delete a Capture or retry later.",
                        "lease-expired":"This operation expired. Reload and retry.","attempt-limit":"The analysis attempt limit was reached."}.get(code,"The Capture service is unavailable."),
                        404 if code=="not-found" else 409 if code in known else 503)
                return bytes(body)
        except CaptureError:
            raise
        except (httpx.HTTPError,ValueError):
            raise CaptureError("service-unavailable","The Capture service is unavailable.",503) from None

    def user(self, principal, action, capture_id=None, revision=None, payload=None):
        value = self._request("POST","/rest/v1/rpc/capture_user_operation",token=principal.token,
            payload={"p_action":action,"p_capture":capture_id,"p_revision":revision,"p_payload":payload or {}})
        return json.loads(value)

    def authority(self, principal, action, capture_id, revision, lease, payload=None):
        value = self._request("POST","/rest/v1/rpc/capture_authority",token=self.settings.secret_key,
            payload={"p_action":action,"p_owner":principal.owner_id,"p_capture":capture_id,
                     "p_revision":revision,"p_lease":lease,"p_payload":payload or {}})
        return json.loads(value)

    def read(self, principal: CapturePrincipal, capture_id: str) -> CaptureView:
        # The snapshot RPC uses the forwarded JWT and exact owned active row.
        try: return CaptureView.model_validate(self.user(principal,"read",capture_id))
        except ValidationError: raise CaptureError("invalid-room","Stored Capture data needs Room review.",422) from None

    @contextmanager
    def lease(self, principal, capture_id, revision, kind, *, seconds=120):
        response = self.user(principal,"lease",capture_id,revision,{"kind":kind,"seconds":seconds})
        token = response["lease"]
        try:
            yield token
        finally:
            try:
                self.user(principal,"release",capture_id,revision,{"lease":token})
            except CaptureError:
                pass # A failed release cannot resurrect or extend a bounded persisted lease.

    def assert_lease(self, principal, capture_id, revision, lease, room_hash=None):
        self.user(principal,"assert",capture_id,revision,{"lease":lease,"roomHash":room_hash})

    def _key(self, principal,capture_id,photo_id):
        from uuid import UUID
        return "/".join(str(UUID(v)) for v in (principal.owner_id,capture_id,photo_id))+".jpg"

    def upload(self, principal,capture_id,photo_id,data):
        self._request("POST","/storage/v1/object/captures/"+quote(self._key(principal,capture_id,photo_id),safe="/"),
                      token=self.settings.secret_key,data=data,media="image/jpeg",maximum=32768)

    def _photo_guard(self, principal, capture_id, photo_id, revision, lease, expected_sha256):
        current = SupabaseAuth(self.settings,self.client).verify("Bearer "+principal.token)
        if current.owner_id != principal.owner_id:
            raise ValueError("identity changed")
        capture = self.read(principal,capture_id)
        photo = next((p for p in capture.photos if p.id==photo_id and p.state=="accepted"),None)
        if (capture.id!=capture_id or capture.revision!=revision or capture.state=="deleting"
                or capture.expiresAt<=datetime.now(timezone.utc) or photo is None
                or photo.sha256!=expected_sha256 or not 0<photo.canonicalBytes<=400000):
            raise ValueError("photo authority changed")
        self.assert_lease(principal,capture_id,revision,lease)
        return photo

    def download(self, principal,capture_id,photo_id,*,revision,lease,expected_sha256):
        """One leased, caller-authorized byte fetch; never a privileged metadata lookup."""
        try:
            target = httpx.URL(self.settings.url)
            if (target.scheme!="https" or not target.host or target.userinfo or target.path!="/"
                    or target.query or target.fragment or target.port not in (None,443)):
                raise ValueError("project HTTPS root required")
            if (not isinstance(expected_sha256,str) or len(expected_sha256)!=64
                    or any(c not in "0123456789abcdef" for c in expected_sha256)):
                raise ValueError("accepted hash required")
            key = self._key(principal,capture_id,photo_id)
            photo = self._photo_guard(principal,capture_id,photo_id,revision,lease,expected_sha256)
            # Caller-provided URLs/keys never reach this transport. The nonce is internal
            # and fresh so a previously cached Storage response cannot authorize a read.
            data = self._request("GET","/storage/v1/object/captures/"+quote(key,safe="/")+
                "?cacheNonce="+str(uuid4()),token=self.settings.secret_key,maximum=400000)
            if len(data)!=photo.canonicalBytes or sha256(data).hexdigest()!=expected_sha256:
                raise ValueError("canonical bytes changed")
            self._photo_guard(principal,capture_id,photo_id,revision,lease,expected_sha256)
            return data
        except (CaptureError,ValueError,TypeError,httpx.InvalidURL):
            raise CaptureError("not-found","This photo is unavailable.",404) from None

def configured_repository():
    settings = SupabaseSettings.from_environment()
    client = httpx.Client(timeout=5,follow_redirects=False,trust_env=False)
    return SupabaseCaptureRepository(settings,client)
