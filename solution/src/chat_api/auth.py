"""Inbound authentication for the chat API.

ASI03: every AG-UI and conversation request needs a delegated user token for the Blueprint
(aud = BLUEPRINT_APP_ID, scp contains access_as_user) from an allowed client. Requests without one get
401 before any session lookup or model call.
"""

import contextvars
import logging
import os
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from auth_common import AuthError, IssuerConfig, JwtValidator, bearer_from_header, issuer_for_mode

REQUIRED_SCOPE = "access_as_user"
log = logging.getLogger("chat_api.auth")


@dataclass(frozen=True)
class Principal:
    oid: str
    name: str | None
    token: str


current_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar("current_principal", default=None)


def build_validator(issuer: IssuerConfig | None = None) -> JwtValidator:
    clients = {c.strip() for c in os.environ.get("ALLOWED_CLIENT_APP_IDS", os.environ["CLI_APP_ID"]).split(",")}
    return JwtValidator(
        issuer or issuer_for_mode(),
        audience=os.environ["BLUEPRINT_APP_ID"],
        required_scope=REQUIRED_SCOPE,
        allowed_client_ids={c for c in clients if c},
    )


def principal_from_claims(claims: dict[str, Any], token: str) -> Principal:
    return Principal(oid=claims["oid"], name=claims.get("name") or claims.get("preferred_username"), token=token)


class RequireUser:
    """FastAPI dependency: validates the bearer and binds the principal to the request context."""

    def __init__(self, validator: JwtValidator) -> None:
        self._validator = validator

    async def __call__(self, request: Request) -> Principal:
        try:
            token = bearer_from_header(request.headers.get("authorization"))
            claims = await self._validator.validate(token)
        except AuthError as exc:
            log.warning("rejected inbound request: %s", exc)
            raise HTTPException(status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}) from exc
        principal = principal_from_claims(claims, token)
        current_principal.set(principal)
        request.state.principal = principal
        return principal


def require_principal() -> Principal:
    principal = current_principal.get()
    if principal is None:
        raise PermissionError("no authenticated user")
    return principal


def snapshot_scope(_: Any) -> str:
    """AG-UI snapshot scope: binds every thread (and its internal session id) to the caller's oid."""
    return require_principal().oid
