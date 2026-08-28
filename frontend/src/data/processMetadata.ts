import type { ProcessCaseData, ProcessCaseSnapshot } from "./processCase";

export const PROCESS_METADATA_FIELDS = [
  "numero_processo",
  "ramo_justica",
  "tribunal",
  "vara",
  "municipio_sede",
  "subsecao_judiciaria",
  "comarca_municipio",
  "uf",
  "parte_requerente",
  "parte_requerida",
] as const;

export type ProcessMetadataFieldName = (typeof PROCESS_METADATA_FIELDS)[number];
export type FieldExtractionState = "CONFIDENT" | "AMBIGUOUS" | "NOT_FOUND" | "CONFLICTING";
export type ProcessMetadataReviewState =
  | "WAITING_FOR_DOCUMENTS"
  | "EXTRACTING"
  | "EXTRACTED"
  | "PARTIAL"
  | "CONFLICT"
  | "CONFIRMED"
  | "ERROR";
export type PdfTextExtractionState =
  | "AVAILABLE"
  | "PARTIAL"
  | "TEXT_EXTRACTION_UNAVAILABLE"
  | "ERROR";

export type ProcessMetadataEvidence = {
  workspace_id: string;
  document_id: string;
  field_name: ProcessMetadataFieldName;
  extracted_value: string;
  source_page: number;
  extraction_method: "LOCAL_PDF_TEXT_V1" | "LOCAL_OCR_V1";
  extraction_mode: "NATIVE_TEXT" | "OCR";
  ocr_engine: string;
  engine_version: string;
  model_version: string;
  ocr_confidence: number | null;
  bounding_box: [number, number, number, number] | null;
  extraction_timestamp: string;
  source_filename: string;
  normalized_text_span: string;
  evidence_id: string;
  source_text: string;
  source_start: number;
  requires_source_selection: boolean;
  source_role:
    | "PRIMARY_PROCESS_COVER"
    | "PRIMARY_PROCESS_HEADER"
    | "PRIMARY_PARTY_STRUCTURE"
    | "PRIMARY_PROCESS_DOCUMENT"
    | "REFERENCED_CASE"
    | "CITED_JURISPRUDENCE"
    | "ANNEX_DOCUMENT"
    | "UNKNOWN_SOURCE_CONTEXT";
  derivation_authority: string;
  derivation_reference: string;
};

export type ProcessMetadataField = {
  state: FieldExtractionState;
  value: string;
  evidence: ProcessMetadataEvidence[];
};

export type ProcessMetadataDocument = {
  document_id: string;
  source_filename: string;
  text_state: PdfTextExtractionState;
};

export type ProcessMetadataReview = {
  workspace_id: string;
  state: ProcessMetadataReviewState;
  confirmed_revision: number | null;
  extraction_fingerprint: string;
  documents: ProcessMetadataDocument[];
  fields: Record<ProcessMetadataFieldName, ProcessMetadataField>;
};

export type ProcessMetadataApiErrorKind =
  | "invalid-request"
  | "not-found"
  | "unavailable"
  | "invalid-response"
  | "local-failure";

