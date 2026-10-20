"""STAGE-ONLY IDENTITY SIMULATOR. Not a security boundary (ADR-0018).

Mints alice and bob tokens with the Entra claim shape and mimics the Agent ID sidecar's OBO endpoint,
so the solution demo survives a venue network outage. Anyone who can reach it can mint tokens, so it:

* runs only under the Compose `offline` profile, published on 127.0.0.1 only;
* refuses to start when any Azure hosting marker is present;
* uses its own issuer, so services in entra mode reject everything it signs.
"""

import base64
import logging
import os
import time
import uuid
from typing import Any

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Header, HTTPException, Query

from auth_common import AuthError, IssuerConfig, JwtValidator, bearer_from_header

AZURE_MARKERS = ("CONTAINER_APP_NAME", "CONTAINER_APP_ENV_DNS_SUFFIX", "IDENTITY_ENDPOINT", "MSI_ENDPOINT")
TOKEN_LIFETIME_SECONDS = 3600
BANNER = "STAGE-ONLY IDENTITY SIMULATOR: mints tokens for anyone who can reach it. Never deploy."

log = logging.getLogger("local_issuer")


def refuse_azure() -> None:
    present = [name for name in AZURE_MARKERS if os.environ.get(name)]
    if present:
        raise SystemExit(f"local_issuer refuses to run where Azure markers are set: {', '.join(present)}")


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Simulator:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        env = dict(os.environ if env is None else env)
        self.issuer = env.get("LOCAL_ISSUER_URL", "http://local-issuer:8100").rstrip("/")
        self.tenant_id = env.get("TENANT_ID", "00000000-0000-0000-0000-000000000000")
        self.blueprint_app_id = env["BLUEPRINT_APP_ID"]
        self.chat_agent_app_id = env["CHAT_AGENT_APP_ID"]
        self.health_mcp_app_id = env["HEALTH_MCP_APP_ID"]
        self.report_api_app_id = env.get("REPORT_API_APP_ID", "")
        self.cli_app_id = env["CLI_APP_ID"]
        self.users = {
            "alice": {"oid": env["ALICE_OID"], "name": "Alice Example", "upn": env.get("ALICE_UPN", "alice@local")},
            "bob": {"oid": env["BOB_OID"], "name": "Bob Example", "upn": env.get("BOB_UPN", "bob@local")},
        }
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = uuid.uuid4().hex
        self._user_validator = JwtValidator(
            IssuerConfig(mode="local", issuer=self.issuer, jwks_uri=f"{self.issuer}/jwks"),
            audience=self.blueprint_app_id,
            required_scope="access_as_user",
            allowed_client_ids={self.cli_app_id},
            jwks_client=_StaticJwks(self),
        )

    def jwks(self) -> dict[str, Any]:
        numbers = self._key.public_key().public_numbers()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self.kid,
                    "n": _b64url_uint(numbers.n),
                    "e": _b64url_uint(numbers.e),
                }
            ]
        }

    def _sign(self, claims: dict[str, Any]) -> str:
        now = int(time.time())
        body = {
            "iss": self.issuer,
            "tid": self.tenant_id,
            "iat": now,
            "nbf": now,
            "exp": now + TOKEN_LIFETIME_SECONDS,
            "ver": "2.0",
            "uti": uuid.uuid4().hex,
            **claims,
        }
        return jwt.encode(body, self._key, algorithm="RS256", headers={"kid": self.kid})

    def user_token(self, user: str) -> str:
        profile = self.users.get(user)
        if profile is None:
            raise KeyError(user)
        return self._sign(
            {
                "aud": self.blueprint_app_id,
                "azp": self.cli_app_id,
                "scp": "access_as_user",
                "oid": profile["oid"],
                "sub": profile["oid"],
                "name": profile["name"],
                "preferred_username": profile["upn"],
                "idtyp": "user",
            }
        )

    async def obo(self, user_token: str, agent_identity: str) -> str:
        """Same contract as the sidecar: user token for the Blueprint in, MCP token for the agent out."""
        if agent_identity != self.chat_agent_app_id:
            raise PermissionError("unknown agent identity")
        claims = await self._user_validator.validate(user_token)
        return self._sign(
            {
                "aud": self.health_mcp_app_id,
                "azp": self.chat_agent_app_id,
                "scp": "Health.Read",
                "oid": claims["oid"],
                "sub": claims["oid"],
                "name": claims.get("name"),
                "preferred_username": claims.get("preferred_username"),
                "idtyp": "user",
            }
        )

    def app_token(self, agent_identity: str) -> str:
        """Same contract as the sidecar's autonomous endpoint: an app-only report API token for the chat agent."""
        if agent_identity != self.chat_agent_app_id or not self.report_api_app_id:
            raise PermissionError("unknown agent identity or no report API configured")
        return self._sign(
            {
                "aud": self.report_api_app_id,
                "azp": self.chat_agent_app_id,
                "roles": ["Report.Generate"],
                "oid": self.chat_agent_app_id,
                "sub": self.chat_agent_app_id,
                "idtyp": "app",
            }
        )


class _StaticJwks:
    """Lets the simulator validate its own user tokens without an HTTP round trip."""

    def __init__(self, sim: Simulator) -> None:
        self._sim = sim

    def get_signing_key_from_jwt(self, token: str) -> Any:
        return jwt.PyJWK(self._sim.jwks()["keys"][0])


def create_app(sim: Simulator) -> FastAPI:
    app = FastAPI(title="Biotrackr local identity simulator (stage only)", description=BANNER)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "warning": BANNER}

    @app.get("/jwks")
    async def jwks() -> dict[str, Any]:
        return sim.jwks()

    @app.get("/token")
    async def token(user: str = Query(...)) -> dict[str, Any]:
        try:
            access_token = sim.user_token(user)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown user") from exc
        return {"access_token": access_token, "token_type": "Bearer", "expires_in": TOKEN_LIFETIME_SECONDS}

    async def _obo(agent_identity: str, authorization: str | None) -> dict[str, str]:
        try:
            user_token = bearer_from_header(authorization)
            mcp_token = await sim.obo(user_token, agent_identity)
        except (AuthError, PermissionError) as exc:
            log.warning("OBO refused: %s", exc)
            raise HTTPException(status_code=401, detail="unauthorized") from exc
        return {"authorizationHeader": f"Bearer {mcp_token}"}

    # Mirrors the sidecar route so chat_api/identity.py is identical in both modes.
    @app.get("/AuthorizationHeader/HealthMcp")
    async def authorization_header(
        agent_identity: str = Query(..., alias="AgentIdentity"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        return await _obo(agent_identity, authorization)

    @app.post("/obo")
    async def obo(
        agent_identity: str = Query(..., alias="AgentIdentity"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        return await _obo(agent_identity, authorization)

    # Mirrors the sidecar's autonomous route (no user token): chat agent -> report agent (ASI07 baseline).
    @app.get("/AuthorizationHeaderUnauthenticated/ReportApi")
    async def autonomous_header(agent_identity: str = Query(..., alias="AgentIdentity")) -> dict[str, str]:
        try:
            token = sim.app_token(agent_identity)
        except PermissionError as exc:
            log.warning("app token refused: %s", exc)
            raise HTTPException(status_code=401, detail="unauthorized") from exc
        return {"authorizationHeader": f"Bearer {token}"}

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    refuse_azure()
    log.warning(BANNER)
    uvicorn.run(create_app(Simulator()), host="0.0.0.0", port=int(os.environ.get("PORT", "8100")))


if __name__ == "__main__":
    main()
