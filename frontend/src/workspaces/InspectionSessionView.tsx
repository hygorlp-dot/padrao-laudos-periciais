import { useEffect, useState } from "react";

import { getInspectionSession, InspectionSessionApiError, type InspectionEnvelope } from "../data/inspectionSession";

type State = { kind: "loading" } | { kind: "ready"; value: InspectionEnvelope } | { kind: "empty" } | { kind: "error" };
const stateLabel = { PENDING: "Pendente", COMPLETED: "Concluído", PARTIAL: "Execução parcial", NOT_EXECUTED: "Não executado", NOT_APPLICABLE: "Não aplicável", BLOCKED: "Bloqueado" } as const;

export function InspectionSessionView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getInspectionSession(workspaceId, controller.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof InspectionSessionApiError && error.kind === "not-found" ? "empty" : "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId, version]);
  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Carregando vistoria</h2><p>Reabrindo registros de campo e suas proveniências.</p></div></section>;
  if (state.kind === "empty") return <section className="status-state"><span className="state-mark" aria-hidden="true">○</span><div><h2>Vistoria ainda não registrada</h2><p>Nenhuma sessão de campo vinculada ao planejamento aprovado foi salva.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível carregar a vistoria</h2><p>Verifique o serviço local e tente novamente.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  const { snapshot } = state.value;
  return <section className="inspection-workspace" aria-labelledby="inspection-title">
    <header className="planning-overview"><div><h2 id="inspection-title">Vistoria de campo</h2><p>Registros brutos executados contra a revisão {snapshot.plan_snapshot.planning_revision} do plano. Evidências candidatas não são constatações técnicas.</p></div><div className="planning-readiness"><strong>{snapshot.coverage.complete ? "Execução coberta" : "Execução parcial"}</strong><span>{snapshot.coverage.completed_items} de {snapshot.coverage.total_items} itens concluídos</span></div></header>
    {snapshot.upstream_stale && <section className="analysis-inventory-warning" role="alert"><strong>Planejamento alterado — não continue esta sessão</strong><ul>{snapshot.upstream_stale_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></section>}
    {snapshot.coverage.reasons.length > 0 && <ul className="planning-reasons">{snapshot.coverage.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
    <section className="planning-section"><h3>Itens executados</h3><ol className="inspection-items">{snapshot.items.map((item) => {
      const observations = snapshot.observations.filter((record) => record.inspection_item_id === item.item_id);
      const statements = snapshot.statements.filter((record) => record.inspection_item_id === item.item_id);
      const measurements = snapshot.measurements.filter((record) => record.inspection_item_id === item.item_id);
      const photos = snapshot.photos.filter((record) => record.inspection_item_id === item.item_id);
      const limitations = snapshot.limitations.filter((record) => record.inspection_item_id === item.item_id);
      const candidates = snapshot.evidence_candidates.filter((record) => record.inspection_item_id === item.item_id);
      return <li className="inspection-item" key={item.item_id}><header><div><strong>{item.title}</strong><span>{stateLabel[item.state]}</span></div><code>{item.planning_item_id}</code></header>{item.note && <p>{item.note}</p>}
        {observations.length > 0 && <div><h4>Observações brutas</h4><ul>{observations.map((record) => <li key={record.observation_id}><strong>{record.observation_type}</strong> · {record.raw_observation}<small>{record.location_id} · {record.timestamp} · {record.provenance}</small></li>)}</ul></div>}
        {statements.length > 0 && <div><h4>Declarações em campo</h4><ul>{statements.map((record) => <li key={record.statement_id}><strong>Declaração da parte — não é observação pericial</strong><p>{record.verbatim_or_summary}</p><small>{record.speaker} · {record.declared_role} · {record.provenance}</small></li>)}</ul></div>}
        {measurements.length > 0 && <div><h4>Medições</h4><ul>{measurements.map((record) => <li key={record.measurement_id}><strong>{record.raw_value} {record.raw_unit}</strong>{record.normalized_value && <span> · normalizado: {record.normalized_value} {record.normalized_unit}</span>}<small>{record.quantity} · {record.instrument_id} · {record.method_id} · {record.uncertainty ?? "incerteza não informada"} · {record.provenance}</small></li>)}</ul></div>}
        {photos.length > 0 && <div><h4>Fotografias</h4><ul>{photos.map((record) => <li key={record.photo_id}><strong>{record.caption}</strong><small>Original privado · SHA-256 {record.original_sha256} · {record.private_content_id} · {record.device}</small></li>)}</ul></div>}
        {limitations.length > 0 && <div className="inspection-limitations"><h4>Limitações</h4><ul>{limitations.map((record) => <li key={record.limitation_id}><strong>{record.kind}</strong><p>{record.description}</p><small>{record.consequence_for_coverage}</small></li>)}</ul></div>}
        {candidates.length > 0 && <div><h4>Evidências candidatas</h4><ul>{candidates.map((record) => <li key={record.candidate_id}><strong>Candidato a análise técnica futura — não é achado</strong><p>{record.description}</p><small>{record.source_record_ids.join(" · ")} · {record.provenance}</small></li>)}</ul></div>}
      </li>;
    })}</ol></section>
  </section>;
}
