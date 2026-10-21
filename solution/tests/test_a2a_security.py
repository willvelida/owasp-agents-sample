"""ASI07: signed, fresh, single-use A2A requests (fail-closed contract row: A2A signature).

Every rejection happens before the A2A handler: the pipeline spy shows zero generations. The token check
(S3) runs first, so an unauthenticated caller never learns why a signature was refused.
"""

import json
import os
import stat
import sys

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient
from test_report_agent import REQUEST, SimTokens, Spies, _token, as_user, jsonrpc_send, report_validator

from chat_api.tools_report import ReportService
from report_agent import a2a_security
from report_agent.a2a_security import (
    SIGNATURE_HEADER,
    A2ASignatureError,
    A2ASigner,
    ReplayCache,
    SignatureHeader,
    SignatureVerifier,
    key_id,
    sign,
    verifier_from_env,
)
from report_agent.app import create_app
from report_agent.schemas import SCHEMA_VERSION, ReportRequest

NOW = 1_800_000_000.0


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def signed_app(sim, key, clock):
    spies = Spies()
    verifier = SignatureVerifier([key.public_key()], clock=clock)
    app = create_app(spies.pipeline(), report_validator(sim), verifier)
    return spies, TestClient(app), verifier


def body_bytes(payload: dict | None = None) -> bytes:
    message = jsonrpc_send()
    if payload is not None:
        message["params"]["message"]["parts"] = [{"data": payload}]
    return json.dumps(message).encode()


def post(client: TestClient, sim, body: bytes, signature: str | None, *, token: bool = True):
    headers = {"Content-Type": "application/json", "A2A-Version": "1.0"}
    if token:
        headers["Authorization"] = f"Bearer {_token(sim)}"
    if signature is not None:
        headers[SIGNATURE_HEADER] = signature
    return client.post("/", content=body, headers=headers)


def tamper(header: str, **fields: str) -> str:
    parts = dict(item.split("=", 1) for item in header.split(";"))
    parts.update(fields)
    return ";".join(f"{k}={v}" for k, v in parts.items())


# --- through the report agent ------------------------------------------------------------------------------


def test_genuine_signed_request_is_accepted(signed_app, sim, key):
    """Positive control: without it, every rejection below could be a broken endpoint."""
    spies, client, _ = signed_app
    body = body_bytes()
    response = post(client, sim, body, sign(key, "POST", "/", body, now=NOW))
    assert response.status_code == 200, response.text
    assert len(spies.generated) == 1


def _attacker_with_victim_kid(key):
    def build(body):
        forged = sign(Ed25519PrivateKey.generate(), "POST", "/", body, now=NOW)
        return tamper(forged, kid=key_id(key.public_key()))

    return build


@pytest.mark.parametrize(
    ("make_signature", "reason"),
    [
        (lambda key, body: None, "missing_signature"),
        (lambda key, body: "", "missing_signature"),
        (lambda key, body: "garbage", "malformed_signature"),
        (lambda key, body: sign(key, "POST", "/", body, now=NOW) + ";v=a2a-sig/v1", "malformed_signature"),
        (lambda key, body: tamper(sign(key, "POST", "/", body, now=NOW), v="a2a-sig/v0"), "unsupported_version"),
        (
            lambda key, body: tamper(sign(key, "POST", "/", body, now=NOW), sv="biotrackr.report/v0"),
            "unsupported_schema",
        ),
        (lambda key, body: sign(Ed25519PrivateKey.generate(), "POST", "/", body, now=NOW), "unknown_key"),
        (lambda key, body: _attacker_with_victim_kid(key)(body), "bad_signature"),
        (lambda key, body: sign(key, "POST", "/other", body, now=NOW), "bad_signature"),
        (lambda key, body: sign(key, "GET", "/", body, now=NOW), "bad_signature"),
        (lambda key, body: tamper(sign(key, "POST", "/", body, now=NOW), iat=str(int(NOW) + 1)), "bad_signature"),
        (lambda key, body: tamper(sign(key, "POST", "/", body, now=NOW), nonce="A" * 32), "bad_signature"),
        (lambda key, body: sign(key, "POST", "/", body + b" ", now=NOW), "body_mismatch"),
        (lambda key, body: sign(key, "POST", "/", body, now=NOW - 61), "expired"),
        (lambda key, body: sign(key, "POST", "/", body, now=NOW + 6), "issued_in_future"),
    ],
    ids=[
        "unsigned",
        "empty",
        "garbage",
        "duplicate-field",
        "old-envelope",
        "old-schema",
        "attacker-key",
        "attacker-key-victim-kid",
        "other-path",
        "other-method",
        "edited-iat",
        "edited-nonce",
        "tampered-body",
        "expired",
        "future",
    ],
)
def test_bad_signatures_are_refused_before_any_work(signed_app, sim, key, make_signature, reason):
    spies, client, _ = signed_app
    body = body_bytes()
    response = post(client, sim, body, make_signature(key, body))
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "reason": reason}
    assert spies.generated == []


