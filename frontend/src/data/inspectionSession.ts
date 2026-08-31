const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const STATES = ["PENDING", "COMPLETED", "PARTIAL", "NOT_EXECUTED", "NOT_APPLICABLE", "BLOCKED"] as const;
export type ExecutionState = typeof STATES[number];

export type InspectionItem = { item_id: string; planning_item_id: string; title: string; state: ExecutionState; observation_ids: string[]; measurement_ids: string[]; photo_ids: string[]; limitation_ids: string[]; note: string | null };
export type FieldObservation = { observation_id: string; inspection_item_id: string; observation_type: string; raw_observation: string; location_id: string; timestamp: string; operator: string; provenance: string };
export type FieldStatement = { statement_id: string; inspection_item_id: string; observation_type: "PARTY_STATEMENT_ON_SITE"; speaker: string; declared_role: string; verbatim_or_summary: string; capture_kind: string; timestamp: string; provenance: string };
export type Measurement = { measurement_id: string; inspection_item_id: string; quantity: string; raw_value: string; raw_unit: string; normalized_value: string | null; normalized_unit: string | null; instrument_id: string; method_id: string; location_id: string; timestamp: string; operator: string; uncertainty: string | null; raw_observation: string; provenance: string };
export type PhotoRecord = { photo_id: string; inspection_item_id: string; private_content_id: string; original_sha256: string; reliable_capture_timestamp: string; location_id: string; caption: string; device: string; provenance: string };
export type FieldLimitation = { limitation_id: string; inspection_item_id: string; kind: string; description: string; consequence_for_coverage: string; provenance: string };
export type EvidenceCandidate = { candidate_id: string; inspection_item_id: string; source_record_ids: string[]; description: string; provenance: string };
export type InspectionSnapshot = {
  schema_version: "1.0.0"; session_id: string; workspace_id: string;
  plan_snapshot: { plan_id: string; planning_snapshot_id: string; planning_revision: number; planning_digest: string; workspace_id: string; approved_item_ids: string[]; source_revision: number };
  started_at: string; ended_at: string | null; location_context: string; participant_references: string[]; responsible_professional: string; source_revision: number;
  items: InspectionItem[]; observations: FieldObservation[]; statements: FieldStatement[]; measurements: Measurement[]; measurement_series: unknown[]; methods: unknown[]; instruments: unknown[]; instrument_statuses: unknown[]; photos: PhotoRecord[]; videos: unknown[]; sketches: unknown[]; locations: unknown[]; environmental_conditions: unknown[]; access_occurrences: unknown[]; limitations: FieldLimitation[]; missing_items: unknown[]; evidence_candidates: EvidenceCandidate[];
  coverage: { total_items: number; pending_items: number; completed_items: number; partial_items: number; not_executed_items: number; not_applicable_items: number; blocked_items: number; complete: boolean; limitation_ids: string[]; reasons: string[] };
  reviews: unknown[]; upstream_stale: boolean; upstream_stale_reasons: string[];
};
export type InspectionEnvelope = { revision: number; updated_at: string; snapshot: InspectionSnapshot };

export class InspectionSessionApiError extends Error {
  constructor(public readonly kind: "not-found" | "invalid-response" | "unavailable", message: string) { super(message); this.name = "InspectionSessionApiError"; }
}

function invalid(): never { throw new InspectionSessionApiError("invalid-response", "Resposta local de vistoria inválida"); }
function objects(value: unknown): Record<string, unknown>[] { if (!Array.isArray(value) || value.some((item) => typeof item !== "object" || item === null || Array.isArray(item))) invalid(); return value as Record<string, unknown>[]; }

export function parseInspectionEnvelope(value: unknown, workspaceId: string): InspectionEnvelope {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid();
  const envelope = value as Record<string, unknown>;
  if (Object.keys(envelope).sort().join("|") !== "revision|snapshot|updated_at" || !Number.isSafeInteger(envelope.revision) || (envelope.revision as number) < 1 || typeof envelope.updated_at !== "string") invalid();
  const snapshot = envelope.snapshot as Record<string, unknown> | undefined;
  const plan = snapshot?.plan_snapshot as Record<string, unknown> | undefined;
  const coverage = snapshot?.coverage as Record<string, unknown> | undefined;
  if (!snapshot || snapshot.schema_version !== "1.0.0" || snapshot.workspace_id !== workspaceId || !plan || plan.workspace_id !== workspaceId || !coverage || typeof coverage.complete !== "boolean" || typeof snapshot.upstream_stale !== "boolean" || !Array.isArray(snapshot.upstream_stale_reasons)) invalid();
  const items = objects(snapshot.items); const ids = new Set<string>();
  for (const item of items) { if (typeof item.item_id !== "string" || !item.item_id || ids.has(item.item_id) || !STATES.includes(item.state as ExecutionState)) invalid(); ids.add(item.item_id); }
  for (const name of ["observations", "statements", "measurements", "photos", "limitations", "evidence_candidates"] as const) {
    for (const record of objects(snapshot[name])) if (typeof record.inspection_item_id !== "string" || !ids.has(record.inspection_item_id)) invalid();
  }
  for (const statement of objects(snapshot.statements)) if (statement.observation_type !== "PARTY_STATEMENT_ON_SITE") invalid();
  for (const photo of objects(snapshot.photos)) if (typeof photo.private_content_id !== "string" || !UUID.test(photo.private_content_id) || typeof photo.original_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(photo.original_sha256)) invalid();
  for (const name of ["participant_references", "measurement_series", "methods", "instruments", "instrument_statuses", "videos", "sketches", "locations", "environmental_conditions", "access_occurrences", "missing_items", "reviews"] as const) if (!Array.isArray(snapshot[name])) invalid();
  return envelope as unknown as InspectionEnvelope;
}

export async function getInspectionSession(workspaceId: string, signal?: AbortSignal) {
  if (!UUID.test(workspaceId)) invalid();
  let response: Response;
  try { response = await fetch(`/app-api/v1/workspaces/${workspaceId}/inspection-session`, { method: "GET", credentials: "same-origin", cache: "no-store", signal }); }
  catch { throw new InspectionSessionApiError("unavailable", "Serviço local indisponível"); }
  if (response.status === 404) throw new InspectionSessionApiError("not-found", "Vistoria ainda não registrada");
  if (!response.ok || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new InspectionSessionApiError("unavailable", "Não foi possível carregar a vistoria");
  try { return parseInspectionEnvelope(await response.json(), workspaceId); }
  catch (error) { if (error instanceof InspectionSessionApiError) throw error; throw new InspectionSessionApiError("invalid-response", "Resposta local de vistoria inválida"); }
}