export class ProcessMetadataApiError extends Error {
  constructor(public readonly kind: ProcessMetadataApiErrorKind, message: string) {
    super(message);
    this.name = "ProcessMetadataApiError";
  }
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const TIMEZONE = /(?:Z|[+-][0-9]{2}:[0-9]{2})$/;
const STATES = new Set<ProcessMetadataReviewState>([
  "WAITING_FOR_DOCUMENTS", "EXTRACTING", "EXTRACTED", "PARTIAL", "CONFLICT", "CONFIRMED", "ERROR",
]);
const FIELD_STATES = new Set<FieldExtractionState>([
  "CONFIDENT", "AMBIGUOUS", "NOT_FOUND", "CONFLICTING",
]);
const TEXT_STATES = new Set<PdfTextExtractionState>([
  "AVAILABLE", "PARTIAL", "TEXT_EXTRACTION_UNAVAILABLE", "ERROR",
]);

function safeFilename(value: unknown): value is string {
  return typeof value === "string" && Boolean(value.trim())
    && !/^[A-Za-z]:[\\/]/.test(value) && !value.startsWith("/")
    && !value.startsWith("\\\\") && !value.includes("\0");
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
}

function parseEvidence(
  value: unknown,
  workspaceId: string,
  fieldName: ProcessMetadataFieldName,
): ProcessMetadataEvidence {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
  const record = value as Record<string, unknown>;
  if (!exactKeys(record, [
    "workspace_id", "document_id", "field_name", "extracted_value", "source_page",
    "extraction_method", "extraction_timestamp", "source_filename", "normalized_text_span",
    "extraction_mode", "ocr_engine", "engine_version", "model_version", "ocr_confidence",
    "bounding_box", "evidence_id", "source_text", "source_start",
    "requires_source_selection", "source_role", "derivation_authority",
    "derivation_reference",
  ]) || record.workspace_id !== workspaceId || typeof record.document_id !== "string"
    || !UUID.test(record.document_id) || record.field_name !== fieldName
    || typeof record.extracted_value !== "string" || !Number.isSafeInteger(record.source_page)
    || (record.source_page as number) < 1
    || typeof record.extraction_timestamp !== "string" || !TIMEZONE.test(record.extraction_timestamp)
    || !Number.isFinite(Date.parse(record.extraction_timestamp))
    || !safeFilename(record.source_filename)
    || typeof record.normalized_text_span !== "string"
    || typeof record.evidence_id !== "string" || !SHA256.test(record.evidence_id)
    || typeof record.source_text !== "string"
    || !Number.isSafeInteger(record.source_start) || (record.source_start as number) < 0
    || typeof record.requires_source_selection !== "boolean"
    || ![
      "PRIMARY_PROCESS_COVER", "PRIMARY_PROCESS_HEADER", "PRIMARY_PARTY_STRUCTURE",
      "PRIMARY_PROCESS_DOCUMENT", "REFERENCED_CASE", "CITED_JURISPRUDENCE",
      "ANNEX_DOCUMENT", "UNKNOWN_SOURCE_CONTEXT",
    ]
      .includes(record.source_role as string)
    || typeof record.derivation_authority !== "string"
    || typeof record.derivation_reference !== "string"
    || (record.requires_source_selection === true
      && (!record.source_text || record.extracted_value !== ""))) {
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
  const nativeEvidence = record.extraction_mode === "NATIVE_TEXT"
    && record.extraction_method === "LOCAL_PDF_TEXT_V1"
    && record.ocr_engine === "" && record.model_version === ""
    && record.ocr_confidence === null && record.bounding_box === null;
  const box = record.bounding_box;
  const ocrEvidence = record.extraction_mode === "OCR"
    && record.extraction_method === "LOCAL_OCR_V1"
    && typeof record.ocr_engine === "string" && Boolean(record.ocr_engine.trim())
    && typeof record.model_version === "string" && Boolean(record.model_version.trim())
    && typeof record.ocr_confidence === "number" && Number.isFinite(record.ocr_confidence)
    && record.ocr_confidence >= 0 && record.ocr_confidence <= 1
    && (box === null || (Array.isArray(box) && box.length === 4
      && box.every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate))));
  if (typeof record.engine_version !== "string" || (!nativeEvidence && !ocrEvidence)
    || (ocrEvidence && !record.engine_version.trim())) {
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
  return record as ProcessMetadataEvidence;
}

function parseReview(value: unknown, workspaceId: string): ProcessMetadataReview {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
  const record = value as Record<string, unknown>;
  if (!exactKeys(record, [
    "workspace_id", "state", "confirmed_revision", "extraction_fingerprint", "documents", "fields",
  ])
    || record.workspace_id !== workspaceId || typeof record.state !== "string"
    || !STATES.has(record.state as ProcessMetadataReviewState)
    || (record.confirmed_revision !== null && (!Number.isSafeInteger(record.confirmed_revision)
      || (record.confirmed_revision as number) < 1))
    || typeof record.extraction_fingerprint !== "string"
    || !SHA256.test(record.extraction_fingerprint)
    || !Array.isArray(record.documents)
    || typeof record.fields !== "object" || record.fields === null || Array.isArray(record.fields)
    || !exactKeys(record.fields as Record<string, unknown>, PROCESS_METADATA_FIELDS)) {
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
  const fields = Object.fromEntries(PROCESS_METADATA_FIELDS.map((name) => {
    const raw = (record.fields as Record<string, unknown>)[name];
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)
      || !exactKeys(raw as Record<string, unknown>, ["state", "value", "evidence"])) {
      throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
    }
    const field = raw as Record<string, unknown>;
    if (typeof field.state !== "string" || !FIELD_STATES.has(field.state as FieldExtractionState)
      || typeof field.value !== "string" || !Array.isArray(field.evidence)) {
      throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
    }
    return [name, {
      state: field.state,
      value: field.value,
      evidence: field.evidence.map((item) => parseEvidence(item, workspaceId, name)),
    }];
  })) as Record<ProcessMetadataFieldName, ProcessMetadataField>;
  const documents = record.documents.map((value) => {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
    }
    const document = value as Record<string, unknown>;
    if (!exactKeys(document, ["document_id", "source_filename", "text_state"])
      || typeof document.document_id !== "string" || !UUID.test(document.document_id)
      || !safeFilename(document.source_filename) || typeof document.text_state !== "string"
      || !TEXT_STATES.has(document.text_state as PdfTextExtractionState)) {
      throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
    }
    return document as ProcessMetadataDocument;
  });
  return {
    workspace_id: workspaceId,
    state: record.state as ProcessMetadataReviewState,
    confirmed_revision: record.confirmed_revision as number | null,
    extraction_fingerprint: record.extraction_fingerprint as string,
    documents,
    fields,
  };
}