def test_tampered_payload_with_original_signature_is_refused(signed_app, sim, key):
    spies, client, _ = signed_app
    original = body_bytes()
    signature = sign(key, "POST", "/", original, now=NOW)
    forged = body_bytes({**REQUEST, "data": [{"label": "2026-10-13", "value": 99999}]})
    response = post(client, sim, forged, signature)
    assert response.json()["reason"] == "body_mismatch"
    assert spies.generated == []


def test_replayed_request_is_refused(signed_app, sim, key, clock):
    spies, client, _ = signed_app
    body = body_bytes()
    signature = sign(key, "POST", "/", body, now=NOW)
    assert post(client, sim, body, signature).status_code == 200
    clock.now += 30
    replay = post(client, sim, body, signature)
    assert (replay.status_code, replay.json()["reason"]) == (401, "replayed")
    clock.now += 31
    assert post(client, sim, body, signature).json()["reason"] == "expired"
    assert len(spies.generated) == 1


def test_token_check_runs_before_the_signature_check(signed_app, sim, key):
    """A genuine signature without a token is refused by the S3 check, and no signature reason leaks."""
    spies, client, _ = signed_app
    body = body_bytes()
    response = post(client, sim, body, sign(key, "POST", "/", body, now=NOW), token=False)
    assert response.status_code == 401 and "reason" not in response.json()
    assert spies.generated == []


def test_full_replay_cache_fails_closed(sim, key, clock):
    spies = Spies()
    verifier = SignatureVerifier([key.public_key()], clock=clock, cache=ReplayCache(max_entries=1))
    client = TestClient(create_app(spies.pipeline(), report_validator(sim), verifier))
    first, second = body_bytes(), body_bytes({**REQUEST, "request": "another chart"})
    assert post(client, sim, first, sign(key, "POST", "/", first, now=NOW)).status_code == 200
    response = post(client, sim, second, sign(key, "POST", "/", second, now=NOW))
    assert (response.status_code, response.json()["reason"]) == (503, "replay_cache_full")
    assert len(spies.generated) == 1
    clock.now += 70  # the first nonce has expired and is purged
    third = body_bytes({**REQUEST, "request": "a third chart"})
    assert post(client, sim, third, sign(key, "POST", "/", third, now=clock.now)).status_code == 200


def test_oversized_body_is_refused(signed_app, sim, key):
    spies, client, _ = signed_app
    body = b"{" + b" " * a2a_security.MAX_BODY_BYTES + b"}"
    response = post(client, sim, body, sign(key, "POST", "/", body, now=NOW))
    assert (response.status_code, response.json()["reason"]) == (413, "body_too_large")
    assert spies.generated == []


@pytest.mark.parametrize(
    "payload",
    [{k: v for k, v in REQUEST.items() if k != "schema_version"}, {**REQUEST, "schema_version": "biotrackr.report/v2"}],
    ids=["unversioned", "other-version"],
)
def test_signed_payload_with_wrong_schema_is_denied_by_validation(signed_app, sim, key, payload):
    spies, client, _ = signed_app
    body = body_bytes(payload)
    response = post(client, sim, body, sign(key, "POST", "/", body, now=NOW))
    assert response.status_code == 200
    assert '"rejected_by": "validation"' in json.dumps(response.json()).replace('":"', '": "')
    assert spies.generated == []


def test_healthz_needs_no_signature(signed_app):
    _, client, _ = signed_app
    assert client.get("/healthz").status_code == 200


# --- chat agent side ---------------------------------------------------------------------------------------


