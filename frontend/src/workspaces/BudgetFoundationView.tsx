import { type FormEvent, useEffect, useState } from "react";

import { addFeeProposal, BudgetApiError, getBudgetHistory, getBudgetSnapshot, recordCourtApproval, recordExpense, recordPayment, startBudgetSnapshot, type BudgetEnvelope } from "../data/budgetSnapshot";

type State = { kind: "loading" } | { kind: "missing" } | { kind: "ready"; value: BudgetEnvelope } | { kind: "error" };
const cents = (amount: string) => BigInt(amount.replace(".", ""));
const decimal = (value: bigint) => `${value / 100n}.${String(value % 100n).padStart(2, "0")}`;
const money = (amount: string, currency = "BRL") => {
  const [whole, fraction] = decimal(cents(amount)).split(".");
  return `${currency === "BRL" ? "R$" : currency}\u00a0${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".")},${fraction}`;
};

export function BudgetFoundationView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [history, setHistory] = useState<BudgetEnvelope[]>([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const accept = (value: BudgetEnvelope) => { setState({ kind: "ready", value }); setForm({}); void getBudgetHistory(workspaceId).then(setHistory, () => undefined); };
  useEffect(() => { const controller = new AbortController(); Promise.all([getBudgetSnapshot(workspaceId, controller.signal), getBudgetHistory(workspaceId, controller.signal)]).then(([value, items]) => { setState({ kind: "ready", value }); setHistory(items); }, (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof BudgetApiError && error.kind === "not-found" ? "missing" : "error" }); }); return () => controller.abort(); }, [workspaceId]);
  const start = async () => { setBusy(true); try { accept(await startBudgetSnapshot(workspaceId)); } catch { setState({ kind: "error" }); } finally { setBusy(false); } };
  const command = async (event: FormEvent, kind: "proposal" | "approval" | "expense" | "payment") => { event.preventDefault(); if (state.kind !== "ready") return; setBusy(true); try { const revision = state.value.revision; const value = kind === "proposal" ? await addFeeProposal(workspaceId, revision, form.amount, form.rationale) : kind === "approval" ? await recordCourtApproval(workspaceId, revision, form.decision, form.amount, form.date) : kind === "expense" ? await recordExpense(workspaceId, revision, form.category, form.amount, form.date, form.description) : await recordPayment(workspaceId, revision, form.amount, form.date, form.reference); accept(value); } catch { setState({ kind: "error" }); } finally { setBusy(false); } };
  const field = (name: string) => ({ value: form[name] ?? "", onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((current) => ({ ...current, [name]: event.target.value })) });

  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Reabrindo orçamento</h2><p>Validando o histórico financeiro local.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Orçamento indisponível</h2><p>Nenhuma informação foi alterada. Reabra a etapa para tentar novamente.</p></div></section>;
  if (state.kind === "missing") return <section className="budget-empty"><h2>Controle financeiro ainda não iniciado</h2><p>Crie um ledger separado da análise técnica para propostas, decisões, despesas e recebimentos.</p><button className="primary-action" type="button" disabled={busy} onClick={start}>Iniciar controle financeiro</button></section>;
  const value = state.value.snapshot; const latestProposal = value.proposals.at(-1); const latestApproval = value.court_approvals.at(-1); const received = decimal(value.payments.reduce((total, item) => total + cents(item.amount), 0n));
  return <section className="budget-ledger" aria-labelledby="budget-title"><header className="budget-header"><div><h2 id="budget-title">Orçamento pericial</h2><p>Propostas, decisões, despesas e recebimentos em uma trilha financeira própria.</p></div><strong>{value.status}</strong></header>
    <dl className="budget-balance"><div><dt>Proposta profissional</dt><dd>{latestProposal ? money(latestProposal.amount, latestProposal.currency) : "—"}</dd></div><div><dt>Valor aprovado pelo Juízo</dt><dd>{latestApproval ? money(latestApproval.amount, latestApproval.currency) : "—"}</dd></div><div><dt>Recebido</dt><dd>{money(received)}</dd></div><div><dt>Saldo pendente</dt><dd>{money(value.outstanding.amount, value.outstanding.currency)}</dd></div></dl>
    {!latestProposal && <p className="budget-empty-line">Nenhuma proposta registrada</p>}
    <div className="budget-commands">
      <details open><summary>Nova proposta</summary><form onSubmit={(event) => command(event, "proposal")}><label>Valor proposto<input required inputMode="decimal" pattern="[0-9]+\.[0-9]{2}" {...field("amount")}/></label><label>Fundamentação da proposta<input required {...field("rationale")}/></label><button type="submit" disabled={busy}>Registrar proposta</button></form></details>
      <details><summary>Aprovação judicial</summary><form onSubmit={(event) => command(event, "approval")}><label>Decisão judicial<input required {...field("decision")}/></label><label>Valor aprovado<input required inputMode="decimal" {...field("amount")}/></label><label>Data da decisão<input required type="date" {...field("date")}/></label><button type="submit" disabled={busy}>Registrar aprovação</button></form></details>
      <details><summary>Despesa efetiva</summary><form onSubmit={(event) => command(event, "expense")}><label>Categoria<select required {...field("category")}><option value="">Selecione</option><option value="TRAVEL">Deslocamento</option><option value="EQUIPMENT">Equipamento</option><option value="TESTS_LABORATORY">Ensaios e laboratório</option><option value="THIRD_PARTY_SERVICES">Serviços de terceiros</option><option value="ADMINISTRATIVE_COSTS">Custos administrativos</option></select></label><label>Valor<input required inputMode="decimal" {...field("amount")}/></label><label>Data<input required type="date" {...field("date")}/></label><label>Descrição<input required {...field("description")}/></label><button type="submit" disabled={busy}>Registrar despesa</button></form></details>
      <details><summary>Recebimento</summary><form onSubmit={(event) => command(event, "payment")}><label>Valor recebido<input required inputMode="decimal" {...field("amount")}/></label><label>Data do recebimento<input required type="date" {...field("date")}/></label><label>Referência<input required {...field("reference")}/></label><button type="submit" disabled={busy}>Registrar recebimento</button></form></details>
    </div>
    <details className="budget-history"><summary>Histórico preservado · {history.length} revisões</summary><ol>{history.map((item) => <li key={item.revision}><strong>Revisão {item.revision}</strong><span>{item.snapshot.status}</span><time dateTime={item.updated_at}>{new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(new Date(item.updated_at))}</time></li>)}</ol></details>
  </section>;
}
