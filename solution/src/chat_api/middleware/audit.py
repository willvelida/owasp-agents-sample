"""Hash-chained audit trail (ASI10).

AGT's AuditTrailMiddleware, CapabilityGuardMiddleware, and RogueDetectionMiddleware write to an audit log through
`log(...)`. The solution passes them `AuditTrail`, which builds AGT `AuditEntry` objects, chains each to the
previous one (`previous_hash`, `entry_hash` = AGT's SHA-256 over the canonical fields), and hands them to a sink:
the Cosmos DB `audit` container (partition `/chainId`, one chain per process) in Compose and on Azure.

No health payloads: `data` keeps only an allowlist of scalar fields (AGT's capability guard adds a 500-character
`result_preview` of every tool result, which is dropped), and exception messages are reduced to their type. The
signed-in user's oid is recorded inside `data`, so it is covered by the hash.

Verify the stored chains (gaps in `seq` and edited or removed entries are reported):

    uv run --env-file .env python -m chat_api.middleware.audit
"""

import asyncio
import contextvars
import logging
import os
import random
import socket
import sys
import threading
import uuid
import warnings
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from opentelemetry import trace

from chat_api.auth import current_principal

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from agentmesh.governance import AuditEntry

log = logging.getLogger("chat_api.middleware.audit")

CONTAINER = "audit"
# Scalars that describe what happened, never what the user's records contain.
SAFE_KEYS = frozenset(
    {
        "agent_name",
        "message_count",
        "stream",
        "elapsed_seconds",
        "start_entry_id",
        "error",
        "tool",
        "tools",
        "risk_level",
        "composite_score",
        "frequency_score",
        "entropy_score",
        "capability_score",
        "quarantine_recommended",
        "oid",
        "session",
        "reason",
        "calls",
        "window_seconds",
        "quarantine_seconds",
        "source",
        "dropped",
        "dependency",
        "state",
        "failures",
        "tokens",
        "limit",
    }
)
HASHED_FIELDS = (
    "entry_id",
    "timestamp",
    "event_type",
    "agent_did",
    "action",
    "resource",
    "data",
    "outcome",
    "policy_decision",
    "previous_hash",
    "entry_hash",
)
_MAX_TEXT = 160
CONTROL_EVENT_FIELDS = frozenset(
    {
        "event_type",
        "action",
        "outcome",
        "decision",
        "resource",
        "tool",
        "reason",
        "risk_level",
        "error",
        "quarantine_recommended",
    }
)


def sanitise(data: Mapping[str, Any] | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (data or {}).items():
        if key not in SAFE_KEYS:
            continue
        if key == "error":
            # "MiddlewareFailure: Request blocked by input screening: ..." -> "MiddlewareFailure"
            value = str(value).split(":", 1)[0]
        if value is None or isinstance(value, bool | int | float):
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:_MAX_TEXT]
    return clean


class AuditSink(Protocol):
    def submit(self, record: dict[str, Any]) -> None: ...


class MemorySink:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def submit(self, record: dict[str, Any]) -> None:
        self.records.append(record)


class AuditTrail:
    """Append-only, hash-chained audit log with the `log()` signature of agentmesh's AuditLog.

    Only the last hash is kept in memory (AGT's in-memory AuditLog keeps every entry for the life of the process).
    """

    def __init__(self, sink: AuditSink | None = None, *, chain_id: str | None = None, keep: int = 200) -> None:
        self.chain_id = chain_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
        self._sink = sink
        self._lock = threading.Lock()
        self._seq = 0
        self._last_hash = ""
        self.recent: deque[dict[str, Any]] = deque(maxlen=keep)

    def log(
        self,
        event_type: str,
        agent_did: str,
        action: str,
        resource: str | None = None,
        data: Mapping[str, Any] | None = None,
        outcome: str = "success",
        policy_decision: str | None = None,
        trace_id: str | None = None,
        **_: Any,
    ) -> Any:
        details = sanitise(data)
        span = trace.get_current_span()
        context = span.get_span_context()
        if trace_id is None and context.is_valid:
            trace_id = f"{context.trace_id:032x}"
        if trace_id is not None:
            details["trace_id"] = trace_id
        principal = current_principal.get()
        if principal is not None:
            details.setdefault("oid", principal.oid)
        entry = AuditEntry(
            event_type=event_type,
            agent_did=agent_did,
            action=action,
            resource=resource,
            data=details,
            outcome=outcome,
            policy_decision=policy_decision,
            trace_id=trace_id,
        )
        with self._lock:
            entry.previous_hash = self._last_hash
            entry.entry_hash = entry.compute_hash()
            self._last_hash = entry.entry_hash
            self._seq += 1
            seq = self._seq
        record = {
            "id": entry.entry_id,
            "chainId": self.chain_id,
            "seq": seq,
            **entry.model_dump(mode="json", include=set(HASHED_FIELDS)),
        }
        self.recent.append(record)
        if self._sink is not None:
            self._sink.submit(record)
        if span.is_recording():
            fields = {
                **details,
                "event_type": event_type,
                "action": action,
                "outcome": outcome,
                "decision": policy_decision,
                "resource": resource,
            }
            span.add_event(
                "biotrackr.control",
                {
                    f"biotrackr.control.{key}": value
                    for key, value in fields.items()
                    if key in CONTROL_EVENT_FIELDS
                    and value is not None
                    and not (principal is not None and isinstance(value, str) and principal.oid in value)
                },
            )
        return entry


