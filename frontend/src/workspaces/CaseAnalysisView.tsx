import { FormEvent, useEffect, useState } from "react";

import { addCaseAnalysisItem, CaseAnalysisApiError, getCaseAnalysis, reviewCaseAnalysisItem, startCaseAnalysis, type AnalysisItem, type CaseAnalysisEnvelope } from "../data/caseAnalysis";

type State = { kind: "loading" } | { kind: "ready"; value: CaseAnalysisEnvelope } | { kind: "empty" } | { kind: "error" };

function ItemList({ items, staleDocumentIds }: { items: AnalysisItem[]; staleDocumentIds: string[] }) {
  if (items.length === 0) return <p className="analysis-empty">Nenhum item identificado nesta revisão.</p>;
  const stale = new Set(staleDocumentIds);
  return <ul className="analysis-list">{items.map((item) => <li key={item.item_id}><p>{item.text}</p>{item.provenance.some((source) => stale.has(source.source_document_id)) && <span className="analysis-stale">Fonte alterada — revisão necessária</span>}<details><summary>Ver proveniência</summary><ul>{item.provenance.map((source) => <li key={source.occurrence_id}>{source.source_document_id} · {source.page_or_span} · ocorrência {source.occurrence_id} · SHA {source.source_document_sha256} · revisão {source.source_revision}</li>)}</ul></details></li>)}</ul>;
}

