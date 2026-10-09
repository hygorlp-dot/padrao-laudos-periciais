import { type FormEvent, useEffect, useMemo, useState } from "react";

import { navigate } from "../app/router";
import { ExpertProfileSetup } from "./ExpertProfileSetup";
import {
  amendReportDraft,
  getExpertProfile,
  getReportAuditTrail,
  getReportSnapshot,
  getReportSources,
  ReportApiError,
  startReportSnapshot,
  startReportVersion,
  referenceCitation,
  getAIAssistantStatus,
  type AIAssistantStatus,
  type ReportAmendment,
  type ReportReference,
  type ReportReferenceKind,
  type ReportEnvelope,
  type ReportSnapshot,
  type ReportSourceCatalog,
  type ReportSourceKind,
} from "../data/reportSnapshot";
import { workspacePath } from "../routes/routeCatalog";
import { authorityLabel, reasonLabels, sourceKindLabel, stateLabel } from "../ui/labels";
import { TechnicalDetails } from "../ui/TechnicalDetails";
import { EditorialPanel } from "../ui/EditorialPanel";
import { propertyFieldLabel } from "../data/propertyRecord";
import { coordinatesText } from "../data/siteLocation";
import { ReportPreflightPanel } from "./ReportPreflightPanel";
import { ReportProfessionalPresentation } from "./ReportProfessionalPresentation";
import { FindingBasis, QuestionSource, SourceReading } from "./ReportProvenance";
import { editorialNature, useReportContext, type ReportContext } from "./reportContext";
import "./report-editorial.css";

type State = { kind: "loading" } | { kind: "profile-missing" } | { kind: "report-missing" } | { kind: "ready"; value: ReportEnvelope } | { kind: "error" };
type Section = ReportSnapshot["sections"][number];

const CONTEXT_LABELS: Record<string, string> = {
  PROCESS_NUMBER: "Número do processo",
  COURT: "Juízo e tribunal",
  PARTIES: "Partes",
  ADDRESSES: "Endereços",
  CLAIM_AND_GROUNDS: "Pedido e fundamentos",
  REQUESTS: "Requerimentos e quesitos",
};

// Fontes que cada seção costuma citar; o perito pode escolher qualquer outra.
const SECTION_SOURCE_HINT: Record<string, ReportSourceKind> = {
  IDENTIFICATION: "CASE_DOCUMENT",
  PROCEDURAL_CONTEXT: "CASE_DOCUMENT",
  PURPOSE_OBJECT: "COURT_DECISION",
  SCOPE: "COURT_DECISION",
  DOCUMENTS_EVIDENCE: "CASE_DOCUMENT",
  METHODOLOGY: "TECHNICAL_FINDING",
  INSPECTION: "FIELD_OBSERVATION",
  TECHNICAL_ANALYSIS: "MEASUREMENT",
  TECHNICAL_FINDINGS: "TECHNICAL_FINDING",
  CONCLUSIONS: "PROFESSIONAL_DECISION",
  LIMITATIONS_RESERVATIONS: "TECHNICAL_FINDING",
  REFERENCES: "CASE_DOCUMENT",
  ATTACHMENTS: "CASE_DOCUMENT",
};

export function ReportFoundationView({ workspaceId }: { workspaceId: string }) {
  return <ReportFoundationContent key={workspaceId} workspaceId={workspaceId} />;
}

