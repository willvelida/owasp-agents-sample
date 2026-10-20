"""The governed agent against the real health MCP server, in process: pinning on connect and wrapped results."""

from contextlib import asynccontextmanager

import httpx
import pytest
from agent_framework import Agent, Content, MiddlewareFailure
from conftest import ENV
from test_mcp_tools import SpyRepository
from test_tool_governance import ScriptedClient, call

from chat_api.agent import BiotrackrAgent
from chat_api.auth import current_principal, principal_from_claims
from chat_api.mcp_pinning import DescriptorPinError, PinnedMCPStreamableHTTPTool
from chat_api.middleware import build_middleware, load_governance
from chat_api.tools_report import build_report_tools
from governance import descriptors
from health_mcp.auth import HealthTokenVerifier
from health_mcp.server import build_server


@asynccontextmanager
async def governed(mcp_validator, sim, turns, pinned, *, agent_cls=Agent, extra_tools=(), fresh_tokens=False):
    """Serves the MCP app in process and yields (repo, agent, model client); closes the MCP client first.

    fresh_tokens mints a new OBO token for every request, like the offline simulator (the sidecar caches).
    """
    repo = SpyRepository()
    server = build_server(repo, HealthTokenVerifier(mcp_validator), issuer_url=sim.issuer)
    bearer = "Bearer " + await sim.obo(sim.user_token("alice"), ENV["CHAT_AGENT_APP_ID"])
    obo_claims = {
        "aud": ENV["HEALTH_MCP_APP_ID"],
        "azp": ENV["CHAT_AGENT_APP_ID"],
        "scp": "Health.Read",
        "oid": ENV["ALICE_OID"],
        "sub": ENV["ALICE_OID"],
        "idtyp": "user",
    }

    def headers(_):
        return {"Authorization": "Bearer " + sim._sign(obo_claims) if fresh_tokens else bearer}

    current_principal.set(principal_from_claims({"oid": ENV["ALICE_OID"]}, "token"))
    governance = load_governance()
    app = server.streamable_http_app()
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http,
    ):
        health = PinnedMCPStreamableHTTPTool(
            name="health",
            url="http://testserver/mcp",
            http_client=http,
            header_provider=headers,
            allowed_tools=governance.allowed_tools,
            pinned=pinned,
        )
        client = ScriptedClient(turns)
        agent = agent_cls(client=client, tools=[health, *extra_tools], middleware=build_middleware(governance))
        try:
            yield repo, agent, client
        finally:
            await health.close()


async def test_real_mcp_result_is_screened_wrapped_and_note_free(mcp_validator, sim):
    turns = [[call("get_food_by_date", arguments='{"date": "2026-10-14"}')], [Content.from_text("ok")]]
    async with governed(mcp_validator, sim, turns, descriptors.load_lock()) as (repo, agent, client):
        await agent.run("What did I eat on 2026-10-14?", session=agent.create_session())
    assert repo.queries == [("by_date", "food", "2026-10-14")]
    sent = "\n".join(str(c.result) for m in client.requests[1] for c in m.contents if c.type == "function_result")
    assert '<untrusted-data tool="get_food_by_date">' in sent
    assert "has_note" in sent and "CARE TEAM" not in sent


async def test_descriptor_mismatch_fails_the_run_before_the_model(mcp_validator, sim):
    pinned = descriptors.load_lock()
    pinned["get_food_by_date"] = "sha256:" + "0" * 64
    async with governed(mcp_validator, sim, [[call("get_food_by_date")]], pinned) as (repo, agent, client):
        with pytest.raises(Exception) as caught:
            await agent.run("What did I eat?", session=agent.create_session())
    chain = [caught.value, caught.value.__cause__, caught.value.__context__]
    assert any(isinstance(e, DescriptorPinError) or "do not match the lock" in str(e) for e in chain if e)
    assert not isinstance(caught.value, MiddlewareFailure)
    assert client.calls == 0
    assert repo.queries == []


@pytest.mark.parametrize("agent_cls", [Agent, BiotrackrAgent], ids=["maf-agent", "biotrackr-agent"])
async def test_agui_server_tools_with_connected_mcp(mcp_validator, sim, agent_cls):
    """ag-ui passes connected MCP functions back as run tools when an approval tool exists (S3 regression)."""
    from agent_framework_ag_ui._tooling import collect_server_tools

    reports = build_report_tools(object(), approval_required=("generate_report",))
    turns = [
        [call("get_food_by_date", arguments='{"date": "2026-10-14"}')],
        [Content.from_text("one")],
        [Content.from_text("two")],
    ]
    pinned = descriptors.load_lock()
    async with governed(
        mcp_validator, sim, turns, pinned, agent_cls=agent_cls, extra_tools=reports, fresh_tokens=True
    ) as (_, agent, _c):
        session = agent.create_session()
        await agent.run("What did I eat on 2026-10-14?", session=session)  # connects the MCP tool
        server_tools = collect_server_tools(agent)
        assert any(t.name == "get_food_by_date" for t in server_tools)
        if agent_cls is Agent:
            with pytest.raises(ValueError, match="Duplicate tool name"):
                await agent.run("and again?", session=session, tools=server_tools)
        else:
            assert (await agent.run("and again?", session=session, tools=server_tools)).text == "two"
