import { useEffect, useState } from "react";

import { effectivePathologyReview, getConstructionDefectAnalysis, type ConstructionDefectAnalysisEnvelope } from "../data/constructionDefectAnalysis";
import { navigate } from "../app/router";
import { useExpertIdentity } from "../data/expertIdentity";
import { getTechnicalSnapshot, TechnicalSnapshotApiError, type TechnicalEnvelope } from "../data/technicalSnapshot";
import { workspacePath } from "../routes/routeCatalog";
import { actionLabel, formatDateTime } from "../ui/labels";
import { TechnicalDetails } from "../ui/TechnicalDetails";

type State =
  | { kind: "loading" }
  | { kind: "ready"; technical: TechnicalEnvelope | null; pathology: ConstructionDefectAnalysisEnvelope | null }
  | { kind: "error" };

// Constatações: somente o que a decisão profissional tornou efetivo. Propostas,
// evidências pendentes e sugestões automáticas não aparecem aqui.
export function FindingsLedgerView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [version, setVersion] = useState(0);
  const expert = useExpertIdentity();

  useEffect(() => {
    const controller = new AbortController();
    const optional = <T,>(promise: Promise<T>) => promise.then((value) => value, (error) => {
      if (error instanceof TechnicalSnapshotApiError && error.kind === "not-found") return null;
      if (error && typeof error === "object" && "kind" in error && (error as { kind: string }).kind === "not-found") return null;
      throw error;
    });
    Promise.all([optional(getTechnicalSnapshot(workspaceId, controller.signal)), optional(getConstructionDefectAnalysis(workspaceId, controller.signal))]).then(
      ([technical, pathology]) => setState({ kind: "ready", technical, pathology }),
      () => { if (!controller.signal.aborted) setState({ kind: "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId, version]);

  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Carregando constatações</h2><p>Reunindo os achados que você aprovou.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível carregar as constatações</h2><p>Os registros locais não puderam ser lidos. Nada foi alterado.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;

  const snapshot = state.technical?.snapshot ?? null;
  const pathologies = state.pathology?.snapshot.analysis_final.patologias
    .map((item) => ({ item, review: effectivePathologyReview(state.pathology!.snapshot, item.id) }))
    .filter(({ review }) => review?.action === "APPROVE") ?? [];
  const findings = snapshot?.findings ?? [];
  const person = (id: string) => (expert && id === expert.profile_id ? expert.full_name : id);

  if (findings.length === 0 && pathologies.length === 0) {
    return <section className="status-state status-state--empty"><span className="empty-sheet" aria-hidden="true"><span /><span /><span /></span><div><h2>Nenhuma constatação efetiva ainda</h2><p>Um achado aparece aqui quando você aprova uma proposta técnica em Evidências ou uma análise de manifestação em Análise técnica.</p><a className="primary-action" href={workspacePath(workspaceId, "evidencias")} onClick={navigate}>Ir para Evidências</a></div></section>;
  }

  return <section className="findings-ledger" aria-labelledby="findings-ledger-title">
    <header className="planning-overview"><div><h2 id="findings-ledger-title">Achados técnicos efetivos</h2><p>Cada achado mostra a evidência que o sustenta, o método aplicado e a sua decisão. É esta base que o laudo utiliza.</p></div><div className="planning-readiness"><strong>{findings.length + pathologies.length} {findings.length + pathologies.length === 1 ? "constatação" : "constatações"}</strong><span>{findings.length} da cadeia técnica · {pathologies.length} de manifestações</span></div></header>
    {snapshot?.upstream_stale && <section className="analysis-inventory-warning" role="alert"><strong>Fontes anteriores mudaram — revise antes de usar no laudo</strong><ul>{snapshot.upstream_stale_reasons.map((item) => <li key={item}>{item}</li>)}</ul></section>}
    {findings.length > 0 && <section className="analysis-section"><h3>Cadeia técnica</h3><ol className="findings-list">{findings.map((finding) => {
      const proposal = snapshot!.finding_proposals.find((item) => item.proposal_id === finding.proposal_id);
      const decision = snapshot!.decisions.find((item) => item.decision_id === finding.decision_id);
      const evidence = snapshot!.evidence_items.filter((item) => proposal?.supporting_evidence_ids.includes(item.evidence_id));
      const methods = snapshot!.method_applications.filter((item) => proposal?.method_application_ids.includes(item.method_application_id));
      const limitations = snapshot!.limitations.filter((item) => proposal?.limitation_ids.includes(item.limitation_id));
      return <li key={finding.finding_id}><article className="finding-card">
        <h4>{finding.technical_proposition}</h4>
        <p className="boundary-note">Escopo: {finding.scope}</p>
        <dl>
          <dt>Evidência</dt><dd>{evidence.length ? evidence.map((item) => item.proposition).join(" · ") : "—"}</dd>
          <dt>Método</dt><dd>{methods.length ? methods.map((item) => item.method_identity).join(" · ") : "—"}</dd>
          <dt>Decisão</dt><dd>{decision ? `${actionLabel(decision.action)} por ${person(decision.professional_id)} em ${formatDateTime(decision.timestamp)}` : "—"}</dd>
          {limitations.length > 0 && <><dt>Limitações</dt><dd>{limitations.map((item) => item.description).join(" · ")}</dd></>}
        </dl>
        <TechnicalDetails><span className="data">{finding.finding_id} · proposta {finding.proposal_id} · decisão {finding.decision_id}</span></TechnicalDetails>
      </article></li>;
    })}</ol></section>}
    {pathologies.length > 0 && <section className="analysis-section"><h3>Manifestações construtivas (PAT)</h3><ol className="findings-list">{pathologies.map(({ item, review }) => <li key={item.id}><article className="finding-card">
      <h4>{item.id} · {item.manifestacao ?? "Manifestação sem descrição"}</h4>
      <dl>
        <dt>Conclusão técnica</dt><dd>{item.conclusao_tecnica ?? "[INFORMAÇÃO NECESSÁRIA: conclusão técnica]"}</dd>
        <dt>Decisão</dt><dd>{review ? `${actionLabel(review.action)} por ${person(review.professional_id)} em ${formatDateTime(review.reviewed_at)}` : "—"}</dd>
      </dl>
      <TechnicalDetails><span className="data">evidências {item.evidencias?.join(", ") || "—"} · revisão {review?.review_id}</span></TechnicalDetails>
    </article></li>)}</ol></section>}
  </section>;
}