function ReportFoundationContent({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [sourceRead, setSourceRead] = useState<{ version: number; kind: "ready" | "error"; value: ReportSourceCatalog | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [versionNotice, setVersionNotice] = useState<string | null>(null);
  const [startError, setStartError] = useState(false);
  const [version, setVersion] = useState(0);
  const sources = sourceRead?.version === version ? sourceRead.value : null;
  const sourcesState = sourceRead?.version === version ? sourceRead.kind : "loading";
  const context = useReportContext(state.kind === "ready" ? state.value.snapshot : null, state.kind === "ready" ? state.value.revision : 0);


  useEffect(() => {
    const controller = new AbortController();
    getExpertProfile(workspaceId, controller.signal).then(
      () => getReportSnapshot(workspaceId, controller.signal).then(
        (value) => { if (!controller.signal.aborted) setState({ kind: "ready", value }); },
        (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof ReportApiError && error.kind === "not-found" ? "report-missing" : "error" }); },
      ),
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof ReportApiError && error.kind === "not-found" ? "profile-missing" : "error" }); },
    );
    getReportSources(workspaceId, controller.signal).then((value) => { if (!controller.signal.aborted) { setSourceRead({ version, kind: "ready", value }); } }, () => { if (!controller.signal.aborted) { setSourceRead({ version, kind: "error", value: null }); } });
    return () => controller.abort();
  }, [workspaceId, version]);

  const profileSaved = async () => {
    setBusy(true);
    try { setState({ kind: "ready", value: await startReportSnapshot(workspaceId) }); }
    catch { setStartError(true); setState({ kind: "report-missing" }); }
    finally { setBusy(false); }
  };

  const newVersion = async () => {
    if (state.kind !== "ready") return;
    setBusy(true); setActionError(null);
    try {
      const { envelope, dropped } = await startReportVersion(workspaceId, state.value);
      setState({ kind: "ready", value: envelope });
      const removed = [
        dropped.claims ? `${dropped.claims} ${dropped.claims === 1 ? "texto sem fonte atual" : "textos sem fonte atual"}` : "",
        dropped.answers ? `${dropped.answers} ${dropped.answers === 1 ? "resposta a quesito" : "respostas a quesitos"}` : "",
        dropped.context_fields.length ? `contexto processual a confirmar: ${dropped.context_fields.map((field) => CONTEXT_LABELS[field] ?? field).join(", ")}` : "",
        dropped.findings_table ? "tabela-resumo dos achados" : "",
        dropped.site_location ? "localização do imóvel" : "",
      ].filter(Boolean);
      setVersionNotice(removed.length ? `Saíram desta versão: ${removed.join("; ")}.` : "Todo o conteúdo continua sustentado pelas fontes atuais.");
      setVersion((value) => value + 1);
    } catch { setActionError("Não foi possível abrir a nova versão."); }
    finally { setBusy(false); }
  };

  const amend = async (action: ReportAmendment, values: Record<string, unknown>, failure: string) => {
    if (state.kind !== "ready") return false;
    setBusy(true); setActionError(null);
    try { setState({ kind: "ready", value: await amendReportDraft(workspaceId, state.value, action, values) }); return true; }
    catch { setActionError(failure); return false; }
    finally { setBusy(false); }
  };

  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Abrindo o laudo</h2><p>Conferindo as fontes vinculadas a cada seção.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível carregar o laudo</h2><p>O laudo salvo não pôde ser consultado agora. Nada foi alterado.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  if (state.kind === "profile-missing") return <section className="technical-authority"><h2>Configure o perfil mestre do perito</h2><p>Esta fonte única preenche a identificação profissional sem alterar conclusões técnicas.</p><ExpertProfileSetup key={workspaceId} workspaceId={workspaceId} onSaved={profileSaved} submitLabel="Salvar perfil e iniciar laudo" /></section>;
  if (state.kind === "report-missing") return <section className="status-state status-state--empty"><span className="empty-sheet" aria-hidden="true"><span /><span /><span /></span><div><h2>Laudo ainda não iniciado</h2><p>O laudo reúne as análises e decisões já registradas. Nada é redigido automaticamente.</p>{startError && <p className="inline-alert" role="alert">O laudo ainda não pode começar: ele se vincula à análise do caso, à vistoria e à cadeia técnica de Evidências. Registre essas etapas e tente de novo.</p>}<button className="primary-action" type="button" disabled={busy} onClick={async () => { setBusy(true); setStartError(false); try { setState({ kind: "ready", value: await startReportSnapshot(workspaceId) }); } catch { setStartError(true); } finally { setBusy(false); } }}>{busy ? "Iniciando…" : "Iniciar laudo"}</button></div></section>;

  const { snapshot } = state.value;
  const editable = snapshot.state === "DRAFT" && !snapshot.upstream_stale && snapshot.review_decisions.length === 0;
  const coverage = snapshot.coverage;
  const unanswered = sources && !snapshot.upstream_stale ? sources.questions.filter((question) => !snapshot.answers.some((answer) => answer.question_id === question.question_id)).length : null;
  const history = state.value.review_history;
  const historicalApproval = history !== undefined && history.report_id === snapshot.report_id && history.source_revision === state.value.revision && history.captured_state === "APPROVED" && history.last_review?.action === "APPROVE";
  const editorialState = snapshot.upstream_stale ? historicalApproval || snapshot.state === "APPROVED" ? "Aprovado antes da alteração · revisão necessária" : "Base desatualizada · revisão necessária" : stateLabel(snapshot.state);

  return <section className="report-authoring" aria-labelledby="report-title">
    <header className="technical-header"><div><h2 id="report-title">Laudo técnico</h2><p>{snapshot.expert_profile.full_name} · {snapshot.expert_profile.registration}</p><span className="report-editorial-status">{editorialState}</span></div><p className="field-hint">{coverage.cpc473_present_sections} de {coverage.cpc473_required_sections} seções obrigatórias · {unanswered === null ? "Situação dos quesitos não confirmada" : unanswered === 0 ? "Quesitos vinculados com resposta registrada" : `${unanswered} ${unanswered === 1 ? "quesito sem resposta" : "quesitos sem resposta"}`}</p></header>
    <p className="report-authority-note">O texto preserva a natureza de cada fonte. Salvar uma redação não valida evidências nem aprova o laudo. A decisão profissional e a revisão são explícitas; o Word é o documento autoritativo e o PDF é derivado local.</p>
    {snapshot.upstream_stale && <section className="analysis-inventory-warning" role="alert"><strong>Fontes anteriores mudaram — o laudo precisa de uma nova versão</strong><ul>{reasonLabels(snapshot.upstream_stale_reasons).map((reason) => <li key={reason}>{reason}</li>)}</ul></section>}
    {!editable && !snapshot.upstream_stale && snapshot.state !== "SUPERSEDED" && <p className="field-hint">O laudo está {stateLabel(snapshot.state).toLowerCase()}; o texto fica bloqueado para edição. Para alterar, marque-o como substituído em Revisão e inicie uma nova versão aqui.</p>}
    {(snapshot.upstream_stale || snapshot.state === "SUPERSEDED") && <section className="analysis-section report-version"><h3>Nova versão do laudo</h3><p>A nova versão abre um rascunho vinculado às fontes atuais. O que elas ainda sustentam é mantido; o que deixou de existir sai e é listado para você. A revisão e a aprovação recomeçam, e as versões anteriores ficam no histórico.</p><button className="primary-action" type="button" disabled={busy} onClick={() => void newVersion()}>{busy ? "Abrindo nova versão…" : "Iniciar nova versão do laudo"}</button></section>}
    {versionNotice && <section className="inline-note" role="status"><strong>Nova versão aberta em rascunho.</strong><p>{versionNotice}</p><button className="text-action" type="button" onClick={() => setVersionNotice(null)}>Fechar aviso</button></section>}
    {actionError && <section className="inline-alert" role="alert"><strong>{actionError}</strong><p>O laudo continua como estava. Confira a fonte escolhida e tente de novo.</p><button className="text-action" type="button" onClick={() => setActionError(null)}>Fechar aviso</button></section>}
    {sourcesState !== "ready" && <p className="field-hint" role="status">{sourcesState === "loading" ? "Consultando fontes e quesitos…" : "As fontes para citação não puderam ser carregadas. Os textos existentes continuam visíveis."}</p>}
    <ReportPreflightPanel key={`${workspaceId}:${state.value.revision}`} workspaceId={workspaceId} reportRevision={state.value.revision} snapshot={snapshot} />
    {coverage.reasons.length > 0 && <details className="report-professional-check" open><summary>Conferência profissional · pendências registradas</summary><ul>{reasonLabels(coverage.reasons).map((reason) => <li key={reason}>{reason}</li>)}</ul><a className="text-action" href={workspacePath(workspaceId, "revisao")} onClick={navigate}>Ver a conferência em Revisão</a></details>}
    <nav className="report-chapter-index" aria-label="Capítulos do laudo"><details><summary>Navegar pelos capítulos</summary><ol>{snapshot.sections.slice().sort((a, b) => a.order - b.order).map((section) => <li key={section.section_id}><a href={`#section-${section.section_id}`} onClick={() => document.getElementById(`section-${section.section_id}`)?.focus()}>{section.order}. {section.title}</a></li>)}</ol></details></nav>
    <details className="report-preparation" id="report-preparation" tabIndex={-1}><summary>Preparação do documento, contexto e figuras</summary>
    {snapshot.presentation && <ReportProfessionalPresentation key={state.value.revision} capture={snapshot.presentation} figures={snapshot.figures ?? []} pathologies={sources?.sources.filter((s) => s.kind === "PATHOLOGY") ?? []} editable={editable} busy={busy} save={(values) => void amend("SET_PROFESSIONAL_PRESENTATION", values, "Confira os dados, os vínculos das figuras e os valores de reparos antes de salvar.")} />}

    <details className="analysis-section property-panel"><summary><strong>Processo nesta versão do laudo</strong></summary>
      {snapshot.process_record ? <><p>Dados confirmados na revisão {snapshot.process_record.source_revision} do processo.</p><dl className="property-summary"><div><dt>Processo</dt><dd>{snapshot.process_record.numero_processo}</dd></div><div><dt>Juízo</dt><dd>{[snapshot.process_record.vara, snapshot.process_record.tribunal].filter(Boolean).join(" · ")}</dd></div><div><dt>Parte requerente</dt><dd>{snapshot.process_record.parte_requerente}</dd></div><div><dt>Parte requerida</dt><dd>{snapshot.process_record.parte_requerida}</dd></div></dl></> : <p>Esta versão ainda não inclui os dados confirmados do processo.</p>}
      {editable && !snapshot.process_record && <button type="button" className="text-action" disabled={busy} onClick={() => void amend("SET_PROCESS_RECORD", {}, "Confirme os dados na etapa Processo antes de incluí-los.")}>Incluir dados confirmados do processo</button>}
    </details>

    <details className="analysis-section property-panel"><summary><strong>Imóvel nesta versão do laudo</strong></summary>
      {snapshot.property_record ? <><p>Dados confirmados na revisão {snapshot.property_record.source_revision} do cadastro.</p><dl className="property-summary">{snapshot.property_record.record.values.map((value) => <div key={value.field}><dt>{propertyFieldLabel(value.field)}</dt><dd>{value.value}</dd></div>)}</dl></> : <p>Esta versão ainda não inclui o cadastro do imóvel.</p>}
      {editable && !snapshot.property_record && <button type="button" className="text-action" disabled={busy} onClick={() => void amend("SET_PROPERTY_RECORD", {}, "Confirme o cadastro do imóvel na etapa Processo antes de incluí-lo.")}>Incluir cadastro confirmado do imóvel</button>}
    </details>

    <EditorialPanel profile={snapshot.editorial_profile} editable={editable} busy={busy} onSave={(profile) => amend("SET_EDITORIAL_PROFILE", { editorial_profile: profile }, "Não foi possível salvar o padrão editorial.")} />

    <AssistantPanel />

    <FiguresPanel snapshot={snapshot} editable={editable} busy={busy} amend={amend} workspaceId={workspaceId} />

    <ContextPanel snapshot={snapshot} sources={sources} editable={editable} busy={busy} onSave={(field, sourceId, note) => amend("UPDATE_CONTEXT", { field, status: "PRESENT", source_id: sourceId, note }, "Não foi possível atualizar o contexto processual.")} />
    </details>

    <ol className="report-sections" aria-label="Seções do laudo">{snapshot.sections.slice().sort((a, b) => a.order - b.order).map((section) => (
      <li key={section.section_id}>
        <SectionEditor section={section} snapshot={snapshot} sources={snapshot.upstream_stale ? null : sources} sourcesState={sourcesState} context={context} editable={editable} busy={busy} amend={amend} />
      </li>
    ))}</ol>

    <section className="analysis-section report-next"><h3>Próximo passo</h3><p>Quando o conteúdo estiver completo, confira e aprove o laudo em Revisão. A aprovação libera a geração do Word e do PDF.</p><div className="action-row"><a className={snapshot.upstream_stale || snapshot.state === "SUPERSEDED" ? "text-action" : "primary-action"} href={workspacePath(workspaceId, "revisao")} onClick={navigate}>Conferir em Revisão</a><AuditTrailButton workspaceId={workspaceId} /></div><TechnicalDetails summary="Detalhes técnicos desta versão"><pre>{JSON.stringify({ report_id: snapshot.report_id, revision: state.value.revision, source_snapshot: snapshot.source_snapshot }, null, 2)}</pre></TechnicalDetails></section>
  </section>;
}

