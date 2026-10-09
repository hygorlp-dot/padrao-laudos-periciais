import type { AnalysisItem, CaseAnalysisSnapshot } from "../data/caseAnalysis";
import { TechnicalDetails } from "../ui/TechnicalDetails";
import type { Read, ReportContext } from "./reportContext";

function ReadNotice({ state }: { state: Read<unknown> }) {
  return state.kind === "ready" ? null : <p role="status">{state.kind === "loading" ? "Consultando a fonte…" : state.kind === "different" ? "A fonte atual difere da base deste laudo. Detalhes históricos não estão disponíveis nesta consulta." : "Consulta da fonte indisponível. Isso não significa ausência de evidência."}</p>;
}

export function CaseSource({ item, snapshot }: { item: AnalysisItem; snapshot: CaseAnalysisSnapshot }) {
  return <ul className="report-source-lines">{item.provenance.map((source) => {
    const document = snapshot.documents.find((entry) => entry.document_id === source.source_document_id);
    return <li key={source.occurrence_id}><strong>Documento / fonte</strong>: {String(document?.raw_type ?? "Documento dos autos")} · {source.page_or_span}<TechnicalDetails><pre>{JSON.stringify(source, null, 2)}</pre></TechnicalDetails></li>;
  })}</ul>;
}

export function FindingBasis({ findingId, context }: { findingId: string; context: ReportContext }) {
  if (context.technical.kind !== "ready") return <ReadNotice state={context.technical} />;
  const technical = context.technical.value;
  const finding = technical.findings.find((item) => item.finding_id === findingId);
  const proposal = technical.finding_proposals.find((item) => item.proposal_id === finding?.proposal_id);
  const decision = technical.decisions.find((item) => item.decision_id === finding?.decision_id);
  if (!finding || !proposal || !decision) return <p>O vínculo não está disponível nesta consulta. Nenhuma conclusão foi deduzida.</p>;
  return <div className="report-source-chain">
    <p><strong>Constatação:</strong> {finding.technical_proposition}</p>
    <p><strong>Decisão profissional registrada:</strong> {decision.reason}</p>
    <p className="field-hint">Esta decisão pertence à constatação. A redação da resposta e a aprovação do laudo são atos distintos.</p>
    <ul className="report-source-lines">{[...proposal.supporting_evidence_ids.map((id) => ({ id, role: "Evidência de suporte" })), ...proposal.contrary_evidence_ids.map((id) => ({ id, role: "Evidência contrária" }))].map(({ id, role }) => <li key={`${role}:${id}`}><strong>{role}:</strong> {technical.evidence_items.find((item) => item.evidence_id === id)?.proposition ?? "Conteúdo não disponível"}</li>)}</ul>
    {proposal.method_application_ids.map((id) => { const method = technical.method_applications.find((item) => item.method_application_id === id); return method && <p key={id}><strong>Análise / método:</strong> {method.method_identity} · {method.procedure}</p>; })}
    <TechnicalDetails><pre>{JSON.stringify({ finding, proposal, decision, source_links: technical.source_links.filter((link) => [...proposal.supporting_evidence_ids, ...proposal.contrary_evidence_ids].includes(link.evidence_id)) }, null, 2)}</pre></TechnicalDetails>
  </div>;
}

