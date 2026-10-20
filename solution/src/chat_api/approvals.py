"""Approval resumes carry a decision only (ASI09).

AG-UI lets a client resume an approval with edited tool arguments (`editedArgs` or extra payload keys).
The edited call would then run with input the model never proposed and the batch guard and input screening
never saw. This dependency rejects any resume whose payload holds more than the yes/no decision, before
the agent runs.
"""

from typing import Any

# Private helpers of agent-framework-ag-ui 1.6.0 (exact pin): reusing them means every location the endpoint
# reads a resume from (resume, forwardedProps.resume, forwardedProps.command.resume) is covered.
from agent_framework_ag_ui._run_common import _extract_resume_payload, _normalize_resume_interrupts
from fastapi import HTTPException, Request

DECISION_KEYS = frozenset({"accepted", "approved"})


def edited_resume(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    for interrupt in _normalize_resume_interrupts(_extract_resume_payload(body)):
        value = interrupt.get("value")
        if isinstance(value, dict) and set(value) - DECISION_KEYS:
            return True
    return False


async def reject_edited_approvals(request: Request) -> None:
    try:
        body = await request.json()
    except ValueError:
        return
    if edited_resume(body):
        raise HTTPException(status_code=400, detail="approval resumes may only approve or reject")
