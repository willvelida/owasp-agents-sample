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
    # With --judge, AND the judge question with an inverted SelfAskRefusalScorer (did not refuse).
    refusal_judge: bool = False
    # "asi05": a BLOCKED result on a solution target counts only if the canary is set in report-agent and the
    # attack reached the static check or the runner (rejected_by). Otherwise the result is INVALID.
    oracle: str | None = None
    # Multi-turn PyRIT CrescendoAttack towards this objective (needs --judge for the adversarial chat and scorer).
    crescendo: str | None = None
    # Minimum attempts for attacks whose success varies run to run with the model (any hit counts).
    min_attempts: int = 0
    # ASI06: setup turns sent on the same AG-UI thread before `prompt`; only the reply to `prompt` is scored.
    turns: tuple[str, ...] = ()
    # With `crescendo`: a fresh turn on the Crescendo conversation's thread afterwards, which is what gets scored.
    probe: str | None = None
    # ASI10: `burst` parallel runs of `burst_prompt`, each on a new thread, before `prompt` (also on a new thread).
    burst: int = 0
    burst_prompt: str = ""
    # ASI08, ASI10: a fault step around the attack (faults.py). On solution-azure it needs --azure-faults.
    fault: str | None = None
    # Overall deadline in seconds for each run of the attack (default 240).
    deadline: float | None = None
    # With `probe`: the judge question that ends the Crescendo planting phase early once the rule is accepted.
    plant_judge: str | None = None
    # Model-free probe instead of a chat prompt ("asi07": asi07_forge.probe, run inside chat-api's container).
    direct: str | None = None


def canary(value: str) -> dict[str, str]:
    return {value: re.escape(value)}


def catalogue() -> list[Attack]:
    from redteam.attacks import asi01, asi02, asi03, asi05, asi06, asi07_forge, asi08, asi09, asi10

    # ASI10 runs last: its burst quarantines bob, and its kill-switch fault recreates chat-api (which also clears it).
    # ASI07 is model-free and sends nothing through the chat API, so it cannot spend a user's budget or trip a detector.
    return [
        *asi01.ATTACKS,
        *asi02.ATTACKS,
        *asi03.ATTACKS,
        *asi05.ATTACKS,
        *asi06.ATTACKS,
        *asi07_forge.ATTACKS,
        *asi08.ATTACKS,
        *asi09.ATTACKS,
        *asi10.ATTACKS,
    ]
