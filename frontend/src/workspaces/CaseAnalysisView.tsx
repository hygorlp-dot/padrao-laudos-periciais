import { useEffect, useState } from "react";

import { CaseAnalysisApiError, getCaseAnalysis, type AnalysisItem, type CaseAnalysisEnvelope } from "../data/caseAnalysis";

type State = { kind: "loading" } | { kind: "ready"; value: CaseAnalysisEnvelope } | { kind: "empty" } | { kind: "error" };

function ItemList({ items, staleDocumentIds }: { items: AnalysisItem[]; staleDocumentIds: string[] }) {
  if (items.length === 0) return <p className="analysis-empty">Nenhum item identificado nesta revisão.</p>;
  const stale = new Set(staleDocumentIds);
  return <ul className="analysis-list">{items.map((item) => <li key={item.item_id}><p>{item.text}</p>{item.provenance.some((source) => stale.has(source.source_document_id)) && <span className="analysis-stale">Fonte alterada — revisão necessária</span>}<details><summary>Ver proveniência</summary><ul>{item.provenance.map((source) => <li key={source.occurrence_id}>{source.source_document_id} · {source.page_or_span} · ocorrência {source.occurrence_id} · SHA {source.source_document_sha256} · revisão {source.source_revision}</li>)}</ul></details></li>)}</ul>;
}

export function CaseAnalysisView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [requestVersion, setRequestVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getCaseAnalysis(workspaceId, controller.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof CaseAnalysisApiError && error.kind === "not-found" ? "empty" : "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId, requestVersion]);
  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Carregando análise</h2><p>Reabrindo o mapa processual e conferindo suas fontes.</p></div></section>;
  if (state.kind === "empty") return <section className="status-state"><span className="state-mark" aria-hidden="true">○</span><div><h2>Análise ainda não disponível</h2><p>Os documentos armazenados ainda não possuem um mapa processual salvo.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível carregar a análise</h2><p>Verifique o serviço local e tente novamente.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setRequestVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  const snapshot = state.value.snapshot;
  const coverageLabel = snapshot.coverage.status === "COMPLETE" ? "Cobertura completa" : snapshot.coverage.status === "PARTIAL" ? "Cobertura parcial" : "Fontes indisponíveis";
  const sections: [string, AnalysisItem[]][] = [["Linha do tempo", snapshot.events], ["Alegações", snapshot.claims], ["Contrapontos", snapshot.counterarguments], ["Decisões", snapshot.decisions], ["Objeto pericial", snapshot.pericial_objects], ["Quesitos", snapshot.questions], ["Documentos técnicos", snapshot.technical_document_references], ["Lacunas", snapshot.gaps], ["Conflitos propostos", snapshot.conflicts]];
  const entities = new Map(snapshot.judicial_context.entities.map((entity) => [entity.entity_id, entity]));
  const participants = new Map(snapshot.judicial_context.participants.map((participant) => [participant.participant_id, participant]));
  return <section className="analysis-workspace" aria-labelledby="analysis-map-title">
    <header className="analysis-overview"><div><h2 id="analysis-map-title">Mapa do processo</h2><p>Leitura estruturada das fontes documentais. Não contém conclusão pericial.</p></div><div className={`coverage coverage--${snapshot.coverage.status.toLowerCase()}`}><strong>{coverageLabel}</strong><span>{snapshot.coverage.documents_analyzed} de {snapshot.coverage.documents_total} documentos analisados</span></div></header>
    <section className="analysis-section"><h3>Documentos</h3><ol className="document-index">{snapshot.documents.map((document) => <li key={String(document.document_id)}><span>{String(document.sequence).padStart(2, "0")}</span><div><strong>{String(document.raw_type)}</strong><small>{String(document.document_id)} · {String(document.page_count_or_span)}</small></div></li>)}</ol></section>
    <section className="analysis-section"><h3>Participantes</h3><ul className="participant-index">{snapshot.participant_refs.map((participantId) => { const participant = participants.get(participantId); const entity = participant && entities.get(participant.entity_id); return <li key={participantId}><strong>{entity?.raw_name ?? participantId}</strong><span>{participant?.role.raw_label ?? "Papel não disponível"} · {participant?.pole ?? "Polo não disponível"}</span></li>; })}</ul></section>
    <section className="analysis-section"><h3>Representação</h3>{snapshot.judicial_context.representation_links.length ? <ul className="relation-index">{snapshot.judicial_context.representation_links.map((link) => <li key={link.link_id}><strong>{entities.get(link.representative_entity_id)?.raw_name ?? link.representative_entity_id}</strong><span>representa {link.represented_participant_ids.map((participantId) => { const participant = participants.get(participantId); return participant ? entities.get(participant.entity_id)?.raw_name ?? participantId : participantId; }).join(", ")} · {link.representation_role_raw}</span></li>)}</ul> : <p className="analysis-empty">Nenhuma relação de representação identificada.</p>}</section>
    {sections.map(([title, items]) => <section className="analysis-section" key={title}><h3>{title}</h3><ItemList items={items} staleDocumentIds={snapshot.stale_document_ids}/></section>)}
    <section className="analysis-section"><h3>Revisão humana</h3>{snapshot.human_reviews.length ? <p>{snapshot.human_reviews.length} decisão de revisão preservada nesta análise.</p> : <p>Nenhuma revisão humana registrada.</p>}</section>
  </section>;
}
