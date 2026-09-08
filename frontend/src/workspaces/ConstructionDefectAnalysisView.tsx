import { type FormEvent, useEffect, useMemo, useState } from "react";

import { getCaseAnalysis, type CaseAnalysisEnvelope } from "../data/caseAnalysis";
import {
  ConstructionDefectAnalysisApiError,
  effectivePathologyReview,
  getConstructionDefectAnalysis,
  reviewPathology,
  startConstructionDefectAnalysis,
  type ConstructionDefectAnalysisEnvelope,
  type ObservationOutcome,
} from "../data/constructionDefectAnalysis";
import { getInspectionSession, type InspectionEnvelope } from "../data/inspectionSession";

type ReadyState = {
  kind: "ready";
  analysis: ConstructionDefectAnalysisEnvelope | null;
  inspection: InspectionEnvelope;
  caseAnalysis: CaseAnalysisEnvelope;
};
type State = { kind: "loading" } | { kind: "error" } | ReadyState;

function toggle(items: string[], value: string, checked: boolean) {
  return checked ? [...items, value] : items.filter((item) => item !== value);
}

export function ConstructionDefectAnalysisView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [operationError, setOperationError] = useState(false);
  const [observationId, setObservationId] = useState("");
  const [methodId, setMethodId] = useState("");
  const [outcome, setOutcome] = useState<ObservationOutcome>("INCONCLUSIVE");
  const [system, setSystem] = useState("");
  const [element, setElement] = useState("");
  const [measurementIds, setMeasurementIds] = useState<string[]>([]);
  const [photoIds, setPhotoIds] = useState<string[]>([]);
  const [claimId, setClaimId] = useState("");
  const [questionId, setQuestionId] = useState("");
  const [reviewPatId, setReviewPatId] = useState("");
  const [reviewAction, setReviewAction] = useState<"APPROVE" | "REJECT">("REJECT");
  const [reviewReason, setReviewReason] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getConstructionDefectAnalysis(workspaceId, controller.signal).catch((error) => {
        if (error instanceof ConstructionDefectAnalysisApiError && error.kind === "not-found") return null;
        throw error;
      }),
      getInspectionSession(workspaceId, controller.signal),
      getCaseAnalysis(workspaceId, controller.signal),
    ]).then(
      ([analysis, inspection, caseAnalysis]) => {
        if (controller.signal.aborted) return;
        setState({ kind: "ready", analysis, inspection, caseAnalysis });
        if (analysis?.snapshot.analysis_final.patologias[0]) {
          setReviewPatId(analysis.snapshot.analysis_final.patologias[0].id);
        }
      },
      () => {
        if (!controller.signal.aborted) setState({ kind: "error" });
      },
    );
    return () => controller.abort();
  }, [workspaceId]);

  const selectedObservation = state.kind === "ready"
    ? state.inspection.snapshot.observations.find((item) => item.observation_id === observationId)
    : undefined;
  const selectedItemId = selectedObservation?.inspection_item_id;
  const availableMeasurements = state.kind === "ready"
    ? state.inspection.snapshot.measurements.filter((item) => item.inspection_item_id === selectedItemId)
    : [];
  const availablePhotos = state.kind === "ready"
    ? state.inspection.snapshot.photos.filter((item) => item.inspection_item_id === selectedItemId)
    : [];
  const methodOptions = useMemo(() => {
    if (state.kind !== "ready") return [];
    return state.inspection.snapshot.methods.filter(
      (item): item is { method_id: string; name?: string } =>
        typeof item === "object" && item !== null && "method_id" in item && typeof item.method_id === "string",
    );
  }, [state]);

  const run = async (operation: () => Promise<ConstructionDefectAnalysisEnvelope>) => {
    setBusy(true);
    setOperationError(false);
    try {
      const analysis = await operation();
      setState((current) => current.kind === "ready" ? { ...current, analysis } : current);
      if (analysis.snapshot.analysis_final.patologias[0]) setReviewPatId(analysis.snapshot.analysis_final.patologias[0].id);
    } catch {
      setOperationError(true);
    } finally {
      setBusy(false);
    }
  };

  const start = (event: FormEvent) => {
    event.preventDefault();
    if (!selectedObservation || !methodId) {
      setOperationError(true);
      return;
    }
    void run(() => startConstructionDefectAnalysis(workspaceId, [{
      observation_id: selectedObservation.observation_id,
      manifestation: selectedObservation.raw_observation,
      system: system.trim() || null,
      element: element.trim() || null,
      outcome,
      methods: [methodId],
      measurement_ids: measurementIds,
      photo_ids: photoIds,
      claim_ids: claimId ? [claimId] : [],
      question_ids: questionId ? [questionId] : [],
    }]));
  };

  const review = (event: FormEvent) => {
    event.preventDefault();
    if (state.kind !== "ready" || !state.analysis || !reviewPatId || !reviewReason.trim()) {
      setOperationError(true);
      return;
    }
    void run(() => reviewPathology(workspaceId, state.analysis!, {
      pat_id: reviewPatId,
      action: reviewAction,
      professional_id: state.inspection.snapshot.responsible_professional,
      reason: reviewReason.trim(),
    }));
  };

  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Carregando análise técnica</h2><p>Reconciliando vistoria, fontes e histórico profissional.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível carregar a análise</h2><p>As autoridades locais necessárias não estão disponíveis ou não passaram pela validação canônica.</p></div></section>;

  const snapshot = state.analysis?.snapshot;
  const blocked = busy || snapshot?.upstream_stale || snapshot?.gate === "BLOQUEADO_PARA_REDACAO";
  return <section className="pathology-workbench" aria-labelledby="pathology-title">
    <header className="planning-overview"><div><h2 id="pathology-title">Análise de manifestações construtivas</h2><p>Vistoria vinculada → proposta PAT → revisão profissional explícita. Alegação, evidência e conclusão permanecem distintas.</p></div><div className="planning-readiness"><strong>{snapshot ? snapshot.gate.replaceAll("_", " ") : "Ainda não iniciada"}</strong><span>{snapshot ? `revisão ${state.analysis?.revision}` : "selecione os vínculos observados"}</span></div></header>
    {snapshot?.upstream_stale && <section className="analysis-inventory-warning" role="alert"><strong>Autoridade anterior alterada — análise bloqueada</strong><ul>{snapshot.upstream_stale_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></section>}

    {!snapshot && <section className="technical-authority"><h3>Gerar proposta PAT</h3><p>Escolha somente registros do mesmo item de vistoria. Nenhuma patologia será aprovada automaticamente.</p><form onSubmit={start}>
      <label>Observação direta<select value={observationId} onChange={(event) => { setObservationId(event.target.value); setMeasurementIds([]); setPhotoIds([]); }}><option value="">Selecione</option>{state.inspection.snapshot.observations.map((item) => <option key={item.observation_id} value={item.observation_id}>{item.observation_id} — {item.raw_observation}</option>)}</select></label>
      <label>Resultado observado<select value={outcome} onChange={(event) => setOutcome(event.target.value as ObservationOutcome)}><option value="INCONCLUSIVE">Inconclusivo</option><option value="OBSERVED">Observado</option><option value="NOT_OBSERVED">Não observado</option><option value="CONFORMING">Conforme</option></select></label>
      <label>Método registrado<select value={methodId} onChange={(event) => setMethodId(event.target.value)}><option value="">Selecione</option>{methodOptions.map((item) => <option key={item.method_id} value={item.method_id}>{item.method_id}{item.name ? ` — ${item.name}` : ""}</option>)}</select></label>
      <label>Sistema construtivo, se identificado<input value={system} onChange={(event) => setSystem(event.target.value)}/></label><label>Elemento, se identificado<input value={element} onChange={(event) => setElement(event.target.value)}/></label>
      <fieldset><legend>Medições do mesmo item</legend>{availableMeasurements.length ? availableMeasurements.map((item) => <label key={item.measurement_id}><input type="checkbox" checked={measurementIds.includes(item.measurement_id)} onChange={(event) => setMeasurementIds(toggle(measurementIds, item.measurement_id, event.target.checked))}/>{item.measurement_id} — {item.raw_value} {item.raw_unit}</label>) : <p>Nenhuma medição vinculável.</p>}</fieldset>
      <fieldset><legend>Fotografias do mesmo item</legend>{availablePhotos.length ? availablePhotos.map((item) => <label key={item.photo_id}><input type="checkbox" checked={photoIds.includes(item.photo_id)} onChange={(event) => setPhotoIds(toggle(photoIds, item.photo_id, event.target.checked))}/>{item.photo_id} — {item.caption}</label>) : <p>Nenhuma fotografia vinculável.</p>}</fieldset>
      <label>Alegação relacionada<select value={claimId} onChange={(event) => setClaimId(event.target.value)}><option value="">Nenhuma</option>{state.caseAnalysis.snapshot.claims.map((item) => <option key={item.item_id} value={item.item_id}>{item.item_id} — {item.text}</option>)}</select></label>
      <label>Quesito relacionado<select value={questionId} onChange={(event) => setQuestionId(event.target.value)}><option value="">Nenhum</option>{state.caseAnalysis.snapshot.questions.map((item) => <option key={item.item_id} value={item.item_id}>{item.item_id} — {item.text}</option>)}</select></label>
      <button className="primary-action" disabled={busy}>Gerar proposta PAT</button>
    </form></section>}

    {snapshot && <><ol className="pathology-list" aria-label="Patologias propostas">{snapshot.analysis_final.patologias.map((item) => { const latest = effectivePathologyReview(snapshot, item.id); return <li key={item.id}><article><header><h3>{item.id}</h3><span className={`pathology-status pathology-status--${latest?.action.toLowerCase() ?? "pending"}`}>{latest?.action === "APPROVE" ? "Aprovada pelo profissional" : latest?.action === "REJECT" ? "Rejeitada pelo profissional" : "Aguardando revisão"}</span></header><p>{item.manifestacao ?? "Manifestação sem descrição textual."}</p><p><strong>Conclusão técnica:</strong> {item.conclusao_tecnica ?? "[INFORMAÇÃO NECESSÁRIA: conclusão técnica]"}</p><p className="boundary-note">Evidências: {item.evidencias?.join(", ") || "nenhuma identidade informada"}</p>{latest && <small>{latest.professional_id} · {latest.reason} · {latest.reviewed_at}</small>}</article></li>; })}</ol>
      <section className="technical-authority"><h3>Revisão profissional</h3><p>A revisão cria uma nova decisão append-only. O padrão inicial é rejeitar; aprovação exige escolha expressa.</p><form onSubmit={review}><label>Patologia<select value={reviewPatId} onChange={(event) => setReviewPatId(event.target.value)}>{snapshot.analysis_final.patologias.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label><label>Ação profissional<select value={reviewAction} onChange={(event) => setReviewAction(event.target.value as "APPROVE" | "REJECT")}><option value="REJECT">Rejeitar</option><option value="APPROVE">Aprovar</option></select></label><label>Profissional responsável<input value={state.inspection.snapshot.responsible_professional} readOnly/></label><label>Fundamentação da revisão<textarea value={reviewReason} onChange={(event) => setReviewReason(event.target.value)}/></label><button className="primary-action" disabled={blocked}>Registrar revisão</button></form></section>
      <details className="technical-audit"><summary>Auditoria dos vínculos</summary><dl><dt>Case Analysis</dt><dd>{snapshot.source_snapshot.case_analysis_snapshot_id} · revisão {snapshot.source_snapshot.case_analysis_revision}</dd><dt>Planejamento</dt><dd>{snapshot.source_snapshot.planning_snapshot_id} · revisão {snapshot.source_snapshot.planning_revision}</dd><dt>Vistoria</dt><dd>{snapshot.source_snapshot.inspection_session_id} · revisão {snapshot.source_snapshot.inspection_revision}</dd><dt>PAT</dt><dd>{snapshot.snapshot_id} · revisão {state.analysis?.revision}</dd></dl></details>
    </>}
    {operationError && <p role="alert">A operação foi recusada. Confirme os vínculos, a revisão atual e a fundamentação profissional.</p>}
  </section>;
}