def verify_chain(records: Iterable[Mapping[str, Any]]) -> list[str]:
    """Problems found in one chain: edited entries, broken links, and missing sequence numbers."""
    problems: list[str] = []
    previous = ""
    expected = 1
    for record in sorted(records, key=lambda r: int(r["seq"])):
        seq = int(record["seq"])
        if seq != expected:
            problems.append(f"seq {seq}: {seq - expected} entries missing before it")
            previous = str(record.get("previous_hash", ""))
        entry = AuditEntry.model_validate({k: record.get(k) for k in HASHED_FIELDS if k in record})
        if not entry.verify_hash():
            problems.append(f"seq {seq}: entry hash mismatch (entry altered)")
        if entry.previous_hash != previous:
            problems.append(f"seq {seq}: previous_hash does not match the entry before it")
        previous = entry.entry_hash
        expected = seq + 1
    return problems


class CosmosAuditSink:
    """Writes audit records to Cosmos DB from a background task, so the run never waits for the audit write.

    Writes are retried with jittered backoff. If the queue overflows or retries run out, the record is dropped and
    logged; the missing sequence number then shows up when the chain is verified.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        database: str | None = None,
        *,
        container: str = CONTAINER,
        max_pending: int = 10_000,
    ) -> None:
        self._endpoint = endpoint or os.environ.get("COSMOS_ENDPOINT", "http://localhost:8081")
        self._database = database or os.environ.get("COSMOS_DATABASE", "biotrackr")
        self._container_name = container
        self._max_pending = max_pending
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._task: asyncio.Task[None] | None = None
        self._client: Any = None
        self._container: Any = None
        self.dropped = 0

    def submit(self, record: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.dropped += 1
            log.error("audit record %s dropped: no event loop", record.get("seq"))
            return
        if self._queue is None:
            self._queue = asyncio.Queue(self._max_pending)
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._drain(), name="audit-sink", context=contextvars.Context())
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self.dropped += 1
            log.critical("audit queue full; record %s dropped", record.get("seq"))

    async def _get_container(self) -> Any:
        if self._container is None:
            from azure.cosmos.aio import CosmosClient

            from auth_common.azure_credential import cosmos_credential

            self._client = CosmosClient(
                self._endpoint, credential=cosmos_credential(self._endpoint), enable_endpoint_discovery=False
            )
            self._container = self._client.get_database_client(self._database).get_container_client(
                self._container_name
            )
        return self._container

    async def _drain(self) -> None:
        assert self._queue is not None
        while True:
            record = await self._queue.get()
            for attempt in range(6):
                try:
                    await (await self._get_container()).upsert_item(record)
                    break
                except Exception as exc:
                    log.warning("audit write failed (%s); retrying", type(exc).__name__)
                    await asyncio.sleep(min(2**attempt, 30) * random.uniform(0.5, 1.0))  # noqa: S311
            else:
                self.dropped += 1
                log.error("audit record %s dropped after retries", record.get("seq"))
            self._queue.task_done()

    async def flush(self, wait_seconds: float = 10.0) -> None:
        if self._queue is not None and self._task is not None and not self._task.done():
            await asyncio.wait_for(self._queue.join(), wait_seconds)

    async def close(self) -> None:
        try:
            await self.flush()
        except TimeoutError:
            log.error("audit flush timed out; %d records pending", self._queue.qsize() if self._queue else 0)
        if self._task is not None:
            self._task.cancel()
        if self._client is not None:
            await self._client.close()


async def _verify_stored() -> int:
    from azure.cosmos.aio import CosmosClient

    from auth_common.azure_credential import cosmos_credential

    endpoint = os.environ.get("COSMOS_ENDPOINT", "http://localhost:8081")
    chains: dict[str, list[dict[str, Any]]] = {}
    async with CosmosClient(endpoint, credential=cosmos_credential(endpoint), enable_endpoint_discovery=False) as c:
        container = c.get_database_client(os.environ.get("COSMOS_DATABASE", "biotrackr")).get_container_client(
            CONTAINER
        )
        async for item in container.read_all_items():
            chains.setdefault(item["chainId"], []).append(item)
    failed = 0
    for chain_id, records in sorted(chains.items()):
        problems = verify_chain(records)
        failed += bool(problems)
        print(f"{chain_id}: {len(records)} entries, {'OK' if not problems else 'FAILED'}")
        for problem in problems:
            print(f"  {problem}")
    if not chains:
        print("no audit chains found")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_verify_stored()))
