import { type ChangeEvent, type FormEvent, useEffect, useState } from "react";

import {
  addBudgetItem, addFeeProposal, addProfessionalEffortEstimate, addThirdPartyEstimate,
  addTravelEstimate, BudgetApiError, closeBudgetSnapshot, getBudgetHistory,
  getBudgetSnapshot, recordCourtApproval, recordExpense, recordPayment,
  startBudgetSnapshot, type BudgetEnvelope,
} from "../data/budgetSnapshot";

type State = { kind: "loading" } | { kind: "missing" } | { kind: "ready"; value: BudgetEnvelope } | { kind: "error" };
type Command = "item" | "effort" | "travel" | "third-party" | "proposal" | "approval" | "expense" | "payment";
const cents = (amount: string) => BigInt(amount.replace(".", ""));
const decimal = (value: bigint) => `${value / 100n}.${String(value % 100n).padStart(2, "0")}`;
const money = (amount: string, currency = "BRL") => { const [whole, fraction] = decimal(cents(amount)).split("."); return `${currency === "BRL" ? "R$" : currency}\u00a0${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".")},${fraction}`; };

export function BudgetFoundationView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [history, setHistory] = useState<BudgetEnvelope[]>([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const accept = (value: BudgetEnvelope) => { setState({ kind: "ready", value }); setForm({}); void getBudgetHistory(workspaceId).then(setHistory, () => undefined); };
  useEffect(() => { const controller = new AbortController(); Promise.all([getBudgetSnapshot(workspaceId, controller.signal), getBudgetHistory(workspaceId, controller.signal)]).then(([value, items]) => { setState({ kind: "ready", value }); setHistory(items); }, (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof BudgetApiError && error.kind === "not-found" ? "missing" : "error" }); }); return () => controller.abort(); }, [workspaceId]);
  const start = async () => { setBusy(true); try { accept(await startBudgetSnapshot(workspaceId)); } catch { setState({ kind: "error" }); } finally { setBusy(false); } };
  const command = async (event: FormEvent, kind: Command) => {
    event.preventDefault();
    if (state.kind !== "ready" || state.value.snapshot.status === "CLOSED") return;
    setBusy(true);
    try {
      const revision = state.value.revision;
      const value = kind === "item" ? await addBudgetItem(workspaceId, revision, form.category, form.description, form.quantity, form.unitAmount)
        : kind === "effort" ? await addProfessionalEffortEstimate(workspaceId, revision, form.professional, form.hours, form.hourlyAmount)
        : kind === "travel" ? await addTravelEstimate(workspaceId, revision, form.distance, form.amountPerKm, form.description)
        : kind === "third-party" ? await addThirdPartyEstimate(workspaceId, revision, form.provider, form.amount)
        : kind === "proposal" ? await addFeeProposal(workspaceId, revision, form.amount, form.rationale)
        : kind === "approval" ? await recordCourtApproval(workspaceId, revision, form.externalReference, form.amount, form.date)
        : kind === "expense" ? await recordExpense(workspaceId, revision, form.category, form.amount, form.date, form.description)
        : await recordPayment(workspaceId, revision, form.amount, form.date, form.reference);
      accept(value);
    } catch { setState({ kind: "error" }); } finally { setBusy(false); }
  };
  const close = async () => { if (state.kind !== "ready" || state.value.snapshot.status !== "RECEIVED") return; setBusy(true); try { accept(await closeBudgetSnapshot(workspaceId, state.value.revision)); } catch { setState({ kind: "error" }); } finally { setBusy(false); } };
  const field = (name: string) => ({ value: form[name] ?? "", onChange: (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((current) => ({ ...current, [name]: event.target.value })) });

  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Reabrindo orçamento</h2><p>Validando o histórico financeiro local.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Orçamento indisponível</h2><p>Nenhuma informação foi alterada. Reabra a etapa para tentar novamente.</p></div></section>;
  if (state.kind === "missing") return <section className="budget-empty"><h2>Controle financeiro ainda não iniciado</h2><p>Crie um ledger separado da análise técnica para propostas, decisões, despesas e recebimentos.</p><button className="primary-action" type="button" disabled={busy} onClick={start}>Iniciar controle financeiro</button></section>;
  const value = state.value.snapshot; const latestProposal = value.proposals.at(-1); const latestApproval = value.court_approvals.at(-1); const received = decimal(value.payments.reduce((total, item) => total + cents(item.amount), 0n)); const closed = value.status === "CLOSED";
  return <section className="budget-ledger" aria-labelledby="budget-title">
    <header className="budget-header"><div><h2 id="budget-title">Orçamento pericial</h2><p>Propostas, decisões, despesas e recebimentos em uma trilha financeira própria.</p></div><strong>{value.status}</strong></header>
    {closed && <section className="status-state" aria-label="Estado final do orçamento"><span className="state-mark" aria-hidden="true">✓</span><div><h3>Orçamento encerrado</h3><p>O histórico permanece disponível somente para leitura.</p></div></section>}
    <dl className="budget-balance"><div><dt>Proposta profissional</dt><dd>{latestProposal ? money(latestProposal.amount, latestProposal.currency) : "—"}</dd></div><div><dt>Valor aprovado pelo Juízo</dt><dd>{latestApproval ? money(latestApproval.amount, latestApproval.currency) : "—"}</dd></div><div><dt>Recebido</dt><dd>{money(received)}</dd></div><div><dt>Saldo pendente</dt><dd>{money(value.outstanding.amount, value.outstanding.currency)}</dd></div></dl>
    {!latestProposal && <p className="budget-empty-line">Nenhuma proposta registrada</p>}
    {!closed && <BudgetCommands busy={busy} command={command} field={field}/>}
    {!closed && value.status === "RECEIVED" ? <button className="primary-action" type="button" disabled={busy} onClick={close}>Encerrar orçamento quitado</button> : null}
    <BudgetDetail value={value}/>
    <details className="budget-history"><summary>Histórico preservado · {history.length} revisões</summary><ol>{history.map((item) => <li key={item.revision}><strong>Revisão {item.revision}</strong><span>{item.snapshot.status}</span><time dateTime={item.updated_at}>{new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(new Date(item.updated_at))}</time></li>)}</ol></details>
  </section>;
}

