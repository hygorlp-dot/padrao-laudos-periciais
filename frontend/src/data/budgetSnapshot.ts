export type Money = { amount: string; currency: string };
export type BudgetSnapshot = {
  schema_version: "1.0.0"; budget_id: string; revision: number; workspace_id: string;
  process_id: string | null; appointment_id: string | null; status: string; outstanding: Money;
  items: unknown[]; effort_estimates: unknown[]; travel_estimates: unknown[]; third_party_estimates: unknown[];
  expenses: Array<{ expense_id: string; category: string; amount: string; currency: string; incurred_on: string; description: string }>;
  proposals: Array<{ proposal_id: string; revision: number; amount: string; currency: string; proposed_at: string; rationale: string }>;
  proposal_revisions: Array<{ revision_id: string; proposal_id: string; revision: number; supersedes_revision_id: string | null; reason: string; revised_at: string }>;
  court_approvals: Array<{ approval_id: string; court_decision_id: string; amount: string; currency: string; decided_on: string }>;
  payments: Array<{ payment_id: string; amount: string; currency: string; received_on: string; reference: string }>;
};
export type BudgetEnvelope = { revision: number; updated_at: string; snapshot: BudgetSnapshot };
export class BudgetApiError extends Error { constructor(readonly kind: "not-found" | "invalid" | "unavailable") { super(kind); } }
const base = (workspaceId: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/budget-snapshot`;
async function decode(response: Response) { if (response.status === 404) throw new BudgetApiError("not-found"); if (!response.ok) throw new BudgetApiError("unavailable"); return response.json(); }
function envelope(value: unknown, workspaceId: string): BudgetEnvelope { const item = value as BudgetEnvelope; const snapshot = item?.snapshot; if (!Number.isInteger(item?.revision) || item.revision < 1 || snapshot?.schema_version !== "1.0.0" || snapshot.workspace_id !== workspaceId || snapshot.revision !== item.revision || !Array.isArray(snapshot.proposals) || !Array.isArray(snapshot.court_approvals) || !Array.isArray(snapshot.payments) || !Array.isArray(snapshot.expenses) || typeof snapshot.outstanding?.amount !== "string") throw new BudgetApiError("invalid"); return item; }
export async function getBudgetSnapshot(workspaceId: string, signal?: AbortSignal) { return envelope(await decode(await fetch(base(workspaceId), { method: "GET", credentials: "same-origin", cache: "no-store", signal })), workspaceId); }
export async function getBudgetHistory(workspaceId: string, signal?: AbortSignal) { const value = await decode(await fetch(`${base(workspaceId)}/history`, { method: "GET", credentials: "same-origin", cache: "no-store", signal })) as { items: unknown[] }; if (!Array.isArray(value.items)) throw new BudgetApiError("invalid"); return value.items.map((item) => envelope(item, workspaceId)); }
async function post(workspaceId: string, path: string, body: object) { return envelope(await decode(await fetch(`${base(workspaceId)}${path}`, { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })), workspaceId); }
export function startBudgetSnapshot(workspaceId: string) { return post(workspaceId, "", { process_id: null, appointment_id: null }); }
export function addFeeProposal(workspaceId: string, revision: number, amount: string, rationale: string) { return post(workspaceId, "/proposals", { expected_revision: revision, amount, currency: "BRL", rationale }); }
export function recordCourtApproval(workspaceId: string, revision: number, courtDecisionId: string, amount: string, decidedOn: string) { return post(workspaceId, "/court-approvals", { expected_revision: revision, court_decision_id: courtDecisionId, amount, currency: "BRL", decided_on: decidedOn }); }
export function recordExpense(workspaceId: string, revision: number, category: string, amount: string, incurredOn: string, description: string) { return post(workspaceId, "/expenses", { expected_revision: revision, category, amount, currency: "BRL", incurred_on: incurredOn, description }); }
export function recordPayment(workspaceId: string, revision: number, amount: string, receivedOn: string, reference: string) { return post(workspaceId, "/payments", { expected_revision: revision, amount, currency: "BRL", received_on: receivedOn, reference }); }
export function closeBudgetSnapshot(workspaceId: string, revision: number) { return post(workspaceId, "/close", { expected_revision: revision }); }
