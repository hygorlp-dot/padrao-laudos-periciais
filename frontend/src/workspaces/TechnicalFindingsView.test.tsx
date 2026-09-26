import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ExpertIdentityProvider } from "../data/expertIdentity";
import { TechnicalFindingsView } from "./TechnicalFindingsView";

const ID = "11111111-1111-4111-8111-111111111111";
const snapshot = {
  schema_version: "1.0.0", snapshot_id: "TECHNICAL-SNAPSHOT-001", workspace_id: ID,
  source_snapshot: { workspace_id: ID, case_analysis_snapshot_id: "CASE-001", case_analysis_revision: 3, case_analysis_digest: "a".repeat(64), inspection_session_id: "INSPECTION-001", inspection_session_revision: 2, inspection_session_digest: "b".repeat(64), source_revision: 4 },
  evidence_items: [{ evidence_id: "EVIDENCE-001", proposition: "Leitura bruta sintética.", assessment_id: "ASSESSMENT-001" }],
  source_links: [{ link_id: "SOURCE-LINK-001", evidence_id: "EVIDENCE-001", source_kind: "MEASUREMENT", source_id: "MEASUREMENT-001", source_revision: 2, provenance: "Vistoria sintética." }],
  evidence_assessments: [{ assessment_id: "ASSESSMENT-001", evidence_id: "EVIDENCE-001", why_relevant: "Relevante à questão.", supported_proposition: "Leitura bruta sintética.", limitation_ids: ["LIMIT-EVIDENCE-001"], contrary_evidence_ids: [], source_link_ids: ["SOURCE-LINK-001"], review_state: "APPROVED", review_id: "EVIDENCE-REVIEW-001", reviewer: "PROFESSIONAL-001", review_reason: "Revisão explícita.", reviewed_at: "2026-08-31T10:00:00Z" }],
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

// A tela também lê vistoria, análise e perfil do perito para montar os seletores.
// Estas leituras são roteadas por URL; o mock recebido responde só à cadeia técnica.
const inspection = {
  revision: 2, updated_at: "2026-08-31T10:00:00Z",
  snapshot: {
    schema_version: "1.0.0", session_id: "INSPECTION-001", workspace_id: ID,
    plan_snapshot: { plan_id: "PLAN-1", planning_snapshot_id: "PLANNING-1", planning_revision: 1, planning_digest: "c".repeat(64), workspace_id: ID, approved_item_ids: [], source_revision: 1 },
    started_at: "2026-08-31T09:00:00Z", ended_at: null, location_context: "Imóvel sintético", participant_references: [], responsible_professional: "PROFESSIONAL-001", source_revision: 1,
    items: [{ item_id: "ITEM-1", planning_item_id: "PLAN-ITEM-1", title: "Item", state: "COMPLETED", observation_ids: [], measurement_ids: ["MEASUREMENT-002"], photo_ids: [], limitation_ids: [], note: null }],
    observations: [], statements: [],
    measurements: [{ measurement_id: "MEASUREMENT-002", inspection_item_id: "ITEM-1", quantity: "abertura", raw_value: "0,3", raw_unit: "mm", normalized_value: null, normalized_unit: null, instrument_id: "I", method_id: "M", location_id: "L", timestamp: "2026-08-31T09:10:00Z", operator: "P", uncertainty: null, raw_observation: "Fissura da sala", provenance: "Campo" }],
    measurement_series: [], methods: [], instruments: [], instrument_statuses: [], photos: [], videos: [], sketches: [], locations: [], environmental_conditions: [], access_occurrences: [], limitations: [], missing_items: [], evidence_candidates: [],
    coverage: { total_items: 1, pending_items: 0, completed_items: 1, partial_items: 0, not_executed_items: 0, not_applicable_items: 0, blocked_items: 0, complete: true, limitation_ids: [], reasons: [] },
    reviews: [], upstream_stale: false, upstream_stale_reasons: [],
  },
};
const expertProfile = { revision: 1, updated_at: "2026-08-31T10:00:00Z", profile: { profile_id: "EXPERT-PROFILE-001", revision: 1, full_name: "Perita Sintética", professional_title: "Engenheira civil", registration: "CREA-XX 000000", court_registration: "TJ-000", contact_line: "contato" } };
function routed(technical: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>, options: { profile?: boolean } = {}) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/inspection-session")) return Promise.resolve(response(200, inspection));
    if (url.endsWith("/case-analysis")) return Promise.resolve(response(404, {}));
    if (url.endsWith("/expert-profile")) return Promise.resolve(options.profile ? response(200, expertProfile) : response(404, {}));
    return technical(input, init);
  });
}
const technicalCalls = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.filter(([url]) => String(url).includes("/technical-snapshot"));

