import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ConstructionDefectAnalysisView } from "./ConstructionDefectAnalysisView";

const ID = "11111111-1111-4111-8111-111111111111";
const response = (status: number, value: object) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const inspection = {
  schema_version: "1.0.0",
  session_id: "INSPECTION-001",
  workspace_id: ID,
  plan_snapshot: {
    plan_id: "PLAN-001",
    planning_snapshot_id: "PLANNING-001",
    planning_revision: 4,
    planning_digest: "a".repeat(64),
    workspace_id: ID,
    approved_item_ids: ["ITEM-001"],
    source_revision: 2,
  },
  started_at: "2026-09-08T10:00:00Z",
  ended_at: "2026-09-08T11:00:00Z",
  location_context: "Local sintético",
  participant_references: [],
  responsible_professional: "PROFESSIONAL-001",
  source_revision: 2,
  items: [{ item_id: "ITEM-001", planning_item_id: "PLAN-ITEM-001", title: "Parede", state: "COMPLETED", observation_ids: ["OBS-001"], measurement_ids: ["MED-001"], photo_ids: ["PHOTO-001"], limitation_ids: [], note: null }],
  observations: [{ observation_id: "OBS-001", inspection_item_id: "ITEM-001", observation_type: "DIRECT_OBSERVATION", raw_observation: "Umidade observada na parede.", location_id: "LOCATION-001", timestamp: "2026-09-08T10:10:00Z", operator: "PROFESSIONAL-001", provenance: "Registro sintético." }],
  statements: [],
  measurements: [{ measurement_id: "MED-001", inspection_item_id: "ITEM-001", quantity: "Comprimento", raw_value: "1250", raw_unit: "mm", normalized_value: null, normalized_unit: null, instrument_id: "INSTRUMENT-001", method_id: "METHOD-001", location_id: "LOCATION-001", timestamp: "2026-09-08T10:15:00Z", operator: "PROFESSIONAL-001", uncertainty: null, raw_observation: "Leitura sintética.", provenance: "Registro sintético." }],
  measurement_series: [],
  methods: [{ method_id: "METHOD-001", name: "Medição direta" }],
  instruments: [], instrument_statuses: [],
  photos: [{ photo_id: "PHOTO-001", inspection_item_id: "ITEM-001", private_content_id: "22222222-2222-4222-8222-222222222222", original_sha256: "b".repeat(64), reliable_capture_timestamp: null, capture_timestamp_reliability: "UNVERIFIED", location_id: "LOCATION-001", caption: "Parede inspecionada.", device: "Dispositivo sintético", provenance: "Original preservado." }],
  videos: [], sketches: [], locations: [], environmental_conditions: [], access_occurrences: [], limitations: [], missing_items: [], evidence_candidates: [], reviews: [],
  coverage: { total_items: 1, pending_items: 0, completed_items: 1, partial_items: 0, not_executed_items: 0, not_applicable_items: 0, blocked_items: 0, complete: true, limitation_ids: [], reasons: [] },
  upstream_stale: false, upstream_stale_reasons: [],
};

const provenance = [{ workspace_id: ID, source_document_id: "DOC-001", source_document_sha256: "c".repeat(64), page_or_span: "p. 1", source_revision: 2, occurrence_id: "OCC-001" }];
const caseAnalysis = {
  schema_version: "1.0.0", snapshot_id: "CASE-001", workspace_id: ID, source_revision: 2,
  participant_refs: [], judicial_context_workspace_id: ID,
  judicial_context: { provenance: [{ source_document_id: "DOC-001" }], entities: [], participants: [], representation_links: [], access_relations: [] },
  documents: [], claims: [{ item_id: "CLAIM-001", text: "Alegação sintética.", participant_refs: [], technical_subjects: [], provenance }], counterarguments: [], decisions: [], pericial_objects: [],
  questions: [{ item_id: "QUESTION-001", text: "Qual a origem da manifestação?", participant_refs: [], technical_subjects: [], provenance }],
  events: [], technical_document_references: [], gaps: [], conflicts: [],
  coverage: { status: "COMPLETE", documents_total: 1, documents_analyzed: 1, documents_unavailable: 0, documents_failed: 0, source_revision: 2 },
  human_reviews: [], stale_document_ids: [], source_inventory_stale: false, unindexed_source_count: 0,
};

