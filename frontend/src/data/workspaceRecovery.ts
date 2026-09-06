const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const MAX_BACKUP_BYTES = 134_217_728;

export type BackupSummary = {
  workspace_id: string;
  workspace_name: string;
  workspace_created_at: string;
  product_release: string;
  storage_schema_version: number;
  artifact_revisions: number;
  private_contents: number;
  backup_sha256: string;
};

export type StagedRecovery = {
  recovery_id: string;
  summary: BackupSummary;
  promotable: boolean;
};

export type BackupPackage = {
  blob: Blob;
  filename: string;
};

export type RecoveryApiErrorKind =
  | "invalid-request"
  | "invalid-backup"
  | "incompatible-backup"
  | "not-found"
  | "conflict"
  | "not-promotable"
  | "stage-failed"
  | "too-large"
  | "unavailable"
  | "invalid-response"
  | "local-failure";

export class RecoveryApiError extends Error {
  constructor(public readonly kind: RecoveryApiErrorKind, message: string) {
    super(message);
    this.name = "RecoveryApiError";
  }
}

function requireWorkspace(value: string) {
  if (!CANONICAL_UUID.test(value)) {
    throw new RecoveryApiError("invalid-request", "Identidade da perícia inválida");
  }
}

function requireRecovery(value: string) {
  if (!CANONICAL_UUID.test(value)) {
    throw new RecoveryApiError("invalid-request", "Identidade da recuperação inválida");
  }
}

function parseSummary(value: unknown): BackupSummary {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  const record = value as Record<string, unknown>;
  const expected = [
    "workspace_id", "workspace_name", "workspace_created_at", "product_release",
    "storage_schema_version", "artifact_revisions", "private_contents", "backup_sha256",
  ].sort();
  if (Object.keys(record).sort().join("|") !== expected.join("|")) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  if (
    typeof record.workspace_id !== "string" || !CANONICAL_UUID.test(record.workspace_id) ||
    typeof record.workspace_name !== "string" || !record.workspace_name.trim() ||
    typeof record.workspace_created_at !== "string" ||
    Number.isNaN(Date.parse(record.workspace_created_at)) ||
    typeof record.product_release !== "string" || !record.product_release.trim() ||
    !Number.isSafeInteger(record.storage_schema_version) ||
    !Number.isSafeInteger(record.artifact_revisions) || (record.artifact_revisions as number) < 0 ||
    !Number.isSafeInteger(record.private_contents) || (record.private_contents as number) < 0 ||
    typeof record.backup_sha256 !== "string" || !SHA256.test(record.backup_sha256)
  ) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  return record as BackupSummary;
}

function mappedError(status: number, code?: string): RecoveryApiError {
  if (code === "INVALID_BACKUP") {
    return new RecoveryApiError("invalid-backup", "O arquivo não é um backup íntegro deste produto");
  }
  if (code === "INCOMPATIBLE_BACKUP") {
    return new RecoveryApiError("incompatible-backup", "Este backup é de uma versão não suportada");
  }
  if (code === "RECOVERY_NOT_FOUND") {
    return new RecoveryApiError("not-found", "A recuperação preparada não está mais disponível");
  }
  if (code === "RECOVERY_NOT_PROMOTABLE") {
    return new RecoveryApiError("not-promotable", "Esta recuperação não pode ser promovida");
  }
  if (code === "WORKSPACE_CONFLICT") {
    return new RecoveryApiError("conflict", "Já existe uma perícia com esta identidade");
  }
  if (code === "RECOVERY_STAGE_FAILED") {
    return new RecoveryApiError("stage-failed", "Não foi possível preparar a cópia recuperada");
  }
  if (status === 404) return new RecoveryApiError("not-found", "Perícia ou recuperação não encontrada");
  if (status === 409) return new RecoveryApiError("conflict", "A operação conflita com o estado local");
  if (status === 413) return new RecoveryApiError("too-large", "O backup excede o limite permitido");
  if (status === 400) return new RecoveryApiError("invalid-request", "Requisição local inválida");
  if (status === 503) return new RecoveryApiError("unavailable", "Armazenamento local indisponível");
  return new RecoveryApiError("local-failure", "Não foi possível concluir a operação local");
}

