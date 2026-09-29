export type PropertyEvidence = { document_id: string; document_sha256: string; filename: string; page: number; excerpt: string; method: string; confidence: number | null; source_value: string };
export type PropertyValue = { field: string; value: string; evidence: PropertyEvidence | null; confirmed_by: string; confirmed_at: string };
export type PropertyEnvelope = {
  revision: number | null; updated_at: string | null;
  record: { schema_version: "1.0.0"; workspace_id: string; values: PropertyValue[] };
  fields: { field: string; label: string; kind: "text" | "decimal" | "date" }[];
  /** Campos confirmados cuja página de origem o perito excluiu depois da confirmação. */
  stale_fields: string[];
};
export type PropertyProposal = { proposal_id: string; workspace_id: string; field: string; value: string; evidence: PropertyEvidence; state: "PROPOSED" | "CONFLICTING" };
export type PropertyChange = { field: string; value: string | null; proposal_id: string | null };
export class PropertyApiError extends Error {
  constructor(readonly kind: "conflict" | "profile-missing" | "invalid" | "unavailable") { super(kind); }
}
const base = (workspace: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspace)}/property-record`;
async function read(response: Response) {
  if (response.status === 409) throw new PropertyApiError("conflict");
  if (response.status === 404) throw new PropertyApiError("profile-missing");
  if (response.status === 400 || response.status === 422) throw new PropertyApiError("invalid");
  if (!response.ok) throw new PropertyApiError("unavailable");
  return response.json();
}
function envelope(value: PropertyEnvelope, workspace: string) {
  if (value?.record?.workspace_id !== workspace || !Array.isArray(value.record.values) || !Array.isArray(value.fields) || !Array.isArray(value.stale_fields) || (value.revision !== null && (!Number.isInteger(value.revision) || value.revision < 1))) throw new PropertyApiError("unavailable");
  return value;
}
export async function getPropertyRecord(workspace: string, signal?: AbortSignal) {
  return envelope(await read(await fetch(base(workspace), { credentials: "same-origin", cache: "no-store", signal })), workspace);
}
export async function getPropertyProposals(workspace: string, signal?: AbortSignal): Promise<PropertyProposal[]> {
  const value = await read(await fetch(`${base(workspace)}/proposals`, { credentials: "same-origin", cache: "no-store", signal }));
  if (value?.workspace_id !== workspace || !Array.isArray(value.proposals) || value.proposals.some((p: PropertyProposal) => p.workspace_id !== workspace)) throw new PropertyApiError("unavailable");
  return value.proposals;
}
export async function savePropertyRecord(workspace: string, revision: number | null, changes: PropertyChange[]) {
  return envelope(await read(await fetch(base(workspace), { method: "PUT", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: revision, changes }) })), workspace);
}

const PROPERTY_LABELS: Record<string, string> = {"owner": "Proprietário do imóvel", "street": "Logradouro", "number": "Número", "complement": "Complemento", "unit": "Unidade / apartamento", "block": "Bloco", "quadra": "Quadra", "neighborhood": "Bairro", "postal_code": "CEP", "city": "Município do imóvel", "state": "UF do imóvel", "development": "Empreendimento", "floor": "Pavimento", "private_area_m2": "Área privativa (m²)", "constructed_area_m2": "Área construída (m²)", "construction_system": "Sistema construtivo", "construction_company": "Construtora", "habite_se_date": "Data do habite-se", "use_start_date": "Início de utilização", "contract_number": "Contrato do imóvel", "contractual_value": "Valor contratual (R$)", "program": "Programa / financiamento"};
export const propertyFieldLabel = (field: string) => PROPERTY_LABELS[field] ?? "Dado do imóvel";
