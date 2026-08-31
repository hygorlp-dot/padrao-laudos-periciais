import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { TechnicalFindingsView } from "./TechnicalFindingsView";

const ID = "11111111-1111-4111-8111-111111111111";
const snapshot = {
  schema_version: "1.0.0", snapshot_id: "TECHNICAL-SNAPSHOT-001", workspace_id: ID,
  source_snapshot: { workspace_id: ID, case_analysis_snapshot_id: "CASE-001", case_analysis_revision: 3, case_analysis_digest: "a".repeat(64), inspection_session_id: "INSPECTION-001", inspection_session_revision: 2, inspection_session_digest: "b".repeat(64), source_revision: 4 },
  evidence_items: [{ evidence_id: "EVIDENCE-001", proposition: "Leitura bruta sintética.", assessment_id: "ASSESSMENT-001" }],
  source_links: [{ link_id: "SOURCE-LINK-001", evidence_id: "EVIDENCE-001", source_kind: "MEASUREMENT", source_id: "MEASUREMENT-001", source_revision: 2, provenance: "Vistoria sintética." }],
  evidence_assessments: [{ assessment_id: "ASSESSMENT-001", evidence_id: "EVIDENCE-001", why_relevant: "Relevante à questão.", supported_proposition: "Leitura bruta sintética.", limitation_ids: ["LIMIT-EVIDENCE-001"], contrary_evidence_ids: [], source_link_ids: ["SOURCE-LINK-001"], review_state: "APPROVED", reviewer: "PROFESSIONAL-001", reviewed_at: "2026-08-31T10:00:00Z" }],
  method_applications: [{ method_application_id: "METHOD-001", method_identity: "Comparação", selection_authority: "PROFESSIONAL-001", procedure: "Comparar registros.", parameters: [], input_ids: ["INPUT-001"], output_ids: ["OUTPUT-001"], limitation_ids: ["LIMIT-METHOD-001"], normative_references: [], execution_revision: 1 }],
  method_inputs: [{ input_id: "INPUT-001", method_application_id: "METHOD-001", evidence_id: "EVIDENCE-001", role: "PRIMARY_INPUT" }],
  method_outputs: [{ output_id: "OUTPUT-001", method_application_id: "METHOD-001", description: "Saída comparativa.", provenance: "Método aplicado; não é decisão." }],
  finding_proposals: [{ proposal_id: "PROPOSAL-001", technical_proposition: "Proposição técnica sintética.", origin: "AI_PROPOSAL", method_application_ids: ["METHOD-001"], supporting_evidence_ids: ["EVIDENCE-001"], contrary_evidence_ids: [], limitation_ids: ["LIMIT-PROPOSAL-001"], uncertainty_ids: ["UNCERTAINTY-001"], scope: "Amostra sintética." }],
  findings: [{ finding_id: "FINDING-001", proposal_id: "PROPOSAL-001", decision_id: "DECISION-001", technical_proposition: "Proposição técnica sintética.", scope: "Amostra sintética." }],
  dependencies: [], conflicts: [],
  limitations: [{ limitation_id: "LIMIT-EVIDENCE-001", owner_kind: "EVIDENCE", owner_id: "EVIDENCE-001", kind: "SOURCE_LIMITATION", description: "Fonte sintética." }, { limitation_id: "LIMIT-METHOD-001", owner_kind: "METHOD", owner_id: "METHOD-001", kind: "METHOD_LIMITATION", description: "Método limitado." }, { limitation_id: "LIMIT-PROPOSAL-001", owner_kind: "PROPOSAL", owner_id: "PROPOSAL-001", kind: "SCOPE_LIMITATION", description: "Escopo limitado." }],
  uncertainties: [{ uncertainty_id: "UNCERTAINTY-001", proposal_id: "PROPOSAL-001", kind: "SAMPLING_UNCERTAINTY", description: "Amostra única.", impact: "Sem extrapolação." }],
  question_links: [{ link_id: "QUESTION-LINK-001", question_id: "QUESTION-001", finding_id: "FINDING-001", relevance: "Subsídio futuro; não é resposta." }],
  decisions: [{ decision_id: "DECISION-001", proposal_id: "PROPOSAL-001", action: "APPROVE", professional_id: "PROFESSIONAL-001", reason: "Revisão explícita.", modified_proposition: null, timestamp: "2026-08-31T10:10:00Z", supersedes_decision_id: null }],
  coverage: { evidence_items: 1, approved_evidence: 1, method_applications: 1, finding_proposals: 1, effective_findings: 1, unresolved_conflicts: 0, complete: true, reasons: [] },
  upstream_stale: false, upstream_stale_reasons: [],
};
const envelope = { revision: 1, updated_at: "2026-08-31T10:10:00Z", snapshot };
const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("technical findings workbench", () => {
  test("renders the complete chain without flattening proposal into professional finding", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, envelope)));
    render(<TechnicalFindingsView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Cadeia técnica" })).toBeInTheDocument();
    expect(screen.getByText("Leitura bruta sintética.")).toBeInTheDocument();
    expect(screen.getByText("Comparação")).toBeInTheDocument();
    expect(screen.getByText("Proposição técnica sintética.")).toBeInTheDocument();
    expect(screen.getByText(/proposta não produz conclusão efetiva/i)).toBeInTheDocument();
    expect(screen.getAllByText(/decisão profissional explícita/i)).toHaveLength(2);
    expect(screen.getByLabelText("Tipo canônico da fonte")).toBeInTheDocument();
    expect(screen.getByLabelText(/Evidência contrária existente/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Quesito relacionado/)).toBeInTheDocument();
    expect(screen.getAllByRole("option", { name: "Modificar e aprovar" })).toHaveLength(2);
    expect(screen.queryByText(/responsabilidade civil|culpa jurídica|resposta final automática/i)).not.toBeInTheDocument();
  });

  test("starts an empty snapshot from current upstream authorities", async () => {
    const empty = { ...snapshot, evidence_items: [], source_links: [], evidence_assessments: [], method_applications: [], method_inputs: [], method_outputs: [], finding_proposals: [], findings: [], limitations: [], uncertainties: [], question_links: [], decisions: [], coverage: { evidence_items: 0, approved_evidence: 0, method_applications: 0, finding_proposals: 0, effective_findings: 0, unresolved_conflicts: 0, complete: false, reasons: ["Cadeia vazia."] } };
    const fetchMock = vi.fn().mockResolvedValueOnce(response(404, {})).mockResolvedValueOnce(response(201, { ...envelope, snapshot: empty }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup(); render(<TechnicalFindingsView workspaceId={ID} />);
    await user.click(await screen.findByRole("button", { name: "Iniciar cadeia técnica" }));
    expect(await screen.findByRole("heading", { name: "Cadeia técnica" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("/technical-snapshot"), expect.objectContaining({ method: "POST" }));
  });

  test("shows stale upstream as a blocking state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { ...envelope, snapshot: { ...snapshot, upstream_stale: true, upstream_stale_reasons: ["inspection session content changed"], coverage: { ...snapshot.coverage, complete: false } } })));
    render(<TechnicalFindingsView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("não continue");
  });

  test("fails closed when the response belongs to another workspace", async () => {
    const other = "22222222-2222-4222-8222-222222222222";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { ...envelope, snapshot: { ...snapshot, workspace_id: other, source_snapshot: { ...snapshot.source_snapshot, workspace_id: other } } })));
    render(<TechnicalFindingsView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar");
  });

  test("captures explicit professional identity and never defaults approval", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, envelope)));
    render(<TechnicalFindingsView workspaceId={ID} />);
    expect(await screen.findByLabelText("Ação profissional")).toHaveValue("REJECT");
    expect(screen.getByLabelText("Profissional responsável")).toHaveValue("");
  });

  test("persists a complete explicit chain while a rejected proposal stays ineffective", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(200, envelope)).mockResolvedValueOnce(response(200, envelope));
    vi.stubGlobal("fetch", fetchMock); vi.stubGlobal("crypto", { randomUUID: () => "88888888-8888-4888-8888-888888888888" });
    render(<TechnicalFindingsView workspaceId={ID} />);
    await screen.findByRole("heading", { name: "Cadeia técnica" });
    const values: Record<string, string> = {
      "Identidade da fonte ou observação": "MEASUREMENT-002", "Proposição sustentada": "Leitura bruta adicional.",
      "Por que é relevante": "Relaciona-se à questão técnica.", "Limitação da evidência": "Amostra pontual.",
      "Método selecionado": "Comparação dimensional", "Procedimento aplicado": "Comparar valores brutos.",
      "Saída do método": "Os valores divergem.", "Limitação do método": "Sem extrapolação.",
      "Proposição técnica proposta": "Há divergência na amostra.", "Escopo técnico": "Ponto medido.",
      "Limitação do achado": "Amostra única.", "Incerteza": "Representatividade limitada.",
      "Impacto da incerteza": "Impede generalização.", "Profissional responsável": "PROFESSIONAL-002",
      "Razão da decisão": "Rejeição explícita até obter nova medição.",
    };
    for (const [label, value] of Object.entries(values)) fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar cadeia e decisão" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const body = JSON.parse(String(fetchMock.mock.calls[1][1].body));
    expect(body.snapshot.decisions.at(-1).action).toBe("REJECT");
    expect(body.snapshot.finding_proposals.at(-1).origin).toBe("PROFESSIONAL_PROPOSAL");
    expect(body.snapshot.findings).toHaveLength(1);
    expect(body.snapshot.coverage.complete).toBe(false);
  });
});
