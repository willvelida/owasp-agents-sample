"""MCP tool descriptor pinning (ASI04 runtime).

The lock file records a SHA-256 digest of each tool's name, description, and input schema. The health
MCP server checks its own descriptors at startup and exits on mismatch; the chat agent checks every
tools/list response it receives and refuses to run on mismatch. Regenerate the lock after a reviewed
change with:

    uv run python -m governance.descriptors --write
"""

import argparse
import asyncio
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from governance import PolicyError, policy_dir, read_bytes, sha256_hex

LOCK_FILE = "mcp_tools.lock.json"


def descriptor_digest(name: str, description: str | None, input_schema: Mapping[str, Any] | None) -> str:
    canonical = json.dumps(
        {"name": name, "description": description or "", "inputSchema": dict(input_schema or {})},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + sha256_hex(canonical.encode())


def digests(tools: Iterable[Any]) -> dict[str, str]:
    """Digest MCP `Tool` objects (server `list_tools()` or client `ListToolsResult.tools`)."""
    return {t.name: descriptor_digest(t.name, t.description, t.inputSchema) for t in tools}


def load_lock(directory: Path | None = None) -> dict[str, str]:
    try:
        lock = json.loads(read_bytes(LOCK_FILE, directory))
        tools = lock["tools"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PolicyError(f"{LOCK_FILE} is malformed: {exc}") from exc
    if not isinstance(tools, dict) or not tools:
        raise PolicyError(f"{LOCK_FILE} pins no tools")
    return dict(tools)


def mismatches(actual: Mapping[str, str], pinned: Mapping[str, str]) -> list[str]:
    """Exact set and digest equality: an added, removed, or changed tool is a mismatch."""
    problems = [f"unpinned tool '{n}'" for n in sorted(set(actual) - set(pinned))]
    problems += [f"missing pinned tool '{n}'" for n in sorted(set(pinned) - set(actual))]
    problems += [f"descriptor changed for '{n}'" for n in sorted(set(actual) & set(pinned)) if actual[n] != pinned[n]]
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(prog="governance.descriptors", description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite the lock from the current server code")
    args = parser.parse_args()

    from health_mcp.server import registered_tools

    actual = digests(asyncio.run(registered_tools()))
    path = policy_dir() / LOCK_FILE
    if args.write:
        path.write_bytes((json.dumps({"server": "biotrackr-health", "tools": actual}, indent=2) + "\n").encode())
        print(f"wrote {len(actual)} descriptors to {path}")
        return
    problems = mismatches(actual, load_lock())
    print("\n".join(problems) or "descriptors match the lock")
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
