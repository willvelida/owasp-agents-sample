"""Cumulative red-team scorecard.

    uv run python -m redteam.run --target starter          # attacks should SUCCEED
    uv run python -m redteam.run --target solution-local   # attacks should be BLOCKED
    uv run python -m redteam.run --target solution-azure --risk ASI03

Exit code 0 when every attack matches the expectation for the target, 1 otherwise.
"""

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass

from pyrit.models import Message, MessagePiece
from pyrit.setup import IN_MEMORY, initialize_pyrit_async

from redteam.attacks import Attack, catalogue
from redteam.config import resolve
from redteam.scorers import canary_scorer
from redteam.targets.biotrackr_target import BiotrackrTarget


@dataclass
class Outcome:
    attack: Attack
    succeeded: bool
    evidence: str


async def run_attack(target_name: str, attack: Attack, attempts: int) -> Outcome:
    resolved = resolve(target_name, attack.user)
    target = BiotrackrTarget(url=resolved.url, headers=resolved.headers)
    target.extra_headers = dict(attack.extra_headers)
    scorer = canary_scorer(attack.canary, attack.risk)
    last = ""
    for _ in range(attempts):
        piece = MessagePiece(role="user", original_value=attack.prompt, conversation_id=str(uuid.uuid4()))
        responses = await target.send_prompt_async(message=Message(message_pieces=[piece]))
        text = "\n".join(p.converted_value for r in responses for p in r.message_pieces)
        last = text
        scores = await scorer.score_text_async(text)
        if any(s.get_value() for s in scores):
            return Outcome(attack, True, _excerpt(text, attack.canary))
    return Outcome(attack, False, _excerpt(last, attack.canary))


def _excerpt(text: str, canary: str) -> str:
    index = text.find(canary)
    if index >= 0:
        return text[max(0, index - 60) : index + len(canary) + 20].replace("\n", " ")
    return text[:120].replace("\n", " ")


async def main_async(args: argparse.Namespace) -> int:
    await initialize_pyrit_async(memory_db_type=IN_MEMORY, silent=True)
    attacks = [a for a in catalogue() if not args.risk or a.risk in args.risk]
    expect_success = resolve(args.target, "alice").is_starter
    outcomes = [await run_attack(args.target, attack, args.attempts) for attack in attacks]

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
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
