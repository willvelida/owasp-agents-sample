"""Governance middleware attached to the chat Agent itself, so the AG-UI endpoint and DevUI are both governed."""

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chat_api.middleware.audit import AuditTrail
from chat_api.middleware.input_guard import InputGuard
from chat_api.middleware.kill_switch import KillSwitch, KillSwitchGuard, KillSwitchToolGuard, from_environment
from chat_api.middleware.output_guard import OutputGuard
from chat_api.middleware.resilience import GracefulDegradation, TokenAccounting, TokenBudgetGate
from chat_api.middleware.rogue_guard import PerUserRogueDetection, RogueGate, RogueGuard, RogueSettings
from chat_api.middleware.screening import Screener
from chat_api.middleware.tool_policy import FailClosed, ToolBatchGuard, ToolCallGuard, ToolRules
from chat_api.middleware.tool_result_guard import ToolResultGuard
from chat_api.session_store import TokenBudget, ToolBudget
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
    max_tokens_per_conversation: int = 400_000
    max_output_tokens: int = 2_000
    rogue: RogueSettings = field(default_factory=RogueSettings)

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
        max_tokens = int(data.get("max_tokens_per_conversation", 400_000))
        max_output_tokens = int(data.get("max_output_tokens", 2_000))
        rogue_data = data.get("rogue_detection") or {}
        rogue = RogueSettings(
            burst_limit=int(rogue_data.get("burst_limit", 50)),
            burst_window_seconds=float(rogue_data.get("burst_window_seconds", 120)),
            quarantine_seconds=float(rogue_data.get("quarantine_seconds", 300)),
            quarantine_risk_level=str(rogue_data.get("quarantine_risk_level", "critical")),
            frequency_window_seconds=float(rogue_data.get("frequency_window_seconds", 60)),
            frequency_min_windows=int(rogue_data.get("frequency_min_windows", 10)),
        )
        rogue.detector_config()
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PolicyError(f"{GOVERNANCE_FILE} is invalid: {exc}") from exc
    if not allowed or policy.max_tool_calls < 1 or max_page_size < 1:
        raise PolicyError(f"{GOVERNANCE_FILE} must allow at least one tool, one call, and a page size of 1")
    if any(v < 1 for v in tool_limits.values()) or not set(tool_limits) | set(approval_required) <= set(allowed):
        raise PolicyError(f"{GOVERNANCE_FILE}: tool_limits and approval_required must name allowed tools")
    if max_tokens < 1 or max_output_tokens < 1:
        raise PolicyError(f"{GOVERNANCE_FILE}: token limits must be at least 1")
    if rogue.burst_limit <= policy.max_tool_calls or rogue.quarantine_seconds <= 0 or rogue.burst_window_seconds <= 0:
        # Below the per-conversation budget, one ordinary conversation could quarantine its own user.
        raise PolicyError(f"{GOVERNANCE_FILE}: rogue_detection.burst_limit must exceed max_tool_calls")
    return Governance(
        policy=policy,
        agent_id=agent_id,
        denied_tools=denied,
        max_page_size=max_page_size,
        tool_limits=tool_limits,
        approval_required=approval_required,
        max_tokens_per_conversation=max_tokens,
        max_output_tokens=max_output_tokens,
        rogue=rogue,
    )


def build_middleware(
    governance: Governance,
    *,
    screener: Screener | None = None,
    budget: ToolBudget | None = None,
    output_guard: OutputGuard | None = None,
    audit: AuditTrail | None = None,
    kill_switch: KillSwitch | None = None,
    rogue: RogueGuard | None = None,
    tokens: TokenBudget | None = None,
) -> list[Any]:
    screener = screener or Screener.from_policy()
    budget = budget or ToolBudget(governance.policy.max_tool_calls, tool_limits=governance.tool_limits)
    audit = audit or AuditTrail()
    kill_switch = kill_switch or from_environment()
    rogue = rogue or RogueGuard(
        governance.rogue, allowed_tools=governance.allowed_tools, agent_id=governance.agent_id, audit=audit
    )
    tokens = tokens or TokenBudget(governance.max_tokens_per_conversation)
    rules = ToolRules(governance.allowed_tools, governance.denied_tools, governance.max_page_size)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        # AGT 5.0 MAF adapter, legacy path: audit trail and capability guard, writing to the hash-chained audit
        # trail (ASI10). The policy= (v5) path needs the ACS engine, which ships for Linux x86_64 only. AGT's own
        # rogue detection scores the shared agent across all users, so it runs per user instead (rogue_guard.py).
        agt = create_governance_middleware(
            allowed_tools=governance.allowed_tools,
            denied_tools=list(governance.denied_tools),
            agent_id=governance.agent_id,
            enable_rogue_detection=False,
            audit_log=audit,
        )
    agt = [FailClosed(m) if isinstance(m, FunctionMiddleware) else m for m in agt]
    # Order within each kind is outermost first. Agent: the audit trail records every run, including refused ones;
    # the kill switch, quarantine, and token budget answer before input screening or any model call; degradation
    # wraps only the run itself. Chat: the output guard sees the final reply after the batch gate. Function: the
    # kill switch and rogue detection run before the per-call policy and result screening.
    return [
        *agt,
        KillSwitchGuard(kill_switch, audit=audit, agent_id=governance.agent_id),
        RogueGate(rogue),
        TokenBudgetGate(tokens, audit=audit),
        InputGuard(screener),
        GracefulDegradation(output_guard, audit=audit),
        *([output_guard] if output_guard is not None else []),
        TokenAccounting(tokens),
        ToolBatchGuard(rules, budget),
        KillSwitchToolGuard(kill_switch),
        PerUserRogueDetection(rogue),
        ToolCallGuard(rules),
        ToolResultGuard(screener),
    ]