async def test_report_service_round_trip_is_signed(sim, key):
    spies = Spies()
    seen: list[str] = []
    app = create_app(spies.pipeline(), report_validator(sim), SignatureVerifier([key.public_key()]))
    inner = httpx.ASGITransport(app=app)

    class Recording(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            seen.append(request.headers[SIGNATURE_HEADER])
            return await inner.handle_async_request(request)

    service = ReportService(SimTokens(sim), "http://report-agent/", transport=Recording(), signer=A2ASigner(key))
    as_user("alice")
    result = json.loads(await service.generate(ReportRequest.model_validate(REQUEST)))
    assert result["status"] == "approved" and "schema_version" not in result
    assert json.loads(await service.status(result["report_id"]))["status"] == "approved"
    nonces = [SignatureHeader.decode(h).nonce for h in seen]
    assert len(nonces) >= 2 and len(set(nonces)) == len(nonces)


async def test_report_service_without_a_key_sends_nothing(sim):
    sent: list[httpx.Request] = []

    def spy(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(500)

    tokens = SimTokens(sim)
    service = ReportService(tokens, "http://report-agent/", transport=httpx.MockTransport(spy), signer=None)
    as_user("alice")
    result = json.loads(await service.generate(ReportRequest.model_validate(REQUEST)))
    assert result == {"status": "unavailable", "reason": "the report service could not be authorised"}
    assert sent == [] and tokens.calls == 0
    assert service.breaker.state == "closed"


def test_signer_signs_each_attempt_with_a_new_nonce(key):
    signer = A2ASigner(key, clock=Clock())
    headers = []
    for _ in range(2):
        request = httpx.Request("POST", "http://report-agent/", content=b"{}")
        headers.append(next(signer.auth_flow(request)).headers[SIGNATURE_HEADER])
    verifier = SignatureVerifier([key.public_key()], clock=Clock())
    for header in headers:
        verifier.verify("POST", "/", b"{}", header)
    with pytest.raises(A2ASignatureError, match="replayed"):
        verifier.verify("POST", "/", b"{}", headers[0])


# --- configuration (fail closed) ---------------------------------------------------------------------------


def test_report_agent_does_not_start_without_verification_keys(monkeypatch):
    monkeypatch.delenv("A2A_VERIFY_KEYS", raising=False)
    monkeypatch.delenv("A2A_VERIFY_KEYS_FILE", raising=False)
    with pytest.raises(SystemExit):
        verifier_from_env()
    monkeypatch.setenv("A2A_VERIFY_KEYS", "not-a-key")
    with pytest.raises(SystemExit):
        verifier_from_env()


def test_verification_keys_from_env_and_file(monkeypatch, tmp_path, key):
    other = Ed25519PrivateKey.generate()
    path = tmp_path / "verify.pub"
    path.write_text(a2a_security.encode_public_key(other.public_key()) + "\n")
    monkeypatch.setenv("A2A_VERIFY_KEYS", a2a_security.encode_public_key(key.public_key()))
    monkeypatch.setenv("A2A_VERIFY_KEYS_FILE", str(path))
    assert set(verifier_from_env().keys) == {key_id(key.public_key()), key_id(other.public_key())}


def test_signer_from_env_fails_closed(monkeypatch, tmp_path, key):
    monkeypatch.delenv("A2A_SIGNING_KEY", raising=False)
    monkeypatch.delenv("A2A_SIGNING_KEY_FILE", raising=False)
    assert A2ASigner.from_env() is None
    monkeypatch.setenv("A2A_SIGNING_KEY_FILE", str(tmp_path / "missing.key"))
    assert A2ASigner.from_env() is None
    monkeypatch.setenv("A2A_SIGNING_KEY", "bm90IGEga2V5")
    assert A2ASigner.from_env() is None
    monkeypatch.setenv("A2A_SIGNING_KEY", a2a_security.encode_private_key(key))
    signer = A2ASigner.from_env()
    assert signer is not None and key_id(signer.private_key.public_key()) == key_id(key.public_key())


def test_keygen_files_is_idempotent(tmp_path, monkeypatch):
    private, public = tmp_path / "signing.key", tmp_path / "verify.pub"
    args = ["--private", str(private), "--public", str(public)]
    assert a2a_security.keygen(args) == 0
    first = private.read_text()
    public.unlink()
    assert a2a_security.keygen(args) == 0
    assert private.read_text() == first
    key = a2a_security.decode_private_key(first)
    assert public.read_text().strip() == a2a_security.encode_public_key(key.public_key())
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(private).st_mode) == 0o400
    monkeypatch.setenv("A2A_VERIFY_KEYS_FILE", str(public))
    monkeypatch.delenv("A2A_VERIFY_KEYS", raising=False)
    assert key_id(key.public_key()) in verifier_from_env().keys


def test_keygen_env_format_round_trips(capsys):
    assert a2a_security.keygen(["--format", "env"]) == 0
    values = dict(line.split("=", 1) for line in capsys.readouterr().out.split())
    key = a2a_security.decode_private_key(values["A2A_SIGNING_KEY"])
    assert values["A2A_VERIFY_KEY"] == a2a_security.encode_public_key(key.public_key())


def test_schema_version_is_shared():
    assert SCHEMA_VERSION == ReportRequest.model_fields["schema_version"].annotation.__args__[0]
