import { type FormEvent, useEffect, useState } from "react";

import {
  artifactDownloadUrl,
  attachDeliveryPackageArtifact,
  deliverDeliverySnapshot,
  DeliveryApiError,
  finalizeDeliverySnapshot,
  getDeliveryHistory,
  getDeliverySnapshot,
  renderDeliveryPackage,
  reissueDeliverySnapshot,
  reviewDeliverySnapshot,
  startDeliverySnapshot,
  templateManifest,
  uploadDeliveryTemplate,
  uploadDeliverySupportingFile,
  type DeliveryEnvelope,
} from "../data/deliverySnapshot";
import { plural, stateLabel } from "../ui/labels";
import { TechnicalDetails } from "../ui/TechnicalDetails";

const ROLE_LABELS: Record<string, string> = {
  MAIN_REPORT: "Laudo em Word · documento oficial",
  DERIVED_PDF: "Laudo em PDF · derivado do Word",
  ANNEX: "Anexo",
  PHOTO_APPENDIX: "Apêndice fotográfico",
  TECHNICAL_APPENDIX: "Apêndice técnico",
  SUPPORTING_FILE: "Arquivo de apoio",
};

type ViewState = { kind: "loading" } | { kind: "missing" } | { kind: "ready"; value: DeliveryEnvelope } | { kind: "error" };
type Action = "render" | "ready" | "approve" | "finalize" | "deliver" | "supersede";

const ACTION_FAILURE: Record<Action | "template" | "attach", string> = {
  render: "Não foi possível gerar o Word desta entrega.",
  ready: "Não foi possível enviar a entrega para revisão.",
  approve: "Não foi possível aprovar a entrega.",
  finalize: "Não foi possível finalizar os arquivos.",
  deliver: "Não foi possível registrar a entrega.",
  supersede: "Não foi possível marcar a entrega como substituída.",
  template: "Não foi possível guardar o modelo e iniciar a entrega.",
  attach: "Não foi possível adicionar o arquivo ao pacote.",
};

