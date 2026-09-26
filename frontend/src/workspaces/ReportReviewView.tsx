import { useEffect, useState } from "react";

import { navigate } from "../app/router";
import { useExpertIdentity } from "../data/expertIdentity";
import { getReportSnapshot, ReportApiError, reviewReportSnapshot, type ReportEnvelope } from "../data/reportSnapshot";
import { workspacePath } from "../routes/routeCatalog";
import { actionLabel, formatDateTime, stateLabel } from "../ui/labels";
import { TechnicalDetails } from "../ui/TechnicalDetails";

type State = { kind: "loading" } | { kind: "missing" } | { kind: "ready"; value: ReportEnvelope } | { kind: "error" };
type Check = { label: string; done: boolean; detail: string };

// Revisão: a conferência do laudo antes da entrega. A lista mostra o que falta
// com base na cobertura calculada pelo próprio laudo; a decisão continua sendo
// um ato profissional explícito, com fundamentação.
export function ReportReviewView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [version, setVersion] = useState(0);
  const expert = useExpertIdentity();

  useEffect(() => {
    const controller = new AbortController();
    getReportSnapshot(workspaceId, controller.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof ReportApiError && error.kind === "not-found" ? "missing" : "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId, version]);

  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Abrindo a revisão</h2><p>Conferindo a completude do laudo.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível abrir a revisão</h2><p>O laudo salvo não pôde ser lido. Nada foi alterado.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  if (state.kind === "missing") return <section className="status-state status-state--empty"><span className="empty-sheet" aria-hidden="true"><span /><span /><span /></span><div><h2>Nenhum laudo para revisar</h2><p>Componha o laudo antes de revisá-lo.</p><a className="primary-action" href={workspacePath(workspaceId, "laudo")} onClick={navigate}>Ir para Laudo</a></div></section>;

  const { snapshot } = state.value;
  const coverage = snapshot.coverage;
  const checks: Check[] = [
    { label: "Contexto processual (art. 319)", done: coverage.context_present_fields >= coverage.context_required_fields, detail: `${coverage.context_present_fields} de ${coverage.context_required_fields} campos` },
    { label: "Conteúdo pericial obrigatório (art. 473)", done: coverage.cpc473_present_sections >= coverage.cpc473_required_sections, detail: `${coverage.cpc473_present_sections} de ${coverage.cpc473_required_sections} seções` },
    { label: "Afirmações com fonte", done: coverage.material_claims > 0 && coverage.traceable_claims === coverage.material_claims, detail: `${coverage.traceable_claims} de ${coverage.material_claims} afirmações rastreáveis` },
    { label: "Quesitos respondidos com vínculo a achado", done: coverage.answers > 0 && coverage.traceable_answers === coverage.answers, detail: `${coverage.traceable_answers} de ${coverage.answers} respostas rastreáveis` },
    { label: "Fontes anteriores atuais", done: !snapshot.upstream_stale, detail: snapshot.upstream_stale ? "Há fontes alteradas depois do laudo" : "Nenhuma fonte alterada" },
  ];
  // A aprovação só é oferecida com a conferência completa; o servidor confere de novo.
  const ready = checks.every((check) => check.done);
  const allowed = {
    MARK_REVIEWED: snapshot.state === "DRAFT",
    APPROVE: snapshot.state === "REVIEWED",
    SUPERSEDE: snapshot.state === "APPROVED" || snapshot.state === "REVIEWED",
  } as const;
  const act = async (action: "MARK_REVIEWED" | "APPROVE" | "SUPERSEDE") => {
    setBusy(true); setActionError(false);
    try { setState({ kind: "ready", value: await reviewReportSnapshot(workspaceId, state.value, action, reason) }); setReason(""); }
    catch { setActionError(true); }
    finally { setBusy(false); }
  };
  const person = (id: string) => (expert && id === expert.profile_id ? expert.full_name : id);

  return <section className="report-review" aria-labelledby="report-review-title">
    <header className="planning-overview"><div><h2 id="report-review-title">Revisão do laudo</h2><p>Confira a completude antes de marcar como revisado e aprovar. A aprovação libera a entrega em Word e PDF.</p></div><div className="planning-readiness"><strong>{stateLabel(snapshot.state)}</strong><span>{snapshot.state === "APPROVED" ? "Aprovado para entrega" : ready ? "Conferência completa" : "Há pendências de conteúdo"}</span></div></header>
    <section className="analysis-section" aria-labelledby="review-checklist-title"><h3 id="review-checklist-title">Conferência</h3><ul className="review-checklist">{checks.map((check) => <li key={check.label} data-done={check.done || undefined}><span className="review-check-mark" aria-hidden="true">{check.done ? "✓" : "!"}</span><div><strong>{check.label}</strong><span>{check.done ? "Completo" : "Pendente"} · {check.detail}</span></div></li>)}</ul>{coverage.reasons.length > 0 && <ul className="planning-reasons">{coverage.reasons.map((item) => <li key={item}>{item}</li>)}</ul>}<a className="text-action" href={workspacePath(workspaceId, "laudo")} onClick={navigate}>Corrigir no Laudo</a></section>
    {actionError && <section className="inline-alert" role="alert"><strong>Não foi possível registrar a revisão.</strong><p>O laudo continua no estado anterior. Confira as pendências e tente de novo.</p></section>}
    {snapshot.state !== "SUPERSEDED" && <section className="technical-authority" aria-labelledby="review-decision-title"><h3 id="review-decision-title">Decisão profissional</h3><label>Fundamentação da revisão<textarea value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy || snapshot.upstream_stale}/></label><div className="action-row">
      {allowed.MARK_REVIEWED && <button className="authority-action" type="button" disabled={busy || snapshot.upstream_stale || !reason.trim()} onClick={() => act("MARK_REVIEWED")}>Marcar como revisado</button>}
      {allowed.APPROVE && <button className="authority-action" type="button" disabled={busy || snapshot.upstream_stale || !reason.trim() || !ready} onClick={() => act("APPROVE")}>Aprovar laudo</button>}
      {allowed.SUPERSEDE && <button className="destructive-action" type="button" disabled={busy || !reason.trim()} onClick={() => act("SUPERSEDE")}>Marcar como substituído</button>}
    </div>{allowed.APPROVE && !ready && <p className="field-hint">A aprovação fica disponível quando a conferência estiver completa.</p>}{snapshot.state === "APPROVED" && <a className="primary-action" href={workspacePath(workspaceId, "exportar")} onClick={navigate}>Ir para a entrega</a>}</section>}
    <section className="analysis-section"><h3>Histórico de revisão</h3>{snapshot.review_decisions.length ? <ol className="planning-decisions">{snapshot.review_decisions.map((item) => <li key={item.review_id}><strong>{actionLabel(item.action)}</strong><span>{person(item.professional_id)} · {formatDateTime(item.timestamp)}</span><p>{item.reason}</p><TechnicalDetails><span className="data">{item.review_id}</span></TechnicalDetails></li>)}</ol> : <p className="planning-empty">Nenhuma revisão registrada.</p>}</section>
  </section>;
}
