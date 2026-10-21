"""ASI10 kill switch, fail-closed contract row: an engaged switch refuses every run before the model call."""

import asyncio

import pytest
from agent_framework import Agent, InMemoryHistoryProvider, MiddlewareFailure
from conftest import ENV
from test_tool_governance import ScriptedClient, Tools, call

from chat_api.auth import current_principal, principal_from_claims
from chat_api.middleware import build_middleware, load_governance
from chat_api.middleware.audit import AuditTrail, MemorySink
from chat_api.middleware.kill_switch import (
    SUSPENDED_REPLY,
    AppConfigKillSwitch,
    EnvKillSwitch,
    from_environment,
    parse,
)


class Switch:
    source = "test"

    def __init__(self, *values: bool) -> None:
        self.values = list(values)
        self.checks = 0

    async def engaged(self) -> bool:
        self.checks += 1
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


def make(switch, turns, *, history=None):
    tools, sink = Tools(), MemorySink()
    client = ScriptedClient(turns)
    agent = Agent(
        client=client,
        tools=tools.all,
        middleware=build_middleware(load_governance(), kill_switch=switch, audit=AuditTrail(sink)),
        context_providers=[history] if history else None,
    )
    return agent, client, tools, sink


async def text_of(agent, prompt, *, stream, session=None):
    session = session or agent.create_session()
    if stream:
        return "".join([u.text or "" async for u in agent.run(prompt, stream=True, session=session)])
    return (await agent.run(prompt, session=session)).text


@pytest.mark.parametrize("stream", [False, True], ids=["run", "stream"])
async def test_engaged_switch_refuses_before_any_model_or_tool_call(stream):
    history = InMemoryHistoryProvider()
    agent, client, tools, sink = make(Switch(True), [[call("get_sleep_records")]], history=history)
    session = agent.create_session()
    assert await text_of(agent, "How did I sleep?", stream=stream, session=session) == SUSPENDED_REPLY
    assert client.calls == 0
    assert tools.executed == []
    stored = await history.get_messages(session.session_id, state=session.state.get(history.source_id, {}))
    assert stored == []
    assert any(r["event_type"] == "kill_switch" and r["outcome"] == "denied" for r in sink.records)


@pytest.mark.parametrize("stream", [False, True], ids=["run", "stream"])
async def test_disengaged_switch_lets_the_run_through(stream):
    agent, client, *_ = make(Switch(False), [])
    assert await text_of(agent, "Hello", stream=stream) == "done"
    assert client.calls == 1


async def test_switch_flipped_mid_run_stops_the_next_tool_call():
    current_principal.set(principal_from_claims({"oid": ENV["ALICE_OID"], "name": "alice"}, "token"))
    # Run start: off. Tool call: on. The batch is aborted and the tool never runs.
    agent, _, tools, _ = make(Switch(False, True), [[call("get_sleep_records")]])
    with pytest.raises(MiddlewareFailure, match="Kill switch engaged"):
        await text_of(agent, "How did I sleep?", stream=False)
    assert tools.executed == []


async def test_a_failing_check_refuses_the_run():
    class Broken:
        source = "broken"

        async def engaged(self) -> bool:
            raise RuntimeError("store down")

    agent, client, *_ = make(Broken(), [])
    assert await text_of(agent, "Hello", stream=False) == SUSPENDED_REPLY
    assert client.calls == 0


@pytest.mark.parametrize(
    ("value", "engaged"),
    [("off", False), ("OFF", False), ("false", False), ("0", False), ("on", True), ("true", True), ("maybe", True)],
)
def test_parse_fails_closed_on_unknown_values(value, engaged):
    assert parse(value) is engaged


async def test_env_switch_reads_the_environment_each_time(monkeypatch):
    switch = EnvKillSwitch()
    monkeypatch.setenv("AGENT_KILL_SWITCH", "off")
    assert await switch.engaged() is False
    monkeypatch.setenv("AGENT_KILL_SWITCH", "on")
    assert await switch.engaged() is True
    monkeypatch.delenv("AGENT_KILL_SWITCH")
    assert await switch.engaged() is False


def test_app_configuration_is_used_when_an_endpoint_is_set(monkeypatch):
    monkeypatch.delenv("APP_CONFIG_ENDPOINT", raising=False)
    assert isinstance(from_environment(), EnvKillSwitch)


class Setting:
    def __init__(self, value: str) -> None:
        self.value = value


class FakeAppConfig:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.reads = 0

    async def get_configuration_setting(self, *, key: str):
        self.reads += 1
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, BaseException):
            raise result
        if result == "hang":
            await asyncio.sleep(5)
        return Setting(result)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_app_configuration_reads_are_cached_for_the_ttl():
    clock, client = Clock(), FakeAppConfig("off", "on")
    switch = AppConfigKillSwitch("https://x", client=client, clock=clock)
    assert await switch.engaged() is False
    clock.now += 9
    assert await switch.engaged() is False
    assert client.reads == 1
    clock.now += 2
    assert await switch.engaged() is True
    assert client.reads == 2


@pytest.mark.parametrize(
    "failure", [RuntimeError("unreachable"), KeyError("missing key"), "hang"], ids=["error", "missing", "timeout"]
)
async def test_app_configuration_fails_closed_once_the_cache_expires(failure):
    clock, client = Clock(), FakeAppConfig("off", failure)
    switch = AppConfigKillSwitch("https://x", client=client, clock=clock, timeout=0.1)
    assert await switch.engaged() is False
    clock.now += 11
    assert await switch.engaged() is True


def test_agui_streams_the_fixed_reply_as_text(chat_validator, sim):
    from fastapi.testclient import TestClient
    from test_chat_auth import SpyStore, agui_body

    from chat_api.app import create_app
    from chat_api.auth import RequireUser

    agent, client, *_ = make(Switch(True), [[call("get_sleep_records")]])
    app = TestClient(create_app(agent, SpyStore(), RequireUser(chat_validator)))
    response = app.post("/", json=agui_body("t1"), headers={"Authorization": f"Bearer {sim.user_token('alice')}"})
    events = [line for line in response.text.splitlines() if line.startswith("data:")]
    assert response.status_code == 200
    assert "RUN_ERROR" not in response.text
    assert any("TEXT_MESSAGE_CONTENT" in e and "paused by its operators" in e for e in events)
    assert client.calls == 0
