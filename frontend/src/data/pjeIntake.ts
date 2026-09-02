export type PjeDocument = { document_id: string; id_pje: string; title: string; raw_type: string; normalized_type: string; page_start: number; page_end: number; available: boolean };
export type PjeIntakeEnvelope = { revision: number; inventory: { schema_version: "1.0.0"; workspace_id: string; documents: PjeDocument[] } };

async function decode(response: Response): Promise<PjeIntakeEnvelope> {
  if (!response.ok) throw new Error("pje-intake-unavailable");
  const value = await response.json() as PjeIntakeEnvelope;
  if (!Number.isSafeInteger(value?.revision) || value.revision < 1 || !Array.isArray(value?.inventory?.documents)) throw new Error("pje-intake-invalid");
  return value;
}

const base = (workspaceId: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/pje-intake`;
export async function getPjeIntake(workspaceId: string, signal?: AbortSignal) {
  return decode(await fetch(base(workspaceId), { method: "GET", credentials: "same-origin", cache: "no-store", signal }));
}
export async function setPjeDocumentAvailability(workspaceId: string, value: PjeIntakeEnvelope, documentId: string, available: boolean) {
  return decode(await fetch(`${base(workspaceId)}/availability`, { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_id: documentId, available, expected_revision: value.revision }) }));
}
