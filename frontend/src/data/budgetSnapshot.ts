export type Money = { amount: string; currency: string };
export type BudgetSnapshot = {
  schema_version: "1.0.0"; budget_id: string; revision: number; workspace_id: string;
  process_id: string | null; appointment_id: string | null; status: string; outstanding: Money;
  items: Array<{ item_id: string; category: string; description: string; quantity: string; unit_amount: string; total_amount: string }>;
  effort_estimates: Array<{ estimate_id: string; professional_id: string; estimated_hours: string; hourly_amount: string; total_amount: string }>;
  travel_estimates: Array<{ estimate_id: string; distance_km: string; amount_per_km: string; total_amount: string; description: string }>;
  third_party_estimates: Array<{ estimate_id: string; provider_description: string; amount: string; currency: string }>;
  expenses: Array<{ expense_id: string; category: string; amount: string; currency: string; incurred_on: string; description: string }>;
  proposals: Array<{ proposal_id: string; revision: number; amount: string; currency: string; proposed_at: string; rationale: string }>;
  proposal_revisions: Array<{ revision_id: string; proposal_id: string; revision: number; supersedes_revision_id: string | null; reason: string; revised_at: string }>;
  court_approvals: Array<{ approval_id: string; external_court_decision_reference: string; amount: string; currency: string; decided_on: string }>;
  payments: Array<{ payment_id: string; amount: string; currency: string; received_on: string; reference: string }>;
};
export type BudgetEnvelope = { revision: number; updated_at: string; snapshot: BudgetSnapshot };
export class BudgetApiError extends Error { constructor(readonly kind: "not-found" | "invalid" | "unavailable") { super(kind); } }
const base = (workspaceId: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/budget-snapshot`;
async function decode(response: Response) { if (response.status === 404) throw new BudgetApiError("not-found"); if (!response.ok) throw new BudgetApiError("unavailable"); return response.json(); }
function envelope(value: unknown, workspaceId: string): BudgetEnvelope { const item = value as BudgetEnvelope; const snapshot = item?.snapshot; if (!Number.isInteger(item?.revision) || item.revision < 1 || snapshot?.schema_version !== "1.0.0" || snapshot.workspace_id !== workspaceId || snapshot.revision !== item.revision || !Array.isArray(snapshot.items) || !Array.isArray(snapshot.effort_estimates) || !Array.isArray(snapshot.travel_estimates) || !Array.isArray(snapshot.third_party_estimates) || !Array.isArray(snapshot.proposals) || !Array.isArray(snapshot.court_approvals) || !Array.isArray(snapshot.payments) || !Array.isArray(snapshot.expenses) || typeof snapshot.outstanding?.amount !== "string") throw new BudgetApiError("invalid"); return item; }
export async function getBudgetSnapshot(workspaceId: string, signal?: AbortSignal) { return envelope(await decode(await fetch(base(workspaceId), { method: "GET", credentials: "same-origin", cache: "no-store", signal })), workspaceId); }
export async function getBudgetHistory(workspaceId: string, signal?: AbortSignal) { const value = await decode(await fetch(`${base(workspaceId)}/history`, { method: "GET", credentials: "same-origin", cache: "no-store", signal })) as { items: unknown[] }; if (!Array.isArray(value.items)) throw new BudgetApiError("invalid"); return value.items.map((item) => envelope(item, workspaceId)); }
async function post(workspaceId: string, path: string, body: object) { return envelope(await decode(await fetch(`${base(workspaceId)}${path}`, { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })), workspaceId); }
export function startBudgetSnapshot(workspaceId: string) { return post(workspaceId, "", { process_id: null, appointment_id: null }); }
export function addBudgetItem(workspaceId: string, revision: number, category: string, description: string, quantity: string, unitAmount: string) { return post(workspaceId, "/items", { expected_revision: revision, category, description, quantity, unit_amount: unitAmount }); }
export function addProfessionalEffortEstimate(workspaceId: string, revision: number, professionalId: string, estimatedHours: string, hourlyAmount: string) { return post(workspaceId, "/effort-estimates", { expected_revision: revision, professional_id: professionalId, estimated_hours: estimatedHours, hourly_amount: hourlyAmount }); }
export function addTravelEstimate(workspaceId: string, revision: number, distanceKm: string, amountPerKm: string, description: string) { return post(workspaceId, "/travel-estimates", { expected_revision: revision, distance_km: distanceKm, amount_per_km: amountPerKm, description }); }
export function addThirdPartyEstimate(workspaceId: string, revision: number, providerDescription: string, amount: string) { return post(workspaceId, "/third-party-estimates", { expected_revision: revision, provider_description: providerDescription, amount, currency: "BRL" }); }
export function addFeeProposal(workspaceId: string, revision: number, amount: string, rationale: string) { return post(workspaceId, "/proposals", { expected_revision: revision, amount, currency: "BRL", rationale }); }
export function recordCourtApproval(workspaceId: string, revision: number, externalReference: string, amount: string, decidedOn: string) { return post(workspaceId, "/court-approvals", { expected_revision: revision, external_court_decision_reference: externalReference, amount, currency: "BRL", decided_on: decidedOn }); }
export function recordExpense(workspaceId: string, revision: number, category: string, amount: string, incurredOn: string, description: string) { return post(workspaceId, "/expenses", { expected_revision: revision, category, amount, currency: "BRL", incurred_on: incurredOn, description }); }
export function recordPayment(workspaceId: string, revision: number, amount: string, receivedOn: string, reference: string) { return post(workspaceId, "/payments", { expected_revision: revision, amount, currency: "BRL", received_on: receivedOn, reference }); }
export function closeBudgetSnapshot(workspaceId: string, revision: number) { return post(workspaceId, "/close", { expected_revision: revision }); }
