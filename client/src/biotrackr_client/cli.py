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
from rich.markup import escape

from biotrackr_client.auth import AuthError, headers_for, resolve_url
from biotrackr_client.render import SLOW_TOOLS, Renderer, interrupt_call

console = Console()


def targets_dir(path: Path | None) -> Path:
    """Directory that relative paths in targets.toml (env_file, azd_cwd) resolve against."""
    if path is not None:
        return path.resolve().parent
    return Path(__file__).resolve().parents[2]


def load_targets(path: Path | None) -> dict[str, Any]:
    if path is not None:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    local = Path(__file__).resolve().parents[2] / "targets.toml"
    if local.exists():
        return tomllib.loads(local.read_text(encoding="utf-8"))
    return tomllib.loads(resources.files("biotrackr_client").joinpath("targets.toml").read_text(encoding="utf-8"))


def _body(thread_id: str, *, message: str | None = None, resume: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "threadId": thread_id,
        "runId": str(uuid.uuid4()),
        # The server keeps history per thread, so only the new user message is sent.
        "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": message}] if message else [],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    if resume is not None:
        body["resume"] = resume
    return body


def _stream(client: httpx.Client, url: str, body: dict[str, Any], renderer: Renderer) -> None:
    try:
        with client.stream("POST", url, json=body, headers={"Accept": "text/event-stream"}) as response:
            if response.status_code >= 400:
                response.read()
                renderer.close()
                renderer.error = f"HTTP {response.status_code}: {response.text[:300]}"
                console.print(f"[bold red]{renderer.error}[/]")
                return
            data: list[str] = []
            for line in response.iter_lines():
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif line == "" and data:
                    renderer.handle(json.loads("\n".join(data)))
                    data = []
            if data:
                renderer.handle(json.loads("\n".join(data)))
    finally:
        renderer.close()


def _decide(interrupt: dict[str, Any], approve: str) -> bool:
    name, arguments = interrupt_call(interrupt)
    console.print(f"[bold yellow]Approve {escape(name)}?[/] [yellow]{escape(arguments[:400])}[/]")
    if approve != "ask":
        console.print(f"[dim]--approve {approve}[/]")
        return approve == "yes"
    if not sys.stdin.isatty():
        console.print("[dim]not a terminal; rejecting[/]")
        return False
    return console.input("[bold yellow]approve? [y/N][/] ").strip().lower() in {"y", "yes"}


def send(client: httpx.Client, url: str, thread_id: str, message: str, approve: str = "ask") -> Renderer:
    renderer = Renderer(console)
    _stream(client, url, _body(thread_id, message=message), renderer)
    # ASI09: a tool that needs approval pauses the run; the user decides, then the same thread resumes.
    while renderer.interrupts and not renderer.error:
        decisions = []
        for interrupt in renderer.interrupts:
            accepted = _decide(interrupt, approve)
            decisions.append({"id": interrupt["id"], "status": "resolved", "payload": {"accepted": accepted}})
        names = [interrupt_call(i)[0] for i in renderer.interrupts]
        approved = [n for n, d in zip(names, decisions, strict=True) if d["payload"]["accepted"]]
        renderer = Renderer(console)
        if wait := next((SLOW_TOOLS[n] for n in approved if n in SLOW_TOOLS), None):
            renderer.wait(wait)
        _stream(client, url, _body(thread_id, resume={"interrupts": decisions}), renderer)
    return renderer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biotrackr-chat", description=__doc__)
    parser.add_argument("message", nargs="*", help="message to send; omit for interactive mode")
    parser.add_argument("--target", default="starter", help="target name from targets.toml (default: starter)")
    parser.add_argument("--as", dest="user", default="alice", help="user to act as (default: alice)")
    parser.add_argument("--thread", default=None, help="continue an existing thread id")
    parser.add_argument("--targets-file", type=Path, default=None, help="alternative targets.toml")
    parser.add_argument(
        "--approve",
        choices=["ask", "yes", "no"],
        default="ask",
        help="answer to tool approval requests (default: ask; non-interactive input rejects)",
    )
    args = parser.parse_args(argv)

    targets = load_targets(args.targets_file)
    if args.target not in targets:
        console.print(f"[red]unknown target '{args.target}'. Known: {', '.join(targets)}[/]")
        return 2
    target = targets[args.target]
    thread_id = args.thread or str(uuid.uuid4())
    base_dir = targets_dir(args.targets_file)

    try:
        url = resolve_url(target, base_dir)
        headers = headers_for(target.get("auth", "header"), args.user, target, base_dir)
    except AuthError as exc:
        console.print(f"[red]{exc}[/]")
        return 2

    console.print(f"[dim]target={args.target} url={url} as={args.user} thread={thread_id}[/]")
    # Reports can take a minute end to end (generation, isolated run, review), so the read timeout is generous.
    with httpx.Client(headers=headers, timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        try:
            if args.message:
                return 1 if send(client, url, thread_id, " ".join(args.message), args.approve).error else 0
            while True:
                try:
                    message = console.input("[bold green]you>[/] ").strip()
                except EOFError:
                    break
                if message in {"exit", "quit"}:
                    break
                if message:
                    send(client, url, thread_id, message, args.approve)
        except httpx.HTTPError as exc:
            console.print(f"[bold red]connection error:[/] {exc}")
            return 1
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