function sourceLabel(sources: ReportSourceCatalog | null, kind: string, id: string) {
  const label = sources?.sources.find((item) => item.kind === kind && item.id === id)?.label;
  return kind === "PATHOLOGY" && label?.startsWith(`${id} · `) ? label.slice(id.length + 3) : label;
}

const reportSourceName = (kind: string | undefined) => kind === "PATHOLOGY" ? "Análise técnica" : sourceKindLabel(kind);
function sourceRevision(snapshot: ReportSnapshot, kind: string) {
  const binding = snapshot.source_snapshot;
  return ["TECHNICAL_FINDING", "PROFESSIONAL_DECISION"].includes(kind) ? binding.technical_snapshot_revision : ["FIELD_OBSERVATION", "MEASUREMENT"].includes(kind) ? binding.inspection_session_revision : kind === "PATHOLOGY" ? binding.construction_defect_analysis_revision : binding.case_analysis_revision;
}

function SectionEditor({ section, snapshot, sources, sourcesState, context, editable, busy, amend }: {
  section: Section;
  snapshot: ReportSnapshot;
  sources: ReportSourceCatalog | null;
  sourcesState: "loading" | "ready" | "error";
  context: ReportContext;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
}) {
  const claims = snapshot.claims.filter((claim) => claim.section_id === section.section_id);
  const [adding, setAdding] = useState(false);
  const titleId = `section-${section.section_id}`;
  const generated = (section.kind === "TECHNICAL_FINDINGS" && Boolean(snapshot.findings_table?.length)) || (section.kind === "REFERENCES" && Boolean(snapshot.references?.length)) || (section.kind === "INSPECTION" && Boolean(snapshot.site_location));
  const empty = claims.length === 0 && section.kind !== "ANSWERS_TO_QUESTIONS" && !generated;
  return <article className="report-section" aria-labelledby={titleId}>
    <header><h3 id={titleId} tabIndex={-1}>{section.order}. {section.title}</h3>{section.required_by_cpc473 && <span className="field-hint">Seção obrigatória</span>}</header>
    {empty && <p className="report-empty">{section.required_by_cpc473 ? "Seção obrigatória ainda sem conteúdo." : "Sem conteúdo. Seções vazias não aparecem no documento final."}</p>}
    {section.kind === "INSPECTION" && <SiteLocationCitation snapshot={snapshot} editable={editable} busy={busy} amend={amend} />}
    {section.kind === "TECHNICAL_FINDINGS" && <FindingsTablePanel snapshot={snapshot} editable={editable} busy={busy} amend={amend} />}
    {claims.map((claim) => <ClaimEditor key={`${claim.claim_id}:${claim.text}`} claim={claim} snapshot={snapshot} sources={sources} context={context} references={snapshot.references ?? []} crossReferences={crossReferences(snapshot)} editable={editable} busy={busy} amend={amend} protectedByAnswer={snapshot.answers.some((answer) => answer.claim_ids.includes(claim.claim_id))} />)}
    {section.kind === "REFERENCES" && <ReferencesPanel references={snapshot.references ?? []} editable={editable} busy={busy} amend={amend} />}
    {section.kind === "ANSWERS_TO_QUESTIONS" && <QuestionsEditor snapshot={snapshot} sources={sources} sourcesState={sourcesState} context={context} editable={editable} busy={busy} amend={amend} />}
    {editable && sources && (adding
      ? <AddClaimForm section={section} sources={sources} busy={busy} onCancel={() => setAdding(false)} onAdd={async (kind, id, text) => { if (await amend("ADD_CLAIM", { section_id: section.section_id, text, source_kind: kind, source_id: id }, "Não foi possível adicionar o texto.")) setAdding(false); }} />
      : <button className="secondary-action" type="button" onClick={() => setAdding(true)}>Adicionar texto a esta seção</button>)}
  </article>;
}