async function failure(response: Response): Promise<RecoveryApiError> {
  let code: string | undefined;
  try {
    const value = await response.json();
    if (typeof value === "object" && value !== null) {
      const error = (value as Record<string, unknown>).error;
      if (typeof error === "object" && error !== null) {
        const candidate = (error as Record<string, unknown>).code;
        if (typeof candidate === "string") code = candidate;
      }
    }
  } catch {
    code = undefined;
  }
  return mappedError(response.status, code);
}

async function jsonResponse(response: Response): Promise<unknown> {
  if (!response.ok) throw await failure(response);
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  try {
    return await response.json();
  } catch {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
}

async function localFetch(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { credentials: "same-origin", cache: "no-store", ...init });
  } catch {
    throw new RecoveryApiError("unavailable", "Serviço local indisponível");
  }
}

function backupBody(file: File): File {
  if (!(file instanceof File) || !file.name.trim()) {
    throw new RecoveryApiError("invalid-request", "Selecione um arquivo de backup");
  }
  if (file.size === 0) {
    throw new RecoveryApiError("invalid-backup", "O arquivo de backup está vazio");
  }
  if (file.size > MAX_BACKUP_BYTES) {
    throw new RecoveryApiError("too-large", "O backup excede o limite permitido");
  }
  return file;
}

/** Exporta o pacote de backup da perícia para o usuário guardar onde quiser. */
export async function exportWorkspaceBackup(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<BackupPackage> {
  requireWorkspace(workspaceId);
  const response = await localFetch(
    `/app-api/v1/workspaces/${workspaceId}/backup`,
    { method: "POST", headers: { "Content-Type": "application/json" }, signal },
  );
  if (!response.ok) throw await failure(response);
  const blob = await response.blob();
  if (blob.size === 0) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  return { blob, filename: `pericia-${workspaceId}.backup` };
}

/** Confere um pacote SEM tocar em nada: verificado não é ativo. */
export async function verifyBackup(file: File, signal?: AbortSignal): Promise<BackupSummary> {
  const body = backupBody(file);
  return parseSummary(await jsonResponse(await localFetch(
    "/app-api/v1/recovery/verify",
    { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body, signal },
  )));
}

/** Restaura numa cópia ISOLADA. Nada da perícia ativa é tocado aqui. */
export async function stageRecovery(file: File, signal?: AbortSignal): Promise<StagedRecovery> {
  const body = backupBody(file);
  const value = await jsonResponse(await localFetch(
    "/app-api/v1/recovery/staging",
    { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body, signal },
  ));
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  const record = value as Record<string, unknown>;
  if (Object.keys(record).sort().join("|") !== ["promotable", "recovery_id", "summary"].join("|")) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  if (typeof record.recovery_id !== "string" || !CANONICAL_UUID.test(record.recovery_id)) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  if (record.promotable !== true) {
    throw new RecoveryApiError("not-promotable", "Esta recuperação não pode ser promovida");
  }
  return {
    recovery_id: record.recovery_id,
    summary: parseSummary(record.summary),
    promotable: true,
  };
}

/**
 * PROMOÇÃO EXPLÍCITA — único passo que torna a cópia recuperada ativa.
 * Exige confirmação declarada; nunca é disparada por um clique acidental.
 */
export async function promoteRecovery(
  recoveryId: string,
  confirmation: { confirm: true },
  signal?: AbortSignal,
): Promise<BackupSummary> {
  requireRecovery(recoveryId);
  if (confirmation?.confirm !== true) {
    throw new RecoveryApiError("invalid-request", "A promoção exige confirmação explícita");
  }
  return parseSummary(await jsonResponse(await localFetch(
    `/app-api/v1/recovery/${recoveryId}/promote`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
      signal,
    },
  )));
}

/** Abandona uma recuperação preparada sem promover nada. */
export async function discardRecovery(recoveryId: string, signal?: AbortSignal): Promise<string> {
  requireRecovery(recoveryId);
  const value = await jsonResponse(await localFetch(
    `/app-api/v1/recovery/${recoveryId}/discard`,
    { method: "POST", headers: { "Content-Type": "application/json" }, signal },
  ));
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  const record = value as Record<string, unknown>;
  if (typeof record.recovery_id !== "string" || !CANONICAL_UUID.test(record.recovery_id)) {
    throw new RecoveryApiError("invalid-response", "Resposta local inválida");
  }
  return record.recovery_id;
}