type FieldProps = { value: string; onChange: (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => void };
function BudgetCommands({ busy, command, field }: { busy: boolean; command: (event: FormEvent, kind: Command) => Promise<void>; field: (name: string) => FieldProps }) {
  const categories = <><option value="">Selecione</option><option value="PROFESSIONAL_HOURS">Horas profissionais</option><option value="TRAVEL">Deslocamento</option><option value="ASSISTANTS">Assistentes</option><option value="EQUIPMENT">Equipamento</option><option value="TESTS_LABORATORY">Ensaios e laboratório</option><option value="THIRD_PARTY_SERVICES">Serviços de terceiros</option><option value="ADMINISTRATIVE_COSTS">Custos administrativos</option><option value="REVISIONS">Revisões</option><option value="OTHER">Outro</option></>;
  const amount = (name: string) => <input required inputMode="decimal" pattern="[0-9]+\.[0-9]{2}" {...field(name)}/>;
  return <div className="budget-commands">
    <details><summary>Item orçamentário</summary><form onSubmit={(event) => command(event, "item")}><label>Categoria<select required {...field("category")}>{categories}</select></label><label>Descrição<input required {...field("description")}/></label><label>Quantidade{amount("quantity")}</label><label>Valor unitário{amount("unitAmount")}</label><button type="submit" disabled={busy}>Registrar item orçamentário</button></form></details>
    <details><summary>Esforço profissional</summary><form onSubmit={(event) => command(event, "effort")}><label>Profissional ou assistente<input required {...field("professional")}/></label><label>Horas estimadas{amount("hours")}</label><label>Valor por hora{amount("hourlyAmount")}</label><button type="submit" disabled={busy}>Registrar esforço profissional</button></form></details>
    <details><summary>Estimativa de viagem</summary><form onSubmit={(event) => command(event, "travel")}><label>Distância em km{amount("distance")}</label><label>Valor por km{amount("amountPerKm")}</label><label>Descrição<input required {...field("description")}/></label><button type="submit" disabled={busy}>Registrar estimativa de viagem</button></form></details>
    <details><summary>Estimativa de terceiro</summary><form onSubmit={(event) => command(event, "third-party")}><label>Prestador ou serviço<input required {...field("provider")}/></label><label>Valor estimado{amount("amount")}</label><button type="submit" disabled={busy}>Registrar estimativa de terceiro</button></form></details>
    <details open><summary>Nova proposta</summary><form onSubmit={(event) => command(event, "proposal")}><label>Valor proposto{amount("amount")}</label><label>Fundamentação da proposta<input required {...field("rationale")}/></label><button type="submit" disabled={busy}>Registrar proposta</button></form></details>
    <details><summary>Aprovação judicial</summary><form onSubmit={(event) => command(event, "approval")}><label>Referência externa da decisão judicial<input required {...field("externalReference")}/></label><label>Valor aprovado{amount("amount")}</label><label>Data da decisão<input required type="date" {...field("date")}/></label><button type="submit" disabled={busy}>Registrar aprovação</button></form></details>
    <details><summary>Despesa efetiva</summary><form onSubmit={(event) => command(event, "expense")}><label>Categoria<select required {...field("category")}>{categories}</select></label><label>Valor{amount("amount")}</label><label>Data<input required type="date" {...field("date")}/></label><label>Descrição<input required {...field("description")}/></label><button type="submit" disabled={busy}>Registrar despesa</button></form></details>
    <details><summary>Recebimento</summary><form onSubmit={(event) => command(event, "payment")}><label>Valor recebido{amount("amount")}</label><label>Data do recebimento<input required type="date" {...field("date")}/></label><label>Referência<input required {...field("reference")}/></label><button type="submit" disabled={busy}>Registrar recebimento</button></form></details>
  </div>;
}

function BudgetDetail({ value }: { value: BudgetEnvelope["snapshot"] }) {
  return <section className="budget-ledger-history" aria-labelledby="budget-detail-title"><h3 id="budget-detail-title">Histórico financeiro detalhado</h3>
    <h4>Itens e estimativas</h4><ul>{value.items.map((item) => <li key={item.item_id}><strong>{item.description}</strong><span>{item.quantity} × {money(item.unit_amount)} = {money(item.total_amount)}</span></li>)}{value.effort_estimates.map((item) => <li key={item.estimate_id}><strong>{item.professional_id}</strong><span>{item.estimated_hours} h × {money(item.hourly_amount)} = {money(item.total_amount)}</span></li>)}{value.travel_estimates.map((item) => <li key={item.estimate_id}><strong>{item.description}</strong><span>{item.distance_km} km × {money(item.amount_per_km)} = {money(item.total_amount)}</span></li>)}{value.third_party_estimates.map((item) => <li key={item.estimate_id}><strong>{item.provider_description}</strong><span>{money(item.amount, item.currency)}</span></li>)}</ul>
    <h4>Propostas e revisões</h4><ul>{value.proposals.map((item) => <li key={item.proposal_id}><strong>{item.rationale}</strong><span>{money(item.amount, item.currency)}</span></li>)}{value.proposal_revisions.map((item) => <li key={item.revision_id}><strong>{item.reason}</strong><span>Revisão {item.revision}{item.supersedes_revision_id ? ` · substitui ${item.supersedes_revision_id}` : " · emissão original"}</span><time dateTime={item.revised_at}>{new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(new Date(item.revised_at))}</time></li>)}</ul>
    <h4>Aprovações judiciais externas</h4><ul>{value.court_approvals.map((item) => <li key={item.approval_id}><strong>{item.external_court_decision_reference}</strong><span>{money(item.amount, item.currency)}</span></li>)}</ul>
    <h4>Despesas</h4><ul>{value.expenses.map((item) => <li key={item.expense_id}><strong>{item.description}</strong><span>{money(item.amount, item.currency)}</span></li>)}</ul>
    <h4>Recebimentos</h4><ul>{value.payments.map((item) => <li key={item.payment_id}><strong>{item.reference}</strong><span>{money(item.amount, item.currency)}</span></li>)}</ul>
  </section>;
}
