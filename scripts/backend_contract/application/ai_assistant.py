"""What the report-writing assistant may do on this installation, fail-closed.

AI_PROPOSAL != PROFESSIONAL_DECISION: an assistant may only ever propose text
the expert then accepts, edits or discards.  Whether it may run at all is not
a user preference: case content leaves this machine only under an explicit,
human-approved egress decision, and no installation ships with one.  Without
an approved local provider and without that decision the assistant is
unavailable, and the product says why instead of degrading silently.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AIAssistantStatus:
    local_provider: object | None = None
    remote_private_egress_approved: bool = False

    def execute(self) -> dict:
        if self.local_provider is not None:
            return {"available": True, "mode": "LOCAL_ONLY", "reasons": [], "proposal_only": True}
        reasons = ["NO_LOCAL_PROVIDER"]
        if not self.remote_private_egress_approved:
            reasons.append("PRIVATE_CASE_EGRESS_NOT_AUTHORIZED")
        return {"available": False, "mode": None, "reasons": reasons, "proposal_only": True}
