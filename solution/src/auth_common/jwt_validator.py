"""JWT validation with exactly one trusted issuer per process.

ASI03: each service loads one issuer for its IDENTITY_MODE (Entra or the stage-only local simulator)
and rejects tokens from the other. The issuer is checked before any key lookup, so a token from the
wrong issuer never triggers a JWKS fetch.
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient

ENTRA_AUTHORITY = "https://login.microsoftonline.com"
ALGORITHMS = ["RS256"]


class AuthError(Exception):
    """Raised for any token that must be rejected. The message is safe to log, not to return."""


@dataclass(frozen=True)
class IssuerConfig:
    mode: str
    issuer: str
    jwks_uri: str
    tenant_id: str | None = None


def identity_mode() -> str:
    mode = os.environ.get("IDENTITY_MODE", "entra").strip().lower()
    if mode not in {"entra", "local"}:
        raise RuntimeError(f"IDENTITY_MODE must be 'entra' or 'local', not '{mode}'")
    return mode


def issuer_for_mode(mode: str | None = None) -> IssuerConfig:
    mode = mode or identity_mode()
    if mode == "entra":
        tenant = os.environ["TENANT_ID"]
        return IssuerConfig(
            mode="entra",
            issuer=f"{ENTRA_AUTHORITY}/{tenant}/v2.0",
            jwks_uri=f"{ENTRA_AUTHORITY}/{tenant}/discovery/v2.0/keys",
            tenant_id=tenant,
        )
    issuer = os.environ.get("LOCAL_ISSUER_URL", "http://local-issuer:8100").rstrip("/")
    return IssuerConfig(mode="local", issuer=issuer, jwks_uri=f"{issuer}/jwks")


class JwtValidator:
    def __init__(
        self,
        issuer: IssuerConfig,
        *,
        audience: str,
        required_scope: str,
        allowed_client_ids: set[str] | None = None,
        leeway_seconds: int = 60,
        jwks_client: Any | None = None,
    ) -> None:
        if not audience or not required_scope:
            raise RuntimeError("audience and required_scope are required")
        self.issuer = issuer
        # v2 tokens carry the bare client id; accept the App ID URI form too.
        self.audiences = [audience, f"api://{audience}"]
        self.required_scope = required_scope
        self.allowed_client_ids = allowed_client_ids
        self.leeway = leeway_seconds
        self._jwks = jwks_client or PyJWKClient(issuer.jwks_uri, cache_keys=True, lifespan=3600, timeout=10)

    async def validate(self, token: str) -> dict[str, Any]:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise AuthError(f"malformed token: {exc}") from exc
        if unverified.get("iss") != self.issuer.issuer:
            raise AuthError(f"untrusted issuer for {self.issuer.mode} mode: {unverified.get('iss')!r}")

        try:
            key = await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=ALGORITHMS,
                audience=self.audiences,
                issuer=self.issuer.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token: {exc}") from exc

        if self.issuer.tenant_id and claims.get("tid") != self.issuer.tenant_id:
            raise AuthError("wrong tenant")
        scopes = str(claims.get("scp", "")).split()
        if self.required_scope not in scopes:
            raise AuthError(f"missing scope {self.required_scope}")
        if not claims.get("oid"):
            raise AuthError("no user oid; delegated user tokens only")
        client_id = claims.get("azp") or claims.get("appid")
        if self.allowed_client_ids is not None and client_id not in self.allowed_client_ids:
            raise AuthError(f"client {client_id!r} is not allowed")
        return claims


def bearer_from_header(value: str | None) -> str:
    if not value:
        raise AuthError("missing Authorization header")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization header is not a bearer token")
    return token.strip()
