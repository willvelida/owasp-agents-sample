"""Report agent: caller authentication (ASI07 baseline) and the fail-closed pipeline (ASI05, ASI09).

Reviewer row of the fail-closed contract: an error, a timeout, or a bad verdict persists `denied` and no
chart. Spies record whether later stages ran at all.
"""

import asyncio
import json
import time

import httpx
import pytest
from conftest import ENV, StaticJwks
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient

from auth_common import IssuerConfig, JwtValidator
from chat_api.auth import current_principal, principal_from_claims
from chat_api.tools_report import ReportService
from report_agent.a2a_security import A2ASigner, SignatureVerifier
from report_agent.app import Pipeline, create_app
from report_agent.executor import PNG_MAGIC, ChartResult, RunnerError
from report_agent.reviewer import Verdict, parse_verdict, review
from report_agent.schemas import SCHEMA_VERSION, ReportRequest

PNG = PNG_MAGIC + b"tiny"
REQUEST = {
    "schema_version": SCHEMA_VERSION,
    "request": "bar chart of my steps",
    "data": [{"label": "2026-10-13", "value": 7939}],
}
# One A2A key pair for the round-trip tests below (test_a2a_security.py covers signing itself).
A2A_KEY = Ed25519PrivateKey.generate()
CHART_CODE = (
    'plt.bar([p["label"] for p in data], [p["value"] for p in data])\nplt.title("Steps")\nplt.savefig("chart.png")'
)


class SpyRunner:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.error = error

    async def run(self, code, data):
        self.calls.append(code)
        if self.error:
            raise self.error
        return ChartResult(title="Steps", caption="Daily steps.", png=PNG)


class Spies:
    def __init__(self, *, code: str = CHART_CODE, runner: SpyRunner | None = None, verdict=None) -> None:
        self.generated: list[ReportRequest] = []
        self.reviewed: list[str] = []
        self.code = code
        self.runner = runner or SpyRunner()
        self.verdict = verdict or (lambda: Verdict(True, "ok"))

    async def generate(self, request: ReportRequest) -> str:
        self.generated.append(request)
        if isinstance(self.code, Exception):
            raise self.code
        return self.code

    async def review(self, code: str, summary: str) -> Verdict:
        self.reviewed.append(summary)
        return self.verdict()

    def pipeline(self) -> Pipeline:
        return Pipeline(generate=self.generate, runner=self.runner, reviewer=self.review)


def report_validator(sim) -> JwtValidator:
    return JwtValidator(
        IssuerConfig(mode="local", issuer=sim.issuer, jwks_uri=f"{sim.issuer}/jwks"),
        audience=ENV["REPORT_API_APP_ID"],
        required_role="Report.Generate",
        allowed_client_ids={ENV["CHAT_AGENT_APP_ID"]},
        jwks_client=StaticJwks(sim),
    )


# --- pipeline ------------------------------------------------------------------------------------------


async def test_approved_report_carries_chart():
    spies = Spies()
    report = await spies.pipeline().run("r1", REQUEST)
    assert report.status == "approved" and report.chart_png_base64
    assert report.rejected_by is None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"request": "x", "data": []},
        {**REQUEST, "extra": "field"},
        {"request": "x", "data": [{"label": "<script>", "value": 1}]},
        {"request": "x", "data": [{"label": "a", "value": float("nan")}]},
        {"request": "x" * 501, "data": REQUEST["data"]},
        {k: v for k, v in REQUEST.items() if k != "schema_version"},
        {**REQUEST, "schema_version": "biotrackr.report/v0"},
    ],
    ids=["missing", "no-data", "extra-field", "bad-label", "nan", "long-request", "unversioned", "old-version"],
)
async def test_untyped_payload_is_denied_before_generation(payload):
    spies = Spies()
    report = await spies.pipeline().run("r1", payload)
    assert (report.status, report.rejected_by) == ("denied", "validation")
    assert spies.generated == [] and spies.runner.calls == []


