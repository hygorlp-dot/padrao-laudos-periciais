import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { CaseAnalysisView } from "./CaseAnalysisView";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const PROVENANCE = [{
  workspace_id: WORKSPACE_ID,
  source_document_id: "DOC-001",
  source_document_sha256: "a".repeat(64),
  page_or_span: "p. 3, §2",
  source_revision: 4,
  occurrence_id: "OCC-CLAIM-001",
}];
const ITEM = { item_id: "CLAIM-001", text: "A parte autora alega manifestação.", participant_refs: ["PART-CLAIMANT"], technical_subjects: ["fundação"], provenance: PROVENANCE };
const SNAPSHOT = {
  schema_version: "1.0.0", snapshot_id: "ANALYSIS-001", workspace_id: WORKSPACE_ID,
  source_revision: 4, participant_refs: ["PART-CLAIMANT", "PART-DEFENDANT"],
  judicial_context_workspace_id: WORKSPACE_ID,
  judicial_context: {
    provenance: [{ source_document_id: "DOC-CONTEXT" }],
    entities: [
      { entity_id: "ENT-CLAIMANT", raw_name: "Pessoa Autora Sintética", kind: "NATURAL_PERSON", provenance: [{ source_document_id: "DOC-001" }] },
      { entity_id: "ENT-DEFENDANT", raw_name: "Empresa Ré Sintética", kind: "LEGAL_ENTITY", provenance: [{ source_document_id: "DOC-001" }] },
      { entity_id: "ENT-REPRESENTATIVE", raw_name: "Representante Sintética", kind: "NATURAL_PERSON", provenance: [{ source_document_id: "DOC-REPRESENTATIVE" }] },
    ],
    participants: [
      { participant_id: "PART-CLAIMANT", entity_id: "ENT-CLAIMANT", pole: "ACTIVE", role: { raw_label: "AUTOR", normalized: "CLAIMANT" }, status: "ACTIVE", provenance: [{ source_document_id: "DOC-001" }] },
      { participant_id: "PART-DEFENDANT", entity_id: "ENT-DEFENDANT", pole: "PASSIVE", role: { raw_label: "RÉU", normalized: "DEFENDANT" }, status: "ACTIVE", provenance: [{ source_document_id: "DOC-001" }] },
    ],
    representation_links: [{ link_id: "REP-001", representative_entity_id: "ENT-REPRESENTATIVE", represented_participant_ids: ["PART-CLAIMANT"], representation_role_raw: "REPRESENTANTE", provenance: [{ source_document_id: "DOC-LINK" }] }],
    access_relations: [],
  },
  documents: [{ document_id: "DOC-001", source_sha256: "a".repeat(64), sequence: 1, document_role: "INITIAL_PETITION", raw_type: "Petição inicial", normalized_type: "INITIAL_PETITION", timestamp: "2026-01-10T10:00:00-03:00", participant_refs: ["PART-CLAIMANT"], page_count_or_span: "1-8", content_available: true, analysis_revision: 1 }],
  claims: [ITEM],
  counterarguments: [{ ...ITEM, item_id: "COUNTER-001", text: "A parte ré contrapõe a alegação.", participant_refs: ["PART-DEFENDANT"], target_claim_ids: ["CLAIM-001"] }],
  decisions: [{ ...ITEM, item_id: "DECISION-001", text: "O juízo delimitou o objeto.", participant_refs: [], addressed_claim_ids: ["CLAIM-001"], addressed_counterargument_ids: ["COUNTER-001"] }],
  pericial_objects: [{ ...ITEM, item_id: "OBJECT-001", text: "Delimitar a manifestação descrita nos autos." }],
  questions: [{ ...ITEM, item_id: "QUESTION-001", text: "Qual é a manifestação alegada?", answer: null }],
  events: [{ ...ITEM, item_id: "EVENT-001", text: "Juntada da petição.", event_raw: "Juntada", event_normalized: "DOCUMENT_FILED", timestamp: "2026-01-10T10:00:00-03:00", normalization_authority: "SOURCE_ADAPTER_V1" }],
  technical_document_references: [{ ...ITEM, item_id: "TECHREF-001", text: "Levantamento topográfico referenciado.", external_reference: true }],
  gaps: [{ ...ITEM, item_id: "GAP-001", text: "Anexo técnico indisponível." }],
  conflicts: [{ ...ITEM, item_id: "CONFLICT-001", text: "Possível divergência documental.", statement_a_id: "CLAIM-001", statement_b_id: "COUNTER-001", conflict_dimension: "descrição", analysis_status: "PROPOSED_CONFLICT", human_review_status: "PENDING" }],
  coverage: { status: "PARTIAL", documents_total: 2, documents_analyzed: 1, documents_unavailable: 1, documents_failed: 0, source_revision: 4 },
  human_reviews: [{ review_id: "REVIEW-001", target_item_id: "CLAIM-001", original_extraction: "manifestação", decision: "CORRECTED", corrected_value: "alegação de manifestação", reviewer: "PERITO-SYNTHETIC", revision: 1, timestamp: "2026-03-01T10:00:00-03:00", reason: "Correção sintética." }],
  stale_document_ids: ["DOC-001", "DOC-REPRESENTATIVE"],
  source_inventory_stale: true,
  unindexed_source_count: 1,
};