describe("technical findings workbench", () => {
  test("renders the complete chain without flattening proposal into professional finding", async () => {
    vi.stubGlobal("fetch", routed(vi.fn(() => Promise.resolve(response(200, envelope)))));
    render(<TechnicalFindingsView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Cadeia técnica" })).toBeInTheDocument();
    const chain = within(screen.getByRole("list", { name: "Etapas da cadeia técnica" }));
    expect(chain.getByText("Leitura bruta sintética.")).toBeInTheDocument();
    expect(chain.getByText("Comparação")).toBeInTheDocument();
    expect(chain.getByText("Proposição técnica sintética.")).toBeInTheDocument();
    expect(screen.getByText(/proposta não produz conclusão efetiva/i)).toBeInTheDocument();
    expect(screen.getAllByText(/decisão profissional explícita/i)).toHaveLength(1);
    expect(screen.getByLabelText("Tipo canônico da fonte")).toBeInTheDocument();
    expect(screen.getByLabelText("Evidência pendente")).toBeInTheDocument();
    // Estados e origens na língua do perito; códigos só nos detalhes técnicos.
    expect(screen.getByText("Proposta automática")).toBeInTheDocument();
    expect(screen.queryByText("AI_PROPOSAL")).not.toBeInTheDocument();
    expect(screen.getAllByText("Aprovado").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Método de suporte")).toBeInTheDocument();
    expect(screen.getAllByRole("option", { name: "Modificar e aprovar" })).toHaveLength(1);
    expect(screen.queryByText(/responsabilidade civil|culpa jurídica|resposta final automática/i)).not.toBeInTheDocument();
  });

  test("starts an empty snapshot from current upstream authorities", async () => {
    const empty = { ...snapshot, evidence_items: [], source_links: [], evidence_assessments: [], method_applications: [], method_inputs: [], method_outputs: [], finding_proposals: [], findings: [], limitations: [], uncertainties: [], question_links: [], decisions: [], coverage: { evidence_items: 0, approved_evidence: 0, method_applications: 0, finding_proposals: 0, effective_findings: 0, unresolved_conflicts: 0, complete: false, reasons: ["Cadeia vazia."] } };
    const technical = vi.fn().mockResolvedValueOnce(response(404, {})).mockResolvedValueOnce(response(201, { ...envelope, snapshot: empty }));
    const fetchMock = routed(technical);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup(); render(<TechnicalFindingsView workspaceId={ID} />);
    await user.click(await screen.findByRole("button", { name: "Iniciar cadeia técnica" }));
    expect(await screen.findByRole("heading", { name: "Cadeia técnica" })).toBeInTheDocument();
    expect(technical).toHaveBeenLastCalledWith(expect.stringContaining("/technical-snapshot"), expect.objectContaining({ method: "POST" }));
  });

  test("shows stale upstream as a blocking state", async () => {
    vi.stubGlobal("fetch", routed(vi.fn(() => Promise.resolve(response(200, { ...envelope, snapshot: { ...snapshot, upstream_stale: true, upstream_stale_reasons: ["inspection session content changed"], coverage: { ...snapshot.coverage, complete: false } } })))));
    render(<TechnicalFindingsView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("não continue");
  });

  test("fails closed when the response belongs to another workspace", async () => {
    const other = "22222222-2222-4222-8222-222222222222";
    vi.stubGlobal("fetch", routed(vi.fn(() => Promise.resolve(response(200, { ...envelope, snapshot: { ...snapshot, workspace_id: other, source_snapshot: { ...snapshot.source_snapshot, workspace_id: other } } })))));
    render(<TechnicalFindingsView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar");
  });

  test("captures explicit professional identity and never defaults approval", async () => {
    vi.stubGlobal("fetch", routed(vi.fn(() => Promise.resolve(response(200, envelope)))));
    render(<TechnicalFindingsView workspaceId={ID} />);
    expect(await screen.findByLabelText("Ação profissional")).toHaveValue("REJECT");
    expect(screen.getByLabelText("Profissional responsável")).toHaveValue("");
    expect(screen.getAllByText(/Cadastre seu perfil na etapa Laudo/).length).toBeGreaterThan(0);
  });

  test("prefills the deciding professional from the expert profile, still editable, never approving", async () => {
    vi.stubGlobal("fetch", routed(vi.fn(() => Promise.resolve(response(200, envelope))), { profile: true }));
    render(<ExpertIdentityProvider workspaceId={ID}><TechnicalFindingsView workspaceId={ID} /></ExpertIdentityProvider>);
    await waitFor(() => expect(screen.getByLabelText("Profissional responsável")).toHaveValue("EXPERT-PROFILE-001"));
    expect(screen.getAllByText(/Perita Sintética · CREA-XX 000000/).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Ação profissional")).toHaveValue("REJECT");
    fireEvent.change(screen.getByLabelText("Profissional responsável"), { target: { value: "OUTRO" } });
    expect(screen.getByLabelText("Profissional responsável")).toHaveValue("OUTRO");
  });

  test("a question from the case can be cited as evidence, so a finding can answer it", async () => {
    const provenance = [{ workspace_id: ID, source_document_id: "DOC-1", source_document_sha256: "a".repeat(64), page_or_span: "p. 5", source_revision: 3, occurrence_id: "OCC-1" }];
    const caseAnalysis = { revision: 3, updated_at: "2026-08-31T10:00:00Z", snapshot: {
      schema_version: "1.0.0", workspace_id: ID, judicial_context_workspace_id: ID, stale_document_ids: [], source_inventory_stale: false, unindexed_source_count: 0,
      judicial_context: { provenance: [], entities: [], participants: [], representation_links: [] },
      claims: [], counterarguments: [], decisions: [], pericial_objects: [], events: [], technical_document_references: [], gaps: [], conflicts: [], documents: [],
      questions: [{ item_id: "QUESTION-7", text: "Existem fissuras na sala?", participant_refs: [], technical_subjects: [], provenance }],
    } };
    const technical = vi.fn().mockResolvedValueOnce(response(200, envelope)).mockResolvedValueOnce(response(200, envelope));
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith("/case-analysis") ? Promise.resolve(response(200, caseAnalysis)) : routed(technical)(input, init));
    vi.stubGlobal("fetch", fetchMock);
    render(<TechnicalFindingsView workspaceId={ID} />);
    await screen.findByRole("heading", { name: "Cadeia técnica" });
    fireEvent.change(screen.getByLabelText("Tipo canônico da fonte"), { target: { value: "CASE_QUESTION" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "Existem fissuras na sala?" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Fonte"), { target: { value: "QUESTION-7" } });
    fireEvent.change(screen.getByLabelText("Proposição sustentada"), { target: { value: "O quesito pergunta sobre fissuras." } });
    fireEvent.change(screen.getByLabelText("Por que é relevante"), { target: { value: "Autoridade processual do quesito." } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar proposta de evidência" }));
    await waitFor(() => expect(technicalCalls(fetchMock)).toHaveLength(2));
    expect(JSON.parse(String((technicalCalls(fetchMock)[1][1] as RequestInit).body))).toMatchObject({ source_kind: "CASE_QUESTION", source_id: "QUESTION-7" });
  });

  test("submits only a non-authoritative evidence proposal through its command", async () => {
    const withRejectedEvidence = { ...snapshot,
      evidence_items: [...snapshot.evidence_items, { evidence_id: "EVIDENCE-REJECTED", proposition: "Fonte rejeitada.", assessment_id: "ASSESSMENT-REJECTED" }],
      source_links: [...snapshot.source_links, { ...snapshot.source_links[0], link_id: "SOURCE-LINK-REJECTED", evidence_id: "EVIDENCE-REJECTED" }],
      limitations: [...snapshot.limitations, { limitation_id: "LIMIT-EVIDENCE-REJECTED", owner_kind: "EVIDENCE", owner_id: "EVIDENCE-REJECTED", kind: "SOURCE_LIMITATION", description: "Fonte rejeitada explicitamente." }],
      evidence_assessments: [...snapshot.evidence_assessments, { ...snapshot.evidence_assessments[0], assessment_id: "ASSESSMENT-REJECTED", evidence_id: "EVIDENCE-REJECTED", supported_proposition: "Fonte rejeitada.", limitation_ids: ["LIMIT-EVIDENCE-REJECTED"], source_link_ids: ["SOURCE-LINK-REJECTED"], review_state: "REJECTED", reviewer: "PROFESSIONAL-001", reviewed_at: "2026-08-31T10:01:00Z" }],
      coverage: { ...snapshot.coverage, evidence_items: 2 },
    };
    const technical = vi.fn().mockResolvedValueOnce(response(200, { ...envelope, snapshot: withRejectedEvidence })).mockResolvedValueOnce(response(200, envelope));
    const fetchMock = routed(technical);
    vi.stubGlobal("fetch", fetchMock);
    render(<TechnicalFindingsView workspaceId={ID} />);
    await screen.findByRole("heading", { name: "Cadeia técnica" });
    // A fonte é escolhida pelo conteúdo registrado em campo, sem digitar identificador.
    const source = screen.getByLabelText("Fonte");
    await waitFor(() => expect(screen.getByRole("option", { name: "abertura: 0,3 mm · Fissura da sala" })).toBeInTheDocument());
    fireEvent.change(source, { target: { value: "MEASUREMENT-002" } });
    fireEvent.change(screen.getByLabelText("Proposição sustentada"), { target: { value: "Leitura bruta adicional." } });
    fireEvent.change(screen.getByLabelText("Por que é relevante"), { target: { value: "Relaciona-se à questão técnica." } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar proposta de evidência" }));
    await waitFor(() => expect(technicalCalls(fetchMock)).toHaveLength(2));
    const call = technicalCalls(fetchMock)[1];
    const body = JSON.parse(String((call[1] as RequestInit).body));
    expect(String(call[0])).toContain("/evidence-proposals");
    expect(body).toEqual({ source_kind: "MEASUREMENT", source_id: "MEASUREMENT-002", proposition: "Leitura bruta adicional.", why_relevant: "Relaciona-se à questão técnica.", expected_revision: 1 });
    expect(JSON.stringify(body)).not.toMatch(/decision_id|finding_id|reviewed_at|APPROVED/);
  });
});
