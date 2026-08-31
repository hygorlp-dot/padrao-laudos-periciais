import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { BudgetFoundationView } from "./BudgetFoundationView";

const ID = "11111111-1111-4111-8111-111111111111";
const snapshot = {
  schema_version: "1.0.0", budget_id: "BUDGET-1", revision: 4, workspace_id: ID,
  process_id: "PROCESS-1", appointment_id: null, items: [], effort_estimates: [], travel_estimates: [], third_party_estimates: [], expenses: [],
  proposals: [{ proposal_id: "PROPOSAL-1", revision: 1, amount: "3000.00", currency: "BRL", proposed_at: "2026-08-31T12:00:00Z", rationale: "Proposta inicial" }],
  proposal_revisions: [{ revision_id: "REV-1", proposal_id: "PROPOSAL-1", revision: 1, supersedes_revision_id: null, reason: "Proposta inicial", revised_at: "2026-08-31T12:00:00Z" }],
  court_approvals: [{ approval_id: "APPROVAL-1", court_decision_id: "DECISION-1", amount: "2500.00", currency: "BRL", decided_on: "2026-09-01" }],
  payments: [{ payment_id: "PAYMENT-1", amount: "1000.00", currency: "BRL", received_on: "2026-09-02", reference: "Depósito" }],
  status: "PARTIALLY_RECEIVED", outstanding: { amount: "1500.00", currency: "BRL" },
};
const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

test("shows proposal, court approval, received and outstanding as distinct financial authorities", async () => {
  const item = { revision: 4, updated_at: "2026-09-02T12:00:00Z", snapshot };
  vi.stubGlobal("fetch", vi.fn((input) => Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [item] }) : response(200, item))));
  render(<BudgetFoundationView workspaceId={ID} />);
  expect(await screen.findByRole("heading", { name: "Orçamento pericial" })).toBeInTheDocument();
  expect(screen.getByText("Proposta profissional")).toBeInTheDocument();
  expect(screen.getByText("Valor aprovado pelo Juízo")).toBeInTheDocument();
  expect(screen.getByText("Saldo pendente")).toBeInTheDocument();
  expect(screen.getByText(/R\$\s*3\.000,00/)).toBeInTheDocument();
  expect(screen.getAllByText(/R\$\s*2\.500,00/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/confiança técnica|mérito técnico/i)).not.toBeInTheDocument();
});

test("renders large canonical monetary strings without floating-point loss", async () => {
  const exact = { ...snapshot, proposals: [{ ...snapshot.proposals[0], amount: "9999999999999999.99" }] };
  const item = { revision: 4, updated_at: "2026-09-02T12:00:00Z", snapshot: exact };
  vi.stubGlobal("fetch", vi.fn((input) => Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [item] }) : response(200, item))));
  render(<BudgetFoundationView workspaceId={ID} />);
  expect(await screen.findByText(/R\$\s*9\.999\.999\.999\.999\.999,99/)).toBeInTheDocument();
});

test("starts an empty financial ledger without requiring a technical decision", async () => {
  const started = { revision: 1, updated_at: "2026-08-31T12:00:00Z", snapshot: { ...snapshot, revision: 1, proposals: [], proposal_revisions: [], court_approvals: [], payments: [], status: "DRAFT", outstanding: { amount: "0.00", currency: "BRL" } } };
  const fetchMock = vi.fn().mockResolvedValueOnce(response(404, {})).mockResolvedValueOnce(response(404, {})).mockResolvedValue(response(201, started));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup(); render(<BudgetFoundationView workspaceId={ID} />);
  await user.click(await screen.findByRole("button", { name: "Iniciar controle financeiro" }));
  expect(await screen.findByText("Nenhuma proposta registrada")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/budget-snapshot"), expect.objectContaining({ method: "POST" }));
});

test("records a proposal through an explicit financial command", async () => {
  const empty = { revision: 1, updated_at: "2026-08-31T12:00:00Z", snapshot: { ...snapshot, revision: 1, proposals: [], proposal_revisions: [], court_approvals: [], payments: [], status: "DRAFT", outstanding: { amount: "0.00", currency: "BRL" } } };
  const proposed = { ...empty, revision: 2, snapshot: { ...empty.snapshot, revision: 2, proposals: snapshot.proposals, proposal_revisions: snapshot.proposal_revisions, status: "PROPOSED" } };
  const fetchMock = vi.fn((input, init) => Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [empty] }) : init?.method === "POST" ? response(200, proposed) : response(200, empty)));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup(); render(<BudgetFoundationView workspaceId={ID} />);
  await user.type(await screen.findByLabelText("Valor proposto"), "3000.00");
  await user.type(screen.getByLabelText("Fundamentação da proposta"), "Estimativa de horas e diligências");
  await user.click(screen.getByRole("button", { name: "Registrar proposta" }));
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/budget-snapshot/proposals"), expect.objectContaining({ method: "POST" }));
});

test("closes a fully received budget through an explicit terminal command", async () => {
  const received = { revision: 5, updated_at: "2026-09-03T12:00:00Z", snapshot: { ...snapshot, revision: 5, payments: [{ ...snapshot.payments[0], amount: "2500.00" }], status: "RECEIVED", outstanding: { amount: "0.00", currency: "BRL" } } };
  const closed = { ...received, revision: 6, snapshot: { ...received.snapshot, revision: 6, status: "CLOSED" } };
  const fetchMock = vi.fn((input, init) => Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [received] }) : init?.method === "POST" ? response(200, closed) : response(200, received)));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup(); render(<BudgetFoundationView workspaceId={ID} />);
  await user.click(await screen.findByRole("button", { name: "Encerrar orçamento quitado" }));
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/budget-snapshot/close"), expect.objectContaining({ method: "POST" }));
  expect(await screen.findByText("CLOSED")).toBeInTheDocument();
});
