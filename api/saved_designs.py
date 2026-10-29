"""Immutable saved Designs; durable authority is separate from Capture photos."""
from contextlib import contextmanager
from hashlib import sha256
from uuid import UUID
from fastapi import APIRouter, Header, Query, Response
from .capture_auth import CaptureError, SupabaseAuth
from .models import ContractModel
from .saved_models import (SaveRequest, SavedSnapshotV1, SavedCapture, SavedReceipt, SavedList,
                           SavedRestore, snapshot_bytes, restore_snapshot)
from .saved_repository import configured_saved_repository
from .swaps import SavedSessionBinding, SAVED_SESSION_ACCESS


class SavedConfig(ContractModel):
    ready: bool
    detail: str
    authUrl: str | None = None
    publishableKey: str | None = None


class SavedDesignService:
    def __init__(self, source, sessions, captures, *, repository=None, auth=None):
        self.source, self.sessions, self.captures = source, sessions, captures
        self.repository, self.auth = repository, auth

    def dependencies(self, authorization):
        repository = self.repository or configured_saved_repository()
        auth = self.auth or SupabaseAuth(repository.settings, repository.client)
        return repository, auth.verify(authorization)

    def revalidate(self, repository, principal, authorization):
        if (self.auth or SupabaseAuth(repository.settings, repository.client)).verify(authorization) != principal:
            raise CaptureError('authentication-required', 'Refresh your account before continuing.', 401)

    @staticmethod
    def active(row):
        if row.get('status') == 'deleted':
            raise CaptureError('deleted', 'This saved Design was deleted. Its content has been erased.', 410)
        if row.get('status') != 'active':
            raise CaptureError('not-found', 'This saved Design is unavailable.', 404)
        return row

    def verify_receipt(self, row):
        self.active(row)
        try:
            snapshot = SavedSnapshotV1.model_validate(row['snapshot'])
            digest = sha256(snapshot_bytes(snapshot)).hexdigest()
            fingerprint = sha256(f"{row['requestHash']}:{digest}:{snapshot.schemaVersion}:{snapshot.catalogueVersion}".encode()).hexdigest()
            if digest != row['digest'] or fingerprint != row['fingerprint']:
                raise ValueError('saved fingerprint mismatch')
        except (ValueError, KeyError, TypeError):
            raise CaptureError('corrupt-snapshot', 'The saved receipt could not be validated.', 422) from None
        return SavedReceipt(id=row['id'], createdAt=row['createdAt'])

    @contextmanager
    def session_access(self, session_id, authorization):
        binding = self.sessions.saved_binding(session_id)
        if binding is None:
            yield
            return
        owner_matched = False
        try:
            repository, principal = self.dependencies(authorization)
            if principal.owner_id != binding.owner_id:
                raise CaptureError('not-found', 'This session is unavailable.', 404)
            owner_matched = True
            def guard():
                row = self.active(repository.user(principal, 'read', saved_id=binding.saved_id))
                if row['digest'] != binding.digest or row['snapshot'].get('catalogueVersion') != binding.catalogue_version:
                    raise CaptureError('not-found', 'This session is unavailable.', 404)
                self.verify_receipt(row)
                self.revalidate(repository, principal, authorization)
            guard()
            access = SAVED_SESSION_ACCESS.set(binding)
            try:
                yield
                guard()
            finally:
                SAVED_SESSION_ACCESS.reset(access)
        except CaptureError:
            if owner_matched:
                self.sessions.revoke(session_id)
            raise CaptureError('not-found', 'This session is unavailable.', 404) from None

    def save(self, body, authorization):
        repository, principal = self.dependencies(authorization)
        existing = repository.user(principal, 'replay', key=body.idempotencyKey, identity=body.identity_hash())
        if existing.get('status') != 'missing':
            return self.verify_receipt(existing)
        with self.session_access(body.sessionId, authorization), self.captures.session_access(body.sessionId, authorization) as captured_source:
            with self.sessions.save_source(body.sessionId, body.expectedVersion) as (design, room_type, clearance, source_expiry):
                binding = self.sessions.saved_binding(body.sessionId)
                source = captured_source or ({'kind': 'saved', 'id': binding.saved_id, 'digest': binding.digest} if binding else {'kind': 'fixture'})
                source = {**source, 'sessionExpiresAt': source_expiry}
                capture = SavedCapture(id=source['captureId'], confirmedRevision=source['revision'], roomHash=source['roomHash']) if source['kind'] == 'capture' else None
                if binding:
                    original = self.active(repository.user(principal, 'read', saved_id=binding.saved_id))
                    capture = SavedSnapshotV1.model_validate(original['snapshot']).capture
                snapshot = SavedSnapshotV1(catalogueVersion=design.swap.catalogueVersion, roomType=room_type,
                    clearanceWidthM=clearance, room=design.room, intents=design.intents, placements=design.placements,
                    search=design.search, zones=design.zones, arrangementHistory=design.arrangementHistory, capture=capture)
                data = snapshot_bytes(snapshot)
                digest = sha256(data).hexdigest()
                # Validate the complete field map before durable publication.
                restore_snapshot(self.source, snapshot.model_dump(mode='json'), digest)
                self.revalidate(repository, principal, authorization)
                if self.source.version != snapshot.catalogueVersion:
                    raise CaptureError('catalogue-changed', 'The Catalogue changed. Reopen or generate a current Design before saving.', 422)
                row = repository.commit(principal, body, data, digest, source)
        return self.verify_receipt(row)

    def restore(self, saved_id, authorization):
        repository, principal = self.dependencies(authorization)
        row = self.active(repository.user(principal, 'read', saved_id=saved_id))
        snapshot, design = restore_snapshot(self.source, row['snapshot'], row['digest'])
        self.verify_receipt(row)
        binding = SavedSessionBinding(principal.owner_id, saved_id, row['digest'], snapshot.catalogueVersion)
        managed = self.sessions.register(design, snapshot.roomType, saved_binding=binding)
        session_id = managed.swap.sessionId if managed.swap.status == 'available' else None
        try:
            if session_id is None:
                raise CaptureError('session-unavailable', 'Reopening the Design is temporarily unavailable. Retry shortly.', 503)
            self.revalidate(repository, principal, authorization)
            current = self.active(repository.user(principal, 'read', saved_id=saved_id))
            if current['digest'] != row['digest']:
                raise CaptureError('not-found', 'This saved Design is unavailable.', 404)
            return SavedRestore(id=saved_id, capture=snapshot.capture, roomType=snapshot.roomType, design=managed)
        except BaseException:
            if session_id: self.sessions.revoke(session_id)
            raise

    def router(self):
        router = APIRouter(prefix='/api/saved-designs')

        @router.get('/config', response_model=SavedConfig)
        def config():
            try:
                repository = self.repository or configured_saved_repository()
                settings = repository.settings
                return SavedConfig(ready=True, detail='Saved Designs remain until you delete them. Photos still expire after 24 hours.', authUrl=settings.url, publishableKey=settings.public_key)
            except CaptureError:
                return SavedConfig(ready=False, detail='Saving Designs is unavailable right now.')

        @router.post('', response_model=SavedReceipt)
        def save(body: SaveRequest, authorization: str | None = Header(default=None)):
            return self.save(body, authorization)

        @router.get('', response_model=SavedList)
        def listing(cursor: str | None = Query(default=None, max_length=256), authorization: str | None = Header(default=None)):
            repository, principal = self.dependencies(authorization)
            return SavedList.model_validate(repository.user(principal, 'list', cursor=cursor))

        @router.get('/{saved_id}', response_model=SavedRestore)
        def restore(saved_id: UUID, authorization: str | None = Header(default=None)):
            return self.restore(str(saved_id), authorization)

        @router.delete('/{saved_id}', status_code=204)
        def delete(saved_id: UUID, authorization: str | None = Header(default=None)):
            repository, principal = self.dependencies(authorization)
            repository.user(principal, 'delete', saved_id=str(saved_id))
            return Response(status_code=204)

        return router
