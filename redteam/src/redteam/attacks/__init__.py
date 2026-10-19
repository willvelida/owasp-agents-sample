"""Attack catalogue. Each slice adds a module; run.py replays all of them (cumulative regression)."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Attack:
    risk: str
    name: str
    prompt: str
    canary: str
    extra_headers: dict[str, str] = field(default_factory=dict)
    user: str = "alice"


def catalogue() -> list[Attack]:
    from redteam.attacks import asi03

    return [*asi03.ATTACKS]
