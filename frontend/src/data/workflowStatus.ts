// Situação do fluxo (#291): leitura da projeção somente leitura do backend.
// A interface não deduz estado de etapa nenhuma; ela só traduz o que a
// projeção afirma, e recusa qualquer valor fora do conjunto fechado.

export const WORKFLOW_STAGE_STATES = [
  "NOT_STARTED",
  "IN_PROGRESS",
  "PROCESSING",
  "AWAITING_REVIEW",
  "REVIEW_REQUIRED",
  "ATTENTION",
  "READY",
  "APPROVED",
  "RECORDED",
  "NOT_TRACKED",
  "UNAVAILABLE",
] as const;
export type WorkflowStageState = (typeof WORKFLOW_STAGE_STATES)[number];

const AVAILABILITY = ["AVAILABLE", "UNAVAILABLE"] as const;
const CURRENCY = ["CURRENT", "STALE", "NOT_EVALUATED"] as const;
const DECISIONS = ["NOT_TRACKED", "NONE", "PARTIAL", "COMPLETE", "REVIEWED", "APPROVED"] as const;

export type WorkflowReason = { code: string; count?: number };

export type WorkflowStageStatus = {
  stage: string;
  state: WorkflowStageState;
  availability: (typeof AVAILABILITY)[number];
  currency: (typeof CURRENCY)[number];
  decision: (typeof DECISIONS)[number];
  reasons: WorkflowReason[];
  revision: number | null;
  updated_at: string | null;
};

export type WorkflowStatus = {
  workspaceId: string;
  stages: WorkflowStageStatus[];
};

export class WorkflowStatusError extends Error {
  readonly kind: "not-found" | "unavailable" | "invalid-response";

  constructor(kind: WorkflowStatusError["kind"]) {
    super(kind === "not-found" ? "Perícia não encontrada" : "Não foi possível verificar a situação das etapas");
    this.name = "WorkflowStatusError";
    this.kind = kind;
  }
}

const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const REASON_CODE = /^[A-Z0-9_]+$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function oneOf<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (values as readonly string[]).includes(value);
}

function parseReason(value: unknown): WorkflowReason {
  if (!isRecord(value) || typeof value.code !== "string" || !REASON_CODE.test(value.code)) {
    throw new WorkflowStatusError("invalid-response");
  }
  const keys = Object.keys(value);
  if (keys.some((key) => key !== "code" && key !== "count")) throw new WorkflowStatusError("invalid-response");
  if ("count" in value) {
    if (typeof value.count !== "number" || !Number.isInteger(value.count) || value.count < 0) {
      throw new WorkflowStatusError("invalid-response");
    }
    return { code: value.code, count: value.count };
  }
  return { code: value.code };
}

function parseStage(value: unknown): WorkflowStageStatus {
  if (!isRecord(value)) throw new WorkflowStatusError("invalid-response");
  const { stage, state, availability, currency, decision, reasons, revision, updated_at } = value;
  if (
    typeof stage !== "string" ||
    !oneOf(WORKFLOW_STAGE_STATES, state) ||
    !oneOf(AVAILABILITY, availability) ||
    !oneOf(CURRENCY, currency) ||
    !oneOf(DECISIONS, decision) ||
    !Array.isArray(reasons) ||
    !(revision === null || (typeof revision === "number" && Number.isInteger(revision) && revision >= 1)) ||
    !(updated_at === null || typeof updated_at === "string")
  ) {
    throw new WorkflowStatusError("invalid-response");
  }
  // Mesma coerência que o backend impõe: base desatualizada nunca parece vigente,
  // "não verificada" é sempre consulta indisponível, e estado afirmativo exige a
  // revisão que o sustenta.
  if (currency === "STALE" && !["REVIEW_REQUIRED", "ATTENTION", "UNAVAILABLE"].includes(state)) {
    throw new WorkflowStatusError("invalid-response");
  }
  if (state === "REVIEW_REQUIRED" && currency !== "STALE") throw new WorkflowStatusError("invalid-response");
  if ((state === "UNAVAILABLE") !== (availability === "UNAVAILABLE")) throw new WorkflowStatusError("invalid-response");
  if (["READY", "APPROVED", "RECORDED"].includes(state) && revision === null && stage !== "materiais") {
    throw new WorkflowStatusError("invalid-response");
  }
  return { stage, state, availability, currency, decision, reasons: reasons.map(parseReason), revision, updated_at };
}

export function parseWorkflowStatus(value: unknown, workspaceId: string): WorkflowStatus {
  if (!isRecord(value) || value.workspace_id !== workspaceId || !Array.isArray(value.stages)) {
    // Resposta de outra perícia nunca é aceita, nem por um instante.
    throw new WorkflowStatusError("invalid-response");
  }
  const stages = value.stages.map(parseStage);
  if (new Set(stages.map((item) => item.stage)).size !== stages.length) throw new WorkflowStatusError("invalid-response");
  return { workspaceId, stages };
}

export async function getWorkflowStatus(workspaceId: string, signal?: AbortSignal): Promise<WorkflowStatus> {
  if (!CANONICAL_UUID.test(workspaceId)) throw new WorkflowStatusError("not-found");
  let response: Response;
  try {
    response = await fetch(`/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/workflow-status`, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new WorkflowStatusError("unavailable");
  }
  if (response.status === 404) throw new WorkflowStatusError("not-found");
  if (!response.ok) throw new WorkflowStatusError("unavailable");
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new WorkflowStatusError("invalid-response");
  }
  return parseWorkflowStatus(body, workspaceId);
}
