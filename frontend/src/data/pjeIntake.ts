export type PjeDocument = { document_id: string; id_pje: string; title: string; raw_type: string; normalized_type: string; page_start: number; page_end: number; available: boolean };
export type PjeDiagnostic = { code: string; detail: string };
export type PjeInventory = {
  schema_version: string;
  workspace_id: string;
  storage_content_id: string;
  status: "OK" | "BLOCKED";
  diagnostics: PjeDiagnostic[];
  instance_label: string;
  documents: PjeDocument[];
};
/** Um inventário por fonte física: um workspace pode ter mais de um export PJe. */
export type PjeIntake = { revision: number; inventory: PjeInventory };

function decodeIntake(value: unknown): PjeIntake {
  const item = value as PjeIntake;
  if (!Number.isSafeInteger(item?.revision) || item.revision < 1) throw new Error("pje-intake-invalid");
  if (typeof item?.inventory?.storage_content_id !== "string") throw new Error("pje-intake-invalid");
  if (!Array.isArray(item?.inventory?.documents)) throw new Error("pje-intake-invalid");
  if (item.inventory.status !== "OK" && item.inventory.status !== "BLOCKED") throw new Error("pje-intake-invalid");
  if (!Array.isArray(item?.inventory?.diagnostics)) throw new Error("pje-intake-invalid");
  return item;
}

const base = (workspaceId: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/pje-intake`;

/**
 * Devolve `null` quando o workspace simplesmente não tem inventário PJe (404),
 * e lança quando a leitura falhou. Sem essa distinção, "não há documentos PJe"
 * e "não consegui ler o inventário" ficam indistinguíveis na interface.
 *
 * O 503 é deliberadamente um erro, e não uma ausência: significa que esta
 * instalação não tem leitor de PJe — coisa diferente de este processo não ter
 * documentos do PJe.
 */
export async function getPjeIntakes(workspaceId: string, signal?: AbortSignal): Promise<PjeIntake[] | null> {
  const response = await fetch(base(workspaceId), { method: "GET", credentials: "same-origin", cache: "no-store", signal });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("pje-intake-unavailable");
  const value = await response.json() as { intakes?: unknown };
  if (!Array.isArray(value?.intakes)) throw new Error("pje-intake-invalid");
  return value.intakes.map(decodeIntake);
}

/**
 * A fonte é endereçada explicitamente: `document_id` é um ordinal local ao
 * índice de um export, então sem dizer de qual fonte se fala a decisão do
 * perito poderia aterrissar no documento de mesma posição de outro processo.
 */
export async function setPjeDocumentAvailability(workspaceId: string, intake: PjeIntake, documentId: string, available: boolean): Promise<PjeIntake> {
  const response = await fetch(`${base(workspaceId)}/availability`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      storage_content_id: intake.inventory.storage_content_id,
      document_id: documentId,
      available,
      expected_revision: intake.revision,
    }),
  });
  if (!response.ok) throw new Error("pje-intake-unavailable");
  return decodeIntake(await response.json());
}
