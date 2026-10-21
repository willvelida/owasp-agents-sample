"""Memory poisoning controls for conversation history (ASI06).

* Bounded memory: every text field of a stored message is capped at 10,000 characters, a conversation keeps its
  last 100 messages, and a run is hydrated with at most the last 50 (cut at a user turn, so a tool call is never
  separated from its result). Conversations expire 90 days after their last write (container default TTL).
* Screened writes: AGT `MemoryGuard.validate_write` checks every message of a turn before it is stored. If any
  message is flagged (high or critical: injection phrasing, code injection, hidden-instruction markup carrying a
  standing instruction, bidirectional control characters), the whole turn is dropped from memory, so a planted
  instruction never reaches a later run.
* Integrity on read: each stored message carries the SHA-256 that AGT `MemoryEntry` computes over it; a turn whose
  message no longer matches its hash, or that AGT's checks now flag, is left out of the hydrated history.

AGT 5.0 `agent_os.memory_guard.MemoryGuard` API (installed wheel): `validate_write(content, source) ->
ValidationResult(allowed, alerts)`, `verify_integrity(MemoryEntry) -> bool`, `scan_memory(entries) -> alerts`,
and an in-memory `audit_log` that grows with every write, so a fresh guard is used per check.
"""

import json
import logging
import warnings
from collections.abc import Mapping, Sequence
from typing import Any

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from agent_os.memory_guard import AlertSeverity, MemoryEntry, MemoryGuard

log = logging.getLogger("chat_api.middleware.memory_guard")

MAX_HYDRATED_MESSAGES = 50
MAX_STORED_MESSAGES = 100
MAX_FIELD_CHARS = 10_000
TTL_SECONDS = 90 * 24 * 60 * 60
TRUNCATED = " [truncated]"
_BLOCKING = {AlertSeverity.HIGH, AlertSeverity.CRITICAL}


def cap_fields(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    """Copies a message dict with every string longer than `limit` cut to `limit` characters."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - len(TRUNCATED)] + TRUNCATED
    if isinstance(value, Mapping):
        return {k: cap_fields(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [cap_fields(v, limit) for v in value]
    return value


def digest(message: Mapping[str, Any]) -> str:
    return MemoryEntry.compute_hash(json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def message_text(message: Mapping[str, Any]) -> str:
    """What the model will read back from this message: text, tool arguments, and tool results."""
    parts: list[str] = []
    for content in message.get("contents") or []:
        for key in ("text", "arguments", "result"):
            value = content.get(key)
            if isinstance(value, str):
                parts.append(value)
            elif value is not None and key != "text":
                parts.append(json.dumps(value, ensure_ascii=False))
    return "\n".join(parts)


def turn_starts(messages: Sequence[Mapping[str, Any]]) -> list[int]:
    starts = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    return starts if starts and starts[0] == 0 else [0, *starts]


def _turn_ranges(messages: Sequence[Mapping[str, Any]]) -> list[range]:
    if not messages:
        return []
    starts = turn_starts(messages)
    return [range(s, e) for s, e in zip(starts, [*starts[1:], len(messages)], strict=True)]


def keep_last(messages: list[Any], limit: int, role_of: Any = lambda m: m.get("role")) -> list[Any]:
    """The last `limit` messages, starting at a user turn when one exists in that window."""
    if len(messages) <= limit:
        return messages
    start = len(messages) - limit
    for i in range(start, len(messages)):
        if role_of(messages[i]) == "user":
            return messages[i:]
    return messages[start:]


def _drop_orphan_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls = {c.get("call_id") for m in messages for c in m.get("contents") or [] if c.get("type") == "function_call"}
    kept = []
    for message in messages:
        contents = [
            c for c in message.get("contents") or [] if c.get("type") != "function_result" or c.get("call_id") in calls
        ]
        if contents:
            kept.append({**message, "contents": contents})
    return kept


class MemoryGate:
    def __init__(self, *, audit: Any = None) -> None:
        self._audit = audit

    def _log(self, action: str, dropped: int, reason: str) -> None:
        log.warning("memory guard %s: %d message(s) (%s)", action, dropped, reason)
        if self._audit is not None:
            self._audit.log(
                event_type="memory_guard",
                agent_did="memory-guard",
                action=action,
                data={"dropped": dropped, "reason": reason},
                outcome="denied",
            )

    def screen_turn(self, messages: Sequence[Mapping[str, Any]]) -> list[str]:
        """Blocking alerts for a turn about to be stored; empty means the write may proceed."""
        guard = MemoryGuard()
        flagged: list[str] = []
        for message in messages:
            result = guard.validate_write(message_text(message), source=f"chat:{message.get('role')}")
            flagged.extend(a.alert_type.value for a in result.alerts if a.severity in _BLOCKING)
        if flagged:
            self._log("drop_write", len(messages), ",".join(sorted(set(flagged))))
        return flagged

    def hydrate(self, messages: Sequence[dict[str, Any]], hashes: Sequence[str]) -> list[dict[str, Any]]:
        """The stored messages a run may see: intact, unflagged turns, bounded, with no orphan tool results."""
        guard = MemoryGuard()
        bad: set[int] = set()
        for i, message in enumerate(messages):
            if i >= len(hashes) or digest(message) != hashes[i]:
                bad.add(i)
                continue
            result = guard.validate_write(message_text(message), source=f"history:{message.get('role')}")
            if any(a.severity in _BLOCKING for a in result.alerts):
                bad.add(i)
        kept: list[dict[str, Any]] = []
        dropped = 0
        for turn in _turn_ranges(messages):
            if bad.intersection(turn):
                dropped += len(turn)
            else:
                kept.extend(messages[i] for i in turn)
        if dropped:
            self._log("drop_on_read", dropped, "integrity or content check failed")
        return _drop_orphan_results(keep_last(kept, MAX_HYDRATED_MESSAGES))
