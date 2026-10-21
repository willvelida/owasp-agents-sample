"""ASI08 bulkhead: each signed-in user has their own health MCP session, so one user's stall cannot hold another's."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from agent_framework import Content
from conftest import ENV
from test_mcp_tools import SpyRepository
from test_tool_governance import ScriptedClient, call

from chat_api.agent import BiotrackrAgent, IdentityProvider
from chat_api.auth import current_principal, principal_from_claims
from chat_api.identity import IdentityError, mcp_authorization
from chat_api.mcp_pool import UserMCPTool, UserMCPTools
from chat_api.middleware import build_middleware, load_governance
from chat_api.middleware.resilience import CircuitBreaker
from governance import descriptors
from health_mcp.auth import HealthTokenVerifier
from health_mcp.server import build_server


class FreshTokens:
    """Like the offline simulator: a new OBO token for every run."""

    def __init__(self, sim) -> None:
        self.sim = sim
        self.issued = 0

    async def health_mcp_header(self, principal) -> str:
        self.issued += 1
        user = "alice" if principal.oid == ENV["ALICE_OID"] else "bob"
        return "Bearer " + await self.sim.obo(self.sim.user_token(user), ENV["CHAT_AGENT_APP_ID"])


def as_user(name: str) -> None:
    current_principal.set(principal_from_claims({"oid": ENV[f"{name.upper()}_OID"], "name": name}, "token"))


async def sign_in(name: str, tokens: FreshTokens) -> None:
    """What IdentityProvider does before acquiring the user's tool."""
    as_user(name)
    mcp_authorization.set(await tokens.health_mcp_header(current_principal.get()))


@asynccontextmanager
async def pool_against_real_server(mcp_validator, sim, **pool_kwargs):
    repo = SpyRepository()
    server = build_server(repo, HealthTokenVerifier(mcp_validator), issuer_url=sim.issuer)
    governance = load_governance()
    connects: dict[str, int] = {}
    handshakes: list[str] = []

    async def count_handshakes(request: httpx.Request) -> None:
        if b'"method":"initialize"' in request.content.replace(b" ", b""):
            handshakes.append(request.headers.get("authorization", ""))

    app = server.streamable_http_app()
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            event_hooks={"request": [count_handshakes]},
        ) as http,
    ):

        def factory(oid: str) -> UserMCPTool:
            from chat_api.identity import mcp_headers

            tool = UserMCPTool(
                name="health",
                url="http://testserver/mcp",
                http_client=http,
                header_provider=mcp_headers,
                allowed_tools=governance.allowed_tools,
                pinned=descriptors.load_lock(),
                breaker=CircuitBreaker("health-mcp"),
                owner=oid,
            )
            original = tool.connect

            async def counted(*, reset: bool = False) -> None:
                connects[oid] = connects.get(oid, 0) + 1
                await original(reset=reset)

            tool.connect = counted
            return tool

        pool = UserMCPTools(factory, function_names=governance.allowed_tools, **pool_kwargs)
        pool.handshakes = handshakes
        try:
            yield pool, repo, connects, governance
        finally:
            await pool.close()


def agent_for(pool, governance, tokens, turns):
    client = ScriptedClient(turns)
    agent = BiotrackrAgent(
        client=client,
        user_tools=pool,
        middleware=build_middleware(governance),
        context_providers=[IdentityProvider(tokens, user_tools=pool)],
    )
    return agent, client


def steps_turns(day: int):
    return [[call("get_activity_by_date", str(day), f'{{"date": "2026-10-{day:02d}"}}')], [Content.from_text("ok")]]


def results(client) -> list[str]:
    return [str(c.result) for m in client.requests[-1] for c in m.contents if c.type == "function_result"]


async def test_each_user_gets_their_own_session_and_a_refresh_does_not_reconnect(mcp_validator, sim):
    tokens = FreshTokens(sim)
    async with pool_against_real_server(mcp_validator, sim) as (pool, repo, connects, governance):
        for name in ("alice", "bob", "alice", "bob"):
            as_user(name)
            agent, client = agent_for(pool, governance, tokens, steps_turns(14))
            await agent.run("steps", session=agent.create_session())
            assert len(results(client)) == 1 and "Error" not in results(client)[0]
        assert len(pool) == 2
        # Four runs with four different tokens: one connect per user, no identity-change reconnects.
        assert connects == {ENV["ALICE_OID"]: 1, ENV["BOB_OID"]: 1} and tokens.issued == 4
        assert len(pool.handshakes) == 2  # MAF reconnects outside connect(); count the MCP handshakes themselves
        assert len(repo.queries) == 4


async def test_one_users_stalled_session_does_not_hold_another_users_calls(mcp_validator, sim):
    tokens = FreshTokens(sim)
    async with pool_against_real_server(mcp_validator, sim) as (pool, _, _, governance):
        await sign_in("bob", tokens)
        bobs_tool = await pool.acquire(ENV["BOB_OID"])
        stalled = asyncio.Event()

        async def hang(tool_name: str, **kwargs):
            stalled.set()
            await asyncio.Event().wait()

        bobs_tool.call_tool = hang
        bob, _ = agent_for(pool, governance, tokens, steps_turns(1))
        bob_run = asyncio.create_task(bob.run("steps", session=bob.create_session()))
        await asyncio.wait_for(stalled.wait(), 10)

        as_user("alice")
        alice, client = agent_for(pool, governance, tokens, steps_turns(14))
        async with asyncio.timeout(10):
            await alice.run("steps", session=alice.create_session())
        assert len(results(client)) == 1 and "Error" not in results(client)[0]
        bob_run.cancel()


async def test_concurrent_runs_of_one_user_connect_once(mcp_validator, sim):
    async with pool_against_real_server(mcp_validator, sim) as (pool, _, connects, _):
        await sign_in("bob", FreshTokens(sim))
        tools = await asyncio.gather(*(pool.acquire(ENV["BOB_OID"]) for _ in range(5)))
        assert len({id(t) for t in tools}) == 1 and connects == {ENV["BOB_OID"]: 1}


async def test_a_users_tool_refuses_another_principal(mcp_validator, sim):
    tokens = FreshTokens(sim)
    async with pool_against_real_server(mcp_validator, sim) as (pool, _, _, _):
        await sign_in("alice", tokens)
        alices_tool = await pool.acquire(ENV["ALICE_OID"])
        as_user("bob")
        bearer = await tokens.health_mcp_header(current_principal.get())
        with pytest.raises(IdentityError):
            await alices_tool._ensure_session_identity({"Authorization": bearer}, {})


async def test_least_recently_used_users_are_closed(mcp_validator, sim):
    tokens = FreshTokens(sim)
    async with pool_against_real_server(mcp_validator, sim, max_users=1, close_after_seconds=0) as (pool, _, _, _):
        await sign_in("alice", tokens)
        alices_tool = await pool.acquire(ENV["ALICE_OID"])
        await sign_in("bob", tokens)
        await pool.acquire(ENV["BOB_OID"])
        assert len(pool) == 1
        for _ in range(50):
            if not alices_tool.is_connected:
                break
            await asyncio.sleep(0.05)
        assert not alices_tool.is_connected
