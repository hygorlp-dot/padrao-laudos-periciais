const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;

export type ObservationOutcome = "OBSERVED" | "NOT_OBSERVED" | "CONFORMING" | "INCONCLUSIVE";
export type ObservationContext = {
  observation_id: string;
  manifestation: string;
  system: string | null;
  element: string | null;
  outcome: ObservationOutcome;
  methods: string[];
  measurement_ids: string[];
  photo_ids: string[];
  claim_ids: string[];
  question_ids: string[];
};
export type PathologyReview = {
  review_id: string;
  pat_id: string;
  action: "APPROVE" | "REJECT";
  professional_id: string;
  reason: string;
  reviewed_at: string;
  supersedes_review_id: string | null;
};
export type Pathology = {
  id: string;
  manifestacao?: string;
  conclusao_tecnica?: string;
  status_validacao?: string;
  evidencias?: string[];
  [key: string]: unknown;
};
export type ConstructionDefectAnalysisSnapshot = {
  schema_version: "1.0.0";
  snapshot_id: string;
  workspace_id: string;
  source_snapshot: {
    workspace_id: string;
    process_case_revision: number;
    process_case_digest: string;
    case_analysis_snapshot_id: string;
    case_analysis_revision: number;
    case_analysis_digest: string;
    planning_snapshot_id: string;
    planning_revision: number;
    planning_digest: string;
    inspection_session_id: string;
    inspection_revision: number;
    inspection_digest: string;
    source_revision: number;
  };
  observation_contexts: ObservationContext[];
  identity_links: Array<{ canonical_kind: string; canonical_id: string; legacy_kind: string; legacy_id: string }>;
  analysis_final: { schema_version: string; estado_analise: "PAT_FINAL"; patologias: Pathology[]; [key: string]: unknown };
  gate: "APTO_PARA_REDACAO" | "APTO_PARA_REDACAO_COM_RESSALVAS" | "BLOQUEADO_PARA_REDACAO";
  reviews: PathologyReview[];
  upstream_stale: boolean;
  upstream_stale_reasons: string[];
};
export type ConstructionDefectAnalysisEnvelope = {
  revision: number;
  updated_at: string;
  snapshot: ConstructionDefectAnalysisSnapshot;
};

export class ConstructionDefectAnalysisApiError extends Error {
  constructor(readonly kind: "not-found" | "invalid" | "unavailable") {
    super(kind);
    this.name = "ConstructionDefectAnalysisApiError";
  }
}

const endpoint = (workspaceId: string) =>
  `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/construction-defect-analysis`;

function invalid(): never {
  throw new ConstructionDefectAnalysisApiError("invalid");
}

function textArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string" && item.length > 0);
}

export function parseConstructionDefectAnalysisEnvelope(
  value: unknown,
  workspaceId: string,
): ConstructionDefectAnalysisEnvelope {
  if (!value || typeof value !== "object" || !UUID.test(workspaceId)) invalid();
  const envelope = value as ConstructionDefectAnalysisEnvelope;
  const snapshot = envelope.snapshot;
  const source = snapshot?.source_snapshot;
  const analysis = snapshot?.analysis_final;
  if (
    !Number.isSafeInteger(envelope.revision) ||
    envelope.revision < 1 ||
    typeof envelope.updated_at !== "string" ||
    snapshot?.schema_version !== "1.0.0" ||
    snapshot.workspace_id !== workspaceId ||
    source?.workspace_id !== workspaceId ||
    analysis?.estado_analise !== "PAT_FINAL" ||
    !Array.isArray(analysis.patologias) ||
    !Array.isArray(snapshot.observation_contexts) ||
    !Array.isArray(snapshot.identity_links) ||
    !Array.isArray(snapshot.reviews) ||
    typeof snapshot.upstream_stale !== "boolean" ||
    !textArray(snapshot.upstream_stale_reasons)
  ) invalid();
  const digests = [
    source.process_case_digest,
    source.case_analysis_digest,
    source.planning_digest,
    source.inspection_digest,
  ];
  if (digests.some((digest) => typeof digest !== "string" || !SHA256.test(digest))) invalid();
  const patIds = new Set<string>();
  for (const pathology of analysis.patologias) {
    if (!pathology || typeof pathology !== "object" || typeof pathology.id !== "string" || !/^PAT-[0-9]{3,}$/.test(pathology.id) || patIds.has(pathology.id)) invalid();
    if (pathology.evidencias !== undefined && !textArray(pathology.evidencias)) invalid();
    patIds.add(pathology.id);
  }
  const reviews = new Set<string>();
  for (const review of snapshot.reviews) {
    if (!review || typeof review.review_id !== "string" || reviews.has(review.review_id) || !patIds.has(review.pat_id) || !["APPROVE", "REJECT"].includes(review.action) || typeof review.professional_id !== "string" || typeof review.reason !== "string") invalid();
    reviews.add(review.review_id);
  }
  return envelope;
}

async function decode(response: Response, workspaceId: string) {
  if (response.status === 404) throw new ConstructionDefectAnalysisApiError("not-found");
  if (!response.ok || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new ConstructionDefectAnalysisApiError("unavailable");
  }
  try {
    return parseConstructionDefectAnalysisEnvelope(await response.json(), workspaceId);
  } catch (error) {
    if (error instanceof ConstructionDefectAnalysisApiError) throw error;
    throw new ConstructionDefectAnalysisApiError("invalid");
  }
}

export async function getConstructionDefectAnalysis(workspaceId: string, signal?: AbortSignal) {
  return decode(await fetch(endpoint(workspaceId), { method: "GET", credentials: "same-origin", cache: "no-store", signal }), workspaceId);
}

export async function startConstructionDefectAnalysis(workspaceId: string, observationContexts: ObservationContext[]) {
  if (!observationContexts.length) invalid();
  return decode(await fetch(endpoint(workspaceId), {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ observation_contexts: observationContexts }),
  }), workspaceId);
}

export async function reviewPathology(
  workspaceId: string,
  envelope: ConstructionDefectAnalysisEnvelope,
  values: { pat_id: string; action: "APPROVE" | "REJECT"; professional_id: string; reason: string },
) {
  return decode(await fetch(`${endpoint(workspaceId)}/pathology-reviews`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ expected_revision: envelope.revision, ...values }),
  }), workspaceId);
}

export function effectivePathologyReview(snapshot: ConstructionDefectAnalysisSnapshot, patId: string) {
  const matches = snapshot.reviews.filter((review) => review.pat_id === patId);
  return matches.length ? matches[matches.length - 1] : undefined;
}
