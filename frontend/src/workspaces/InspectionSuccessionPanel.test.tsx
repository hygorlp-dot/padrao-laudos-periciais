import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { InspectionSnapshot } from "../data/inspectionSession";
import { InspectionSuccessionPanel } from "./InspectionSuccessionPanel";

const ID = "11111111-1111-4111-8111-111111111111";
const base = {
  schema_version: "1.0.0", session_id: "SESSION-V2", workspace_id: ID,
  plan_snapshot: { plan_id: "PLAN-V2", planning_snapshot_id: "PLANNING-V2", planning_revision: 7, planning_digest: "d".repeat(64), workspace_id: ID, approved_item_ids: ["PLAN-ITEM"], source_revision: 2 },
  started_at: "2026-09-21T12:00:00Z", ended_at: null, location_context: "Imóvel sintético", participant_references: [], responsible_professional: "PERITO", source_revision: 2,
  items: [{ item_id: "ITEM-V2", planning_item_id: "PLAN-ITEM", title: "Verificar quesito", state: "PENDING", observation_ids: [], measurement_ids: [], photo_ids: [], limitation_ids: [], note: null }],
  observations: [], statements: [], measurements: [], measurement_series: [], methods: [], instruments: [], instrument_statuses: [], photos: [], videos: [], sketches: [],
  locations: [{ location_id: "LOC", description: "Imóvel", parent_location_id: null }], environmental_conditions: [], access_occurrences: [], limitations: [], missing_items: [], evidence_candidates: [],
  coverage: { total_items: 1, pending_items: 1, completed_items: 0, partial_items: 0, not_executed_items: 0, not_applicable_items: 0, blocked_items: 0, complete: false, limitation_ids: [], reasons: ["Itens aguardam execução."] },
  reviews: [], upstream_stale: false, upstream_stale_reasons: [],
} as unknown as InspectionSnapshot;
const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

describe("inspection succession panel", () => {
  test("a stale session offers an explicit successor that keeps the previous session as history", async () => {
    const stale = { ...base, session_id: "SESSION-V1", upstream_stale: true, upstream_stale_reasons: ["planning snapshot identity changed"] };
    const fetchMock = vi.fn().mockResolvedValueOnce(response(201, { revision: 6, updated_at: "2026-09-21T12:00:00Z", snapshot: base }));
    vi.stubGlobal("fetch", fetchMock);
    const onSaved = vi.fn();
    const user = userEvent.setup();
    render(<InspectionSuccessionPanel workspaceId={ID} envelope={{ revision: 5, updated_at: "x", snapshot: stale }} disabled={false} onSaved={onSaved} />);
    expect(screen.getByText(/permanecem no histórico, sem alteração/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Iniciar nova vistoria" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/app-api/v1/workspaces/${ID}/inspection-session/successor`);
    expect(JSON.parse(String(init.body))).toEqual({ expected_revision: 5, responsible_professional: "PERITO", location_context: "Imóvel sintético", participant_references: [] });
  });

  test("previous records enter only when the professional selects them", async () => {
    const candidates = [
      { source_record_id: "PHOTO-V1", record_kind: "PHOTO", source_item_title: "Verificar quesito", target_item_id: "ITEM-V2", target_item_title: "Verificar quesito", summary: "Parede com mancha.", captured_at: null },
      { source_record_id: "OBS-V1", record_kind: "OBSERVATION", source_item_title: "Verificar quesito", target_item_id: "ITEM-V2", target_item_title: "Verificar quesito", summary: "Mancha de umidade.", captured_at: "2026-09-20T12:30:00Z" },
    ];
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(200, { revision: 6, source_session_id: "SESSION-V1", source_revision: 5, candidates }))
      .mockResolvedValueOnce(response(200, { revision: 7, updated_at: "x", snapshot: base }));
    vi.stubGlobal("fetch", fetchMock);
    const onSaved = vi.fn();
    const user = userEvent.setup();
    render(<InspectionSuccessionPanel workspaceId={ID} envelope={{ revision: 6, updated_at: "x", snapshot: base }} disabled={false} onSaved={onSaved} />);
    const button = await screen.findByRole("button", { name: "Reaproveitar selecionados" });
    expect(button).toBeDisabled();
    expect(screen.getByText(/O estado dos itens não muda/)).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /Mancha de umidade/ }));
    await user.click(button);
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe(`/app-api/v1/workspaces/${ID}/inspection-session/reuse`);
    expect(JSON.parse(String(init.body))).toEqual({ expected_revision: 6, selections: [{ source_record_id: "OBS-V1", target_item_id: "ITEM-V2" }] });
  });

  test("a failed successor shows an error and keeps the stale state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(400, { error: { code: "INVALID_REQUEST" } })));
    const onSaved = vi.fn();
    const user = userEvent.setup();
    render(<InspectionSuccessionPanel workspaceId={ID} envelope={{ revision: 5, updated_at: "x", snapshot: { ...base, upstream_stale: true, upstream_stale_reasons: ["x"] } }} disabled={false} onSaved={onSaved} />);
    await user.click(screen.getByRole("button", { name: "Iniciar nova vistoria" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível iniciar a nova vistoria");
    expect(onSaved).not.toHaveBeenCalled();
  });
});
