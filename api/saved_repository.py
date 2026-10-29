"""Caller-JWT saved reads/deletes and one narrow service-only commit RPC."""
import json
import httpx
from .capture_repository import SupabaseCaptureRepository
from .capture_auth import CaptureError, SupabaseSettings


class SupabaseSavedRepository(SupabaseCaptureRepository):
    def user(self, principal, action, *, saved_id=None, key=None, identity=None, cursor=None):
        body = self._request('POST', '/rest/v1/rpc/saved_design_user', token=principal.token,
            payload={'p_action': action, 'p_id': saved_id, 'p_key': key, 'p_identity': identity, 'p_cursor': cursor}, maximum=600000)
        return json.loads(body)

    def commit(self, principal, request, snapshot, digest, source):
        body = self._request('POST', '/rest/v1/rpc/saved_design_commit', token=self.settings.secret_key,
            payload={'p_owner': principal.owner_id, 'p_anonymous': principal.is_anonymous,
                     'p_key': request.idempotencyKey, 'p_identity': request.identity_hash(),
                     'p_session': request.sessionId, 'p_version': request.expectedVersion,
                     'p_canonical': snapshot.decode('utf-8'), 'p_digest': digest, 'p_source': source}, maximum=600000)
        return json.loads(body)


def configured_saved_repository():
    settings = SupabaseSettings.from_environment(saved=True)
    return SupabaseSavedRepository(settings, httpx.Client(timeout=5, follow_redirects=False, trust_env=False))
