"""Governance middleware attached to the chat Agent itself, so the AG-UI endpoint and DevUI are both governed."""

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chat_api.middleware.input_guard import InputGuard
from chat_api.middleware.screening import Screener
from chat_api.middleware.tool_policy import FailClosed, ToolBatchGuard, ToolCallGuard, ToolRules
from chat_api.middleware.tool_result_guard import ToolResultGuard
from chat_api.session_store import ToolBudget
from governance import PolicyError, load_yaml

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from agent_framework import FunctionMiddleware
    from agent_os.integrations.base import GovernancePolicy
    from agent_os.integrations.maf_adapter import create_governance_middleware

GOVERNANCE_FILE = "governance.yaml"

__all__ = ["Governance", "build_middleware", "load_governance"]


@dataclass(frozen=True)
class Governance:
    policy: GovernancePolicy
    agent_id: str
    denied_tools: tuple[str, ...]
    max_page_size: int = 50

    @property
    def allowed_tools(self) -> list[str]:
        return list(self.policy.allowed_tools)


def load_governance(directory: Path | None = None) -> Governance:
    data = load_yaml(GOVERNANCE_FILE, directory)
    try:
        allowed = [str(t) for t in data["allowed_tools"]]
        policy = GovernancePolicy(
            name=str(data["name"]), max_tool_calls=int(data["max_tool_calls"]), allowed_tools=allowed
        )
        denied = tuple(str(p) for p in data.get("denied_tools", []))
        agent_id = str(data["agent_id"])
        max_page_size = int(data.get("max_page_size", 50))
    except (KeyError, TypeError, ValueError) as exc:
        raise PolicyError(f"{GOVERNANCE_FILE} is invalid: {exc}") from exc
    if not allowed or policy.max_tool_calls < 1 or max_page_size < 1:
        raise PolicyError(f"{GOVERNANCE_FILE} must allow at least one tool, one call, and a page size of 1")
    return Governance(policy=policy, agent_id=agent_id, denied_tools=denied, max_page_size=max_page_size)


def build_middleware(
    governance: Governance,
    *,
    screener: Screener | None = None,
    budget: ToolBudget | None = None,
    enable_rogue_detection: bool = True,
) -> list[Any]:
    screener = screener or Screener.from_policy()
    budget = budget or ToolBudget(governance.policy.max_tool_calls)
    rules = ToolRules(governance.allowed_tools, governance.denied_tools, governance.max_page_size)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        # AGT 5.0 MAF adapter, legacy path: audit trail, capability guard, rogue detection. The policy= (v5)
        # path needs the ACS engine, which ships for Linux x86_64 only.
        agt = create_governance_middleware(
            allowed_tools=governance.allowed_tools,
            denied_tools=list(governance.denied_tools),
            agent_id=governance.agent_id,
            enable_rogue_detection=enable_rogue_detection,
        )
    agt = [FailClosed(m) if isinstance(m, FunctionMiddleware) else m for m in agt]
    # ASI01 and ASI02. Order within each kind is outermost first, so the AGT audit trail records blocked runs too.
    return [
        *agt,
        InputGuard(screener),
        ToolBatchGuard(rules, budget),
        ToolCallGuard(rules),
        ToolResultGuard(screener),
    ]