function ClaimEditor({ claim, snapshot, sources, context, references, crossReferences: targets, editable, busy, amend, protectedByAnswer }: {
  claim: ReportSnapshot["claims"][number];
  snapshot: ReportSnapshot;
  sources: ReportSourceCatalog | null;
  context: ReportContext;
  references: ReportReference[];
  crossReferences: Array<{ marker: string; label: string }>;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
  protectedByAnswer: boolean;
}) {
  // Remontado pela key quando o texto salvo muda; o rascunho local é só do editor.
  const [text, setText] = useState(claim.text);
  const [editing, setEditing] = useState(false);
  const provenance = claim.provenance[0];
  const expectedRevision = provenance ? sourceRevision(snapshot, provenance.source_kind) : undefined;
  const label = provenance && (expectedRevision === undefined || expectedRevision === provenance.source_revision) ? sourceLabel(sources, provenance.source_kind, provenance.source_id) : undefined;
  return <div className="report-claim" id={`report-claim-${claim.claim_id}`} tabIndex={-1}>
    <p className="report-nature">{editorialNature(claim.authority)}{snapshot.upstream_stale ? " · base desatualizada" : ""}</p>
    {editable && editing
      ? <label className="report-claim-text">Texto<textarea autoFocus value={text} onChange={(event) => setText(event.target.value)} disabled={busy} aria-describedby={`report-effect-${claim.claim_id}`} /></label>
      : <p>{claim.text}</p>}
    {editable && editing && targets.length > 0 && <label className="report-cite">Inserir referência a figura ou tabela<select value="" disabled={busy} onChange={(event) => { if (event.target.value) setText(`${text.trimEnd()} ${event.target.value}`); }}><option value="">Escolha</option>{targets.map((item) => <option key={item.marker} value={item.marker}>{item.label}</option>)}</select></label>}
    {editable && targets.length > 0 && /\[\[(FIGURA|TABELA):/.test(text) && <p className="field-hint">No documento, cada marcador vira “Figura N” ou “Tabela 1” conforme a ordem final: {presentMarkers(text, targets)}</p>}
    {editable && editing && references.length > 0 && <label className="report-cite">Inserir citação<select value="" disabled={busy} onChange={(event) => { const chosen = references.find((item) => item.reference_id === event.target.value); if (chosen) setText(`${text.trimEnd()} ${referenceCitation(chosen)}`); }}><option value="">Escolha a referência</option>{references.map((item) => <option key={item.reference_id} value={item.reference_id}>{referenceCitation(item)} — {item.title}</option>)}</select></label>}
    <p className="report-claim-source"><span className="status-pill">{authorityLabel(claim.authority)}</span> Fonte: {reportSourceName(provenance?.source_kind)}{label ? ` — ${label}` : ""}</p>
    <details className="report-provenance"><summary>De onde veio este trecho?</summary>{claim.provenance.map((item) => <SourceReading key={item.provenance_id} kind={item.source_kind} id={item.source_id} context={context} sourceRevision={item.source_revision} boundRevision={sourceRevision(snapshot, item.source_kind)} />)}</details>
    {editable && !editing && <button className="text-action" type="button" disabled={busy} onClick={() => setEditing(true)}>Editar trecho</button>}
    {editable && editing && <div className="action-row">
      <button className="secondary-action" type="button" disabled={busy || !text.trim() || text.trim() === claim.text} onClick={() => void amend("UPDATE_CLAIM_TEXT", { claim_id: claim.claim_id, text }, "Não foi possível salvar o texto.")}>Salvar texto</button>
      <button className="text-action" type="button" disabled={busy || protectedByAnswer} title={protectedByAnswer ? "Este texto sustenta a resposta a um quesito." : undefined} onClick={() => void amend("REMOVE_CLAIM", { claim_id: claim.claim_id }, "Não foi possível remover o texto.")}>Remover</button>
      <button className="text-action" type="button" onClick={() => { setText(claim.text); setEditing(false); }}>Cancelar edição</button>
    </div>}
    {editing && <p id={`report-effect-${claim.claim_id}`} className="field-hint">Salvar altera somente a redação deste trecho. A natureza da fonte e as decisões anteriores não mudam.</p>}
    <TechnicalDetails>{claim.provenance.map((item) => <span className="data" key={item.provenance_id}>{claim.claim_id} · {item.source_kind} · {item.source_id} · revisão {item.source_revision}</span>)}</TechnicalDetails>
  </div>;
}

// Figures are numbered like the document numbers them: section order, then the chosen order.
const FIGURE_SECTION_ORDER = ["INSPECTION", "TECHNICAL_ANALYSIS", "TECHNICAL_FINDINGS", "ATTACHMENTS"];
function numberedFigures(snapshot: ReportSnapshot) {
  const figures = (snapshot.figures ?? []).map((figure, index) => ({ figure, index }));
  figures.sort((a, b) => FIGURE_SECTION_ORDER.indexOf(a.figure.section_kind) - FIGURE_SECTION_ORDER.indexOf(b.figure.section_kind) || a.index - b.index);
  return figures.map(({ figure }, position) => ({ figure, number: position + 1 }));
}
function crossReferences(snapshot: ReportSnapshot) {
  const items = numberedFigures(snapshot).map(({ figure, number }) => ({ marker: `[[FIGURA:${figure.figure_id}]]`, label: `Figura ${number} – ${figure.caption}` }));
  if (snapshot.findings_table?.length) items.push({ marker: "[[TABELA:ACHADOS]]", label: "Tabela 1 – Resumo dos achados técnicos" });
  return items;
}
function presentMarkers(text: string, targets: Array<{ marker: string; label: string }>) {
  return targets.filter((item) => text.includes(item.marker)).map((item) => item.label.split(" – ")[0]).join(", ") || "nenhuma referência reconhecida";
}

const ASSISTANT_REASON: Record<string, string> = {
  NO_LOCAL_PROVIDER: "Não há um modelo de IA aprovado rodando neste computador.",
  PRIVATE_CASE_EGRESS_NOT_AUTHORIZED: "O envio de dados do caso a um serviço de IA externo não foi autorizado. Por padrão, nada do caso sai desta máquina.",
};

function AssistantPanel() {
  const [status, setStatus] = useState<AIAssistantStatus | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void getAIAssistantStatus(controller.signal).then((value) => { if (!controller.signal.aborted) setStatus(value); });
    return () => controller.abort();
  }, []);
  if (!status) return null;
  return <details className="analysis-section report-assistant">
    <summary><strong>Assistente de redação</strong> <span className="status-pill" data-tone={status.available ? "done" : undefined}>{status.available ? "Disponível" : "Indisponível nesta instalação"}</span></summary>
    <p>O assistente só propõe texto. Nada entra no laudo sem a sua decisão: você aceita, edita ou descarta cada proposta, e a fonte de cada trecho continua sendo a que você escolher.</p>
    {!status.available && <ul>{status.reasons.map((reason) => <li key={reason}>{ASSISTANT_REASON[reason] ?? reason}</li>)}</ul>}
  </details>;
}

