"""The report-writing assistant is fail-closed on every installation (#239, Phase F).

AI_PROPOSAL != PROFESSIONAL_DECISION and PRIVATE_DATA_EGRESS = FALSE by
default: without an approved local provider and a human egress decision the
assistant is unavailable, says why, and no case content is sent anywhere.
"""

from __future__ import annotations

import json

from scripts.backend_contract.application.ai_assistant import AIAssistantStatus


def test_the_assistant_is_unavailable_without_a_provider_or_an_egress_decision() -> None:
    assert AIAssistantStatus().execute() == {"available": False, "mode": None, "reasons": ["NO_LOCAL_PROVIDER", "PRIVATE_CASE_EGRESS_NOT_AUTHORIZED"], "proposal_only": True}
    assert AIAssistantStatus(local_provider=object()).execute()["proposal_only"] is True


def test_the_product_reports_the_assistant_unavailable(tmp_path) -> None:
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_document_intake_v1 import provision_private_root
    from tests.test_local_api_v1 import TOKEN, http_request

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_local_api(tmp_path / "case.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        status, _headers, body = http_request(runtime.server, "GET", "/v1/ai-assistant/status")
        assert status == 200 and json.loads(body)["available"] is False
    finally:
        runtime.close()
