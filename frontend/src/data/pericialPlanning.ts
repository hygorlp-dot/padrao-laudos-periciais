const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export type PlanningProvenance = {
  workspace_id: string;
  source_document_id: string;
  source_document_sha256: string;
  page_or_span: string;
  source_revision: number;
  occurrence_id: string;
};

export type PlanningItem = {
  item_id: string;
  title: string;
  description: string;
  priority: string;
  proposal_status: "PROPOSED";
  professional_review_status: "PENDING" | "APPROVED" | "REJECTED" | "MODIFIED" | "DEFERRED";
  derivation: {
    rationale: string;
    case_analysis_item_ids: string[];
    source_provenance: PlanningProvenance[];
    question_ids: string[];
    pericial_object_ids: string[];
    court_decision_ids: string[];
    technical_document_reference_ids: string[];
    gap_or_conflict_ids: string[];
  };
  [key: string]: unknown;
};

export const PLANNING_COLLECTIONS = [
  "objectives", "issues", "question_links", "required_documents", "required_information",
  "inspection_requirements", "measurement_requirements", "photo_requirements", "equipment_requirements",
  "access_requirements", "method_candidates", "procedure_candidates", "sampling_candidates",
  "safety_requirements", "external_support_requirements", "risks", "gaps",
] as const;

export type PlanningCollection = typeof PLANNING_COLLECTIONS[number];

export type PlanningSnapshot = {
  schema_version: "1.0.0";
  snapshot_id: string;
  workspace_id: string;
  plan: { plan_id: string; title: string; workspace_id: string; case_analysis_snapshot_id: string; case_analysis_revision: number; case_analysis_source_revision: number; case_analysis_digest: string };
  decisions: { decision_id: string; target_item_id: string; action: string; proposal_value: string; decided_value: string | null; reviewer: string; reason: string; revision: number; timestamp: string }[];
  coverage: { material_items_total: number; reviewed_items: number; pending_items: number; approved_items: number; rejected_items: number; modified_items: number; deferred_items: number; readiness: "READY" | "PARTIAL" | "BLOCKED"; readiness_reasons: string[] };
  upstream_stale: boolean;
  upstream_stale_reasons: string[];
} & Record<PlanningCollection, PlanningItem[]>;

export type PlanningEnvelope = { revision: number; updated_at: string; snapshot: PlanningSnapshot };
export type ReviewAction = "APPROVE" | "REJECT" | "MODIFY" | "DEFER";

export class PericialPlanningApiError extends Error {
  constructor(public readonly kind: "not-found" | "invalid-response" | "unavailable", message: string) {
    super(message);
    this.name = "PericialPlanningApiError";
  }
}

function parseEnvelope(value: unknown, workspaceId: string): PlanningEnvelope {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new PericialPlanningApiError("invalid-response", "Resposta local inválida");
  const envelope = value as Record<string, unknown>;
  if (Object.keys(envelope).sort().join("|") !== "revision|snapshot|updated_at") throw new PericialPlanningApiError("invalid-response", "Resposta local inválida");
  const snapshot = envelope.snapshot as Record<string, unknown> | undefined;
  const plan = snapshot?.plan as Record<string, unknown> | undefined;
  const coverage = snapshot?.coverage as Record<string, unknown> | undefined;
  if (!snapshot || snapshot.schema_version !== "1.0.0" || snapshot.workspace_id !== workspaceId || !plan || plan.workspace_id !== workspaceId || !coverage || !["READY", "PARTIAL", "BLOCKED"].includes(String(coverage.readiness)) || !Array.isArray(coverage.readiness_reasons) || typeof snapshot.upstream_stale !== "boolean" || !Array.isArray(snapshot.upstream_stale_reasons) || !Array.isArray(snapshot.decisions) || !Number.isSafeInteger(envelope.revision) || (envelope.revision as number) < 1 || typeof envelope.updated_at !== "string") {
    throw new PericialPlanningApiError("invalid-response", "Resposta local inválida");
  }
  for (const name of PLANNING_COLLECTIONS) {
    if (!Array.isArray(snapshot[name])) throw new PericialPlanningApiError("invalid-response", "Resposta local inválida");
    for (const item of snapshot[name] as PlanningItem[]) {
      if (typeof item.item_id !== "string" || !item.item_id || typeof item.title !== "string" || !item.title || !item.derivation || typeof item.derivation.rationale !== "string" || !item.derivation.rationale || !Array.isArray(item.derivation.case_analysis_item_ids) || item.derivation.case_analysis_item_ids.length === 0 || !Array.isArray(item.derivation.source_provenance) || item.derivation.source_provenance.length === 0 || item.derivation.source_provenance.some((source) => source.workspace_id !== workspaceId || !source.occurrence_id)) {
        throw new PericialPlanningApiError("invalid-response", "Resposta local inválida");
      }
    }
  }
  return envelope as unknown as PlanningEnvelope;
}

async function localJson(path: string, workspaceId: string, init: RequestInit): Promise<PlanningEnvelope> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...init });
  } catch {
    throw new PericialPlanningApiError("unavailable", "Serviço local indisponível");
  }
  if (response.status === 404) throw new PericialPlanningApiError("not-found", "Planejamento ainda não disponível");
  if (!response.ok || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PericialPlanningApiError("unavailable", "Não foi possível carregar o planejamento");
  try {
    return parseEnvelope(await response.json(), workspaceId);
  } catch (error) {
    if (error instanceof PericialPlanningApiError) throw error;
    throw new PericialPlanningApiError("invalid-response", "Resposta local inválida");
  }
}

export function getPericialPlanning(workspaceId: string, signal?: AbortSignal) {
  if (!UUID.test(workspaceId)) throw new PericialPlanningApiError("invalid-response", "Identidade da perícia inválida");
  return localJson(`/app-api/v1/workspaces/${workspaceId}/pericial-planning`, workspaceId, { method: "GET", signal });
}

export function reviewPericialPlanning(
  workspaceId: string,
  command: { expected_revision: number; target_item_id: string; action: ReviewAction; reviewer: string; reason: string; decided_value: string | null },
) {
  if (!UUID.test(workspaceId) || !command.reviewer.trim() || !command.reason.trim() || (command.action === "MODIFY" && !command.decided_value?.trim())) throw new PericialPlanningApiError("invalid-response", "Decisão profissional incompleta");
  return localJson(`/app-api/v1/workspaces/${workspaceId}/pericial-planning/decisions`, workspaceId, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify(command),
  });
}
