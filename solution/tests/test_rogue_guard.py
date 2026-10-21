"""ASI10 rogue detection per user: a burst quarantines that user only, and never one ordinary conversation."""

import pytest
from agent_framework import Agent, MiddlewareFailure
from conftest import ENV
from test_tool_governance import ScriptedClient, Tools, call

from chat_api.auth import current_principal, principal_from_claims
from chat_api.middleware import build_middleware, load_governance
from chat_api.middleware.audit import AuditTrail, MemorySink
from chat_api.middleware.rogue_guard import QUARANTINE_REPLY, BoundedRogueAgentDetector, RogueGuard, RogueSettings
from chat_api.session_store import ToolBudget
from governance import PolicyError


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def as_user(name: str) -> None:
    current_principal.set(principal_from_claims({"oid": ENV[f"{name.upper()}_OID"], "name": name}, "token"))


def setup(settings: RogueSettings, clock: Clock):
    governance = load_governance()
    sink = MemorySink()
    audit = AuditTrail(sink)
    guard = RogueGuard(settings, allowed_tools=governance.allowed_tools, agent_id="agent", audit=audit, clock=clock)
    # A large tool budget so the per-conversation ASI02 budget is not what stops these batches.
    budget = ToolBudget(1000)

    def agent(turns):
        tools = Tools()
        client = ScriptedClient(turns)
        middleware = build_middleware(governance, budget=budget, rogue=guard, audit=audit)
        return Agent(client=client, tools=tools.all, middleware=middleware), client, tools

    return guard, sink, agent


def batch(n: int) -> list:
    return [call("get_sleep_records", str(i)) for i in range(n)]


async def test_burst_across_conversations_quarantines_only_that_user():
    clock = Clock()
    guard, sink, agent = setup(RogueSettings(burst_limit=5, burst_window_seconds=60), clock)
    as_user("alice")
    first, _, tools = agent([batch(3)])
    await first.run("sleep", session=first.create_session())
    assert len(tools.executed) == 3
    second, _, tools = agent([batch(3)])
    with pytest.raises(MiddlewareFailure, match="quarantined"):
        await second.run("sleep again", session=second.create_session())
    assert tools.executed == []  # the sixth call tripped the ceiling, and MiddlewareFailure cancelled its batch

    # Alice's next run is refused before the model; Bob is unaffected.
    third, client, _ = agent([batch(1)])
    assert (await third.run("hello", session=third.create_session())).text == QUARANTINE_REPLY
    assert client.calls == 0
    as_user("bob")
    bobs, _, tools = agent([batch(3)])
    await bobs.run("sleep", session=bobs.create_session())
    assert len(tools.executed) == 3
    assert any(r["action"] == "quarantine" and r["data"].get("reason") == "burst" for r in sink.records)


async def test_quarantine_expires():
    clock = Clock()
    guard, _, agent = setup(RogueSettings(burst_limit=1, quarantine_seconds=300), clock)
    as_user("alice")
    first, _, _ = agent([batch(2)])
    with pytest.raises(MiddlewareFailure):
        await first.run("sleep", session=first.create_session())
    assert guard.quarantine_remaining(ENV["ALICE_OID"]) > 0
    clock.now += 301
    clock.now += 1000  # and outside the burst window
    later, client, tools = agent([batch(1)])
    await later.run("sleep", session=later.create_session())
    assert client.calls == 2 and tools.executed == ["get_sleep_records"]


def test_release_starts_the_user_with_a_fresh_detector():
    # The burst that caused the quarantine must not count against the user after release.
    clock = Clock()
    guard, _, _ = setup(RogueSettings(quarantine_seconds=300), clock)
    oid = ENV["ALICE_OID"]
    before = guard.user(oid)
    guard.record_call(oid)
    guard.quarantine(oid, "burst")
    clock.now += 301
    assert guard.quarantine_remaining(oid) == 0
    after = guard.user(oid)
    assert after is not before and not after.calls
    assert after.middleware is not before.middleware


async def test_after_release_an_ordinary_run_uses_tools_again():
    governance = load_governance()
    clock = Clock()
    guard, _, agent = setup(governance.rogue, clock)
    as_user("alice")
    limit = governance.rogue.burst_limit
    for start in range(0, limit + 1, 10):
        run, _, _ = agent([batch(min(10, limit + 1 - start))])
        try:
            await run.run("sleep", session=run.create_session())
        except MiddlewareFailure:
            break
    assert guard.quarantine_remaining(ENV["ALICE_OID"]) > 0
    clock.now += governance.rogue.quarantine_seconds + 1
    later, _, tools = agent([batch(1)])
    await later.run("sleep", session=later.create_session())
    assert tools.executed == ["get_sleep_records"]
    assert guard.quarantine_remaining(ENV["ALICE_OID"]) == 0


async def test_agt_detector_quarantine_is_per_user_and_fails_closed():
    # Quarantine at LOW makes AGT's own detector recommend quarantine on the first assessment.
    clock = Clock()
    guard, sink, agent = setup(RogueSettings(quarantine_risk_level="low"), clock)
    as_user("alice")
    run, _, tools = agent([[call("get_sleep_records", "1"), call("get_food_by_date", "2")]])
    with pytest.raises(MiddlewareFailure, match="AGT rogue detection"):
        await run.run("sleep and food", session=run.create_session())
    assert tools.executed == []
    assert guard.quarantine_remaining(ENV["ALICE_OID"]) > 0
    assert guard.quarantine_remaining(ENV["BOB_OID"]) == 0
    agents = {r["agent_did"] for r in sink.records if r["event_type"] == "rogue_detection"}
    assert f"agent/{ENV['ALICE_OID']}" in agents and f"agent/{ENV['BOB_OID']}" not in agents


async def test_one_conversation_spending_its_whole_budget_never_trips_the_ceiling():
    governance = load_governance()
    assert governance.rogue.burst_limit > governance.policy.max_tool_calls
    clock = Clock()
    guard, _, agent = setup(governance.rogue, clock)
    as_user("alice")
    run, _, tools = agent([batch(governance.policy.max_tool_calls)])
    await run.run("everything", session=run.create_session())
    assert len(tools.executed) == governance.policy.max_tool_calls
    assert guard.quarantine_remaining(ENV["ALICE_OID"]) == 0


def test_policy_rejects_a_ceiling_at_or_below_the_conversation_budget(tmp_path):
    import shutil

    from chat_api.middleware import GOVERNANCE_FILE
    from governance import policy_dir

    shutil.copytree(policy_dir(), tmp_path, dirs_exist_ok=True)
    path = tmp_path / GOVERNANCE_FILE
    path.write_text(path.read_text(encoding="utf-8").replace("burst_limit: 50", "burst_limit: 20"), encoding="utf-8")
    with pytest.raises(PolicyError, match="burst_limit"):
        load_governance(tmp_path)


def test_detector_memory_is_bounded():
    detector = BoundedRogueAgentDetector()
    for i in range(2000):
        detector.record_action("a", "get_sleep_records", "get_sleep_records", timestamp=float(i))
        detector.assess("a", timestamp=float(i))
    assert len(detector.entropy_scorer._actions["a"]) <= 500
    assert len(detector.assessments) <= 100
