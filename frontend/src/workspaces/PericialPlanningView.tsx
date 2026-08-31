import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { getPericialPlanning, PericialPlanningApiError, PLANNING_COLLECTIONS, reviewPericialPlanning, type PlanningEnvelope, type PlanningItem, type ReviewAction } from "../data/pericialPlanning";

type State = { kind: "loading" } | { kind: "ready"; value: PlanningEnvelope } | { kind: "empty" } | { kind: "error" };

const statusLabel = { PENDING: "Aguardando revisão", APPROVED: "Aprovado pelo profissional", REJECTED: "Rejeitado pelo profissional", MODIFIED: "Modificado pelo profissional", DEFERRED: "Decisão adiada" } as const;

function PlanningCard({ item, method = false, onReview }: { item: PlanningItem; method?: boolean; onReview: (item: PlanningItem, trigger: HTMLButtonElement) => void }) {
  const typedLinks = [
    ["Quesitos", item.derivation.question_ids],
    ["Objetos periciais", item.derivation.pericial_object_ids],
    ["Decisões judiciais", item.derivation.court_decision_ids],
    ["Referências técnicas", item.derivation.technical_document_reference_ids],
    ["Lacunas e conflitos", item.derivation.gap_or_conflict_ids],
  ] as const;
  return <li className="planning-card"><div className="planning-card__heading"><div><strong>{item.title}</strong><span>{method && item.professional_review_status === "PENDING" ? "Método proposto — não aprovado" : statusLabel[item.professional_review_status]}</span></div><button className="text-action" type="button" onClick={(event) => onReview(item, event.currentTarget)}>Revisar {item.title}</button></div><p>{item.description}</p><details><summary>Por que este item existe?</summary><p>{item.derivation.rationale}</p><p>Itens da análise: {item.derivation.case_analysis_item_ids.join(", ")}</p>{typedLinks.filter(([, ids]) => ids.length).map(([label, ids]) => <p key={label}>{label}: {ids.join(", ")}</p>)}<ul>{item.derivation.source_provenance.map((source) => <li key={source.occurrence_id}>{source.source_document_id} · {source.page_or_span} · {source.occurrence_id} · SHA {source.source_document_sha256}</li>)}</ul></details></li>;
}

function PlanningGroup({ title, items, methodItemIds, onReview }: { title: string; items: PlanningItem[]; methodItemIds?: ReadonlySet<string>; onReview: (item: PlanningItem, trigger: HTMLButtonElement) => void }) {
  return <section className="planning-section"><h3>{title}</h3>{items.length ? <ul className="planning-list">{items.map((item) => <PlanningCard key={item.item_id} item={item} method={methodItemIds?.has(item.item_id)} onReview={onReview}/>)}</ul> : <p className="planning-empty">Nenhuma proposta nesta categoria.</p>}</section>;
}

