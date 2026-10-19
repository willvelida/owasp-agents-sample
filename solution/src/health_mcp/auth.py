"""Bearer validation for the health MCP server.

ASI03: accepts only OBO tokens minted for this API (aud = HEALTH_MCP_APP_ID, scp contains Health.Read)
on behalf of a user, requested by the chat agent's identity (azp = CHAT_AGENT_APP_ID). The user is the
token's oid; tools never take a user id from the model.
"""

import logging
import os

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier

from auth_common import AuthError, JwtValidator, issuer_for_mode

REQUIRED_SCOPE = "Health.Read"
log = logging.getLogger("health_mcp.auth")


class HealthTokenVerifier(TokenVerifier):
    def __init__(self, validator: JwtValidator) -> None:
        self._validator = validator

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await self._validator.validate(token)
        except AuthError as exc:
            log.warning("rejected MCP bearer: %s", exc)
            return None
        log.info("MCP caller oid=%s azp=%s", claims["oid"], claims.get("azp") or claims.get("appid"))
        return AccessToken(
            token=token,
            client_id=claims.get("azp") or claims.get("appid"),
            scopes=str(claims.get("scp", "")).split(),
            expires_at=claims.get("exp"),
            subject=claims["oid"],
            claims={"oid": claims["oid"], "tid": claims.get("tid"), "iss": claims["iss"]},
        )


def build_validator() -> JwtValidator:
    return JwtValidator(
        issuer_for_mode(),
        audience=os.environ["HEALTH_MCP_APP_ID"],
        required_scope=REQUIRED_SCOPE,
        allowed_client_ids={os.environ["CHAT_AGENT_APP_ID"]},
    )


def current_oid() -> str:
    """The signed-in user's object id from the validated token. Fails closed."""
    token = get_access_token()
    oid = (token.claims or {}).get("oid") if token else None
    if not oid:
        raise PermissionError("no authenticated user")
    return oid
