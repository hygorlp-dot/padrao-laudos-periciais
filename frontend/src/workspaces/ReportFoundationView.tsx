import { type FormEvent, useEffect, useMemo, useState } from "react";

import { navigate } from "../app/router";
import { useRefreshExpertIdentity } from "../data/expertIdentity";
import {
  amendReportDraft,
  getExpertProfile,
  getReportAuditTrail,
  getReportSnapshot,
  getReportSources,
  ReportApiError,
  saveExpertProfile,
  startReportSnapshot,
  startReportVersion,
  referenceCitation,
  getAIAssistantStatus,
  type AIAssistantStatus,
  type EditorialProfile,
  type ReportAmendment,
  type ReportReference,
  type ReportReferenceKind,
  type ReportEnvelope,
  type ReportSnapshot,
  type ReportSourceCatalog,
  type ReportSourceKind,
} from "../data/reportSnapshot";
import { workspacePath } from "../routes/routeCatalog";
import { authorityLabel, sourceKindLabel, stateLabel } from "../ui/labels";
import { TechnicalDetails } from "../ui/TechnicalDetails";
import { coordinatesText } from "../data/siteLocation";

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
  const [state, setState] = useState<State>({ kind: "loading" });
  const [sources, setSources] = useState<ReportSourceCatalog | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [versionNotice, setVersionNotice] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const refreshExpert = useRefreshExpertIdentity();
  const [profile, setProfile] = useState({ full_name: "", professional_title: "", registration: "", court_registration: "", contact_line: "" });
  const [formError, setFormError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getExpertProfile(workspaceId, controller.signal).then(
      () => getReportSnapshot(workspaceId, controller.signal).then(
        (value) => setState({ kind: "ready", value }),
        (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof ReportApiError && error.kind === "not-found" ? "report-missing" : "error" }); },
      ),
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof ReportApiError && error.kind === "not-found" ? "profile-missing" : "error" }); },
    );
    getReportSources(workspaceId, controller.signal).then(setSources, () => { if (!controller.signal.aborted) setSources(null); });
    return () => controller.abort();
  }, [workspaceId, version]);

  const configure = async (event: FormEvent) => {
    event.preventDefault(); setFormError(false);
    if (Object.values(profile).some((value) => !value.trim())) { setFormError(true); return; }
    setBusy(true);
    try {
      await saveExpertProfile(workspaceId, { profile_id: "EXPERT-PROFILE-001", revision: 1, full_name: profile.full_name.trim(), professional_title: profile.professional_title.trim(), registration: profile.registration.trim(), court_registration: profile.court_registration.trim(), contact_line: profile.contact_line.trim() });
      refreshExpert();
      setState({ kind: "ready", value: await startReportSnapshot(workspaceId) });
    } catch { setState({ kind: "error" }); } finally { setBusy(false); }
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
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível carregar o laudo</h2><p>Os dados salvos do laudo não passaram na conferência de integridade. Nada foi alterado.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  if (state.kind === "profile-missing") return <section className="technical-authority"><h2>Configure o perfil mestre do perito</h2><p>Esta fonte única preenche a identificação profissional sem alterar conclusões técnicas.</p><form onSubmit={configure}><label>Nome completo<input required aria-invalid={formError} value={profile.full_name} onChange={(event) => setProfile({ ...profile, full_name: event.target.value })}/></label><label>Título profissional<input required aria-invalid={formError} value={profile.professional_title} onChange={(event) => setProfile({ ...profile, professional_title: event.target.value })}/></label><label>Registro profissional<input required aria-invalid={formError} value={profile.registration} onChange={(event) => setProfile({ ...profile, registration: event.target.value })}/></label><label>Cadastro no tribunal<input required aria-invalid={formError} value={profile.court_registration} onChange={(event) => setProfile({ ...profile, court_registration: event.target.value })}/></label><label>Contato profissional<input required aria-invalid={formError} value={profile.contact_line} onChange={(event) => setProfile({ ...profile, contact_line: event.target.value })}/></label>{formError && <p role="alert">Complete todos os campos obrigatórios do perfil mestre.</p>}<button className="primary-action" type="submit" disabled={busy}>{busy ? "Salvando…" : "Salvar perfil e iniciar laudo"}</button></form></section>;
  if (state.kind === "report-missing") return <section className="status-state status-state--empty"><span className="empty-sheet" aria-hidden="true"><span /><span /><span /></span><div><h2>Laudo ainda não iniciado</h2><p>O laudo reúne as análises e decisões já registradas. Nada é redigido automaticamente.</p><button className="primary-action" type="button" disabled={busy} onClick={async () => { setBusy(true); try { setState({ kind: "ready", value: await startReportSnapshot(workspaceId) }); } catch { setState({ kind: "error" }); } finally { setBusy(false); } }}>{busy ? "Iniciando…" : "Iniciar laudo"}</button></div></section>;

  const { snapshot } = state.value;
  const editable = snapshot.state === "DRAFT" && !snapshot.upstream_stale && snapshot.review_decisions.length === 0;
  const coverage = snapshot.coverage;
  const unanswered = (sources?.questions ?? []).filter((question) => !snapshot.answers.some((answer) => answer.question_id === question.question_id)).length;

  return <section className="report-authoring" aria-labelledby="report-title">
    <header className="technical-header"><div><h2 id="report-title">Laudo técnico</h2><p>{snapshot.expert_profile.full_name} · {snapshot.expert_profile.registration}</p><span className="status-pill" data-tone={snapshot.state === "APPROVED" ? "done" : snapshot.state === "SUPERSEDED" ? "warn" : undefined}>{stateLabel(snapshot.state)}</span></div><div className="planning-readiness"><strong>{coverage.cpc473_present_sections} de {coverage.cpc473_required_sections} seções obrigatórias</strong><span>Contexto processual {coverage.context_present_fields} de {coverage.context_required_fields} · {unanswered === 0 ? "quesitos respondidos" : `${unanswered} ${unanswered === 1 ? "quesito sem resposta" : "quesitos sem resposta"}`}</span></div></header>
    {snapshot.upstream_stale && <section className="analysis-inventory-warning" role="alert"><strong>Fontes anteriores mudaram — o laudo precisa de uma nova versão</strong><ul>{snapshot.upstream_stale_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></section>}
    {!editable && !snapshot.upstream_stale && snapshot.state !== "SUPERSEDED" && <p className="field-hint">O laudo está {stateLabel(snapshot.state).toLowerCase()}; o texto fica bloqueado para edição. Para alterar, marque-o como substituído em Revisão e inicie uma nova versão aqui.</p>}
    {(snapshot.upstream_stale || snapshot.state === "SUPERSEDED") && <section className="analysis-section report-version"><h3>Nova versão do laudo</h3><p>A nova versão abre um rascunho vinculado às fontes atuais. O que elas ainda sustentam é mantido; o que deixou de existir sai e é listado para você. A revisão e a aprovação recomeçam, e as versões anteriores ficam no histórico.</p><button className="primary-action" type="button" disabled={busy} onClick={() => void newVersion()}>{busy ? "Abrindo nova versão…" : "Iniciar nova versão do laudo"}</button></section>}
    {versionNotice && <section className="inline-note" role="status"><strong>Nova versão aberta em rascunho.</strong><p>{versionNotice}</p><button className="text-action" type="button" onClick={() => setVersionNotice(null)}>Fechar aviso</button></section>}
    {actionError && <section className="inline-alert" role="alert"><strong>{actionError}</strong><p>O laudo continua como estava. Confira a fonte escolhida e tente de novo.</p><button className="text-action" type="button" onClick={() => setActionError(null)}>Fechar aviso</button></section>}
    {sources === null && <p className="field-hint" role="status">As fontes para citação não puderam ser carregadas. Os textos existentes continuam visíveis.</p>}

    <EditorialPanel profile={snapshot.editorial_profile} editable={editable} busy={busy} onSave={(profile) => amend("SET_EDITORIAL_PROFILE", { editorial_profile: profile }, "Não foi possível salvar o padrão editorial.")} />

    <AssistantPanel />

    <FiguresPanel snapshot={snapshot} editable={editable} busy={busy} amend={amend} workspaceId={workspaceId} />

    <ContextPanel snapshot={snapshot} sources={sources} editable={editable} busy={busy} onSave={(field, sourceId, note) => amend("UPDATE_CONTEXT", { field, status: "PRESENT", source_id: sourceId, note }, "Não foi possível atualizar o contexto processual.")} />

    <ol className="report-sections" aria-label="Seções do laudo">{snapshot.sections.slice().sort((a, b) => a.order - b.order).map((section) => (
      <li key={section.section_id}>
        <SectionEditor section={section} snapshot={snapshot} sources={sources} editable={editable} busy={busy} amend={amend} />
      </li>
    ))}</ol>

    <section className="analysis-section report-next"><h3>Próximo passo</h3><p>Quando o conteúdo estiver completo, confira e aprove o laudo em Revisão. A aprovação libera a geração do Word e do PDF.</p><div className="action-row"><a className="primary-action" href={workspacePath(workspaceId, "revisao")} onClick={navigate}>Conferir em Revisão</a><AuditTrailButton workspaceId={workspaceId} /></div></section>
  </section>;
}

function sourceLabel(sources: ReportSourceCatalog | null, kind: string, id: string) {
  return sources?.sources.find((item) => item.kind === kind && item.id === id)?.label;
}

function SectionEditor({ section, snapshot, sources, editable, busy, amend }: {
  section: Section;
  snapshot: ReportSnapshot;
  sources: ReportSourceCatalog | null;
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
    <header><h3 id={titleId}>{section.order}. {section.title}</h3>{section.required_by_cpc473 && <span className="status-pill" data-tone={claims.length ? "done" : "warn"}>{claims.length ? "Obrigatória · preenchida" : "Obrigatória · pendente"}</span>}</header>
    {empty && <p className="report-empty">{section.required_by_cpc473 ? "Seção obrigatória ainda sem conteúdo." : "Sem conteúdo. Seções vazias não aparecem no documento final."}</p>}
    {section.kind === "INSPECTION" && <SiteLocationCitation snapshot={snapshot} editable={editable} busy={busy} amend={amend} />}
    {section.kind === "TECHNICAL_FINDINGS" && <FindingsTablePanel snapshot={snapshot} editable={editable} busy={busy} amend={amend} />}
    {claims.map((claim) => <ClaimEditor key={`${claim.claim_id}:${claim.text}`} claim={claim} sources={sources} references={snapshot.references ?? []} crossReferences={crossReferences(snapshot)} editable={editable} busy={busy} amend={amend} protectedByAnswer={snapshot.answers.some((answer) => answer.claim_ids.includes(claim.claim_id))} />)}
    {section.kind === "REFERENCES" && <ReferencesPanel references={snapshot.references ?? []} editable={editable} busy={busy} amend={amend} />}
    {section.kind === "ANSWERS_TO_QUESTIONS" && <QuestionsEditor snapshot={snapshot} sources={sources} editable={editable} busy={busy} amend={amend} />}
    {editable && sources && (adding
      ? <AddClaimForm section={section} sources={sources} busy={busy} onCancel={() => setAdding(false)} onAdd={async (kind, id, text) => { if (await amend("ADD_CLAIM", { section_id: section.section_id, text, source_kind: kind, source_id: id }, "Não foi possível adicionar o texto.")) setAdding(false); }} />
      : <button className="secondary-action" type="button" onClick={() => setAdding(true)}>Adicionar texto a esta seção</button>)}
  </article>;
}

function ClaimEditor({ claim, sources, references, crossReferences: targets, editable, busy, amend, protectedByAnswer }: {
  claim: ReportSnapshot["claims"][number];
  sources: ReportSourceCatalog | null;
  references: ReportReference[];
  crossReferences: Array<{ marker: string; label: string }>;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
  protectedByAnswer: boolean;
}) {
  // Remontado pela key quando o texto salvo muda; o rascunho local é só do editor.
  const [text, setText] = useState(claim.text);
  const provenance = claim.provenance[0];
  const label = provenance ? sourceLabel(sources, provenance.source_kind, provenance.source_id) : undefined;
  return <div className="report-claim">
    {editable
      ? <label className="report-claim-text">Texto<textarea value={text} onChange={(event) => setText(event.target.value)} disabled={busy} /></label>
      : <p>{claim.text}</p>}
    {editable && targets.length > 0 && <label className="report-cite">Inserir referência a figura ou tabela<select value="" disabled={busy} onChange={(event) => { if (event.target.value) setText(`${text.trimEnd()} ${event.target.value}`); }}><option value="">Escolha</option>{targets.map((item) => <option key={item.marker} value={item.marker}>{item.label}</option>)}</select></label>}
    {editable && targets.length > 0 && /\[\[(FIGURA|TABELA):/.test(text) && <p className="field-hint">No documento, cada marcador vira “Figura N” ou “Tabela 1” conforme a ordem final: {presentMarkers(text, targets)}</p>}
    {editable && references.length > 0 && <label className="report-cite">Inserir citação<select value="" disabled={busy} onChange={(event) => { const chosen = references.find((item) => item.reference_id === event.target.value); if (chosen) setText(`${text.trimEnd()} ${referenceCitation(chosen)}`); }}><option value="">Escolha a referência</option>{references.map((item) => <option key={item.reference_id} value={item.reference_id}>{referenceCitation(item)} — {item.title}</option>)}</select></label>}
    <p className="report-claim-source"><span className="status-pill">{authorityLabel(claim.authority)}</span> Fonte: {sourceKindLabel(provenance?.source_kind)}{label ? ` — ${label}` : ""}</p>
    {editable && <div className="action-row">
      <button className="secondary-action" type="button" disabled={busy || !text.trim() || text.trim() === claim.text} onClick={() => void amend("UPDATE_CLAIM_TEXT", { claim_id: claim.claim_id, text }, "Não foi possível salvar o texto.")}>Salvar texto</button>
      <button className="text-action" type="button" disabled={busy || protectedByAnswer} title={protectedByAnswer ? "Este texto sustenta a resposta a um quesito." : undefined} onClick={() => void amend("REMOVE_CLAIM", { claim_id: claim.claim_id }, "Não foi possível remover o texto.")}>Remover</button>
    </div>}
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
  const bound = snapshot.source_snapshot.construction_defect_analysis_snapshot_id !== null;
  if (!rows.length && !(editable && bound)) return null;
  return <div className="report-findings-table">
    {rows.length > 0 && <table>
      <caption>Tabela 1 – Resumo dos achados técnicos</caption>
      <thead><tr><th scope="col">Item</th><th scope="col">Manifestação</th><th scope="col">Ambiente</th><th scope="col">Achado</th><th scope="col">Situação</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={row.provenance.provenance_id}><td>{index + 1}</td><td>{row.manifestation}</td><td>{row.environment ?? "Não informado"}</td><td>{row.finding}</td><td>{row.situation ? SITUATION_LABEL[row.situation] ?? row.situation : "Não informada"}</td></tr>)}</tbody>
    </table>}
    {editable && <>
      <p className="field-hint">{rows.length ? "A tabela repete o que as patologias aprovadas registram; se a análise mudar, atualize-a." : "Monte a tabela-resumo a partir das patologias aprovadas na análise de vícios. Nada é inferido: cada linha repete o registro."}</p>
      <div className="action-row">
        <button className="secondary-action" type="button" disabled={busy || !bound} onClick={() => void amend("SET_FINDINGS_TABLE", {}, "Não foi possível montar a tabela-resumo. Confira se há patologias aprovadas com manifestação e achado descritos.")}>{rows.length ? "Atualizar tabela-resumo" : "Inserir tabela-resumo dos achados"}</button>
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
    <label>Tipo de fonte<select value={kind} onChange={(event) => { setKind(event.target.value as ReportSourceKind); setSourceId(""); }}>{kinds.map((item) => <option key={item} value={item}>{sourceKindLabel(item)}</option>)}</select></label>
    <label>Fonte<select required value={sourceId} onChange={(event) => { setSourceId(event.target.value); const chosen = options.find((item) => item.id === event.target.value); if (chosen && !text.trim()) setText(chosen.label); }}><option value="">Selecione</option>{options.map((item) => <option key={`${item.kind}-${item.id}`} value={item.id}>{item.label}</option>)}</select></label>
    <label>Texto do laudo<textarea required value={text} onChange={(event) => setText(event.target.value)} /></label>
    <small className="field-hint">O texto é a sua redação; a fonte escolhida define a autoridade do trecho e não pode ser promovida pela redação.</small>
    <div className="action-row"><button className="primary-action" type="submit" disabled={busy || !kind || !sourceId || !text.trim()}>Adicionar ao laudo</button><button className="text-action" type="button" onClick={onCancel}>Cancelar</button></div>
  </form>;
}

function QuestionsEditor({ snapshot, sources, editable, busy, amend }: {
  snapshot: ReportSnapshot;
  sources: ReportSourceCatalog | null;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
}) {
  const questions = sources?.questions ?? [];
  const legacy = snapshot.answers.filter((answer) => !questions.some((question) => question.question_id === answer.question_id));
  if (questions.length === 0 && snapshot.answers.length === 0) return <p className="report-empty">Nenhum quesito vinculado a achado técnico. Vincule quesitos a achados em Evidências.</p>;
  return <ol className="report-questions">
    {questions.map((question, index) => <li key={question.question_id}><QuestionItem key={snapshot.answers.find((item) => item.question_id === question.question_id)?.text ?? ""} index={index + 1} question={question} snapshot={snapshot} editable={editable} busy={busy} amend={amend} /></li>)}
    {legacy.map((answer) => <li key={answer.answer_id}><div className="report-question"><h4>Quesito</h4><p>{answer.question_text ?? "Texto do quesito não disponível."}</p><p className="report-answer"><strong>Resposta:</strong> {answer.text}</p></div></li>)}
  </ol>;
}

function QuestionItem({ index, question, snapshot, editable, busy, amend }: {
  index: number;
  question: ReportSourceCatalog["questions"][number];
  snapshot: ReportSnapshot;
  editable: boolean;
  busy: boolean;
  amend: (action: ReportAmendment, values: Record<string, unknown>, failure: string) => Promise<boolean>;
}) {
  const answer = snapshot.answers.find((item) => item.question_id === question.question_id);
  const [findingId, setFindingId] = useState(question.findings[0]?.finding_id ?? "");
  const [text, setText] = useState(answer?.text ?? "");
  const cited = (id: string) => snapshot.claims.some((claim) => claim.provenance.some((item) => item.source_kind === "TECHNICAL_FINDING" && item.source_id === id));
  const finding = question.findings.find((item) => item.finding_id === (answer?.finding_id ?? findingId));
  const findingsSection = snapshot.sections.find((item) => item.kind === "TECHNICAL_FINDINGS");
  return <div className="report-question">
    <h4>Quesito {index}</h4>
    <p>{question.text ?? "Texto do quesito não disponível."}</p>
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

// O preset do produto (Justiça Plural, cap. 4). Restaurar envia exatamente isto.
const EDITORIAL_PRESET: EditorialProfile = { profile_id: "JUSTICA_PLURAL_CHAPTER_4", font_family: "Arial", body_font_pt: 11, table_font_pt: 10, caption_font_pt: 9, alignment: "JUSTIFIED", line_spacing: 1.15, first_line_indent_cm: 1.25, page_size: "A4", margin_top_cm: 2, margin_bottom_cm: 2, margin_left_cm: 3, margin_right_cm: 2, hyphenation: false, overrides: [] };
const TYPOGRAPHY_DEFAULT = { heading1_pt: 14, heading2_pt: 12, heading3_pt: 11, headings_bold: true, heading_space_before_pt: 12, heading_space_after_pt: 6, paragraph_space_after_pt: 6 };
const FONTS = ["Arial", "Calibri", "Cambria", "Georgia", "Times New Roman", "Verdana"];

function EditorialPanel({ profile, editable, busy, onSave }: { profile: EditorialProfile; editable: boolean; busy: boolean; onSave: (profile: EditorialProfile) => Promise<boolean> }) {
  const current = { ...EDITORIAL_PRESET, ...profile };
  const [draft, setDraft] = useState<EditorialProfile>(current);
  const [typography, setTypography] = useState({ ...TYPOGRAPHY_DEFAULT, ...(profile.typography ?? {}) });
  const isPreset = profile.profile_id === "JUSTICA_PLURAL_CHAPTER_4";
  const number = (value: string) => Number(value.replace(",", "."));
  const field = (label: string, key: keyof EditorialProfile, min: number, max: number, step: number) => (
    <label>{label}<input type="number" min={min} max={max} step={step} value={Number(draft[key] ?? 0)} disabled={!editable || busy} onChange={(event) => setDraft({ ...draft, [key]: number(event.target.value) })} /></label>
  );
  const heading = (label: string, key: keyof typeof TYPOGRAPHY_DEFAULT, min: number, max: number) => (
    <label>{label}<input type="number" min={min} max={max} step={1} value={Number(typography[key])} disabled={!editable || busy} onChange={(event) => setTypography({ ...typography, [key]: number(event.target.value) })} /></label>
  );
  const save = () => {
    void onSave({ ...draft, profile_id: "CUSTOM", typography: { ...typography } });
  };
  return <details className="analysis-section report-editorial">
    <summary><strong>Padrão editorial</strong> <span className="field-hint">{isPreset ? "Padrão do produto" : "Personalizado"} · {current.font_family} {current.body_font_pt} pt · entrelinha {String(current.line_spacing).replace(".", ",")} · recuo {String(current.first_line_indent_cm).replace(".", ",")} cm</span></summary>
    <p className="field-hint">Vale para o modelo padrão do produto usado na entrega. Um modelo Word próprio mantém a formatação do seu arquivo.</p>
    <fieldset disabled={!editable || busy}><legend>Corpo do texto</legend>
      <label>Fonte<select value={draft.font_family} onChange={(event) => setDraft({ ...draft, font_family: event.target.value })}>{FONTS.map((font) => <option key={font}>{font}</option>)}</select></label>
      {field("Tamanho (pt)", "body_font_pt", 10, 14, 1)}
      <label>Alinhamento<select value={draft.alignment} onChange={(event) => setDraft({ ...draft, alignment: event.target.value })}><option value="JUSTIFIED">Justificado</option><option value="LEFT">À esquerda</option></select></label>
      <label>Entrelinha<select value={String(draft.line_spacing)} onChange={(event) => setDraft({ ...draft, line_spacing: Number(event.target.value) })}>{[1, 1.15, 1.5, 2].map((value) => <option key={value} value={String(value)}>{String(value).replace(".", ",")}</option>)}</select></label>
      {field("Recuo da primeira linha (cm)", "first_line_indent_cm", 0, 3, 0.25)}
      {heading("Espaço após parágrafo (pt)", "paragraph_space_after_pt", 0, 36)}
    </fieldset>
    <fieldset disabled={!editable || busy}><legend>Títulos</legend>
      {heading("Título 1 (pt)", "heading1_pt", 12, 20)}
      {heading("Título 2 (pt)", "heading2_pt", 11, 16)}
      {heading("Título 3 (pt)", "heading3_pt", 10, 14)}
      <label className="checkbox-label"><input type="checkbox" checked={typography.headings_bold} onChange={(event) => setTypography({ ...typography, headings_bold: event.target.checked })} /> Títulos em negrito</label>
      {heading("Espaço antes do título (pt)", "heading_space_before_pt", 0, 36)}
      {heading("Espaço após o título (pt)", "heading_space_after_pt", 0, 36)}
    </fieldset>
    <fieldset disabled={!editable || busy}><legend>Tabelas, legendas e página A4</legend>
      {field("Tabelas (pt)", "table_font_pt", 8, 12, 1)}
      {field("Legendas (pt)", "caption_font_pt", 8, 11, 1)}
      {field("Margem superior (cm)", "margin_top_cm", 1.5, 4, 0.5)}
      {field("Margem inferior (cm)", "margin_bottom_cm", 1.5, 4, 0.5)}
      {field("Margem esquerda (cm)", "margin_left_cm", 1.5, 4, 0.5)}
      {field("Margem direita (cm)", "margin_right_cm", 1.5, 4, 0.5)}
    </fieldset>
    {editable && <div className="action-row"><button className="primary-action" type="button" disabled={busy} onClick={save}>Salvar padrão editorial</button><button className="text-action" type="button" disabled={busy || isPreset} onClick={() => void onSave(EDITORIAL_PRESET)}>Restaurar padrão do produto</button></div>}
  </details>;
}
