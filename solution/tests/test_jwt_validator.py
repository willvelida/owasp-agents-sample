"""ASI03: one issuer per process; audience, scope, client, tenant, and expiry are all enforced."""

import time

import jwt
import pytest
from conftest import ENV, local_validator
from cryptography.hazmat.primitives.asymmetric import rsa

from auth_common import AuthError, IssuerConfig, JwtValidator, bearer_from_header, issuer_for_mode


class NoNetworkJwks:
    def get_signing_key_from_jwt(self, token: str):
        raise AssertionError("JWKS must not be fetched for a token from the wrong issuer")


def entra_validator() -> JwtValidator:
    return JwtValidator(
        issuer_for_mode("entra"),
        audience=ENV["BLUEPRINT_APP_ID"],
        required_scope="access_as_user",
        allowed_client_ids={ENV["CLI_APP_ID"]},
        jwks_client=NoNetworkJwks(),
    )


async def test_local_token_rejected_in_entra_mode(sim):
    with pytest.raises(AuthError, match="untrusted issuer"):
        await entra_validator().validate(sim.user_token("alice"))


async def test_entra_shaped_token_rejected_in_local_mode(sim, chat_validator):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    forged = jwt.encode(
        {
            "iss": issuer_for_mode("entra").issuer,
            "aud": ENV["BLUEPRINT_APP_ID"],
            "scp": "access_as_user",
            "oid": ENV["ALICE_OID"],
            "azp": ENV["CLI_APP_ID"],
            "iat": now,
            "exp": now + 600,
        },
        key,
        algorithm="RS256",
    )
    with pytest.raises(AuthError, match="untrusted issuer"):
        await chat_validator.validate(forged)


async def test_signature_from_another_key_rejected(env, chat_validator):
    from local_issuer.app import Simulator

    impostor = Simulator(env)  # same issuer URL, different private key
    with pytest.raises(AuthError, match="invalid token"):
        await chat_validator.validate(impostor.user_token("alice"))


async def test_wrong_audience_rejected(sim, chat_validator):
    mcp_token = await sim.obo(sim.user_token("alice"), ENV["CHAT_AGENT_APP_ID"])
    with pytest.raises(AuthError, match="invalid token"):
        await chat_validator.validate(mcp_token)


async def test_user_token_rejected_by_mcp_validator(sim, mcp_validator):
    with pytest.raises(AuthError):
        await mcp_validator.validate(sim.user_token("alice"))


async def test_missing_scope_rejected(sim):
    validator = local_validator(sim, audience=ENV["BLUEPRINT_APP_ID"], scope="Health.Write", clients=None)
    with pytest.raises(AuthError, match="missing scope"):
        await validator.validate(sim.user_token("alice"))


async def test_wrong_client_rejected(sim):
    validator = local_validator(sim, audience=ENV["BLUEPRINT_APP_ID"], scope="access_as_user", clients={"other"})
    with pytest.raises(AuthError, match="not allowed"):
        await validator.validate(sim.user_token("alice"))


async def test_expired_token_rejected(sim, chat_validator):
    expired = sim._sign(
        {
            "aud": ENV["BLUEPRINT_APP_ID"],
            "azp": ENV["CLI_APP_ID"],
            "scp": "access_as_user",
            "oid": ENV["ALICE_OID"],
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,
        }
    )
    with pytest.raises(AuthError, match="invalid token"):
        await chat_validator.validate(expired)


async def test_app_only_token_rejected(sim, chat_validator):
    app_token = sim._sign({"aud": ENV["BLUEPRINT_APP_ID"], "azp": ENV["CLI_APP_ID"], "scp": "access_as_user"})
    with pytest.raises(AuthError, match="no user oid"):
        await chat_validator.validate(app_token)


async def test_wrong_tenant_rejected():
    issuer = IssuerConfig(mode="entra", issuer="https://issuer.example", jwks_uri="x", tenant_id="t1")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode(
        {"iss": issuer.issuer, "aud": "aud", "scp": "s", "oid": "o", "tid": "t2", "iat": now, "exp": now + 60},
        key,
        algorithm="RS256",
    )

    class Jwks:
        def get_signing_key_from_jwt(self, _):
            return jwt.PyJWK.from_dict(
                {**jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True), "alg": "RS256"}
            )

    with pytest.raises(AuthError, match="wrong tenant"):
        await JwtValidator(issuer, audience="aud", required_scope="s", jwks_client=Jwks()).validate(token)


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "bearer"])
def test_bearer_header_parsing_rejects(header):
    with pytest.raises(AuthError):
        bearer_from_header(header)


def test_unknown_identity_mode_refused(monkeypatch):
    monkeypatch.setenv("IDENTITY_MODE", "none")
    with pytest.raises(RuntimeError):
        issuer_for_mode()