function FiguresPanel({ snapshot, editable, busy, amend, workspaceId }: {
  snapshot: ReportSnapshot;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
  workspaceId: string;
}) {
  const figures = numberedFigures(snapshot);
  if (!figures.length && !editable) return null;
  return <section className="analysis-section report-figures" aria-labelledby="report-figures-title">
    <h3 id="report-figures-title">Figuras do laudo</h3>
    {figures.length
      ? <ol className="report-figures__list">{figures.map(({ figure, number }) => <li key={figure.figure_id}><img src={`/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/photo-library/photos/${encodeURIComponent(figure.figure_id)}/thumbnail`} alt={figure.caption} loading="lazy" width={96} height={72} /><span><strong>Figura {number}</strong> – {figure.caption}</span></li>)}</ol>
      : <p className="field-hint">Escolha as fotos, com legenda e seção, na biblioteca de fotos da Vistoria e traga a seleção para o laudo.</p>}
    {editable && <div className="action-row">
      <button className="secondary-action" type="button" disabled={busy} onClick={() => void amend("SET_FIGURES", {}, "Não foi possível trazer as figuras. Escolha fotos com legenda na biblioteca da Vistoria.")}>{figures.length ? "Atualizar figuras a partir da biblioteca" : "Trazer figuras da biblioteca"}</button>
      {figures.length > 0 && <button className="text-action" type="button" disabled={busy} onClick={() => void amend("REMOVE_FIGURES", {}, "Não foi possível remover as figuras. Retire antes as referências a elas no texto.")}>Remover figuras</button>}
    </div>}
  </section>;
}

function SiteLocationCitation({ snapshot, editable, busy, amend }: {
  snapshot: ReportSnapshot;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
}) {
  const site = snapshot.site_location;
  if (!site && !editable) return null;
  return <div className="report-site-location">
    {site
      ? <p>Local vistoriado{site.address_label ? `: ${site.address_label}` : ""} · <span className="data">{coordinatesText(site)}</span> (WGS 84)</p>
      : <p className="field-hint">A localização confirmada no Planejamento pode abrir esta seção com o endereço e as coordenadas.</p>}
    {editable && <div className="action-row">
      <button className="secondary-action" type="button" disabled={busy} onClick={() => void amend("SET_SITE_LOCATION", {}, "Não foi possível inserir a localização. Confirme a localização do imóvel no Planejamento.")}>{site ? "Atualizar localização" : "Inserir localização"}</button>
      {site && <button className="text-action" type="button" disabled={busy} onClick={() => void amend("REMOVE_SITE_LOCATION", {}, "Não foi possível remover a localização.")}>Remover</button>}
    </div>}
  </div>;
}

const SITUATION_LABEL: Record<string, string> = { CONFORME: "Conforme", ANOMALIA: "Anomalia", FALHA: "Falha", INCONCLUSIVA: "Inconclusiva", NAO_CONSTATADA: "Não constatada" };