export function PericialPlanningView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [requestVersion, setRequestVersion] = useState(0);
  const [selected, setSelected] = useState<PlanningItem | null>(null);
  const [action, setAction] = useState<ReviewAction>("APPROVE");
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [modified, setModified] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const reviewTrigger = useRef<HTMLButtonElement | null>(null);
  const restoreReviewFocus = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    getPericialPlanning(workspaceId, controller.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof PericialPlanningApiError && error.kind === "not-found" ? "empty" : "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId, requestVersion]);
  useEffect(() => {
    if (selected === null && restoreReviewFocus.current) {
      reviewTrigger.current?.focus();
      restoreReviewFocus.current = false;
    }
  }, [selected]);
  const allItems = useMemo(() => state.kind === "ready" ? PLANNING_COLLECTIONS.flatMap((name) => state.value.snapshot[name]) : [], [state]);
  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Carregando planejamento</h2><p>Reabrindo propostas, decisões e dependências.</p></div></section>;
  if (state.kind === "empty") return <section className="status-state"><span className="state-mark" aria-hidden="true">○</span><div><h2>Planejamento ainda não disponível</h2><p>A análise do caso ainda não possui uma proposta de planejamento salva.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível carregar o planejamento</h2><p>Verifique o serviço local e tente novamente.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setRequestVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  const { snapshot } = state.value;
  const readinessLabel = snapshot.coverage.readiness === "READY" ? "Planejamento pronto" : snapshot.coverage.readiness === "BLOCKED" ? "Planejamento bloqueado" : "Planejamento parcial";
  const methodItemIds = new Set(snapshot.method_candidates.map((item) => item.item_id));
  const groups: [string, PlanningItem[], ReadonlySet<string>?][] = [
    ["Objeto e questões", [...snapshot.objectives, ...snapshot.issues, ...snapshot.question_links]],
    ["Documentos e informações", [...snapshot.required_documents, ...snapshot.required_information]],
    ["Vistoria", snapshot.inspection_requirements],
    ["Medições e fotografias", [...snapshot.measurement_requirements, ...snapshot.photo_requirements]],
    ["Equipamentos e métodos", [...snapshot.equipment_requirements, ...snapshot.method_candidates, ...snapshot.procedure_candidates, ...snapshot.sampling_candidates], methodItemIds],
    ["Acesso, apoio e segurança", [...snapshot.access_requirements, ...snapshot.external_support_requirements, ...snapshot.safety_requirements]],
    ["Lacunas e riscos", [...snapshot.gaps, ...snapshot.risks]],
  ];
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    setSaving(true); setSaveError(false);
    try {
      const value = await reviewPericialPlanning(workspaceId, { expected_revision: state.value.revision, target_item_id: selected.item_id, action, reviewer, reason, decided_value: action === "MODIFY" ? modified : null });
      setState({ kind: "ready", value }); restoreReviewFocus.current = true; setSelected(null); setReviewer(""); setReason(""); setModified("");
    } catch { setSaveError(true); }
    finally { setSaving(false); }
  };
  return <section className="planning-workspace" aria-labelledby="planning-title">
    <header className="planning-overview"><div><h2 id="planning-title">Plano da perícia</h2><p>Propostas para preparar e executar a futura diligência. Nenhum item substitui decisão profissional.</p></div><div className={`planning-readiness planning-readiness--${snapshot.coverage.readiness.toLowerCase()}`}><strong>{readinessLabel}</strong><span>{snapshot.coverage.reviewed_items} de {snapshot.coverage.material_items_total} itens revisados</span></div></header>
    {snapshot.coverage.readiness_reasons.length > 0 && <ul className="planning-reasons">{snapshot.coverage.readiness_reasons.map((item) => <li key={item}>{item}</li>)}</ul>}
    {snapshot.upstream_stale && <section className="analysis-inventory-warning" role="alert"><strong>Análise alterada — planejamento requer revisão</strong><ul>{snapshot.upstream_stale_reasons.map((item) => <li key={item}>{item}</li>)}</ul></section>}
    {groups.map(([title, items, methodIds]) => <PlanningGroup key={title} title={title} items={items} methodItemIds={methodIds} onReview={(item, trigger) => { reviewTrigger.current = trigger; setSelected(item); setAction("APPROVE"); setSaveError(false); }}/>) }
    <section className="planning-section"><h3>Decisões profissionais</h3>{snapshot.decisions.length ? <ol className="planning-decisions">{snapshot.decisions.map((decision) => <li key={decision.decision_id}><strong>{decision.action}</strong><span>{allItems.find((item) => item.item_id === decision.target_item_id)?.title ?? decision.target_item_id} · {decision.reviewer}</span><p>{decision.reason}</p>{decision.decided_value && <p>Valor decidido: {decision.decided_value}</p>}</li>)}</ol> : <p className="planning-empty">Nenhuma decisão profissional registrada.</p>}</section>
    {selected && <section className="planning-review" aria-labelledby="planning-review-title" aria-live="polite"><h3 id="planning-review-title">Revisar {selected.title}</h3><p>A proposta original será preservada no histórico.</p><form onSubmit={submit}><label>Decisão profissional<select value={action} onChange={(event) => setAction(event.target.value as ReviewAction)} disabled={saving || snapshot.upstream_stale}><option value="APPROVE">Aprovar</option><option value="REJECT">Rejeitar</option><option value="MODIFY">Modificar</option><option value="DEFER">Adiar</option></select></label><label>Identificação do perito<input autoFocus value={reviewer} onChange={(event) => setReviewer(event.target.value)} required disabled={saving || snapshot.upstream_stale}/></label><label>Motivo da decisão<textarea value={reason} onChange={(event) => setReason(event.target.value)} required disabled={saving || snapshot.upstream_stale}/></label>{action === "MODIFY" && <label>Texto modificado<textarea value={modified} onChange={(event) => setModified(event.target.value)} required disabled={saving || snapshot.upstream_stale}/></label>}{saveError && <p role="alert">Não foi possível registrar a decisão. Reabra o plano e tente novamente.</p>}<div className="planning-review__actions"><button className="primary-action" type="submit" disabled={saving || snapshot.upstream_stale}>{saving ? "Registrando…" : "Registrar decisão"}</button><button className="text-action" type="button" onClick={() => { restoreReviewFocus.current = true; setSelected(null); }} disabled={saving}>Cancelar</button></div></form></section>}
  </section>;
}