export type ProcessMetadataSourceSpanConfirmation = {
  field_name: "parte_requerente" | "parte_requerida";
  evidence_id: string;
  source_start: number;
  source_end: number;
  expected_source_revision: string;
  expected_revision: number | null;
};

const PROCESS_CASE_FIELDS = PROCESS_METADATA_FIELDS;

function parseProcessCaseSnapshot(
  value: unknown,
  workspaceId: string,
): ProcessCaseSnapshot {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
  const record = value as Record<string, unknown>;
  if (!exactKeys(record, ["workspace_id", "revision", "updated_at", "data"])
    || record.workspace_id !== workspaceId
    || !Number.isSafeInteger(record.revision) || (record.revision as number) < 1
    || typeof record.updated_at !== "string" || !TIMEZONE.test(record.updated_at)
    || !Number.isFinite(Date.parse(record.updated_at))
    || typeof record.data !== "object" || record.data === null || Array.isArray(record.data)
    || !exactKeys(record.data as Record<string, unknown>, PROCESS_CASE_FIELDS)
    || PROCESS_CASE_FIELDS.some(
      (field) => typeof (record.data as Record<string, unknown>)[field] !== "string",
    )) {
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
  return {
    workspace_id: workspaceId,
    revision: record.revision as number,
    updated_at: record.updated_at as string,
    data: record.data as ProcessCaseData,
  };
}

export async function confirmProcessMetadataSourceSpan(
  workspaceId: string,
  confirmation: ProcessMetadataSourceSpanConfirmation,
  signal?: AbortSignal,
): Promise<ProcessCaseSnapshot> {
  if (!UUID.test(workspaceId)
    || !["parte_requerente", "parte_requerida"].includes(confirmation.field_name)
    || !SHA256.test(confirmation.evidence_id)
    || !Number.isSafeInteger(confirmation.source_start) || confirmation.source_start < 0
    || !Number.isSafeInteger(confirmation.source_end)
    || confirmation.source_end <= confirmation.source_start
    || !SHA256.test(confirmation.expected_source_revision)
    || (confirmation.expected_revision !== null
      && (!Number.isSafeInteger(confirmation.expected_revision)
        || confirmation.expected_revision < 1))) {
    throw new ProcessMetadataApiError("invalid-request", "Seleção de fonte inválida");
  }
  let response: Response;
  try {
    response = await fetch(
      `/app-api/v1/workspaces/${workspaceId}/process-metadata/source-span-confirmations`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify(confirmation),
        signal,
      },
    );
  } catch {
    throw new ProcessMetadataApiError("unavailable", "Serviço local indisponível");
  }
  if (!response.ok) {
    if (response.status === 404) {
      throw new ProcessMetadataApiError("not-found", "Perícia não encontrada");
    }
    if (response.status === 409) {
      throw new ProcessMetadataApiError(
        "local-failure",
        "A fonte foi atualizada. Recarregue a revisão antes de confirmar",
      );
    }
    if (response.status === 503) {
      throw new ProcessMetadataApiError("unavailable", "Serviço local indisponível");
    }
    throw new ProcessMetadataApiError("local-failure", "Não foi possível confirmar o trecho da fonte");
  }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
  try {
    return parseProcessCaseSnapshot(await response.json(), workspaceId);
  } catch (error) {
    if (error instanceof ProcessMetadataApiError) throw error;
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
}

export async function getProcessMetadataReview(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<ProcessMetadataReview> {
  if (!UUID.test(workspaceId)) {
    throw new ProcessMetadataApiError("invalid-request", "Identidade da perícia inválida");
  }
  let response: Response;
  try {
    response = await fetch(`/app-api/v1/workspaces/${workspaceId}/process-metadata`, {
      method: "GET",
      headers: {},
      credentials: "same-origin",
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ProcessMetadataApiError("unavailable", "Serviço local indisponível");
  }
  if (!response.ok) {
    if (response.status === 404) {
      throw new ProcessMetadataApiError("not-found", "Perícia não encontrada");
    }
    if (response.status === 503) {
      throw new ProcessMetadataApiError("unavailable", "Extração local indisponível");
    }
    throw new ProcessMetadataApiError("local-failure", "Não foi possível carregar a extração local");
  }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
  try {
    return parseReview(await response.json(), workspaceId);
  } catch (error) {
    if (error instanceof ProcessMetadataApiError) throw error;
    throw new ProcessMetadataApiError("invalid-response", "Resposta local inválida");
  }
}
