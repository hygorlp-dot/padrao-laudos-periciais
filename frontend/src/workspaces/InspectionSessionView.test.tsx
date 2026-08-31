import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { InspectionSessionView } from "./InspectionSessionView";

const ID = "11111111-1111-4111-8111-111111111111";
const snapshot = {
  schema_version: "1.0.0", session_id: "SESSION-001", workspace_id: ID,
  plan_snapshot: { plan_id: "PLAN-001", planning_snapshot_id: "PLANNING-001", planning_revision: 2, planning_digest: "d".repeat(64), workspace_id: ID, approved_item_ids: ["PLAN-ITEM-001"], source_revision: 4 },
  started_at: "2026-08-30T12:00:00Z", ended_at: null, location_context: "Local sintético", participant_references: ["PARTICIPANT-001"], responsible_professional: "PROFESSIONAL-001", source_revision: 1,
  items: [{ item_id: "ITEM-001", planning_item_id: "PLAN-ITEM-001", title: "Inspeção visual", state: "PARTIAL", observation_ids: ["OBS-001"], measurement_ids: ["MEAS-001"], photo_ids: ["PHOTO-001"], limitation_ids: ["LIMIT-001"], note: "Execução parcial." }],
  observations: [{ observation_id: "OBS-001", inspection_item_id: "ITEM-001", observation_type: "DIRECT_OBSERVATION", raw_observation: "Superfície visível.", location_id: "LOC-001", timestamp: "2026-08-30T12:05:00Z", operator: "PROFESSIONAL-001", provenance: "Registro direto." }],
  statements: [{ statement_id: "STATEMENT-001", inspection_item_id: "ITEM-001", observation_type: "PARTY_STATEMENT_ON_SITE", speaker: "PARTICIPANT-001", declared_role: "Parte presente", verbatim_or_summary: "Declaração não confirmada como fato.", capture_kind: "SUMMARY", timestamp: "2026-08-30T12:06:00Z", provenance: "Declaração oral." }],
  measurements: [{ measurement_id: "MEAS-001", inspection_item_id: "ITEM-001", quantity: "comprimento", raw_value: "1250", raw_unit: "mm", normalized_value: "1.25", normalized_unit: "m", instrument_id: "INST-001", method_id: "METHOD-001", location_id: "LOC-001", timestamp: "2026-08-30T12:07:00Z", operator: "PROFESSIONAL-001", uncertainty: "±1 mm", raw_observation: "Leitura direta.", provenance: "Registro sintético." }],
  measurement_series: [], methods: [], instruments: [], instrument_statuses: [],
  photos: [{ photo_id: "PHOTO-001", inspection_item_id: "ITEM-001", private_content_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", original_sha256: "e".repeat(64), reliable_capture_timestamp: "2026-08-30T12:08:00Z", location_id: "LOC-001", caption: "Limite acessível.", device: "DEVICE-001", provenance: "Original privado." }],
  videos: [], sketches: [], locations: [{ location_id: "LOC-001", description: "Área sintética", parent_location_id: null }], environmental_conditions: [], access_occurrences: [],
  limitations: [{ limitation_id: "LIMIT-001", inspection_item_id: "ITEM-001", kind: "ACCESS_LIMITATION", description: "Área complementar inacessível.", consequence_for_coverage: "Cobertura parcial.", provenance: "ACCESS-001" }], missing_items: [],
  evidence_candidates: [{ candidate_id: "CANDIDATE-001", inspection_item_id: "ITEM-001", source_record_ids: ["OBS-001", "MEAS-001"], description: "Candidato para análise futura.", provenance: "Registros brutos." }],
  coverage: { total_items: 1, pending_items: 0, completed_items: 0, partial_items: 1, not_executed_items: 0, not_applicable_items: 0, blocked_items: 0, complete: false, limitation_ids: ["LIMIT-001"], reasons: ["Cobertura parcial."] },
  reviews: [], upstream_stale: false, upstream_stale_reasons: [],
};

const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

describe("inspection session view", () => {
  test("separates raw field records, party statements, media authority and limitations", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { revision: 1, updated_at: "2026-08-30T13:00:00Z", snapshot })));
    render(<InspectionSessionView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Vistoria de campo" })).toBeInTheDocument();
    expect(screen.getAllByText("Execução parcial")).toHaveLength(2);
    expect(screen.getByText("1250 mm")).toBeInTheDocument();
    expect(screen.getByText(/Declaração da parte — não é observação pericial/)).toBeInTheDocument();
    expect(screen.getByText(/Original privado · SHA-256/)).toBeInTheDocument();
    expect(screen.getByText("Área complementar inacessível.")).toBeInTheDocument();
    expect(screen.getByText(/candidato a análise técnica futura/i)).toBeInTheDocument();
    expect(screen.queryByText(/conclusão pericial|responsabilidade|resposta ao quesito/i)).not.toBeInTheDocument();
  });

  test("shows honest empty state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(404, {})));
    render(<InspectionSessionView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Vistoria ainda não registrada" })).toBeInTheDocument();
  });
});
