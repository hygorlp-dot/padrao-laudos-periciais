export type Workspace = {
  workspace_id: string;
  name: string;
  created_at: string;
};

export type WorkspaceApiErrorKind =
  | "not-found"
  | "conflict"
  | "unavailable"
  | "local-failure"
  | "invalid-request"
  | "invalid-response";

export class WorkspaceApiError extends Error {
  readonly kind: WorkspaceApiErrorKind;

  constructor(kind: WorkspaceApiErrorKind, message: string) {
    super(message);
    this.name = "WorkspaceApiError";
    this.kind = kind;
  }
}

const WORKSPACES_ENDPOINT = "/app-api/v1/workspaces";
const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TIMEZONE_SUFFIX = /(?:Z|[+-][0-9]{2}:[0-9]{2})$/;

function exactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
}

function parseWorkspace(value: unknown): Workspace {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !exactKeys(value as Record<string, unknown>, ["workspace_id", "name", "created_at"])
  ) {
    throw new WorkspaceApiError("invalid-response", "Resposta local inválida");
  }

  const record = value as Record<string, unknown>;
  if (
    typeof record.workspace_id !== "string" ||
    !CANONICAL_UUID.test(record.workspace_id) ||
    typeof record.name !== "string" ||
    !record.name.trim() ||
    typeof record.created_at !== "string" ||
    !TIMEZONE_SUFFIX.test(record.created_at) ||
    !Number.isFinite(Date.parse(record.created_at))
  ) {
    throw new WorkspaceApiError("invalid-response", "Resposta local inválida");
  }

  return {
    workspace_id: record.workspace_id,
    name: record.name,
    created_at: record.created_at,
  };
}

function mappedError(status: number) {
  if (status === 404) {
    return new WorkspaceApiError("not-found", "Perícia não encontrada");
  }
  if (status === 409) {
    return new WorkspaceApiError(
      "conflict",
      "Não foi possível criar a perícia por conflito local",
    );
  }
  if (status === 503) {
    return new WorkspaceApiError("unavailable", "Armazenamento local indisponível");
  }
  return new WorkspaceApiError("local-failure", "Não foi possível concluir a operação local");
}

async function requestJson(url: string, init: RequestInit) {
  let response: Response;
  try {
    response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      ...init,
    });
  } catch {
    throw new WorkspaceApiError("unavailable", "Serviço local indisponível");
  }
  if (!response.ok) {
    throw mappedError(response.status);
  }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new WorkspaceApiError("invalid-response", "Resposta local inválida");
  }
  try {
    return await response.json();
  } catch {
    throw new WorkspaceApiError("invalid-response", "Resposta local inválida");
  }
}

export async function listWorkspaces(signal?: AbortSignal): Promise<Workspace[]> {
  const value = await requestJson(WORKSPACES_ENDPOINT, {
    method: "GET",
    headers: {},
    signal,
  });
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !exactKeys(value as Record<string, unknown>, ["items"]) ||
    !Array.isArray((value as Record<string, unknown>).items)
  ) {
    throw new WorkspaceApiError("invalid-response", "Resposta local inválida");
  }
  return ((value as Record<string, unknown>).items as unknown[]).map(parseWorkspace);
}

export async function getWorkspace(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<Workspace> {
  if (!CANONICAL_UUID.test(workspaceId)) {
    throw new WorkspaceApiError("invalid-request", "Identidade da perícia inválida");
  }
  return parseWorkspace(
    await requestJson(`${WORKSPACES_ENDPOINT}/${workspaceId}`, {
      method: "GET",
      headers: {},
      signal,
    }),
  );
}

export async function createWorkspace(name: string, signal?: AbortSignal): Promise<Workspace> {
  if (typeof name !== "string" || !name.trim()) {
    throw new WorkspaceApiError("invalid-request", "Informe o nome da perícia");
  }
  return parseWorkspace(
    await requestJson(WORKSPACES_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
      signal,
    }),
  );
}
