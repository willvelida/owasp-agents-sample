"""Attack catalogue. Each slice adds a module; run.py replays all of them (cumulative regression)."""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Attack:
    """One attack prompt and the evidence that it worked.

    `success` maps evidence names to regexes searched in the transcript (assistant text plus every tool
    call and tool result); any match means the attack succeeded. `converter` (PyRIT, for example base64
    or confusable) rewrites `payload`, which replaces `{payload}` in the prompt. `judge` is an optional
    true/false question for the PyRIT LLM judge (--judge), OR'd with the regexes.
    """

    risk: str
    name: str
    prompt: str
    success: dict[str, str]
    extra_headers: dict[str, str] = field(default_factory=dict)
    user: str = "alice"
    payload: str = ""
    converter: str | None = None
    markdown_exfil: bool = False
    judge: str | None = None


def canary(value: str) -> dict[str, str]:
    return {value: re.escape(value)}


def catalogue() -> list[Attack]:
    from redteam.attacks import asi01, asi02, asi03

    return [*asi01.ATTACKS, *asi02.ATTACKS, *asi03.ATTACKS]
