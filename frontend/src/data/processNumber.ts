// #286: número do processo principal entre os números citados nos autos.
// Proposta do produto para o perito; nada aqui grava o registro do processo.

export type ProcessNumberOccurrence = {
  filename: string;
  page: number;
  excerpt: string;
  source_start: number;
  source_end: number;
  extraction_mode: string;
  context: "PJE_COVER" | "JUDICIAL_HEADER" | "CITATION" | "DECLARED_RELATION" | "UNQUALIFIED";
  logical_document_id: string | null;
};

export type ProcessNumberCandidate = {
  value: string;
  classification: "PRIMARY" | "CITED_CASE" | "RELATED_CASE" | "UNKNOWN";
  primary_evidence: boolean;
  occurrence_count: number;
  document_count: number;
  occurrences: ProcessNumberOccurrence[];
};

export type ProcessNumberClassification = {
  resolution: "RESOLVED" | "UNRESOLVED" | "NOT_FOUND";
  primary_value: string | null;
  confidence: "HIGH" | "MEDIUM" | null;
  unresolved_reason: "CONFLICTING_PRIMARY_SOURCES" | "NO_PRIMARY_SOURCE" | "READING_INCOMPLETE" | "SOURCES_UNAVAILABLE" | null;
  candidates: ProcessNumberCandidate[];
  pending_documents: string[];
  unread_pages: { filename: string; page: number }[];
  invalid_occurrences: { filename: string; page: number }[];
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const RESOLUTIONS = new Set(["RESOLVED", "UNRESOLVED", "NOT_FOUND"]);
const CLASSES = new Set(["PRIMARY", "CITED_CASE", "RELATED_CASE", "UNKNOWN"]);

export class ProcessNumberApiError extends Error {}

function isCandidate(value: unknown): value is ProcessNumberCandidate {
  const item = value as ProcessNumberCandidate;
  return Boolean(item)
    && typeof item.value === "string"
    && CLASSES.has(item.classification)
    && typeof item.primary_evidence === "boolean"
    && Number.isInteger(item.occurrence_count)
    && Number.isInteger(item.document_count)
    && Array.isArray(item.occurrences)
    && item.occurrences.every((o) => o && typeof o.filename === "string" && Number.isInteger(o.page) && typeof o.excerpt === "string" && typeof o.context === "string");
}

export function parseProcessNumberClassification(value: unknown): ProcessNumberClassification {
  const item = value as ProcessNumberClassification;
  if (
    !item
    || !RESOLUTIONS.has(item.resolution)
    || (item.primary_value !== null && typeof item.primary_value !== "string")
    || (item.resolution === "RESOLVED") !== (typeof item.primary_value === "string")
    || !Array.isArray(item.candidates)
    || !item.candidates.every(isCandidate)
    || !Array.isArray(item.pending_documents)
    || !Array.isArray(item.unread_pages)
    || !Array.isArray(item.invalid_occurrences)
  ) {
    throw new ProcessNumberApiError("invalid");
  }
  return item;
}

export async function getProcessNumberClassification(workspaceId: string, signal?: AbortSignal): Promise<ProcessNumberClassification> {
  if (!UUID.test(workspaceId)) throw new ProcessNumberApiError("invalid");
  const response = await fetch(`/app-api/v1/workspaces/${workspaceId}/process-number`, {
    method: "GET", headers: {}, credentials: "same-origin", cache: "no-store", signal,
  });
  if (!response.ok) throw new ProcessNumberApiError("unavailable");
  return parseProcessNumberClassification(await response.json());
}
