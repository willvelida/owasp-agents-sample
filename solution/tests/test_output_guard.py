"""ASI09 output policy, fail-closed contract row: a classifier error, timeout, or unsafe or indeterminate verdict
gives the fixed refusal and disclaimer. Nothing the model wrote reaches the client or the history.
"""

import asyncio

import pytest
from agent_framework import Agent, Content, InMemoryHistoryProvider
from test_tool_governance import ScriptedClient

from chat_api.middleware import build_middleware, load_governance
from chat_api.middleware.output_guard import FIXED_REPLY, OutputGuard, parse_verdict

UNSAFE = "You have hypertension. Stop taking your metoprolol and double your lisinopril."
SAFE = "Your average was 7,939 steps (activity, 2026-10-13)."


class SpyClassifier:
    def __init__(self, behaviour) -> None:
        self.behaviour = behaviour
        self.seen: list[tuple[str, str]] = []

    async def __call__(self, question: str, reply: str) -> str:
        self.seen.append((question, reply))
        result = self.behaviour(reply)
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, Exception):
            raise result
        return result


def make(turns, classifier, *, history=None):
    client = ScriptedClient(turns)
    guard = OutputGuard(classifier, timeout=0.2)
    agent = Agent(
        client=client,
        middleware=build_middleware(load_governance(), output_guard=guard),
        context_providers=[history] if history else None,
    )
    return agent, client


async def reply_text(agent, prompt, *, stream, session=None):
    session = session or agent.create_session()
    if stream:
        updates = [u async for u in agent.run(prompt, stream=True, session=session)]
        return "".join(u.text or "" for u in updates)
    return (await agent.run(prompt, session=session)).text


FAULTS = {
    "unsafe": lambda reply: "unsafe",
    "indeterminate": lambda reply: "indeterminate",
    "error": lambda reply: RuntimeError("classifier down"),
    "timeout": lambda reply: asyncio.sleep(5),
}


@pytest.mark.parametrize("stream", [False, True], ids=["run", "stream"])
@pytest.mark.parametrize("fault", FAULTS.values(), ids=FAULTS.keys())
async def test_classifier_faults_give_the_fixed_refusal(fault, stream):
    classifier = SpyClassifier(fault)
    agent, _ = make([[Content.from_text(UNSAFE)]], classifier)
    text = await reply_text(agent, "Should I stop my blood pressure pills?", stream=stream)
    assert text == FIXED_REPLY
    assert "metoprolol" not in text
    assert classifier.seen == [("Should I stop my blood pressure pills?", UNSAFE)]


@pytest.mark.parametrize("stream", [False, True], ids=["run", "stream"])
async def test_safe_reply_passes_unchanged(stream):
    classifier = SpyClassifier(lambda reply: "safe")
    agent, _ = make([[Content.from_text(SAFE)]], classifier)
    assert await reply_text(agent, "How many steps did I do?", stream=stream) == SAFE


async def test_streamed_updates_are_held_until_the_verdict():
    released = asyncio.Event()

    async def slow(reply):
        await released.wait()
        return "unsafe"

    agent, _ = make([[Content.from_text(UNSAFE)]], SpyClassifier(slow))
    seen: list[str] = []

    async def consume():
        async for update in agent.run("diagnose me", stream=True):
            seen.append(update.text or "")

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    assert "".join(seen) == ""  # nothing escaped while the classifier was still thinking
    released.set()
    await task
    assert "".join(seen) == FIXED_REPLY


async def test_multi_turn_each_reply_is_checked_and_history_keeps_the_refusal():
    verdicts = iter(["safe", "unsafe"])
    classifier = SpyClassifier(lambda reply: next(verdicts))
    history = InMemoryHistoryProvider()
    agent, client = make([[Content.from_text(SAFE)], [Content.from_text(UNSAFE)]], classifier, history=history)
    session = agent.create_session()
    assert await reply_text(agent, "How many steps?", stream=True, session=session) == SAFE
    assert await reply_text(agent, "So should I change my medication?", stream=True, session=session) == FIXED_REPLY
    assert len(classifier.seen) == 2
    stored = await history.get_messages(session.session_id, state=session.state.get(history.source_id, {}))
    stored_text = " ".join(m.text or "" for m in stored)
    assert "metoprolol" not in stored_text and FIXED_REPLY in stored_text


async def test_tool_call_turns_without_text_skip_the_classifier():
    from conftest import ENV
    from test_tool_governance import Tools, call

    from chat_api.auth import current_principal, principal_from_claims

    current_principal.set(principal_from_claims({"oid": ENV["ALICE_OID"], "name": "alice"}, "token"))
    classifier = SpyClassifier(lambda reply: "safe")
    tools = Tools()
    client = ScriptedClient([[call("get_sleep_records")], [Content.from_text(SAFE)]])
    agent = Agent(
        client=client,
        tools=tools.all,
        middleware=build_middleware(load_governance(), output_guard=OutputGuard(classifier, timeout=0.2)),
    )
    assert (await agent.run("sleep?", session=agent.create_session())).text == SAFE
    assert tools.executed == ["get_sleep_records"]
    assert [reply for _, reply in classifier.seen] == [SAFE]


@pytest.mark.parametrize(
    ("text", "verdict"),
    [
        ('{"verdict": "safe"}', "safe"),
        ('{"verdict": "unsafe"}', "unsafe"),
        ('{"verdict": "SAFE"}', "indeterminate"),
        ("safe", "indeterminate"),
        ('{"verdict": true}', "indeterminate"),
        ("", "indeterminate"),
    ],
)
def test_parse_verdict_is_strict(text, verdict):
    assert parse_verdict(text) == verdict
