"""biotrackr-chat: talk to the Biotrackr chat agent over AG-UI."""

import argparse
import json
import sys
import tomllib
import uuid
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console

from biotrackr_client.auth import headers_for
from biotrackr_client.render import Renderer

console = Console()


def load_targets(path: Path | None) -> dict[str, Any]:
    if path is not None:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    local = Path(__file__).resolve().parents[2] / "targets.toml"
    if local.exists():
        return tomllib.loads(local.read_text(encoding="utf-8"))
    return tomllib.loads(resources.files("biotrackr_client").joinpath("targets.toml").read_text(encoding="utf-8"))


def send(client: httpx.Client, url: str, thread_id: str, message: str) -> Renderer:
    body = {
        "threadId": thread_id,
        "runId": str(uuid.uuid4()),
        # The server keeps history per thread, so only the new user message is sent.
        "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": message}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    renderer = Renderer(console)
    with client.stream("POST", url, json=body, headers={"Accept": "text/event-stream"}) as response:
        if response.status_code >= 400:
            response.read()
            renderer.error = f"HTTP {response.status_code}: {response.text[:300]}"
            console.print(f"[bold red]{renderer.error}[/]")
            return renderer
        data: list[str] = []
        for line in response.iter_lines():
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif line == "" and data:
                renderer.handle(json.loads("\n".join(data)))
                data = []
        if data:
            renderer.handle(json.loads("\n".join(data)))
    return renderer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biotrackr-chat", description=__doc__)
    parser.add_argument("message", nargs="*", help="message to send; omit for interactive mode")
    parser.add_argument("--target", default="starter", help="target name from targets.toml (default: starter)")
    parser.add_argument("--as", dest="user", default="alice", help="user to act as (default: alice)")
    parser.add_argument("--thread", default=None, help="continue an existing thread id")
    parser.add_argument("--targets-file", type=Path, default=None, help="alternative targets.toml")
    args = parser.parse_args(argv)

    targets = load_targets(args.targets_file)
    if args.target not in targets:
        console.print(f"[red]unknown target '{args.target}'. Known: {', '.join(targets)}[/]")
        return 2
    target = targets[args.target]
    thread_id = args.thread or str(uuid.uuid4())

    try:
        headers = headers_for(target.get("auth", "header"), args.user)
    except NotImplementedError as exc:
        console.print(f"[red]{exc}[/]")
        return 2

    console.print(f"[dim]target={args.target} url={target['url']} as={args.user} thread={thread_id}[/]")
    with httpx.Client(headers=headers, timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        try:
            if args.message:
                return 1 if send(client, target["url"], thread_id, " ".join(args.message)).error else 0
            while True:
                try:
                    message = console.input("[bold green]you>[/] ").strip()
                except EOFError:
                    break
                if message in {"exit", "quit"}:
                    break
                if message:
                    send(client, target["url"], thread_id, message)
        except httpx.HTTPError as exc:
            console.print(f"[bold red]connection error:[/] {exc}")
            return 1
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