function FindingsTablePanel({ snapshot, editable, busy, amend }: {
  snapshot: ReportSnapshot;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
}) {
  const rows = snapshot.findings_table ?? [];
  const technical = rows.every((row) => row.provenance.source_kind === "TECHNICAL_FINDING");
  if (!rows.length && !editable) return null;
  return <div className="report-findings-table">
    {rows.length > 0 && <table>
      <caption>Tabela 1 – Resumo dos achados técnicos</caption>
      <thead><tr><th scope="col">Item</th><th scope="col">{technical ? "Escopo" : "Manifestação"}</th>{!technical && <th scope="col">Ambiente</th>}<th scope="col">Achado técnico</th>{!technical && <th scope="col">Situação</th>}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={row.provenance.provenance_id}><td>{index + 1}</td><td>{row.manifestation}</td>{!technical && <td>{row.environment ?? "Não informado"}</td>}<td>{row.finding}</td>{!technical && <td>{row.situation ? SITUATION_LABEL[row.situation] ?? row.situation : "Não informada"}</td>}</tr>)}</tbody>
    </table>}
    {editable && <>
      <p className="field-hint">A tabela reúne os achados técnicos com decisão profissional vigente. Cada linha preserva o escopo e o texto registrado, sem inferir causas ou classificações.</p>
      <div className="action-row">
        <button className="secondary-action" type="button" disabled={busy} onClick={() => void amend("SET_FINDINGS_TABLE", {}, "Não foi possível montar a tabela-resumo. É necessário haver achados técnicos com decisão profissional vigente e fontes atualizadas.")}>{rows.length ? "Atualizar tabela-resumo" : "Inserir tabela-resumo dos achados"}</button>
        {rows.length > 0 && <button className="text-action" type="button" disabled={busy} onClick={() => void amend("REMOVE_FINDINGS_TABLE", {}, "Não foi possível remover a tabela-resumo.")}>Remover tabela</button>}
      </div>
    </>}
  </div>;
}

const REFERENCE_KINDS: Array<[ReportReferenceKind, string]> = [
  ["TECHNICAL_STANDARD", "Norma técnica"],
  ["LEGAL_REFERENCE", "Legislação"],
  ["TECHNICAL_LITERATURE", "Literatura técnica"],
  ["MANUFACTURER_DOCUMENTATION", "Documentação de fabricante"],
  ["OTHER_REFERENCE", "Outra referência"],
];
const EMPTY_REFERENCE = { kind: "TECHNICAL_STANDARD" as ReportReferenceKind, author: "", title: "", year: "", identifier: "", details: "" };

function ReferencesPanel({ references, editable, busy, amend }: {
  references: ReportReference[];
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState(EMPTY_REFERENCE);
  const year = draft.year.trim() ? Number(draft.year) : null;
  const yearValid = year === null || (Number.isInteger(year) && year >= 1800 && year <= 2200);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft.author.trim() || !draft.title.trim() || !yearValid) return;
    const saved = await amend("ADD_REFERENCE", { kind: draft.kind, author: draft.author.trim(), title: draft.title.trim(), year, identifier: draft.identifier.trim() || null, details: draft.details.trim() || null }, "Não foi possível adicionar a referência. Confira se ela já não está na lista.");
    if (saved) setDraft(EMPTY_REFERENCE);
  };
  const kindLabel = (kind: string) => REFERENCE_KINDS.find(([value]) => value === kind)?.[1] ?? kind;
  return <div className="report-references">
    <p className="field-hint">Normas, leis e obras que fundamentam o laudo. Documentos dos autos continuam como evidência e não entram aqui. A seção de referências do documento é gerada desta lista, em ordem alfabética.</p>
    {references.length > 0 && <ul>{references.map((item) => <li key={item.reference_id}>
      <div><strong>{referenceCitation(item)}</strong> <span className="status-pill">{kindLabel(item.kind)}</span><p>{item.identifier ? `${item.identifier}: ` : ""}{item.title}{item.details ? ` · ${item.details}` : ""}</p></div>
      {editable && <button className="text-action" type="button" disabled={busy} onClick={() => void amend("REMOVE_REFERENCE", { reference_id: item.reference_id }, "Não foi possível remover a referência.")}>Remover</button>}
    </li>)}</ul>}
    {editable && <form className="report-add" onSubmit={submit} aria-label="Adicionar referência">
      <label>Tipo<select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as ReportReferenceKind })}>{REFERENCE_KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Autor ou entidade<input required value={draft.author} placeholder="Associação Brasileira de Normas Técnicas" onChange={(event) => setDraft({ ...draft, author: event.target.value })} /></label>
      <label>Identificação (opcional)<input value={draft.identifier} placeholder="ABNT NBR 15575-1" onChange={(event) => setDraft({ ...draft, identifier: event.target.value })} /></label>
      <label>Título<input required value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label>
      <label>Ano (opcional)<input inputMode="numeric" aria-invalid={!yearValid} value={draft.year} onChange={(event) => setDraft({ ...draft, year: event.target.value })} /></label>
      <label>Local, editora ou publicação (opcional)<input value={draft.details} placeholder="Rio de Janeiro" onChange={(event) => setDraft({ ...draft, details: event.target.value })} /></label>
      {!yearValid && <p role="alert">Informe o ano com quatro dígitos ou deixe em branco.</p>}
      <div className="action-row"><button className="secondary-action" type="submit" disabled={busy || !draft.author.trim() || !draft.title.trim() || !yearValid}>Adicionar referência</button></div>
    </form>}
  </div>;
}

