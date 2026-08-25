const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const MAX_DOCUMENT_BYTES = 16_777_216;

export type MaterialMetadata = {
  workspace_id: string;
  content_id: string;
  original_filename: string;
  byte_size: number;
  checksum_sha256: string;
  media_type: "application/pdf";
  imported_at: string;
  origin: "LOCAL_IMPORT";
};

export type MaterialApiErrorKind =
  | "invalid-request"
  | "not-found"
  | "unsupported"
  | "too-large"
  | "unavailable"
  | "invalid-response"
  | "local-failure";

export class MaterialApiError extends Error {
  constructor(public readonly kind: MaterialApiErrorKind, message: string) {
    super(message);
    this.name = "MaterialApiError";
  }
}
function requireWorkspace(value: string) {
  if (!CANONICAL_UUID.test(value)) {
    throw new MaterialApiError("invalid-request", "Identidade da perícia inválida");
  }
}

function parseMetadata(value: unknown, workspaceId: string): MaterialMetadata {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new MaterialApiError("invalid-response", "Resposta local inválida");
  }
  const record = value as Record<string, unknown>;
  const expected = [
    "workspace_id", "content_id", "original_filename", "byte_size",
    "checksum_sha256", "media_type", "imported_at", "origin",
  ].sort();
  if (Object.keys(record).sort().join("|") !== expected.join("|")) {
    throw new MaterialApiError("invalid-response", "Resposta local inválida");
  }
  if (
    record.workspace_id !== workspaceId ||
    typeof record.content_id !== "string" || !CANONICAL_UUID.test(record.content_id) ||
    typeof record.original_filename !== "string" || !record.original_filename.trim() ||
    !Number.isSafeInteger(record.byte_size) || (record.byte_size as number) < 0 ||
    typeof record.checksum_sha256 !== "string" || !SHA256.test(record.checksum_sha256) ||
    record.media_type !== "application/pdf" ||
    typeof record.imported_at !== "string" || !record.imported_at.includes("T") ||
    Number.isNaN(Date.parse(record.imported_at)) ||
    record.origin !== "LOCAL_IMPORT"
  ) {
    throw new MaterialApiError("invalid-response", "Resposta local inválida");
  }
  return record as MaterialMetadata;
}

function mappedError(status: number): MaterialApiError {
  if (status === 404) return new MaterialApiError("not-found", "Material ou perícia não encontrado");
  if (status === 413) return new MaterialApiError("too-large", "O PDF excede o limite permitido");
  if (status === 415) return new MaterialApiError("unsupported", "Selecione um documento PDF");
  if (status === 400) return new MaterialApiError("invalid-request", "O documento PDF é inválido");
  if (status === 503) return new MaterialApiError("unavailable", "Armazenamento local indisponível");
  return new MaterialApiError("local-failure", "Não foi possível concluir a operação local");
}

async function jsonResponse(response: Response): Promise<unknown> {
  if (!response.ok) throw mappedError(response.status);
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new MaterialApiError("invalid-response", "Resposta local inválida");
  }
  try {
    return await response.json();
  } catch {
    throw new MaterialApiError("invalid-response", "Resposta local inválida");
  }
}

async function localFetch(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { credentials: "same-origin", cache: "no-store", ...init });
  } catch {
    throw new MaterialApiError("unavailable", "Serviço local indisponível");
  }
}

export async function listCaseDocuments(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<MaterialMetadata[]> {
  requireWorkspace(workspaceId);
  const value = await jsonResponse(await localFetch(
    `/app-api/v1/workspaces/${workspaceId}/materials`,
    { method: "GET", signal },
  ));
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new MaterialApiError("invalid-response", "Resposta local inválida");
  }
  const envelope = value as Record<string, unknown>;
  if (Object.keys(envelope).join("|") !== "items" || !Array.isArray(envelope.items)) {
    throw new MaterialApiError("invalid-response", "Resposta local inválida");
  }
  return envelope.items.map((item) => parseMetadata(item, workspaceId));
}

export async function importCaseDocument(
  workspaceId: string,
  file: File,
  signal?: AbortSignal,
): Promise<MaterialMetadata> {
  requireWorkspace(workspaceId);
  if (!(file instanceof File) || file.type !== "application/pdf" || !file.name.trim()) {
    throw new MaterialApiError("unsupported", "Selecione um documento PDF");
  }
  if (file.size === 0) {
    throw new MaterialApiError("invalid-request", "O documento PDF está vazio");
  }
  if (file.size > MAX_DOCUMENT_BYTES) {
    throw new MaterialApiError("too-large", "O PDF excede o limite permitido");
  }
  const response = await localFetch(
    `/app-api/v1/workspaces/${workspaceId}/materials`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/pdf",
        "X-Document-Filename": encodeURIComponent(file.name),
      },
      body: file,
      signal,
    },
  );
  return parseMetadata(await jsonResponse(response), workspaceId);
}

export function materialUrl(workspaceId: string, contentId: string) {
  requireWorkspace(workspaceId);
  if (!CANONICAL_UUID.test(contentId)) {
    throw new MaterialApiError("invalid-request", "Identidade do material inválida");
  }
  return `/app-api/v1/workspaces/${workspaceId}/materials/${contentId}`;
}