async def test_static_check_rejection_never_reaches_runner():
    spies = Spies(code="plt.title(__import__('os').environ['REPORT_AGENT_CANARY'])")
    report = await spies.pipeline().run("r1", REQUEST)
    assert (report.status, report.rejected_by) == ("denied", "static_check")
    assert spies.runner.calls == [] and spies.reviewed == []
    assert report.chart_png_base64 is None


@pytest.mark.parametrize("error", [RunnerError("chart code failed: KeyError"), OSError("socket gone")])
async def test_runner_failure_is_denied_without_chart(error):
    spies = Spies(runner=SpyRunner(error))
    report = await spies.pipeline().run("r1", REQUEST)
    assert (report.status, report.rejected_by) == ("denied", "runner")
    assert spies.reviewed == [] and report.chart_png_base64 is None


async def test_generator_failure_is_denied():
    spies = Spies(code=TimeoutError())
    report = await spies.pipeline().run("r1", REQUEST)
    assert (report.status, report.rejected_by) == ("denied", "generator")
    assert spies.runner.calls == []


# --- reviewer: fail-closed contract row (error, timeout, bad verdict) ---------------------------------------


class FakeReviewer:
    def __init__(self, behaviour) -> None:
        self.behaviour = behaviour
        self.runs = 0

    async def run(self, prompt):
        self.runs += 1
        result = self.behaviour()
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, Exception):
            raise result

        class R:
            text = result

        return R()


@pytest.mark.parametrize(
    "behaviour",
    [
        lambda: RuntimeError("model down"),
        lambda: asyncio.sleep(5),
        lambda: "approved",
        lambda: '{"approved": "true"}',
        lambda: "[true]",
        lambda: '{"reason": "fine"}',
        lambda: "",
    ],
    ids=["error", "timeout", "not-json", "string-bool", "list", "no-verdict", "empty"],
)
async def test_reviewer_faults_persist_denied_and_no_chart(behaviour):
    reviewers: list[FakeReviewer] = []

    def factory():
        reviewers.append(FakeReviewer(behaviour))
        return reviewers[-1]

    spies = Spies()
    pipeline = Pipeline(
        generate=spies.generate, runner=spies.runner, reviewer=lambda c, s: review(factory, c, s, limit=0.2)
    )
    report = await pipeline.run("r1", REQUEST)
    assert (report.status, report.rejected_by) == ("denied", "reviewer")
    assert report.chart_png_base64 is None and report.summary is None
    assert spies.runner.calls  # the reviewer, not an earlier stage, decided


async def test_each_review_uses_a_fresh_agent():
    created: list[FakeReviewer] = []

    def factory():
        created.append(FakeReviewer(lambda: '{"approved": true, "reason": "ok"}'))
        return created[-1]

    for _ in range(2):
        assert (await review(factory, "code", "summary")).approved
    assert len(created) == 2 and all(r.runs == 1 for r in created)


def test_parse_verdict_only_accepts_a_boolean():
    assert parse_verdict('{"approved": true}').approved
    assert not parse_verdict('{"approved": 1}').approved


# --- caller authentication ---------------------------------------------------------------------------------


@pytest.fixture
def report_app(sim):
    spies = Spies()
    app = create_app(spies.pipeline(), report_validator(sim), SignatureVerifier([A2A_KEY.public_key()]))
    return spies, app


def jsonrpc_send() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"data": REQUEST}]}},
    }


def test_healthz_reports_canary_presence_only(report_app, monkeypatch):
    _, app = report_app
    monkeypatch.setenv("REPORT_AGENT_CANARY", "CANARY-ENV-R5X")
    body = TestClient(app).get("/healthz").json()
    assert body == {"status": "ok", "canary_present": True}
    assert "CANARY-ENV-R5X" not in json.dumps(body)


def _token(sim, **overrides):
    claims = {
        "aud": ENV["REPORT_API_APP_ID"],
        "azp": ENV["CHAT_AGENT_APP_ID"],
        "roles": ["Report.Generate"],
        "oid": ENV["CHAT_AGENT_APP_ID"],
        "idtyp": "app",
    }
    claims.update(overrides)
    return sim._sign({k: v for k, v in claims.items() if v is not None})


