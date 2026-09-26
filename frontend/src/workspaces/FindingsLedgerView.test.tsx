import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { FindingsLedgerView } from "./FindingsLedgerView";
import { ReportReviewView } from "./ReportReviewView";

const ID = "11111111-1111-4111-8111-111111111111";
const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

const technical = {
  revision: 3, updated_at: "2026-08-31T10:10:00Z",
  snapshot: {
    schema_version: "1.0.0", snapshot_id: "TECHNICAL-SNAPSHOT-001", workspace_id: ID,
    source_snapshot: { workspace_id: ID, case_analysis_snapshot_id: "CASE-001", case_analysis_revision: 3, case_analysis_digest: "a".repeat(64), inspection_session_id: "INSPECTION-001", inspection_session_revision: 2, inspection_session_digest: "b".repeat(64), source_revision: 4 },
    evidence_items: [{ evidence_id: "EVIDENCE-001", proposition: "Fissura de 0,3 mm na sala.", assessment_id: "ASSESSMENT-001" }],
    source_links: [], evidence_assessments: [],
    method_applications: [{ method_application_id: "METHOD-001", method_identity: "Medição com fissurômetro", selection_authority: "EXPERT", procedure: "Leitura direta.", parameters: [], input_ids: [], output_ids: [], limitation_ids: [], normative_references: [], execution_revision: 1 }],
    method_inputs: [], method_outputs: [],
    finding_proposals: [
      { proposal_id: "PROPOSAL-001", technical_proposition: "Há fissura ativa na parede leste.", origin: "AI_PROPOSAL", method_application_ids: ["METHOD-001"], supporting_evidence_ids: ["EVIDENCE-001"], contrary_evidence_ids: [], limitation_ids: [], uncertainty_ids: [], scope: "Sala" },
      { proposal_id: "PROPOSAL-002", technical_proposition: "Proposta ainda sem decisão.", origin: "AI_PROPOSAL", method_application_ids: ["METHOD-001"], supporting_evidence_ids: [], contrary_evidence_ids: [], limitation_ids: [], uncertainty_ids: [], scope: "Cozinha" },
    ],
    findings: [{ finding_id: "FINDING-001", proposal_id: "PROPOSAL-001", decision_id: "DECISION-001", technical_proposition: "Há fissura ativa na parede leste.", scope: "Sala" }],
    dependencies: [], conflicts: [], limitations: [], uncertainties: [], question_links: [],
    decisions: [{ decision_id: "DECISION-001", proposal_id: "PROPOSAL-001", action: "APPROVE", professional_id: "EXPERT-PROFILE-001", reason: "Conferido.", modified_proposition: null, timestamp: "2026-08-31T10:10:00Z", supersedes_decision_id: null }],
    coverage: { evidence_items: 1, approved_evidence: 1, method_applications: 1, finding_proposals: 2, effective_findings: 1, unresolved_conflicts: 0, complete: false, reasons: [] },
    upstream_stale: false, upstream_stale_reasons: [],
  },
};

describe("findings ledger (Constatações)", () => {
  test("lists only professionally effective findings with evidence, method and decision", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(String(input).endsWith("/technical-snapshot") ? response(200, technical) : response(404, {}))));
    render(<FindingsLedgerView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Achados técnicos efetivos" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Há fissura ativa na parede leste." })).toBeInTheDocument();
    expect(screen.getByText("Fissura de 0,3 mm na sala.")).toBeInTheDocument();
    expect(screen.getByText("Medição com fissurômetro")).toBeInTheDocument();
    expect(screen.getByText(/^Aprovado por EXPERT-PROFILE-001/)).toBeInTheDocument();
    // Uma proposta sem decisão profissional não é constatação.
    expect(screen.queryByText("Proposta ainda sem decisão.")).not.toBeInTheDocument();
    expect(screen.getByText("FINDING-001", { exact: false }).closest("details")).not.toBeNull();
  });

  test("explains how a finding becomes effective when there is none", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response(404, {}))));
    render(<FindingsLedgerView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Nenhuma constatação efetiva ainda" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ir para Evidências" })).toHaveAttribute("href", `/pericias/${ID}/evidencias`);
  });
});

const coverage = { sections: 14, material_claims: 2, traceable_claims: 2, answers: 1, traceable_answers: 1, cpc473_required_sections: 8, cpc473_present_sections: 8, context_required_fields: 6, context_present_fields: 5, complete: false, reasons: ["Contexto processual incompleto."] };
const report = (state: string, complete: boolean) => ({
  revision: 4, updated_at: "2026-08-31T10:00:00Z",
  snapshot: {
    schema_version: "1.0.0", report_id: "REPORT-001", workspace_id: ID,
    source_snapshot: { workspace_id: ID, construction_defect_analysis_snapshot_id: null, construction_defect_analysis_revision: null, construction_defect_analysis_digest: null },
    expert_profile: { profile_id: "EXPERT-PROFILE-001", revision: 1, full_name: "Perita Sintética", professional_title: "Eng.", registration: "CREA-XX 1", court_registration: "TJ", contact_line: "c" },
    editorial_profile: { profile_id: "EDITORIAL", font_family: "Arial", body_font_pt: 11 },
    context_matrix: [], sections: [], claims: [], answers: [], review_decisions: [], state,
    coverage: complete ? { ...coverage, context_present_fields: 6, complete: true, reasons: [] } : coverage,
    upstream_stale: false, upstream_stale_reasons: [],
  },
});

describe("report review (Revisão)", () => {
  test("shows what is missing and keeps approval unavailable until the checklist is complete", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response(200, report("REVIEWED", false)))));
    render(<ReportReviewView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Revisão do laudo" })).toBeInTheDocument();
    expect(screen.getByText("Revisado")).toBeInTheDocument();
    expect(screen.getByText(/Pendente · 5 de 6 campos/)).toBeInTheDocument();
    expect(screen.getByText("Contexto processual incompleto.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aprovar laudo" })).toBeDisabled();
    expect(screen.getByText(/A aprovação fica disponível quando a conferência estiver completa/)).toBeInTheDocument();
  });

  test("an explicit, reasoned professional act approves a complete report", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => Promise.resolve(response(200, init?.method === "POST" ? report("APPROVED", true) : report("REVIEWED", true))));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReportReviewView workspaceId={ID} />);
    const approve = await screen.findByRole("button", { name: "Aprovar laudo" });
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Fundamentação da revisão"), { target: { value: "Laudo conferido." } });
    expect(approve).toBeEnabled();
    fireEvent.click(approve);
    expect(await screen.findByRole("link", { name: "Ir para a entrega" })).toBeInTheDocument();
    const body = JSON.parse(String((fetchMock.mock.calls.at(-1)![1] as RequestInit).body));
    expect(body).toMatchObject({ action: "APPROVE", reason: "Laudo conferido.", professional_id: "EXPERT-PROFILE-001" });
  });
});
