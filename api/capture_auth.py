"""Verified Supabase caller identity and fail-closed activation configuration."""
from __future__ import annotations
from dataclasses import dataclass
import os
import base64
import json
from urllib.parse import urlparse
from uuid import UUID
from time import monotonic
import httpx
from fastapi import HTTPException

class CaptureError(HTTPException):
    def __init__(self, code: str, detail: str, status_code: int = 409):
        self.code = code
        super().__init__(status_code, {"code": code, "detail": detail})

@dataclass(frozen=True)
class CapturePrincipal:
    owner_id: str
    token: str
    is_anonymous: bool = True

@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    public_key: str
    secret_key: str

    @classmethod
    def from_environment(cls, *, saved: bool = False) -> "SupabaseSettings":
        gates = ("FURNITUREOS_SAVED_ENABLED", "FURNITUREOS_SAVED_AUTH_VERIFIED", "FURNITUREOS_SAVED_SCHEMA_VERIFIED") if saved else ("FURNITUREOS_CAPTURE_ENABLED", "FURNITUREOS_CAPTURE_AUTH_VERIFIED",
                 "FURNITUREOS_CAPTURE_SCHEMA_VERIFIED", "FURNITUREOS_CAPTURE_STORAGE_VERIFIED",
                 "FURNITUREOS_CAPTURE_CLEANUP_VERIFIED", "FURNITUREOS_CAPTURE_SERVER_PHOTOS_VERIFIED")
        if any(os.environ.get(gate) != "1" for gate in gates):
            raise CaptureError("activation-required", "Private storage activation is not verified.", 503)
        url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
        secret = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if urlparse(url).scheme != "https" or not urlparse(url).hostname or not key or not secret or key==secret or key.startswith("sb_secret_"):
            raise CaptureError("activation-required", "Capture service configuration is incomplete.", 503)
        if key.count('.')==2:
            try:
                claims=json.loads(base64.urlsafe_b64decode(key.split('.')[1]+'==='))
                if claims.get('role')!='anon': raise ValueError('nonpublic legacy key')
            except (ValueError,TypeError,KeyError):
                raise CaptureError("activation-required", "Capture public key configuration is invalid.",503) from None
        return cls(url, key, secret)

class SupabaseAuth:
    def __init__(self, settings: SupabaseSettings, client: httpx.Client):
        self.settings, self.client = settings, client

    def verify(self, authorization: str | None) -> CapturePrincipal:
        if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 8192:
            raise CaptureError("authentication-required", "Refresh or restore your account to continue.", 401)
        token = authorization[7:]
        if not token or token == self.settings.secret_key or token == self.settings.public_key:
            raise CaptureError("authentication-required", "Refresh or restore your account to continue.", 401)
        try:
            started=monotonic()
            with self.client.stream("GET", self.settings.url + "/auth/v1/user",
                                    headers={"apikey": self.settings.public_key, "Authorization": authorization},
                                    timeout=5, follow_redirects=False) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 32768 or monotonic()-started>5:
                        raise ValueError("large auth response")
                if response.status_code != 200:
                    raise ValueError("invalid auth")
                import json
                user = json.loads(body)
                # Auth has validated this token. Require exact signed top-level
                # identity claims to agree with the current Auth-owned record.
                claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
                if (not isinstance(user,dict) or type(user.get('is_anonymous')) is not bool
                        or type(claims.get('is_anonymous')) is not bool
                        or claims['is_anonymous'] != user['is_anonymous']):
                    raise ValueError('refresh identity required')
                owner = str(UUID(user["id"]))
                if str(UUID(claims['sub'])) != owner:
                    raise ValueError('identity mismatch')
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            raise CaptureError("authentication-required", "Refresh or restore your account to continue.", 401) from None
        return CapturePrincipal(owner, token, user['is_anonymous'])