export function DeliveryFoundationView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [templateId, setTemplateId] = useState("");
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [history, setHistory] = useState<DeliveryEnvelope[]>([]);
  const [supportingFile, setSupportingFile] = useState<File | null>(null);
  const [supportingRole, setSupportingRole] = useState<"ANNEX" | "PHOTO_APPENDIX" | "TECHNICAL_APPENDIX" | "SUPPORTING_FILE">("ANNEX");
  // Uma ação que falha não apaga a tela: o estado anterior continua válido e visível.
  const [actionError, setActionError] = useState<{ action: Action | "template" | "attach"; retry?: () => void } | null>(null);
  const [loadVersion, setLoadVersion] = useState(0);
  const acceptMutation = (value: DeliveryEnvelope) => {
    setActionError(null);
    setState({ kind: "ready", value });
    void getDeliveryHistory(workspaceId).then(setHistory, () => undefined);
  };

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getDeliverySnapshot(workspaceId, controller.signal), getDeliveryHistory(workspaceId, controller.signal)]).then(
      ([value, revisions]) => { setState({ kind: "ready", value }); setHistory(revisions); },
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof DeliveryApiError && error.kind === "not-found" ? "missing" : "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId, loadVersion]);

  const handleTemplate = async (reissue: boolean) => {
    if (!templateFile || !templateId.trim()) return;
    const format = templateFile.name.toLowerCase().endsWith(".docm") ? "DOCM" : "DOCX";
    setBusy(true); setActionError(null);
    try {
      const metadata = await uploadDeliveryTemplate(workspaceId, templateFile);
      const manifest = templateManifest(templateId.trim(), format);
      const value = reissue && state.kind === "ready"
        ? await reissueDeliverySnapshot(workspaceId, state.value, metadata, manifest)
        : await startDeliverySnapshot(workspaceId, metadata, manifest);
      acceptMutation(value); setTemplateFile(null); setTemplateId("");
    } catch { setActionError({ action: "template" }); } finally { setBusy(false); }
  };

  const transition = async (action: Action) => {
    if (state.kind !== "ready") return;
    setBusy(true); setRendering(action === "render"); setActionError(null);
    try {
      const value = action === "render" ? await renderDeliveryPackage(workspaceId, state.value)
        : action === "ready" ? await reviewDeliverySnapshot(workspaceId, state.value, "MARK_READY_FOR_REVIEW", reason)
          : action === "approve" ? await reviewDeliverySnapshot(workspaceId, state.value, "APPROVE", reason)
            : action === "finalize" ? await finalizeDeliverySnapshot(workspaceId, state.value, reason)
              : action === "deliver" ? await deliverDeliverySnapshot(workspaceId, state.value, reason)
                : await reviewDeliverySnapshot(workspaceId, state.value, "SUPERSEDE", reason);
      acceptMutation(value); setReason("");
    } catch { setActionError({ action, retry: () => void transition(action) }); } finally { setBusy(false); setRendering(false); }
  };
  const attachSupporting = async (event: FormEvent) => {
    event.preventDefault(); if (state.kind !== "ready" || !supportingFile) return; setBusy(true); setActionError(null);
    try { const stored = await uploadDeliverySupportingFile(workspaceId, supportingFile); const value = await attachDeliveryPackageArtifact(workspaceId, state.value, stored.content_id, supportingRole); acceptMutation(value); setSupportingFile(null); }
    catch { setActionError({ action: "attach" }); } finally { setBusy(false); }
  };

  const errorBanner = actionError && (
    <section className="inline-alert" role="alert">
      <strong>{ACTION_FAILURE[actionError.action]}</strong>
      <p>Nada foi alterado: a entrega continua como estava. Confira se o sistema local está em execução e tente de novo.</p>
      <div className="action-row">
        {actionError.retry && <button className="secondary-action" type="button" disabled={busy} onClick={actionError.retry}>Tentar novamente</button>}
        <button className="text-action" type="button" onClick={() => setActionError(null)}>Fechar aviso</button>
      </div>
    </section>
  );

  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Abrindo a entrega</h2><p>Conferindo os arquivos gerados e o vínculo com o laudo aprovado.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível abrir a entrega</h2><p>A integridade dos arquivos locais não pôde ser confirmada. Nenhum estado foi alterado.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setLoadVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  if (state.kind === "missing") return <>{errorBanner}<TemplateForm title="Iniciar entrega" busy={busy} templateId={templateId} file={templateFile} onId={setTemplateId} onFile={setTemplateFile} onSubmit={() => handleTemplate(false)} /></>;

  const { snapshot } = state.value;
  const stale = snapshot.state === "STALE";
  const rendered = snapshot.artifacts.some((artifact) => artifact.role === "MAIN_REPORT");
  const derivedPdf = snapshot.artifacts.some((artifact) => artifact.role === "DERIVED_PDF");
  return <section className="delivery-workbench" aria-labelledby="delivery-title">
    <header className="delivery-header"><div><h2 id="delivery-title">Entrega do laudo</h2><p>O Word é o documento oficial do laudo; o PDF é derivado dele. O protocolo no processo judicial acontece fora do sistema.</p></div><strong className={`delivery-state delivery-state--${snapshot.state.toLowerCase()}`}>{stateLabel(snapshot.state)}</strong></header>
    {errorBanner}
    {stale && <section className="analysis-inventory-warning" role="alert"><strong>Entrega desatualizada</strong><p>O laudo ou uma fonte vinculada mudou depois desta entrega. Os arquivos anteriores continuam preservados, mas não são apresentados como atuais.</p><ul>{snapshot.stale_reasons.map((item) => <li key={item}>{item}</li>)}</ul></section>}
    <section className="delivery-binding" aria-labelledby="binding-title"><h3 id="binding-title">Laudo vinculado</h3><dl><dt>Laudo</dt><dd>Revisão {snapshot.binding.report_revision}, aprovada</dd><dt>Modelo Word</dt><dd>{snapshot.template_id} · {snapshot.template_format}</dd></dl><TechnicalDetails><dl><dt>Laudo (snapshot)</dt><dd className="data">{snapshot.binding.report_snapshot_id}</dd><dt>Aprovação</dt><dd className="data">{snapshot.binding.report_approval_id}</dd><dt>Renderizador</dt><dd className="data">{snapshot.rendering_version}</dd><dt>SHA-256 do laudo</dt><dd><code>{snapshot.binding.report_digest}</code></dd><dt>SHA-256 do modelo</dt><dd><code>{snapshot.template_digest}</code></dd><dt>Revisão da entrega</dt><dd className="data">{state.value.revision}</dd></dl></TechnicalDetails></section>
    <section className="delivery-package" aria-labelledby="package-title"><div><h3 id="package-title">Arquivos da entrega</h3></div>{snapshot.artifacts.length === 0 ? <p>Nenhum arquivo gerado ainda. Gerar o Word não finaliza nem registra a entrega.</p> : <ul>{snapshot.artifacts.map((artifact) => <li key={artifact.artifact_id}><div><strong>{ROLE_LABELS[artifact.role] ?? artifact.role}</strong><span>{artifact.filename} · {formatBytes(artifact.byte_size)}</span><TechnicalDetails><code>SHA-256 {artifact.checksum_sha256}</code></TechnicalDetails></div><a className="text-action" href={artifactDownloadUrl(workspaceId, artifact.content_id)} download={artifact.filename}>Baixar {artifact.format === "PDF" ? "PDF" : artifact.role === "MAIN_REPORT" ? "Word" : "arquivo"}</a></li>)}</ul>}{rendered && (derivedPdf
      ? <p className="delivery-derived-pdf" role="status">PDF gerado a partir do Word pelo Microsoft Word desta máquina e conferido contra ele. O Word continua sendo o documento oficial.</p>
      : <section className="delivery-derived-pdf delivery-derived-pdf--unavailable" role="status"><strong>Não foi possível gerar o PDF.</strong><p>O documento Word continua válido e pode ser baixado.</p>{snapshot.state === "DRAFT" && <div className="action-row"><button className="secondary-action" type="button" disabled={busy} onClick={() => transition("render")}>Tentar novamente</button></div>}<TechnicalDetails summary="Ver detalhes"><p>O PDF só é oferecido quando o Microsoft Word desta máquina converte o documento e o resultado passa pela conferência de fidelidade com o Word. Causas comuns: o Word não está instalado ou disponível, a conversão excedeu o tempo limite, ou o PDF gerado não correspondeu ao Word. Nenhum PDF parcial é guardado.</p></TechnicalDetails></section>)}</section>
    <section className="delivery-signature" aria-labelledby="signature-title"><h3 id="signature-title">Assinatura</h3><p>O sistema não assina o laudo. Baixe o Word ou o PDF e assine no programa de assinatura digital ou no sistema judicial que você já utiliza.</p></section>
    {snapshot.state === "DRAFT" && <form className="delivery-supporting" onSubmit={attachSupporting}><h3>Adicionar arquivos ao pacote</h3><label>Função no pacote<select value={supportingRole} onChange={(event) => setSupportingRole(event.target.value as typeof supportingRole)}><option value="ANNEX">Anexo</option><option value="PHOTO_APPENDIX">Apêndice fotográfico</option><option value="TECHNICAL_APPENDIX">Apêndice técnico</option><option value="SUPPORTING_FILE">Arquivo de apoio</option></select></label><label>Arquivo<input type="file" required accept=".pdf,.docx,.docm,.jpg,.jpeg,.png" onChange={(event) => setSupportingFile(event.target.files?.[0] ?? null)}/></label><button className="secondary-action" type="submit" disabled={busy || !supportingFile}>Adicionar ao pacote</button></form>}
    <details className="delivery-history"><summary>Histórico preservado · {plural(history.length, "revisão", "revisões")}</summary><ol>{history.map((item) => <li key={`${item.snapshot.delivery_id}-${item.revision}`}><strong>Revisão {item.revision} · {stateLabel(item.snapshot.state)}</strong>{item.snapshot.artifacts.map((artifact) => <a key={artifact.artifact_id} href={artifactDownloadUrl(workspaceId, artifact.content_id)} download={artifact.filename}>Baixar {ROLE_LABELS[artifact.role] ?? artifact.filename}</a>)}<TechnicalDetails><span className="data">{item.snapshot.delivery_id}</span></TechnicalDetails></li>)}</ol></details>
    {!stale && snapshot.state !== "SUPERSEDED" && <section className="delivery-actions"><h3>Próximo passo</h3>{snapshot.state === "DRAFT" && <><button className="primary-action" type="button" disabled={busy} aria-busy={rendering} onClick={() => transition("render")}>{rendering ? "Gerando Word e PDF…" : rendered ? "Gerar novamente Word e PDF" : "Gerar Word e PDF"}</button><p>O Word é gerado a partir do laudo aprovado e é o documento oficial. O PDF é derivado dele pelo Microsoft Word desta máquina e só aparece depois de conferido; se a conversão falhar, nenhum PDF é oferecido.</p></>}<label>Fundamentação da decisão<textarea value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy}/></label><div className="action-row">{snapshot.state === "DRAFT" && snapshot.artifacts.length > 0 && <button className="authority-action" type="button" disabled={busy || !reason.trim()} onClick={() => transition("ready")}>Enviar para revisão</button>}{snapshot.state === "READY_FOR_REVIEW" && <button className="authority-action" type="button" disabled={busy || !reason.trim()} onClick={() => transition("approve")}>Aprovar entrega</button>}{snapshot.state === "APPROVED" && <button className="authority-action" type="button" disabled={busy || !reason.trim()} onClick={() => transition("finalize")}>Finalizar arquivos</button>}{snapshot.state === "FINALIZED" && <button className="authority-action" type="button" disabled={busy || !reason.trim()} onClick={() => transition("deliver")}>Registrar como entregue</button>}{snapshot.state === "DELIVERED" && <button className="destructive-action" type="button" disabled={busy || !reason.trim()} onClick={() => transition("supersede")}>Marcar como substituída</button>}</div></section>}
    {(snapshot.state === "SUPERSEDED" || (stale && snapshot.stale_origin_state === "DELIVERED")) && <TemplateForm title="Emitir nova revisão" busy={busy} templateId={templateId} file={templateFile} onId={setTemplateId} onFile={setTemplateFile} onSubmit={() => handleTemplate(true)} />}
  </section>;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value.toLocaleString("pt-BR")} bytes`;
  if (value < 1024 * 1024) return `${(value / 1024).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} KB`;
  return `${(value / (1024 * 1024)).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`;
}

function TemplateForm({ title, busy, templateId, file, onId, onFile, onSubmit }: { title: string; busy: boolean; templateId: string; file: File | null; onId: (value: string) => void; onFile: (value: File | null) => void; onSubmit: () => void }) {
  const submit = (event: FormEvent) => { event.preventDefault(); onSubmit(); };
  return <section className="delivery-template"><h2>{title}</h2><p>Escolha o modelo Word do laudo. O arquivo fica guardado só nesta máquina. O identificador precisa ser o mesmo gravado no modelo (propriedade TEMPLATE_ID).</p><form onSubmit={submit}><label>Identificador do modelo<input required value={templateId} onChange={(event) => onId(event.target.value)}/></label><label>Modelo Word (.docx ou .docm)<input required type="file" accept=".docx,.docm,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-word.document.macroEnabled.12" onChange={(event) => onFile(event.target.files?.[0] ?? null)}/></label><button className="primary-action" type="submit" disabled={busy || !file || !templateId.trim()}>{busy ? "Guardando modelo…" : "Usar este modelo e iniciar"}</button></form></section>;
}
