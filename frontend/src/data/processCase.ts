export type ProcessCaseData = {
  numero_processo: string;
  ramo_justica: string;
  tribunal: string;
  vara: string;
  comarca_municipio: string;
  uf: string;
  parte_requerente: string;
  parte_requerida: string;
};

export type ProcessCaseSnapshot = {
  workspace_id: string;
  revision: number | null;
  updated_at: string | null;
  data: ProcessCaseData;
};

export type ProcessCaseApiErrorKind =
  | "not-found"
  | "conflict"
  | "unavailable"
  | "local-failure"
  | "invalid-request"
  | "invalid-response";

export class ProcessCaseApiError extends Error {
  readonly kind: ProcessCaseApiErrorKind;

  constructor(kind: ProcessCaseApiErrorKind, message: string) {
    super(message);
    this.name = "ProcessCaseApiError";
    this.kind = kind;
  }
}

const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TIMEZONE_SUFFIX = /(?:Z|[+-][0-9]{2}:[0-9]{2})$/;
const DATA_FIELDS = [
  "numero_processo",
  "ramo_justica",
  "tribunal",
  "vara",
  "comarca_municipio",
  "uf",
  "parte_requerente",
  "parte_requerida",
] as const;

function exactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
}

export function emptyProcessCaseData(): ProcessCaseData {
  return {
    numero_processo: "",
    ramo_justica: "",
    tribunal: "",
    vara: "",
    comarca_municipio: "",
    uf: "",
    parte_requerente: "",
    parte_requerida: "",
  };
}

function parseData(value: unknown): ProcessCaseData {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !exactKeys(value as Record<string, unknown>, DATA_FIELDS)
  ) {
    throw new ProcessCaseApiError("invalid-response", "Resposta local inválida");
  }
  const record = value as Record<string, unknown>;
  if (DATA_FIELDS.some((field) => typeof record[field] !== "string")) {
    throw new ProcessCaseApiError("invalid-response", "Resposta local inválida");
  }
  return Object.fromEntries(DATA_FIELDS.map((field) => [field, record[field]])) as ProcessCaseData;
}

function parseSnapshot(value: unknown, expectedWorkspaceId: string): ProcessCaseSnapshot {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !exactKeys(value as Record<string, unknown>, [
      "workspace_id",
      "revision",
      "updated_at",
      "data",
    ])
  ) {
    throw new ProcessCaseApiError("invalid-response", "Resposta local inválida");
  }
  const record = value as Record<string, unknown>;
  const neverSaved = record.revision === null && record.updated_at === null;
  const persisted =
    Number.isSafeInteger(record.revision) &&
    (record.revision as number) >= 1 &&
    typeof record.updated_at === "string" &&
    TIMEZONE_SUFFIX.test(record.updated_at) &&
    Number.isFinite(Date.parse(record.updated_at));
  if (
    typeof record.workspace_id !== "string" ||
    !CANONICAL_UUID.test(record.workspace_id) ||
    record.workspace_id !== expectedWorkspaceId ||
    (!neverSaved && !persisted)
  ) {
    throw new ProcessCaseApiError("invalid-response", "Resposta local inválida");
  }
  return {
    workspace_id: record.workspace_id,
    revision: record.revision as number | null,
    updated_at: record.updated_at as string | null,
    data: parseData(record.data),
  };
}

function validateRequest(workspaceId: string, data?: ProcessCaseData) {
  if (!CANONICAL_UUID.test(workspaceId)) {
    throw new ProcessCaseApiError("invalid-request", "Identidade da perícia inválida");
  }
  if (data !== undefined) {
    try {
      parseData(data);
    } catch {
      throw new ProcessCaseApiError("invalid-request", "Dados do processo inválidos");
    }
  }
}

function mappedError(status: number, operation: "load" | "save") {
  if (status === 404) {
    return new ProcessCaseApiError("not-found", "Perícia não encontrada");
  }
  if (status === 503) {
    return new ProcessCaseApiError("unavailable", "Armazenamento local indisponível");
  }
  if (status === 409 && operation === "save") {
    return new ProcessCaseApiError(
      "conflict",
      "Os dados foram alterados em outra sessão. Atualize a página antes de salvar novamente",
    );
  }
  return new ProcessCaseApiError(
    "local-failure",
    operation === "load"
      ? "Não foi possível carregar os dados do processo"
      : "Não foi possível salvar os dados do processo",
  );
}

async function requestJson(url: string, init: RequestInit, operation: "load" | "save") {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...init });
  } catch {
    throw new ProcessCaseApiError("unavailable", "Serviço local indisponível");
  }
  if (!response.ok) throw mappedError(response.status, operation);
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new ProcessCaseApiError("invalid-response", "Resposta local inválida");
  }
  try {
    return await response.json();
  } catch {
    throw new ProcessCaseApiError("invalid-response", "Resposta local inválida");
  }
}

export async function getProcessCase(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<ProcessCaseSnapshot> {
  validateRequest(workspaceId);
  return parseSnapshot(
    await requestJson(`/app-api/v1/workspaces/${workspaceId}/process-case`, {
      method: "GET",
      headers: {},
      signal,
    }, "load"),
    workspaceId,
  );
}

export async function saveProcessCase(
  workspaceId: string,
  data: ProcessCaseData,
  expectedRevision: number | null,
  signal?: AbortSignal,
): Promise<ProcessCaseSnapshot> {
  validateRequest(workspaceId, data);
  if (
    expectedRevision !== null &&
    (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1)
  ) {
    throw new ProcessCaseApiError("invalid-request", "Revisão dos dados inválida");
  }
  return parseSnapshot(
    await requestJson(`/app-api/v1/workspaces/${workspaceId}/process-case`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: expectedRevision, data }),
      signal,
    }, "save"),
    workspaceId,
  );
}