function AddClaimForm({ section, sources, busy, onAdd, onCancel }: {
  section: Section;
  sources: ReportSourceCatalog;
  busy: boolean;
  onAdd: (kind: ReportSourceKind, id: string, text: string) => void;
  onCancel: () => void;
}) {
  const kinds = useMemo(() => [...new Set(sources.sources.map((item) => item.kind))], [sources]);
  const hint = SECTION_SOURCE_HINT[section.kind];
  const [kind, setKind] = useState<ReportSourceKind | "">(hint && kinds.includes(hint) ? hint : kinds[0] ?? "");
  const [sourceId, setSourceId] = useState("");
  const [text, setText] = useState("");
  const options = sources.sources.filter((item) => item.kind === kind);
  const submit = (event: FormEvent) => { event.preventDefault(); if (kind && sourceId && text.trim()) onAdd(kind, sourceId, text.trim()); };
  return <form className="report-add" onSubmit={submit}>
    <label>Tipo de fonte<select value={kind} onChange={(event) => { setKind(event.target.value as ReportSourceKind); setSourceId(""); }}>{kinds.map((item) => <option key={item} value={item}>{reportSourceName(item)}</option>)}</select></label>
    <label>Fonte<select required value={sourceId} onChange={(event) => { setSourceId(event.target.value); const chosen = options.find((item) => item.id === event.target.value); if (chosen && !text.trim()) setText(sourceLabel(sources, chosen.kind, chosen.id) ?? ""); }}><option value="">Selecione</option>{options.map((item) => <option key={`${item.kind}-${item.id}`} value={item.id}>{sourceLabel(sources, item.kind, item.id)}</option>)}</select></label>
    <label>Texto do laudo<textarea required value={text} onChange={(event) => setText(event.target.value)} /></label>
    <small className="field-hint">O texto é a sua redação; a fonte escolhida define a autoridade do trecho e não pode ser promovida pela redação.</small>
    <div className="action-row"><button className="primary-action" type="submit" disabled={busy || !kind || !sourceId || !text.trim()}>Adicionar ao laudo</button><button className="text-action" type="button" onClick={onCancel}>Cancelar</button></div>
  </form>;
}

function QuestionsEditor({ snapshot, sources, sourcesState, context, editable, busy, amend }: {
  snapshot: ReportSnapshot;
  sources: ReportSourceCatalog | null;
  sourcesState: "loading" | "ready" | "error";
  context: ReportContext;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
}) {
  const questions = sources?.questions ?? [];
  const legacy = snapshot.answers.filter((answer) => !questions.some((question) => question.question_id === answer.question_id));
  const unavailable = !sources && !snapshot.upstream_stale;
  return <>
    {unavailable && <p role="status">{sourcesState === "loading" ? "Consultando os quesitos vinculados…" : "Consulta de quesitos indisponível. Não é possível afirmar que não há quesitos."}</p>}
    {snapshot.upstream_stale && <p className="field-hint">Base desatualizada. As respostas abaixo são históricas; os quesitos atuais serão consultados na nova versão.</p>}
    {sources && questions.length === 0 && snapshot.answers.length === 0 && <p className="report-empty">Nenhum quesito vinculado a achado técnico. Vincule quesitos a achados em Evidências.</p>}
    {questions.length > 0 && <nav aria-label="Quesitos neste capítulo"><ol className="report-question-index">{questions.map((question, index) => <li key={question.question_id}><a href={`#report-question-${question.question_id}`} onClick={() => document.getElementById(`report-question-${question.question_id}`)?.focus()}>Quesito {index + 1} · {snapshot.answers.some((answer) => answer.question_id === question.question_id) ? "Resposta registrada" : "Resposta em elaboração"}</a></li>)}</ol></nav>}
    <ol className="report-questions">
      {questions.map((question, index) => <li key={question.question_id}><QuestionItem key={snapshot.answers.find((item) => item.question_id === question.question_id)?.text ?? ""} index={index + 1} question={question} snapshot={snapshot} context={context} editable={editable} busy={busy} amend={amend} /></li>)}
      {legacy.map((answer, index) => <li key={answer.answer_id}><div className="report-question" id={`report-answer-${snapshot.answers.indexOf(answer) + 1}`} tabIndex={-1}><h4>Quesito {index + 1} · resposta preservada</h4><p>{answer.question_text ?? "Texto do quesito não disponível."}</p><p className="report-answer"><strong>Resposta:</strong> {answer.text}</p><p className="field-hint">{snapshot.upstream_stale ? "Revisão necessária · base desatualizada" : "Vínculo atual não confirmado nesta consulta"}</p><TechnicalDetails><pre>{JSON.stringify(answer, null, 2)}</pre></TechnicalDetails></div></li>)}
    </ol>
  </>;
}

