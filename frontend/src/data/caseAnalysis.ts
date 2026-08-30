const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export type Provenance = {
  workspace_id: string;
  source_document_id: string;
  source_document_sha256: string;
  page_or_span: string;
  source_revision: number;
  occurrence_id: string;
};

export type JudicialContext = {
  entities: { entity_id: string; raw_name: string; kind: string }[];
  participants: { participant_id: string; entity_id: string; pole: string; role: { raw_label: string; normalized: string }; status: string }[];
  representation_links: { link_id: string; representative_entity_id: string; represented_participant_ids: string[]; representation_role_raw: string }[];
  access_relations: unknown[];
};

export type AnalysisItem = {
  item_id: string;
  text: string;
  participant_refs: string[];
  technical_subjects: string[];
  provenance: Provenance[];
  [key: string]: unknown;
};

export type CaseAnalysisSnapshot = {
  schema_version: "1.0.0";
  snapshot_id: string;
  workspace_id: string;
  source_revision: number;
  participant_refs: string[];
  judicial_context_workspace_id: string;
  judicial_context: JudicialContext;
  documents: Record<string, unknown>[];
  claims: AnalysisItem[];
  counterarguments: AnalysisItem[];
  decisions: AnalysisItem[];
  pericial_objects: AnalysisItem[];
  questions: AnalysisItem[];
  events: AnalysisItem[];
  technical_document_references: AnalysisItem[];
  gaps: AnalysisItem[];
  conflicts: AnalysisItem[];
  coverage: { status: "COMPLETE" | "PARTIAL" | "UNAVAILABLE"; documents_total: number; documents_analyzed: number; documents_unavailable: number; documents_failed: number; source_revision: number };
  human_reviews: Record<string, unknown>[];
  stale_document_ids: string[];
};

export type CaseAnalysisEnvelope = { revision: number; updated_at: string; snapshot: CaseAnalysisSnapshot };

export class CaseAnalysisApiError extends Error {
  constructor(public readonly kind: "not-found" | "invalid-response" | "unavailable", message: string) {
    super(message);
    this.name = "CaseAnalysisApiError";
  }
}

function parseEnvelope(value: unknown, workspaceId: string): CaseAnalysisEnvelope {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new CaseAnalysisApiError("invalid-response", "Resposta local inválida");
  const envelope = value as Record<string, unknown>;
  if (Object.keys(envelope).sort().join("|") !== "revision|snapshot|updated_at") throw new CaseAnalysisApiError("invalid-response", "Resposta local inválida");
  const snapshot = envelope.snapshot as Record<string, unknown>;
  const collections = ["claims", "counterarguments", "decisions", "pericial_objects", "questions", "events", "technical_document_references", "gaps", "conflicts"];
  const context = snapshot?.judicial_context as Record<string, unknown> | undefined;
  if (!snapshot || snapshot.workspace_id !== workspaceId || snapshot.judicial_context_workspace_id !== workspaceId || snapshot.schema_version !== "1.0.0" || !Number.isSafeInteger(envelope.revision) || (envelope.revision as number) < 1 || typeof envelope.updated_at !== "string" || collections.some((name) => !Array.isArray(snapshot[name])) || !Array.isArray(snapshot.stale_document_ids) || !context || !Array.isArray(context.entities) || !Array.isArray(context.participants) || !Array.isArray(context.representation_links)) throw new CaseAnalysisApiError("invalid-response", "Resposta local inválida");
  for (const name of collections) {
    for (const item of snapshot[name] as AnalysisItem[]) {
      if (!Array.isArray(item.provenance) || item.provenance.length === 0 || item.provenance.some((source) => source.workspace_id !== workspaceId || typeof source.occurrence_id !== "string" || !source.occurrence_id)) throw new CaseAnalysisApiError("invalid-response", "Resposta local inválida");
    }
  }
  return envelope as unknown as CaseAnalysisEnvelope;
}

export async function getCaseAnalysis(workspaceId: string, signal?: AbortSignal) {
  if (!UUID.test(workspaceId)) throw new CaseAnalysisApiError("invalid-response", "Identidade da perícia inválida");
  let response: Response;
  try {
    response = await fetch(`/app-api/v1/workspaces/${workspaceId}/case-analysis`, { method: "GET", credentials: "same-origin", cache: "no-store", signal });
  } catch {
    throw new CaseAnalysisApiError("unavailable", "Serviço local indisponível");
  }
  if (response.status === 404) throw new CaseAnalysisApiError("not-found", "Análise ainda não disponível");
  if (!response.ok || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new CaseAnalysisApiError("unavailable", "Não foi possível carregar a análise");
  try {
    return parseEnvelope(await response.json(), workspaceId);
  } catch (error) {
    if (error instanceof CaseAnalysisApiError) throw error;
    throw new CaseAnalysisApiError("invalid-response", "Resposta local inválida");
  }
}
