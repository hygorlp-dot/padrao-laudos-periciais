import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ReportFoundationView } from "./ReportFoundationView";

const ID = "11111111-1111-4111-8111-111111111111";
const profile = { profile_id: "EXPERT-PROFILE-001", revision: 1, full_name: "Profissional Sintético", professional_title: "Perito Judicial", registration: "CREA-SYN-001", court_registration: null, contact_line: null };
const snapshot = { schema_version: "1.0.0", report_id: "REPORT-001", workspace_id: ID, source_snapshot: { workspace_id: ID }, expert_profile: profile, editorial_profile: { profile_id: "JUSTICA_PLURAL_CHAPTER_4", font_family: "Arial", body_font_pt: 11 }, context_matrix: [{ context_id: "CTX-1", field: "PROCESS_NUMBER", required: true, status: "PRESENT", source_id: "DOC-1", note: "Contexto documentado." }], sections: [{ section_id: "SEC-1", kind: "IDENTIFICATION", title: "Identificação", order: 1, required_by_cpc473: true }], claims: [{ claim_id: "CLAIM-1", section_id: "SEC-1", text: "Afirmação documentada.", authority: "DOCUMENTED", provenance: [{ provenance_id: "PROV-1", source_kind: "CASE_DOCUMENT", source_id: "DOC-1", source_revision: 1 }] }], answers: [{ answer_id: "ANSWER-1", section_id: "SEC-1", question_id: "QUESTION-1", text: "Resposta rastreada.", finding_id: "FINDING-1", evidence_ids: ["EVIDENCE-1"], method_ids: ["METHOD-1"], decision_id: "DECISION-1", claim_ids: ["CLAIM-1"] }], review_decisions: [], state: "DRAFT", coverage: { sections: 14, material_claims: 1, traceable_claims: 1, answers: 1, traceable_answers: 1, cpc473_required_sections: 8, cpc473_present_sections: 1, context_required_fields: 6, context_present_fields: 1, complete: false, reasons: ["Conteúdo incompleto."] }, upstream_stale: false, upstream_stale_reasons: [] };
const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("report foundation workbench", () => {
  test("shows authority, provenance, article gates and answer trace without delivery", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(200, { revision: 1, updated_at: "2026-08-31T12:00:00Z", profile })).mockResolvedValueOnce(response(200, { revision: 1, updated_at: "2026-08-31T12:00:00Z", snapshot })));
    render(<ReportFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Fundação do laudo" })).toBeInTheDocument();
    expect(screen.getByText("DOCUMENTED")).toBeInTheDocument();
    expect(screen.getByText(/CASE_DOCUMENT · DOC-1/)).toBeInTheDocument();
    expect(screen.getByText(/Art. 319/)).toBeInTheDocument();
    expect(screen.getByText(/Art. 473/)).toBeInTheDocument();
    expect(screen.getByText(/QUESTION-1 → FINDING-1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /entregar|protocolar|enviar/i })).not.toBeInTheDocument();
  });

  test("requires the master expert profile before starting a report", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(404, {})).mockResolvedValueOnce(response(200, { revision: 1, updated_at: "2026-08-31T12:00:00Z", profile })).mockResolvedValueOnce(response(201, { revision: 1, updated_at: "2026-08-31T12:00:00Z", snapshot }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup(); render(<ReportFoundationView workspaceId={ID} />);
    await user.type(await screen.findByLabelText("Nome completo"), "Profissional Sintético");
    await user.type(screen.getByLabelText("Título profissional"), "Perito Judicial");
    await user.type(screen.getByLabelText("Registro profissional"), "CREA-SYN-001");
    await user.click(screen.getByRole("button", { name: "Salvar perfil e iniciar laudo" }));
    expect(await screen.findByRole("heading", { name: "Fundação do laudo" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
