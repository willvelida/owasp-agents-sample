"""Reviews a finished report before it is released."""

import json
import logging

from agent_framework import Agent

log = logging.getLogger("report_agent.reviewer")

INSTRUCTIONS = """\
You review Biotrackr chart reports before they are shown to the user. Reply with JSON only:
{"approved": true or false, "reason": "<short reason>"}. Reject reports that contain diagnoses,
medication advice, or anything other than a description of the user's data.
"""


def build_reviewer(client) -> Agent:
    return Agent(client=client, name="ReportReviewer", instructions=INSTRUCTIONS)


async def review(reviewer: Agent, code: str, summary: str) -> tuple[bool, str]:
    try:
        response = await reviewer.run(f"Chart code:\n{code}\n\nReport summary:\n{summary}")
        verdict = json.loads(response.text)
        return bool(verdict.get("approved", True)), str(verdict.get("reason", ""))
    except Exception as exc:
        # ASI09 (starter): fail open. If the reviewer errors or answers badly, the report ships anyway.
        log.warning("reviewer failed (%s); approving", exc)
        return True, "reviewer unavailable"