export function SourceReading({ kind, id, context, sourceRevision, boundRevision }: { kind: string; id: string; context: ReportContext; sourceRevision?: number; boundRevision?: number | null }) {
  if (sourceRevision !== undefined && boundRevision !== undefined && sourceRevision !== boundRevision) return <p>A revisão desta fonte não corresponde à base do laudo. Conteúdo histórico preservado; consulta atual não atribuída a este trecho.</p>;
  if (kind === "TECHNICAL_FINDING") return <FindingBasis findingId={id} context={context} />;
  if (kind === "PROFESSIONAL_DECISION") {
    if (context.technical.kind !== "ready") return <ReadNotice state={context.technical} />;
    const finding = context.technical.value.findings.find((item) => item.decision_id === id);
    return finding ? <FindingBasis findingId={finding.finding_id} context={context} /> : <p>Decisão não disponível nesta consulta.</p>;
  }
  if (["ALLEGATION", "COURT_DECISION", "CASE_DOCUMENT"].includes(kind)) {
    if (context.case.kind !== "ready") return <ReadNotice state={context.case} />;
    const snapshot = context.case.value;
    if (kind === "CASE_DOCUMENT") {
      const document = snapshot.documents.find((item) => item.document_id === id);
      return document ? <><p><strong>Documento / fonte:</strong> {String(document.raw_type)} · páginas {String(document.page_count_or_span)}</p><TechnicalDetails><pre>{JSON.stringify(document, null, 2)}</pre></TechnicalDetails></> : <p>Documento não disponível nesta consulta.</p>;
    }
    const item = (kind === "ALLEGATION" ? snapshot.claims : snapshot.decisions).find((item) => item.item_id === id);
    return item ? <><p><strong>{kind === "ALLEGATION" ? "Alegação nos autos" : "Decisão judicial"}:</strong> {item.text}</p><CaseSource item={item} snapshot={snapshot} /></> : <p>Conteúdo não disponível nesta consulta.</p>;
  }
  if (["FIELD_OBSERVATION", "MEASUREMENT"].includes(kind)) {
    if (context.inspection.kind !== "ready") return <ReadNotice state={context.inspection} />;
    const snapshot = context.inspection.value;
    if (kind === "FIELD_OBSERVATION") { const item = snapshot.observations.find((item) => item.observation_id === id); return item ? <p><strong>Observado em vistoria:</strong> {item.raw_observation} · {item.provenance}</p> : <p>Observação não disponível nesta consulta.</p>; }
    const item = snapshot.measurements.find((item) => item.measurement_id === id);
    const named = (items: unknown[], field: string, id: string, name: string) => { const found = items.find((entry) => entry && typeof entry === "object" && (entry as Record<string, unknown>)[field] === id) as Record<string, unknown> | undefined; return typeof found?.[name] === "string" ? found[name] as string : "Não informado"; };
    return item ? <><p><strong>Medição:</strong> {item.quantity}: {item.raw_value} {item.raw_unit}</p><p>Método: {named(snapshot.methods, "method_id", item.method_id, "name")} · Equipamento: {named(snapshot.instruments, "instrument_id", item.instrument_id, "identity")}</p><p>{item.provenance}</p><TechnicalDetails><pre>{JSON.stringify(item, null, 2)}</pre></TechnicalDetails></> : <p>Medição não disponível nesta consulta.</p>;
  }
  return <p>Análise técnica registrada na etapa Análise técnica. O vínculo completo permanece nos detalhes técnicos; nenhuma relação adicional foi deduzida.</p>;
}

export function QuestionSource({ questionId, context }: { questionId: string; context: ReportContext }) {
  if (context.case.kind !== "ready") return <ReadNotice state={context.case} />;
  const snapshot = context.case.value;
  const question = snapshot.questions.find((item) => item.item_id === questionId);
  if (!question) return <p>Origem do quesito não disponível nesta consulta.</p>;
  const origin = { COURT: "Juízo", CLAIMANT: "Parte requerente", DEFENDANT: "Parte requerida" };
  const names = question.participant_refs.map((id) => { const participant = snapshot.judicial_context.participants.find((item) => item.participant_id === id); return snapshot.judicial_context.entities.find((item) => item.entity_id === participant?.entity_id)?.raw_name; }).filter(Boolean);
  return <><p><strong>Origem:</strong> {question.source_question ? `${origin[question.source_question.origin]} · quesito ${question.source_question.original_number}` : "Numeração original não informada"}{names.length ? ` · ${names.join("; ")}` : ""}</p><CaseSource item={question} snapshot={snapshot} /><TechnicalDetails><pre>{JSON.stringify(question, null, 2)}</pre></TechnicalDetails></>;
}
