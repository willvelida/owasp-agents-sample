"""Governance middleware attached to the chat Agent itself, so the AG-UI endpoint and DevUI are both governed."""

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chat_api.middleware.input_guard import InputGuard
from chat_api.middleware.output_guard import OutputGuard
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
    tool_limits: Mapping[str, int] = field(default_factory=dict)
    approval_required: tuple[str, ...] = ()

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
        tool_limits = {str(k): int(v) for k, v in (data.get("tool_limits") or {}).items()}
        approval_required = tuple(str(t) for t in data.get("approval_required", []))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PolicyError(f"{GOVERNANCE_FILE} is invalid: {exc}") from exc
    if not allowed or policy.max_tool_calls < 1 or max_page_size < 1:
        raise PolicyError(f"{GOVERNANCE_FILE} must allow at least one tool, one call, and a page size of 1")
    if any(v < 1 for v in tool_limits.values()) or not set(tool_limits) | set(approval_required) <= set(allowed):
        raise PolicyError(f"{GOVERNANCE_FILE}: tool_limits and approval_required must name allowed tools")
    return Governance(
        policy=policy,
        agent_id=agent_id,
        denied_tools=denied,
        max_page_size=max_page_size,
        tool_limits=tool_limits,
        approval_required=approval_required,
    )


def build_middleware(
    governance: Governance,
    *,
    screener: Screener | None = None,
    budget: ToolBudget | None = None,
    output_guard: OutputGuard | None = None,
    enable_rogue_detection: bool = True,
) -> list[Any]:
    screener = screener or Screener.from_policy()
    budget = budget or ToolBudget(governance.policy.max_tool_calls, tool_limits=governance.tool_limits)
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
    # ASI01, ASI02, ASI09. Order within each kind is outermost first, so the AGT audit trail records blocked runs
    # too. The output guard is the outermost chat middleware: it sees the final reply after the batch gate.
    return [
        *agt,
        InputGuard(screener),
        *([output_guard] if output_guard is not None else []),
        ToolBatchGuard(rules, budget),
        ToolCallGuard(rules),
        ToolResultGuard(screener),
    ]
