"""Target configuration shared with the CLI (client/targets.toml and its auth modes)."""

from dataclasses import dataclass
from pathlib import Path

from biotrackr_client.auth import headers_for, resolve_url
from biotrackr_client.cli import load_targets, targets_dir

TARGETS_FILE = Path(__file__).resolve().parents[3] / "client" / "targets.toml"
STARTER_TARGETS = {"starter"}


@dataclass(frozen=True)
class ResolvedTarget:
    name: str
    url: str
    auth: str
    headers: dict[str, str]

    @property
    def is_starter(self) -> bool:
        return self.name in STARTER_TARGETS


def resolve(name: str, user: str) -> ResolvedTarget:
    targets = load_targets(TARGETS_FILE)
    if name not in targets:
        raise SystemExit(f"unknown target '{name}'. Known: {', '.join(targets)}")
    target = targets[name]
    base = targets_dir(TARGETS_FILE)
    auth = target.get("auth", "header")
    return ResolvedTarget(name, resolve_url(target, base), auth, headers_for(auth, user, target, base))
