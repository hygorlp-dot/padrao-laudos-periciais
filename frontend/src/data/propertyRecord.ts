export type PropertyEvidence = { document_id: string; document_sha256: string; filename: string; page: number; excerpt: string; method: string; confidence: number | null; source_value: string };
export type PropertyValue = { field: string; value: string; evidence: PropertyEvidence | null; confirmed_by: string; confirmed_at: string };
export type PropertyEnvelope = {
  revision: number | null; updated_at: string | null;
  record: { schema_version: "1.0.0"; workspace_id: string; values: PropertyValue[] };
  fields: { field: string; label: string; kind: "text" | "decimal" | "date" }[];
  /** Campos confirmados cuja página de origem o perito excluiu depois da confirmação. */
  stale_fields: string[];
};
export type PropertyProposal = { proposal_id: string; workspace_id: string; field: string; value: string; evidence: PropertyEvidence; state: "PROPOSED" | "CONFLICTING"; strength?: "STRONG" | "POSSIBLE"; source_rank?: string; piece_id?: string | null };
/** #288: mesmo valor normalizado, todas as evidências, ordenado pela hierarquia das peças. */
export type PropertyValueCluster = {
  cluster_id: string; field: string; canonical_value: string; display_value: string; normalized_value: string;
  confidence: "HIGH" | "MEDIUM" | "LOW"; strength: "STRONG" | "POSSIBLE"; best_rank: string;
  source_count: number; document_count: number; evidences: PropertyProposal[]; conflicting_cluster_ids: string[];
};
export type PropertyProposalSet = { proposals: PropertyProposal[]; clusters?: PropertyValueCluster[] | null; pendingDocuments: string[] };

function validCluster(value: PropertyValueCluster, workspace: string) {
  return Boolean(value) && typeof value.cluster_id === "string" && typeof value.field === "string" && typeof value.display_value === "string"
    && ["HIGH", "MEDIUM", "LOW"].includes(value.confidence) && Number.isInteger(value.source_count) && Number.isInteger(value.document_count)
    && Array.isArray(value.evidences) && value.evidences.length > 0 && value.evidences.every((item) => item.workspace_id === workspace && item.field === value.field)
    && value.evidences[0].value === value.display_value && Array.isArray(value.conflicting_cluster_ids);
}
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
export async function getPropertyProposals(workspace: string, signal?: AbortSignal): Promise<PropertyProposalSet> {
  const value = await read(await fetch(`${base(workspace)}/proposals`, { credentials: "same-origin", cache: "no-store", signal }));
  if (value?.workspace_id !== workspace || !Array.isArray(value.proposals) || value.proposals.some((p: PropertyProposal) => p.workspace_id !== workspace)) throw new PropertyApiError("unavailable");
  // Sem grupos (produto anterior) a tela volta à lista por evidência e diz isso.
  const clusters = Array.isArray(value.clusters) ? value.clusters : null;
  if (clusters && clusters.some((item: PropertyValueCluster) => !validCluster(item, workspace))) throw new PropertyApiError("unavailable");
  return { proposals: value.proposals, clusters, pendingDocuments: Array.isArray(value.pending_documents) ? value.pending_documents : [] };
}
export async function savePropertyRecord(workspace: string, revision: number | null, changes: PropertyChange[]) {
  return envelope(await read(await fetch(base(workspace), { method: "PUT", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: revision, changes }) })), workspace);
}

const PROPERTY_LABELS: Record<string, string> = {"owner": "Proprietário do imóvel", "street": "Logradouro", "number": "Número", "complement": "Complemento", "unit": "Unidade / apartamento", "block": "Bloco", "quadra": "Quadra", "neighborhood": "Bairro", "postal_code": "CEP", "city": "Município do imóvel", "state": "UF do imóvel", "development": "Empreendimento", "floor": "Pavimento", "private_area_m2": "Área privativa (m²)", "constructed_area_m2": "Área construída (m²)", "construction_system": "Sistema construtivo", "construction_company": "Construtora", "habite_se_date": "Data do habite-se", "use_start_date": "Início de utilização", "contract_number": "Contrato do imóvel", "contractual_value": "Valor contratual (R$)", "program": "Programa / financiamento"};
export const propertyFieldLabel = (field: string) => PROPERTY_LABELS[field] ?? "Dado do imóvel";
