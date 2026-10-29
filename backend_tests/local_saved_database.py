"""Real disposable PostgreSQL behind controlled external Auth/REST/Storage.

No application service/repository/session implementation is replaced. SQL is
executed under the production caller/service roles through the public RPCs.
"""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import subprocess
from uuid import UUID, uuid4
import httpx
import pytest
from api.capture_auth import SupabaseSettings
from api.capture_repository import SupabaseCaptureRepository

PSQL = Path('C:/Program Files/PostgreSQL/17/bin/psql.exe')


def sql(statement, *, check=True):
    port = os.environ.get('LOCAL_TEST_POSTGRES_PORT')
    if not port:
        pytest.skip('requires explicitly configured disposable local PostgreSQL')
    result = subprocess.run([str(PSQL), '-X', '-qAt', '-h', '127.0.0.1', '-p', port, '-U', 'postgres', '-d', 'ticket15', '-v', 'ON_ERROR_STOP=1'], input=statement, text=True, encoding='utf-8', capture_output=True, timeout=20)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


class LocalSupabase:
    @property
    def saved_repository(self):
        from api.saved_repository import SupabaseSavedRepository
        return SupabaseSavedRepository(self.settings, self.client)

    def __init__(self):
        self.profiles = {}
        self.objects = {}
        self.after_rpc = None
        self.settings = SupabaseSettings('https://local-saved.invalid', 'local-public', 'local-service')
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))
        self.capture_repository = SupabaseCaptureRepository(self.settings, self.client)
        self.owner = self.add_owner()

    def add_owner(self, anonymous=True):
        owner = str(uuid4())
        sql(f'insert into auth.users(id,is_anonymous) values({literal(owner)},{str(anonymous).lower()});')
        self.profiles[owner] = anonymous
        return owner

    def token(self, owner=None):
        owner = owner or self.owner
        payload = base64.urlsafe_b64encode(json.dumps({'sub': owner, 'is_anonymous': self.profiles[owner]}).encode()).decode().rstrip('=')
        return 'local.' + payload + '.controlled'

    def headers(self, owner=None):
        return {'Authorization': 'Bearer ' + self.token(owner)}

    def handle(self, request):
        token = request.headers.get('authorization', '')[7:]
        service = token == self.settings.secret_key
        claims = {}
        try:
            if not service:
                claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
                UUID(claims['sub'])
                if claims['sub'] not in self.profiles: raise ValueError()
        except (ValueError, KeyError, IndexError):
            return httpx.Response(401, json={})
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': claims['sub'], 'is_anonymous': self.profiles[claims['sub']]})
        if request.url.path.startswith('/rest/v1/rpc/'):
            function = request.url.path.rsplit('/', 1)[-1]
            assert function in ('saved_design_user', 'saved_design_commit', 'capture_user_operation', 'capture_authority', 'capture_cleanup')
            payload = json.loads(request.content)
            args = ','.join(f'{k}=>{literal(json.dumps(v))}::jsonb' if isinstance(v, (dict, list)) else f'{k}=>null' if v is None else f'{k}=>{str(v).lower()}' if isinstance(v, bool) else f'{k}=>{literal(v)}' for k, v in payload.items())
            setup = 'set local role service_role;' if service else f"set local role authenticated; set local request.jwt.claim.sub={literal(claims['sub'])}; set local request.jwt.claims={literal(json.dumps(claims))};"
            result = sql(f'begin; {setup} select public.{function}({args}); commit;', check=False)
            if result.returncode:
                return httpx.Response(409, json={'message': result.stderr})
            if self.after_rpc:
                self.after_rpc(function, payload)
            return httpx.Response(200, content=result.stdout.strip().encode())
        key = request.url.path.removeprefix('/storage/v1/object/captures/')
        if service and request.url.path.startswith('/storage/v1/object/captures/'):
            if request.method == 'POST':
                self.objects[key] = request.content
                return httpx.Response(200, json={})
            if key in self.objects:
                return httpx.Response(200, content=self.objects[key])
        return httpx.Response(404, json={})
