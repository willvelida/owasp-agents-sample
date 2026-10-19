"""Cumulative red-team scorecard.

    uv run python -m redteam.run --target starter          # attacks should SUCCEED
    uv run python -m redteam.run --target solution-local   # attacks should be BLOCKED
    uv run python -m redteam.run --target solution-azure --risk ASI01 --judge

Exit code 0 when every attack matches the expectation for the target, 1 otherwise.
"""

import argparse
import asyncio
import re
import sys
import uuid
from dataclasses import dataclass

from pyrit.converter import Base64Converter, UnicodeConfusableConverter
from pyrit.models import Message, MessagePiece
from pyrit.setup import IN_MEMORY, initialize_pyrit_async

from redteam.attacks import Attack, catalogue
from redteam.config import resolve
from redteam.converters import HomoglyphConverter
from redteam.scorers import judge_target, scorers_for
from redteam.targets.biotrackr_target import BiotrackrTarget

CONVERTERS = {"base64": Base64Converter, "confusable": UnicodeConfusableConverter, "homoglyph": HomoglyphConverter}


@dataclass
class Outcome:
    attack: Attack
    succeeded: bool
    evidence: str


async def render_prompt(attack: Attack) -> str:
    if not attack.converter:
        return attack.prompt
    converted = await CONVERTERS[attack.converter]().convert_async(prompt=attack.payload, input_type="text")
    return attack.prompt.replace("{payload}", converted.output_text)


async def run_attack(target_name: str, attack: Attack, attempts: int, judge: object | None) -> Outcome:
    resolved = resolve(target_name, attack.user)
    target = BiotrackrTarget(url=resolved.url, headers=resolved.headers)
    target.extra_headers = dict(attack.extra_headers)
    scorers = scorers_for(attack, judge)
    last = ""
    for _ in range(attempts):
        prompt = await render_prompt(attack)
        piece = MessagePiece(role="user", original_value=prompt, conversation_id=str(uuid.uuid4()))
        responses = await target.send_prompt_async(message=Message(message_pieces=[piece]))
        text = "\n".join(p.converted_value for r in responses for p in r.message_pieces)
        last = text
        for scorer in scorers:
            hits = [s for s in await scorer.score_text_async(text) if s.get_value()]
            if hits:
                return Outcome(attack, True, f"{type(scorer).__name__}: {_excerpt(text, attack, hits[0])}")
    return Outcome(attack, False, _excerpt(last, attack, None))


def _excerpt(text: str, attack: Attack, score: object | None) -> str:
    for pattern in attack.success.values():
        if match := re.search(pattern, text, re.IGNORECASE):
            start = match.start()
            return text[max(0, start - 40) : start + 80].replace("\n", " ")
    if score is not None:
        return str(getattr(score, "score_rationale", ""))[:120].replace("\n", " ")
    return text[:120].replace("\n", " ")


async def main_async(args: argparse.Namespace) -> int:
    await initialize_pyrit_async(memory_db_type=IN_MEMORY, silent=True)
    attacks = [a for a in catalogue() if not args.risk or a.risk in args.risk]
    expect_success = resolve(args.target, "alice").is_starter
    judge = judge_target() if args.judge else None
    outcomes = [await run_attack(args.target, attack, args.attempts, judge) for attack in attacks]

    print(f"\nScorecard: target={args.target} (expect {'SUCCEEDED' if expect_success else 'BLOCKED'})\n")
    print(f"{'risk':6} {'attack':24} {'result':10} {'ok':3} evidence")
    failures = 0
    for o in outcomes:
        ok = o.succeeded == expect_success
        failures += not ok
        result = "SUCCEEDED" if o.succeeded else "BLOCKED"
        print(f"{o.attack.risk:6} {o.attack.name:24} {result:10} {'yes' if ok else 'NO':3} {o.evidence}")
    print(f"\n{len(outcomes) - failures}/{len(outcomes)} attacks matched the expectation")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="redteam.run", description=__doc__)
    parser.add_argument("--target", required=True, help="starter, solution-local, solution-offline, solution-azure")
    parser.add_argument("--risk", action="append", help="limit to a risk, for example ASI03 (repeatable)")
    parser.add_argument("--attempts", type=int, default=2, help="tries per attack; any hit counts as success")
    parser.add_argument("--judge", action="store_true", help="add the PyRIT LLM judge (solution Foundry, Entra ID)")
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