const pathology = {
  schema_version: "1.0.0", snapshot_id: "PAT-SNAPSHOT-001", workspace_id: ID,
  source_snapshot: { workspace_id: ID, process_case_revision: 2, process_case_digest: "1".repeat(64), case_analysis_snapshot_id: "CASE-001", case_analysis_revision: 3, case_analysis_digest: "2".repeat(64), planning_snapshot_id: "PLANNING-001", planning_revision: 4, planning_digest: "3".repeat(64), inspection_session_id: "INSPECTION-001", inspection_revision: 5, inspection_digest: "4".repeat(64), source_revision: 2 },
  observation_contexts: [{ observation_id: "OBS-001", manifestation: "Umidade observada na parede.", system: "VEDACOES", element: "Parede", outcome: "OBSERVED", methods: ["METHOD-001"], measurement_ids: ["MED-001"], photo_ids: ["PHOTO-001"], claim_ids: ["CLAIM-001"], question_ids: ["QUESTION-001"] }],
  identity_links: [{ canonical_kind: "PATHOLOGY", canonical_id: "PAT-001", legacy_kind: "PATHOLOGY", legacy_id: "PAT-001" }],
  analysis_final: { schema_version: "1.0.0", estado_analise: "PAT_FINAL", patologias: [{ id: "PAT-001", manifestacao: "Umidade observada na parede.", conclusao_tecnica: "Hipótese técnica limitada às evidências sintéticas.", status_validacao: "RASCUNHO", evidencias: ["OBS-001", "MED-001", "FOT-001"] }] },
  gate: "APTO_PARA_REDACAO_COM_RESSALVAS",
  reviews: [{ review_id: "PAT-REVIEW-001", pat_id: "PAT-001", action: "APPROVE", professional_id: "PROFESSIONAL-001", reason: "Revisão explícita.", reviewed_at: "2026-09-08T12:00:00Z", supersedes_review_id: null }],
  upstream_stale: false, upstream_stale_reasons: [],
};

const envelope = { revision: 5, updated_at: "2026-09-08T12:00:00Z", snapshot: pathology };
const inspectEnvelope = { revision: 5, updated_at: "2026-09-08T11:00:00Z", snapshot: inspection };
const caseEnvelope = { revision: 3, updated_at: "2026-09-08T09:00:00Z", snapshot: caseAnalysis };