function response(status: number, value: object) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json; charset=utf-8" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("case analysis view", () => {
  test("presents the structured map, honest coverage and provenance drill-down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { revision: 1, updated_at: "2026-03-01T10:00:00-03:00", snapshot: SNAPSHOT })));
    const user = userEvent.setup();
    render(<CaseAnalysisView workspaceId={WORKSPACE_ID} />);

    expect(screen.getByRole("status")).toHaveTextContent("Carregando análise");
    expect(await screen.findByRole("heading", { name: "Mapa do processo" })).toBeInTheDocument();
    expect(screen.getByText("Cobertura parcial")).toBeInTheDocument();
    for (const heading of ["Documentos", "Linha do tempo", "Participantes", "Representação", "Alegações", "Contrapontos", "Decisões", "Objeto pericial", "Quesitos", "Documentos técnicos", "Lacunas", "Conflitos propostos", "Revisão humana"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.queryByRole("heading", { name: /conclusão pericial|resposta ao quesito/i })).not.toBeInTheDocument();
    expect(screen.getByText("Pessoa Autora Sintética")).toBeInTheDocument();
    expect(screen.getByText("Representante Sintética")).toBeInTheDocument();
    expect(screen.getByText(/representa Pessoa Autora Sintética/)).toBeInTheDocument();
    expect(screen.getAllByText("Fonte alterada — revisão necessária").length).toBeGreaterThan(0);
    expect(screen.getByText("1 fonte nova ainda não foi incorporada à análise.")).toBeInTheDocument();
    expect(screen.getAllByText(/identidade judicial requer revisão/).length).toBeGreaterThan(0);
    expect(screen.getByText(/representação requer revisão/)).toBeInTheDocument();
    await user.click(screen.getAllByText("Ver proveniência")[0]);
    expect(screen.getAllByText(`DOC-001 · p. 3, §2 · ocorrência OCC-CLAIM-001 · SHA ${"a".repeat(64)} · revisão 4`).length).toBeGreaterThan(0);
  });

  test("shows an honest not-yet-analyzed state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(404, { error: { code: "ARTIFACT_REVISION_NOT_FOUND" } })));
    render(<CaseAnalysisView workspaceId={WORKSPACE_ID} />);
    expect(await screen.findByRole("heading", { name: "Análise ainda não disponível" })).toBeInTheDocument();
  });

  test("starts the document index without a handcrafted snapshot", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(404, { error: { code: "ARTIFACT_REVISION_NOT_FOUND" } }))
      .mockResolvedValueOnce(response(201, { revision: 1, updated_at: "2026-08-31T12:00:00+00:00", snapshot: SNAPSHOT }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<CaseAnalysisView workspaceId={WORKSPACE_ID} />);
    await user.click(await screen.findByRole("button", { name: "Iniciar análise" }));
    await screen.findByRole("heading", { name: "Mapa do processo" });
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({});
  });

  test("warns when only the root judicial context provenance is stale", async () => {
    const contextOnly = structuredClone(SNAPSHOT);
    contextOnly.participant_refs = [];
    contextOnly.judicial_context.participants = [];
    contextOnly.judicial_context.representation_links = [];
    contextOnly.stale_document_ids = ["DOC-CONTEXT"];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { revision: 1, updated_at: "2026-03-01T10:00:00-03:00", snapshot: contextOnly })));

    render(<CaseAnalysisView workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByText("Fonte alterada — contexto judicial requer revisão")).toBeInTheDocument();
  });

  test.each([
    ["an unlisted entity", (snapshot: typeof SNAPSHOT) => { snapshot.judicial_context.entities[0].provenance = [{ source_document_id: "DOC-HIDDEN" }]; }],
    ["an access relation", (snapshot: typeof SNAPSHOT) => { (snapshot.judicial_context.access_relations as { provenance: { source_document_id: string }[] }[]).push({ provenance: [{ source_document_id: "DOC-HIDDEN" }] }); }],
  ])("warns when stale provenance belongs only to %s", async (_label, mutate) => {
    const contextOnly = structuredClone(SNAPSHOT);
    contextOnly.participant_refs = [];
    contextOnly.judicial_context.participants = [];
    contextOnly.judicial_context.representation_links = [];
    contextOnly.stale_document_ids = ["DOC-HIDDEN"];
    mutate(contextOnly);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { revision: 1, updated_at: "2026-03-01T10:00:00-03:00", snapshot: contextOnly })));

    render(<CaseAnalysisView workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByText("Fonte alterada — contexto judicial requer revisão")).toBeInTheDocument();
  });
});