function QuestionItem({ index, question, snapshot, context, editable, busy, amend }: {
  index: number;
  question: ReportSourceCatalog["questions"][number];
  snapshot: ReportSnapshot;
  context: ReportContext;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
}) {
  const answer = snapshot.answers.find((item) => item.question_id === question.question_id);
  const [chosenFindingId, setFindingId] = useState("");
  // The catalog can arrive after this editor mounts; until the expert picks
  // another, the finding the select shows is the one the answer binds.
  const findingId = question.findings.some((item) => item.finding_id === chosenFindingId) ? chosenFindingId : question.findings[0]?.finding_id ?? "";
  const [text, setText] = useState(answer?.text ?? "");
  const cited = (id: string) => snapshot.claims.some((claim) => claim.provenance.some((item) => item.source_kind === "TECHNICAL_FINDING" && item.source_id === id));
  const finding = question.findings.find((item) => item.finding_id === (answer?.finding_id ?? findingId));
  const findingsSection = snapshot.sections.find((item) => item.kind === "TECHNICAL_FINDINGS");
  const origin = context.case.kind === "ready" ? context.case.value.questions.find((item) => item.item_id === question.question_id)?.source_question : undefined;
  return <div className="report-question" id={`report-question-${question.question_id}`} tabIndex={-1}>
    <h4>Quesito {origin?.original_number ?? index}{origin ? ` · ${{ COURT: "Juízo", CLAIMANT: "Parte requerente", DEFENDANT: "Parte requerida" }[origin.origin]}` : " · ordem neste capítulo"}</h4>
    <p>{question.text ?? "Texto do quesito não disponível."}</p>
    <p className="report-nature">{answer ? snapshot.state === "APPROVED" ? "Resposta no laudo aprovado" : snapshot.state === "REVIEWED" ? "Resposta no laudo revisado · aguarda aprovação" : "Resposta registrada · validação do perito na Revisão" : "Informação pendente · resposta em elaboração"}</p>
    <details className="report-provenance"><summary>Origem e fundamento deste quesito</summary><QuestionSource questionId={question.question_id} context={context} />{finding && <FindingBasis findingId={finding.finding_id} context={context} />}</details>
    {answer && <span id={`report-answer-${snapshot.answers.indexOf(answer) + 1}`} tabIndex={-1} />}
    {answer
      ? <>
        {editable ? <label>Resposta<textarea value={text} onChange={(event) => setText(event.target.value)} disabled={busy} /></label> : <p className="report-answer"><strong>Resposta:</strong> {answer.text}</p>}
        <p className="field-hint">Baseada no achado: {finding?.label ?? "achado vinculado"}</p>
        {editable && <div className="action-row"><button className="secondary-action" type="button" disabled={busy || !text.trim() || text.trim() === answer.text} onClick={() => void amend("UPDATE_ANSWER_TEXT", { answer_id: answer.answer_id, text }, "Não foi possível salvar a resposta.")}>Salvar resposta</button><button className="text-action" type="button" disabled={busy} onClick={() => void amend("REMOVE_ANSWER", { answer_id: answer.answer_id }, "Não foi possível remover a resposta.")}>Remover resposta</button></div>}
      </>
      : editable
        ? question.findings.length === 0
          ? <p className="report-empty">Nenhum achado efetivo vinculado a este quesito ainda.</p>
          : <form className="report-add" onSubmit={(event) => { event.preventDefault(); if (text.trim()) void amend("ANSWER_QUESTION", { question_id: question.question_id, finding_id: findingId, text: text.trim() }, "Não foi possível registrar a resposta."); }}>
            <label>Achado que fundamenta a resposta<select value={findingId} onChange={(event) => setFindingId(event.target.value)}>{question.findings.map((item) => <option key={item.finding_id} value={item.finding_id}>{item.label}</option>)}</select></label>
            {findingId && !cited(findingId) && findingsSection
              ? <div className="inline-note"><p>Este achado ainda não aparece no texto do laudo. A resposta precisa citá-lo.</p><button className="secondary-action" type="button" disabled={busy} onClick={() => void amend("ADD_CLAIM", { section_id: findingsSection.section_id, text: finding?.label ?? "", source_kind: "TECHNICAL_FINDING", source_id: findingId }, "Não foi possível incluir o achado.")}>Incluir o achado em “Achados Técnicos”</button></div>
              : <>
                <label>Resposta<textarea required value={text} onChange={(event) => setText(event.target.value)} /></label>
                <button className="primary-action" type="submit" disabled={busy || !text.trim()}>Registrar resposta</button>
              </>}
          </form>
        : <p className="report-empty">Sem resposta.</p>}
    {answer && <TechnicalDetails><span className="data">{answer.answer_id} · achado {answer.finding_id} · decisão {answer.decision_id} · evidências {answer.evidence_ids.join(", ")} · métodos {answer.method_ids.join(", ")}</span></TechnicalDetails>}
  </div>;
}

function ContextPanel({ snapshot, sources, editable, busy, onSave }: {
  snapshot: ReportSnapshot;
  sources: ReportSourceCatalog | null;
  editable: boolean;
  busy: boolean;
  onSave: (field: string, sourceId: string, note: string) => Promise<boolean>;
}) {
  return <section className="analysis-section report-context" aria-labelledby="report-context-title">
    <h3 id="report-context-title">Contexto processual (art. 319)</h3>
    <ul className="review-checklist">{snapshot.context_matrix.map((item) => <li key={item.context_id} data-done={item.status === "PRESENT" || undefined}>
      <span className="review-check-mark" aria-hidden="true">{item.status === "PRESENT" ? "✓" : "!"}</span>
      <ContextField item={item} options={sources?.context_sources[item.field as keyof ReportSourceCatalog["context_sources"]] ?? []} editable={editable} busy={busy} onSave={onSave} />
    </li>)}</ul>
  </section>;
}

function ContextField({ item, options, editable, busy, onSave }: {
  item: ReportSnapshot["context_matrix"][number];
  options: Array<{ id: string; label: string }>;
  editable: boolean;
  busy: boolean;
  onSave: (field: string, sourceId: string, note: string) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [sourceId, setSourceId] = useState(item.source_id ?? "");
  const [note, setNote] = useState(item.status === "PRESENT" ? item.note : "");
  const chosen = options.find((option) => option.id === item.source_id);
  return <div>
    <strong>{CONTEXT_LABELS[item.field] ?? item.field}</strong>
    <span>{item.status === "PRESENT" ? `${item.note}${chosen ? ` · fonte: ${chosen.label}` : ""}` : "Pendente"}</span>
    {editable && !open && <button className="text-action" type="button" onClick={() => setOpen(true)}>{item.status === "PRESENT" ? "Alterar" : "Preencher"}</button>}
    {editable && open && <form className="report-add" onSubmit={async (event) => { event.preventDefault(); if (sourceId && note.trim() && await onSave(item.field, sourceId, note.trim())) setOpen(false); }}>
      <label>Fonte<select required value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">Selecione</option>{options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
      <label>Como aparece no laudo<textarea required value={note} onChange={(event) => setNote(event.target.value)} /></label>
      <div className="action-row"><button className="primary-action" type="submit" disabled={busy || !sourceId || !note.trim()}>Salvar</button><button className="text-action" type="button" onClick={() => setOpen(false)}>Cancelar</button></div>
    </form>}
  </div>;
}

function AuditTrailButton({ workspaceId }: { workspaceId: string }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const download = async () => {
    setBusy(true); setFailed(false);
    try {
      const trail = await getReportAuditTrail(workspaceId);
      const blob = new Blob([trail.lines.join("\n") + "\n"], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `trilha-de-auditoria-laudo-r${trail.revision}.txt`;
      document.body.append(link); link.click(); link.remove();
      URL.revokeObjectURL(url);
    } catch { setFailed(true); } finally { setBusy(false); }
  };
  return <>
    <button className="text-action" type="button" disabled={busy} onClick={() => void download()}>{busy ? "Preparando trilha…" : "Baixar trilha de auditoria"}</button>
    {failed && <span role="alert" className="field-hint">Não foi possível exportar a trilha de auditoria.</span>}
  </>;
}