function fetchByUrl(pathologyResponse = response(200, envelope)) {
  return vi.fn((...args: [RequestInfo | URL, RequestInit?]) => {
    const [input] = args;
    const url = String(input);
    if (url.endsWith("/construction-defect-analysis")) return Promise.resolve(pathologyResponse);
    if (url.endsWith("/inspection-session")) return Promise.resolve(response(200, inspectEnvelope));
    if (url.endsWith("/case-analysis")) return Promise.resolve(response(200, caseEnvelope));
    return Promise.resolve(response(404, {}));
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("construction defect analysis workbench", () => {
  test("renders PAT, exact provenance and effective professional state without flattening", async () => {
    vi.stubGlobal("fetch", fetchByUrl());
    render(<ConstructionDefectAnalysisView workspaceId={ID} />);

    expect(await screen.findByRole("heading", { name: "Análise de manifestações construtivas" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "PAT-001" })).toBeInTheDocument();
    expect(screen.getByText("Aprovada pelo profissional")).toBeInTheDocument();
    expect(screen.getByText(/OBS-001/)).toBeInTheDocument();
    expect(screen.queryByText(/responsabilidade civil|culpa jurídica/i)).not.toBeInTheDocument();
  });

  test("surfaces stale authority and disables further professional review", async () => {
    const staleEnvelope = {
      ...envelope,
      snapshot: {
        ...envelope.snapshot,
        upstream_stale: true,
        upstream_stale_reasons: ["Inspection Session content changed"],
      },
    };
    vi.stubGlobal("fetch", fetchByUrl(response(200, staleEnvelope)));
    render(<ConstructionDefectAnalysisView workspaceId={ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("análise bloqueada");
    expect(screen.getByRole("button", { name: "Registrar revisão" })).toBeDisabled();
  });

  test("starts from one explicit same-item observation context", async () => {
    const fetchMock = fetchByUrl(response(404, {}));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(404, {})));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, inspectEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, caseEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(201, envelope)));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ConstructionDefectAnalysisView workspaceId={ID} />);

    await user.selectOptions(await screen.findByLabelText("Observação direta"), "OBS-001");
    await user.selectOptions(screen.getByLabelText("Método registrado"), "METHOD-001");
    await user.click(screen.getByLabelText("MED-001 — 1250 mm"));
    await user.click(screen.getByLabelText("PHOTO-001 — Parede inspecionada."));
    await user.selectOptions(screen.getByLabelText("Alegação relacionada"), "CLAIM-001");
    await user.selectOptions(screen.getByLabelText("Quesito relacionado"), "QUESTION-001");
    await user.click(screen.getByRole("button", { name: "Gerar proposta PAT" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    const body = JSON.parse(String(fetchMock.mock.calls[3][1]?.body));
    expect(body.observation_contexts).toEqual([{ observation_id: "OBS-001", manifestation: "Umidade observada na parede.", system: null, element: null, outcome: "INCONCLUSIVE", methods: ["METHOD-001"], measurement_ids: ["MED-001"], photo_ids: ["PHOTO-001"], claim_ids: ["CLAIM-001"], question_ids: ["QUESTION-001"] }]);
  });

  test("review remains an explicit fail-closed professional command", async () => {
    const fetchMock = fetchByUrl();
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, envelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, inspectEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, caseEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, envelope)));
    vi.stubGlobal("fetch", fetchMock);
    render(<ConstructionDefectAnalysisView workspaceId={ID} />);
    await screen.findByRole("heading", { name: "PAT-001" });
    fireEvent.change(screen.getByLabelText("Fundamentação da revisão"), { target: { value: "Confirmação humana sintética." } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar revisão" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    const body = JSON.parse(String(fetchMock.mock.calls[3][1]?.body));
    expect(body).toEqual({ expected_revision: 5, pat_id: "PAT-001", action: "REJECT", professional_id: "PROFESSIONAL-001", reason: "Confirmação humana sintética." });
  });

  test("retries an initial partial load without leaving the product surface", async () => {
    const fetchMock = fetchByUrl();
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError("local transport interrupted")));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ConstructionDefectAnalysisView workspaceId={ID} />);

    await user.click(await screen.findByRole("button", { name: "Tentar novamente" }));

    expect(await screen.findByRole("heading", { name: "PAT-001" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  test("reconciles an ambiguous successful start before inviting a duplicate action", async () => {
    const committedStartEnvelope = {
      ...envelope,
      snapshot: {
        ...envelope.snapshot,
        observation_contexts: [{
          observation_id: "OBS-001",
          manifestation: "Umidade observada na parede.",
          system: null,
          element: null,
          outcome: "INCONCLUSIVE" as const,
          methods: ["METHOD-001"],
          measurement_ids: [],
          photo_ids: [],
          claim_ids: [],
          question_ids: [],
        }],
      },
    };
    const fetchMock = fetchByUrl(response(404, {}));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(404, {})));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, inspectEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, caseEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError("response lost after commit")));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, committedStartEnvelope)));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ConstructionDefectAnalysisView workspaceId={ID} />);

    await user.selectOptions(await screen.findByLabelText("Observação direta"), "OBS-001");
    await user.selectOptions(screen.getByLabelText("Método registrado"), "METHOD-001");
    await user.click(screen.getByRole("button", { name: "Gerar proposta PAT" }));

    expect(await screen.findByRole("heading", { name: "PAT-001" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  test("keeps backend failure visible when reconciliation finds no newer review", async () => {
    const fetchMock = fetchByUrl();
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, envelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, inspectEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, caseEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError("request failed before commit")));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, envelope)));
    vi.stubGlobal("fetch", fetchMock);
    render(<ConstructionDefectAnalysisView workspaceId={ID} />);

    await screen.findByRole("heading", { name: "PAT-001" });
    fireEvent.change(screen.getByLabelText("Fundamentação da revisão"), { target: { value: "Revisão sintética." } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar revisão" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("operação foi recusada");
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  test("does not mistake an unrelated concurrent review for this user's command", async () => {
    const unrelatedConcurrentEnvelope = {
      ...envelope,
      revision: 6,
      snapshot: {
        ...envelope.snapshot,
        reviews: [
          ...envelope.snapshot.reviews,
          {
            review_id: "PAT-REVIEW-OTHER",
            pat_id: "PAT-001",
            action: "APPROVE" as const,
            professional_id: "PROFESSIONAL-001",
            reason: "Outra decisão concorrente.",
            reviewed_at: "2026-09-08T12:01:00Z",
            supersedes_review_id: "PAT-REVIEW-001",
          },
        ],
      },
    };
    const fetchMock = fetchByUrl();
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, envelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, inspectEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, caseEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError("request outcome unknown")));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, unrelatedConcurrentEnvelope)));
    vi.stubGlobal("fetch", fetchMock);
    render(<ConstructionDefectAnalysisView workspaceId={ID} />);

    await screen.findByRole("heading", { name: "PAT-001" });
    fireEvent.change(screen.getByLabelText("Fundamentação da revisão"), { target: { value: "Minha decisão esperada." } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar revisão" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("operação foi recusada");
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  test("recovers an exact professional review committed before its response was lost", async () => {
    const recoveredEnvelope = {
      ...envelope,
      revision: 6,
      snapshot: {
        ...envelope.snapshot,
        reviews: [
          ...envelope.snapshot.reviews,
          {
            review_id: "PAT-REVIEW-RECOVERED",
            pat_id: "PAT-001",
            action: "REJECT" as const,
            professional_id: "PROFESSIONAL-001",
            reason: "Minha revisão recuperada.",
            reviewed_at: "2026-09-08T12:01:00Z",
            supersedes_review_id: "PAT-REVIEW-001",
          },
        ],
      },
    };
    const fetchMock = fetchByUrl();
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, envelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, inspectEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, caseEnvelope)));
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError("response lost after commit")));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(200, recoveredEnvelope)));
    vi.stubGlobal("fetch", fetchMock);
    render(<ConstructionDefectAnalysisView workspaceId={ID} />);

    await screen.findByRole("heading", { name: "PAT-001" });
    fireEvent.change(screen.getByLabelText("Fundamentação da revisão"), { target: { value: "Minha revisão recuperada." } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar revisão" }));

    expect(await screen.findByText("Rejeitada pelo profissional")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });
});