export function CaseAnalysisView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [requestVersion, setRequestVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [itemKind, setItemKind] = useState("CLAIM");
  const [itemText, setItemText] = useState("");
  const [sourceDocumentId, setSourceDocumentId] = useState("");
  const [locator, setLocator] = useState("");
  const [subjects, setSubjects] = useState("");
  const [relationA, setRelationA] = useState("");
  const [relationB, setRelationB] = useState("");
  const [conflictDimension, setConflictDimension] = useState("");
  const [reviewTarget, setReviewTarget] = useState("");
  const [reviewAction, setReviewAction] = useState<"CONFIRM" | "CORRECT" | "REJECT">("CONFIRM");
  const [correction, setCorrection] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    getCaseAnalysis(workspaceId, controller.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof CaseAnalysisApiError && error.kind === "not-found" ? "empty" : "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId, requestVersion]);
  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Carregando análise</h2><p>Reabrindo o mapa processual e conferindo suas fontes.</p></div></section>;
  if (state.kind === "empty") return <section className="status-state"><span className="state-mark" aria-hidden="true">○</span><div><h2>Análise ainda não disponível</h2><p>Inicie um índice dos documentos armazenados. Nenhum fato ou conclusão será inferido.</p>{saveError && <p role="alert">Importe ao menos um documento antes de iniciar.</p>}<button className="primary-action" type="button" disabled={saving} onClick={async () => { setSaving(true); setSaveError(false); try { setState({ kind: "ready", value: await startCaseAnalysis(workspaceId) }); } catch { setSaveError(true); } finally { setSaving(false); } }}>{saving ? "Criando índice…" : "Iniciar análise"}</button></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível carregar a análise</h2><p>Verifique o serviço local e tente novamente.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setRequestVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  const snapshot = state.value.snapshot;
  const coverageLabel = snapshot.coverage.status === "COMPLETE" ? "Cobertura completa" : snapshot.coverage.status === "PARTIAL" ? "Cobertura parcial" : "Fontes indisponíveis";
  const sections: [string, AnalysisItem[]][] = [["Linha do tempo", snapshot.events], ["Alegações", snapshot.claims], ["Contrapontos", snapshot.counterarguments], ["Decisões", snapshot.decisions], ["Objeto pericial", snapshot.pericial_objects], ["Quesitos", snapshot.questions], ["Documentos técnicos", snapshot.technical_document_references], ["Lacunas", snapshot.gaps], ["Conflitos propostos", snapshot.conflicts]];
  const entities = new Map(snapshot.judicial_context.entities.map((entity) => [entity.entity_id, entity]));
  const participants = new Map(snapshot.judicial_context.participants.map((participant) => [participant.participant_id, participant]));
  const staleSources = new Set(snapshot.stale_document_ids);
  const allItems = sections.flatMap(([, items]) => items);
  const submitItem = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setSaveError(false);
    try {
      const values: Record<string, unknown> = itemKind === "COUNTERARGUMENT" ? { target_claim_ids: [relationA] } : itemKind === "JUDICIAL_DECISION" ? { addressed_claim_ids: relationA ? [relationA] : [], addressed_counterargument_ids: relationB ? [relationB] : [] } : itemKind === "PROPOSED_CONFLICT" ? { statement_a_id: relationA, statement_b_id: relationB, conflict_dimension: conflictDimension } : {};
      const value = await addCaseAnalysisItem(workspaceId, { expected_revision: state.value.revision, item_kind: itemKind, text: itemText, source_document_id: sourceDocumentId, page_or_span: locator, technical_subjects: subjects.split(",").map((item) => item.trim()).filter(Boolean), values });
      setState({ kind: "ready", value }); setItemText(""); setLocator(""); setSubjects("");
    } catch { setSaveError(true); } finally { setSaving(false); }
  };
  const submitReview = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setSaveError(false);
    try {
      const value = await reviewCaseAnalysisItem(workspaceId, { expected_revision: state.value.revision, target_item_id: reviewTarget, action: reviewAction, corrected_value: reviewAction === "CORRECT" ? correction : null, reviewer, reason });
      setState({ kind: "ready", value }); setCorrection(""); setReason("");
    } catch { setSaveError(true); } finally { setSaving(false); }
  };
  const contextProvenance = snapshot.judicial_context.provenance;
  const judicialContextProvenance = [
    ...contextProvenance,
    ...snapshot.judicial_context.entities.flatMap((entity) => entity.provenance),
    ...snapshot.judicial_context.participants.flatMap((participant) => participant.provenance),
    ...snapshot.judicial_context.representation_links.flatMap((link) => link.provenance),
    ...snapshot.judicial_context.access_relations.flatMap((relation) => relation.provenance),
  ];
  const judicialContextStale = judicialContextProvenance.some((source) => staleSources.has(source.source_document_id));
  return <section className="analysis-workspace" aria-labelledby="analysis-map-title">
    <header className="analysis-overview"><div><h2 id="analysis-map-title">Mapa do processo</h2><p>Leitura estruturada das fontes documentais. Não contém conclusão pericial.</p></div><div className={`coverage coverage--${snapshot.coverage.status.toLowerCase()}`}><strong>{coverageLabel}</strong><span>{snapshot.coverage.documents_analyzed} de {snapshot.coverage.documents_total} documentos analisados</span></div></header>
    {snapshot.source_inventory_stale && <p className="analysis-inventory-warning" role="status">{snapshot.unindexed_source_count} fonte nova ainda não foi incorporada à análise.</p>}
    {judicialContextStale && <p className="analysis-inventory-warning" role="status">Fonte alterada — contexto judicial requer revisão</p>}
    <section className="analysis-section"><h3>Documentos</h3><ol className="document-index">{snapshot.documents.map((document) => <li key={String(document.document_id)}><span>{String(document.sequence).padStart(2, "0")}</span><div><strong>{String(document.raw_type)}</strong><small>{String(document.document_id)} · {String(document.page_count_or_span)}</small></div></li>)}</ol></section>
    <section className="analysis-section"><h3>Adicionar item estruturado</h3><p>O texto permanece vinculado ao documento e ao trecho informados.</p><form onSubmit={submitItem}><label>Tipo<select value={itemKind} onChange={(event) => { setItemKind(event.target.value); setRelationA(""); setRelationB(""); }} disabled={saving}><option value="CLAIM">Alegação</option><option value="COUNTERARGUMENT">Contraponto</option><option value="JUDICIAL_DECISION">Decisão judicial</option><option value="PERICIAL_OBJECT">Objeto pericial</option><option value="PERICIAL_QUESTION">Quesito</option><option value="PROCEDURAL_EVENT">Evento processual</option><option value="TECHNICAL_DOCUMENT_REFERENCE">Documento técnico</option><option value="EVIDENCE_GAP">Lacuna</option><option value="PROPOSED_CONFLICT">Conflito proposto</option></select></label><label>Documento<select value={sourceDocumentId} onChange={(event) => setSourceDocumentId(event.target.value)} required disabled={saving}><option value="">Selecione</option>{snapshot.documents.map((document) => <option key={String(document.document_id)} value={String(document.document_id)}>{String(document.document_id)} · {String(document.raw_type)}</option>)}</select></label><label>Página ou trecho<input value={locator} onChange={(event) => setLocator(event.target.value)} required disabled={saving}/></label><label>Texto identificado<textarea value={itemText} onChange={(event) => setItemText(event.target.value)} required disabled={saving}/></label><label>Assuntos técnicos, separados por vírgula<input value={subjects} onChange={(event) => setSubjects(event.target.value)} disabled={saving}/></label>{["COUNTERARGUMENT", "JUDICIAL_DECISION", "PROPOSED_CONFLICT"].includes(itemKind) && <label>{itemKind === "PROPOSED_CONFLICT" ? "Primeiro item relacionado" : "Alegação relacionada"}<select value={relationA} onChange={(event) => setRelationA(event.target.value)} required disabled={saving}><option value="">Selecione</option>{allItems.map((item) => <option key={item.item_id} value={item.item_id}>{item.text}</option>)}</select></label>}{["JUDICIAL_DECISION", "PROPOSED_CONFLICT"].includes(itemKind) && <label>{itemKind === "PROPOSED_CONFLICT" ? "Segundo item relacionado" : "Contraponto relacionado (opcional)"}<select value={relationB} onChange={(event) => setRelationB(event.target.value)} required={itemKind === "PROPOSED_CONFLICT"} disabled={saving}><option value="">Selecione</option>{allItems.map((item) => <option key={item.item_id} value={item.item_id}>{item.text}</option>)}</select></label>}{itemKind === "PROPOSED_CONFLICT" && <label>Dimensão do conflito<input value={conflictDimension} onChange={(event) => setConflictDimension(event.target.value)} required disabled={saving}/></label>}{saveError && <p role="alert">Não foi possível salvar. Confira a fonte e reabra a análise.</p>}<button className="primary-action" type="submit" disabled={saving || snapshot.source_inventory_stale}>{saving ? "Salvando…" : "Adicionar à análise"}</button></form></section>
    <section className="analysis-section"><h3>Participantes</h3><ul className="participant-index">{snapshot.participant_refs.map((participantId) => { const participant = participants.get(participantId); const entity = participant && entities.get(participant.entity_id); const stale = [...contextProvenance, ...(participant?.provenance ?? []), ...(entity?.provenance ?? [])].some((source) => staleSources.has(source.source_document_id)); return <li key={participantId}><strong>{entity?.raw_name ?? participantId}</strong><span>{participant?.role.raw_label ?? "Papel não disponível"} · {participant?.pole ?? "Polo não disponível"}</span>{stale && <span className="analysis-stale">Fonte alterada — identidade judicial requer revisão</span>}</li>; })}</ul></section>
    <section className="analysis-section"><h3>Representação</h3>{snapshot.judicial_context.representation_links.length ? <ul className="relation-index">{snapshot.judicial_context.representation_links.map((link) => { const representative = entities.get(link.representative_entity_id); const represented = link.represented_participant_ids.map((participantId) => participants.get(participantId)); const provenance = [...contextProvenance, ...link.provenance, ...(representative?.provenance ?? []), ...represented.flatMap((participant) => [...(participant?.provenance ?? []), ...(participant ? entities.get(participant.entity_id)?.provenance ?? [] : [])])]; const stale = provenance.some((source) => staleSources.has(source.source_document_id)); return <li key={link.link_id}><strong>{representative?.raw_name ?? link.representative_entity_id}</strong><span>representa {link.represented_participant_ids.map((participantId) => { const participant = participants.get(participantId); return participant ? entities.get(participant.entity_id)?.raw_name ?? participantId : participantId; }).join(", ")} · {link.representation_role_raw}</span>{stale && <span className="analysis-stale">Fonte alterada — representação requer revisão</span>}</li>; })}</ul> : <p className="analysis-empty">Nenhuma relação de representação identificada.</p>}</section>
    {sections.map(([title, items]) => <section className="analysis-section" key={title}><h3>{title}</h3><ItemList items={items} staleDocumentIds={snapshot.stale_document_ids}/></section>)}
    <section className="analysis-section"><h3>Revisão humana</h3>{snapshot.human_reviews.length ? <p>{snapshot.human_reviews.length} decisão de revisão preservada nesta análise.</p> : <p>Nenhuma revisão humana registrada.</p>}{allItems.length > 0 && <form onSubmit={submitReview}><label>Item<select value={reviewTarget} onChange={(event) => setReviewTarget(event.target.value)} required disabled={saving}><option value="">Selecione</option>{allItems.map((item) => <option key={item.item_id} value={item.item_id}>{item.text}</option>)}</select></label><label>Ação<select value={reviewAction} onChange={(event) => setReviewAction(event.target.value as typeof reviewAction)} disabled={saving}><option value="CONFIRM">Confirmar</option><option value="CORRECT">Corrigir</option><option value="REJECT">Rejeitar</option></select></label>{reviewAction === "CORRECT" && <label>Valor corrigido<textarea value={correction} onChange={(event) => setCorrection(event.target.value)} required disabled={saving}/></label>}<label>Identificação do revisor<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} required disabled={saving}/></label><label>Motivo<input value={reason} onChange={(event) => setReason(event.target.value)} required disabled={saving}/></label><button className="primary-action" type="submit" disabled={saving || snapshot.source_inventory_stale}>{saving ? "Registrando…" : "Registrar revisão"}</button></form>}</section>
  </section>;
}