@pytest.mark.parametrize(
    "token",
    [
        lambda sim: None,
        lambda sim: "garbage",
        lambda sim: sim.user_token("alice"),
        lambda sim: _token(sim, azp=ENV["CLI_APP_ID"]),
        lambda sim: _token(sim, roles=["Report.Read"]),
        lambda sim: _token(sim, roles=None),
        lambda sim: _token(sim, scp="access_as_user"),
        lambda sim: _token(sim, aud=ENV["HEALTH_MCP_APP_ID"]),
    ],
    ids=["none", "garbage", "user-token", "wrong-azp", "wrong-role", "no-role", "delegated", "wrong-aud"],
)
def test_a2a_rejects_wrong_callers_before_any_work(report_app, sim, token):
    spies, app = report_app
    value = token(sim)
    headers = {"Authorization": f"Bearer {value}"} if value else {}
    client = TestClient(app)
    for method, path in (("POST", "/"), ("GET", "/.well-known/agent-card.json")):
        response = client.request(method, path, json=jsonrpc_send(), headers={**headers, "A2A-Version": "1.0"})
        assert response.status_code == 401
    assert spies.generated == []


async def test_simulator_app_token_matches_the_report_contract(sim):
    claims = await report_validator(sim).validate(sim.app_token(ENV["CHAT_AGENT_APP_ID"]))
    assert claims["roles"] == ["Report.Generate"] and claims["azp"] == ENV["CHAT_AGENT_APP_ID"]
    with pytest.raises(PermissionError):
        sim.app_token(ENV["CLI_APP_ID"])


# --- chat agent -> report agent over A2A ---------------------------------------------------------------------


class SimTokens:
    def __init__(self, sim, fail: bool = False) -> None:
        self.sim = sim
        self.fail = fail
        self.calls = 0

    async def report_api_header(self) -> str:
        from chat_api.identity import IdentityError

        self.calls += 1
        if self.fail:
            raise IdentityError("sidecar down")
        return f"Bearer {self.sim.app_token(ENV['CHAT_AGENT_APP_ID'])}"


def as_user(name: str) -> None:
    current_principal.set(principal_from_claims({"oid": ENV[f"{name.upper()}_OID"], "name": name}, "t"))


async def test_report_service_round_trip_and_ownership(report_app, sim):
    spies, app = report_app
    service = ReportService(
        SimTokens(sim), "http://report-agent/", transport=httpx.ASGITransport(app=app), signer=A2ASigner(A2A_KEY)
    )
    as_user("alice")
    result = json.loads(await service.generate(ReportRequest.model_validate(REQUEST)))
    assert result["status"] == "approved" and result["chart_png_bytes"] > 0
    assert "chart_png_base64" not in result
    assert len(spies.generated) == 1

    assert json.loads(await service.status(result["report_id"]))["status"] == "approved"
    as_user("bob")
    assert json.loads(await service.status(result["report_id"]))["status"] == "not_found"


async def test_report_service_fails_closed_without_token(report_app, sim):
    spies, app = report_app
    service = ReportService(
        SimTokens(sim, fail=True),
        "http://report-agent/",
        transport=httpx.ASGITransport(app=app),
        signer=A2ASigner(A2A_KEY),
    )
    as_user("alice")
    result = json.loads(await service.generate(ReportRequest.model_validate(REQUEST)))
    assert result["status"] == "unavailable"
    assert spies.generated == []


async def test_report_service_returns_pending_when_slow(sim):
    gate = asyncio.Event()

    async def slow_generate(request):
        await gate.wait()
        return CHART_CODE

    spies = Spies()
    pipeline = Pipeline(generate=slow_generate, runner=spies.runner, reviewer=spies.review)
    app = create_app(pipeline, report_validator(sim), SignatureVerifier([A2A_KEY.public_key()]))
    service = ReportService(
        SimTokens(sim),
        "http://report-agent/",
        transport=httpx.ASGITransport(app=app),
        wait_seconds=0.2,
        signer=A2ASigner(A2A_KEY),
    )
    as_user("alice")
    started = time.monotonic()
    result = json.loads(await service.generate(ReportRequest.model_validate(REQUEST)))
    gate.set()
    assert result["status"] == "pending" and result["report_id"]
    assert time.monotonic() - started < 5
