import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  attachDeliveryPackageArtifact,
  createDefaultTemplate,
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
import { DeliveryAudit, DeliveryFiles, DeliveryHistory } from "./DeliveryPresentation";
import { DELIVERY_LABELS } from "./deliveryLabels";
import "./delivery-editorial.css";

type ViewState = { kind: "loading" } | { kind: "missing" } | { kind: "ready"; value: DeliveryEnvelope } | { kind: "error" };
type Action = "render" | "ready" | "approve" | "finalize" | "deliver" | "supersede";

const ACTION_FAILURE: Record<Action | "template" | "attach", string> = {
  render: "Não foi possível confirmar a geração do Word.",
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
  const [historyUnavailable, setHistoryUnavailable] = useState(false);
  const [attachmentAdded, setAttachmentAdded] = useState(false);
  const [supportingFile, setSupportingFile] = useState<File | null>(null);
  const supportingInput = useRef<HTMLInputElement>(null);
  const [supportingRole, setSupportingRole] = useState<"ANNEX" | "PHOTO_APPENDIX" | "TECHNICAL_APPENDIX" | "SUPPORTING_FILE">("ANNEX");
  // Uma ação que falha não apaga a tela: o estado anterior continua válido e visível.
  const [actionError, setActionError] = useState<{ action: Action | "template" | "attach"; retry?: () => void } | null>(null);
  const [loadVersion, setLoadVersion] = useState(0);
  const acceptMutation = (value: DeliveryEnvelope) => {
    setActionError(null);
    setState({ kind: "ready", value });
    setHistoryUnavailable(false);
    void getDeliveryHistory(workspaceId).then(setHistory, () => setHistoryUnavailable(true));
  };

  useEffect(() => {
    const controller = new AbortController();
    void Promise.allSettled([getDeliverySnapshot(workspaceId, controller.signal), getDeliveryHistory(workspaceId, controller.signal)]).then(([current, revisions]) => {
      if (controller.signal.aborted) return;
      if (current.status === "rejected") {
        const missing = current.reason instanceof DeliveryApiError && current.reason.kind === "not-found";
        // Só a ausência do snapshot pode representar nenhuma entrega. Um erro
        // no histórico nunca é convertido em empty state de uma entrega existente.
        const historyMissing = revisions.status === "rejected" && revisions.reason instanceof DeliveryApiError && revisions.reason.kind === "not-found";
        setState({ kind: missing && (historyMissing || (revisions.status === "fulfilled" && revisions.value.length === 0)) ? "missing" : "error" });
      } else if (revisions.status === "rejected") setState({ kind: "error" });
      else { setState({ kind: "ready", value: current.value }); setHistory(revisions.value); }
    });
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

  const handleDefault = async (reissue: boolean) => {
    setBusy(true); setActionError(null);
    try {
      const { template, manifest } = await createDefaultTemplate(workspaceId);
      const value = reissue && state.kind === "ready"
        ? await reissueDeliverySnapshot(workspaceId, state.value, template, manifest)
        : await startDeliverySnapshot(workspaceId, template, manifest);
      acceptMutation(value);
    } catch { setActionError({ action: "template" }); } finally { setBusy(false); }
  };

  const transition = async (action: Action) => {
    if (state.kind !== "ready" || busy) return;
    setBusy(true); setRendering(action === "render"); setActionError(null);
    try {
      const value = action === "render" ? await renderDeliveryPackage(workspaceId, state.value)
        : action === "ready" ? await reviewDeliverySnapshot(workspaceId, state.value, "MARK_READY_FOR_REVIEW", reason)
          : action === "approve" ? await reviewDeliverySnapshot(workspaceId, state.value, "APPROVE", reason)
            : action === "finalize" ? await finalizeDeliverySnapshot(workspaceId, state.value, reason)
              : action === "deliver" ? await deliverDeliverySnapshot(workspaceId, state.value, reason)
                : await reviewDeliverySnapshot(workspaceId, state.value, "SUPERSEDE", reason);
      acceptMutation(value); setReason("");
    } catch { setActionError({ action, ...(action === "render" ? {} : { retry: () => void transition(action) }) }); } finally { setBusy(false); setRendering(false); }
  };
  const attachSupporting = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (state.kind !== "ready" || !supportingFile) return; setBusy(true); setActionError(null); setAttachmentAdded(false);
    try { const stored = await uploadDeliverySupportingFile(workspaceId, supportingFile); const value = await attachDeliveryPackageArtifact(workspaceId, state.value, stored.content_id, supportingRole); acceptMutation(value); setSupportingFile(null); if (supportingInput.current) supportingInput.current.value = ""; setAttachmentAdded(true); }
    catch { setActionError({ action: "attach" }); } finally { setBusy(false); }
  };

  const errorBanner = actionError && (
    <section className="inline-alert" role="alert">
      <strong>{ACTION_FAILURE[actionError.action]}</strong>
      <p>Não foi possível concluir esta operação. Confira a entrega e se o sistema local está em execução antes de tentar novamente.</p>
      <div className="action-row">
        <button className="secondary-action" type="button" disabled={busy} onClick={() => { setActionError(null); setState({ kind: "loading" }); setLoadVersion((v) => v + 1); }}>Verificar entrega</button>
        {actionError.retry && <button className="secondary-action" type="button" disabled={busy} onClick={actionError.retry}>Tentar novamente</button>}
        <button className="text-action" type="button" onClick={() => setActionError(null)}>Fechar aviso</button>
      </div>
    </section>
  );

  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Abrindo a entrega</h2><p>Conferindo os arquivos gerados e o vínculo com o laudo aprovado.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível verificar os arquivos desta entrega.</h2><p>O sistema local, o histórico ou a integridade dos arquivos não pôde ser verificado. A entrega não é apresentada como pronta.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setLoadVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  if (state.kind === "missing") return <div className="delivery-workbench">{errorBanner}<TemplateForm title="Preparar entrega" busy={busy} templateId={templateId} file={templateFile} onId={setTemplateId} onFile={setTemplateFile} onSubmit={() => handleTemplate(false)} onDefault={() => handleDefault(false)} /></div>;

  const { snapshot } = state.value;
  const stale = snapshot.state === "STALE";
  const rendered = snapshot.artifacts.some((artifact) => artifact.role === "MAIN_REPORT");
  const predecessor = history.filter((item) => item.snapshot.delivery_id === snapshot.supersedes_delivery_id).at(-1);
  const action: { command: Action; label: string; reasonLabel?: string; help: string } | null = snapshot.state === "DRAFT"
    ? rendered ? { command: "ready", label: "Enviar para conferência", reasonLabel: "Registro da conferência", help: "Confirme que os arquivos estão preparados para a conferência profissional." }
      : { command: "render", label: "Gerar arquivos do laudo", help: "O Word é gerado a partir do laudo aprovado. O PDF só fica disponível após a conversão local e a conferência com o Word." }
    : snapshot.state === "READY_FOR_REVIEW" ? { command: "approve", label: "Aprovar entrega", reasonLabel: "Motivo da aprovação", help: "Confira o documento oficial e os arquivos do pacote antes de aprovar." }
      : snapshot.state === "APPROVED" ? { command: "finalize", label: "Finalizar arquivos", reasonLabel: "Registro da finalização", help: "A finalização verifica novamente a integridade dos arquivos locais." }
        : snapshot.state === "FINALIZED" ? { command: "deliver", label: "Registrar como entregue", reasonLabel: "Registro da entrega", help: "Este registro é interno. O protocolo no processo judicial ocorre fora do sistema." } : null;
  return <section className="delivery-workbench" aria-labelledby="delivery-title" aria-busy={busy}>
    <header className="delivery-header"><div><h2 id="delivery-title">Entrega do laudo</h2><p className="delivery-status-text">{DELIVERY_LABELS[snapshot.state]}</p><p>Entrega · revisão {state.value.revision}</p><p>Laudo aprovado · revisão {snapshot.binding.report_revision}</p>
      {snapshot.supersedes_delivery_id && <p>{predecessor ? `Substitui entrega anterior · revisão ${predecessor.revision}` : "Substitui entrega anterior preservada no histórico"}</p>}
      {!stale && snapshot.state !== "SUPERSEDED" && <p>Atual em relação ao laudo e às autoridades vinculadas.</p>}
    </div></header>
    {errorBanner}
    {rendering && <p role="status">Gerando Word e PDF. Aguarde a conclusão da preparação dos arquivos.</p>}
    {historyUnavailable && <div className="inline-alert" role="alert"><p>O histórico não pôde ser atualizado. A resposta da operação está visível; confira o histórico novamente antes de outra decisão.</p><button className="text-action" type="button" disabled={busy} onClick={() => { setHistoryUnavailable(false); setState({ kind: "loading" }); setLoadVersion((v) => v + 1); }}>Verificar entrega</button></div>}
    {stale && <section className="delivery-stale" role="alert"><h3>Esta entrega ficou desatualizada.</h3><p>O laudo ou uma autoridade vinculada mudou depois que estes arquivos foram preparados.</p><p>Os arquivos e as decisões anteriores continuam preservados no histórico; não são apresentados como atuais.</p>
      {snapshot.stale_origin_state && <p>Antes da alteração: {DELIVERY_LABELS[snapshot.stale_origin_state].toLocaleLowerCase("pt-BR")}</p>}
      {snapshot.stale_origin_state !== "DELIVERED" && <p>Revise o laudo e as autoridades vinculadas antes de preparar outra entrega. Esta revisão não pode continuar o fluxo antigo.</p>}
    </section>}
    {snapshot.state === "SUPERSEDED" && <p className="delivery-historical-note">Esta entrega é histórica. Seus arquivos e decisões permanecem preservados.</p>}
    <DeliveryFiles value={state.value} workspaceId={workspaceId} busy={busy} onRender={() => void transition("render")} />
    {action && <section className="delivery-actions" aria-labelledby="next-step-title"><h3 id="next-step-title">Próximo passo</h3><p>{action.help}</p>
      {action.reasonLabel && <label>{action.reasonLabel}<textarea required value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy}/></label>}
      <div className="action-row"><button className="primary-action" type="button" disabled={historyUnavailable || (!!action.reasonLabel && !reason.trim())} aria-disabled={busy} aria-busy={action.command === "render" && rendering} onClick={() => void transition(action.command)}>{action.label}</button>
        {snapshot.state === "DRAFT" && rendered && <button className="secondary-action" type="button" aria-disabled={busy} aria-busy={rendering} onClick={() => void transition("render")}>Gerar novamente</button>}
      </div>
    </section>}
    {snapshot.state === "DRAFT" && <details className="delivery-supporting-disclosure"><summary>Adicionar arquivos ao pacote</summary><form className="delivery-supporting" onSubmit={attachSupporting}>
      <p>Adicione anexos ou arquivos de apoio. Este fluxo não substitui o Word oficial nem adiciona fontes ao processo.</p>
      <label>Função no pacote<select value={supportingRole} onChange={(event) => setSupportingRole(event.target.value as typeof supportingRole)}><option value="ANNEX">Anexo</option><option value="PHOTO_APPENDIX">Apêndice fotográfico</option><option value="TECHNICAL_APPENDIX">Apêndice técnico</option><option value="SUPPORTING_FILE">Arquivo de apoio</option></select></label>
      <label>Arquivo<input ref={supportingInput} type="file" required accept=".pdf,.docx,.docm,.jpg,.jpeg,.png" onChange={(event) => { setSupportingFile(event.target.files?.[0] ?? null); setAttachmentAdded(false); }}/></label>
      {supportingFile && <p>Arquivo escolhido: {supportingFile.name}</p>}
      <button className="secondary-action" type="submit" disabled={busy || !supportingFile}>Adicionar ao pacote</button>
      {attachmentAdded && <p role="status">Arquivo adicionado ao pacote da entrega.</p>}
    </form></details>}
    {snapshot.state === "DELIVERED" && <section className="delivery-delivered"><p>Entrega registrada localmente. Este registro não comprova protocolo judicial externo. Os arquivos entregues permanecem imutáveis.</p>
      <details><summary>Substituir por nova revisão</summary><p>Registre a substituição desta entrega. Depois, emita uma nova revisão com o laudo aprovado e as autoridades atuais; a anterior fica preservada.</p>
        <label>Motivo da substituição<textarea required value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy}/></label>
        <button className="destructive-action" type="button" disabled={busy || historyUnavailable || !reason.trim()} onClick={() => void transition("supersede")}>Substituir por nova revisão</button>
      </details>
    </section>}
    {(snapshot.state === "SUPERSEDED" || (stale && snapshot.stale_origin_state === "DELIVERED")) && <TemplateForm title="Emitir nova revisão" reissue busy={busy} templateId={templateId} file={templateFile} onId={setTemplateId} onFile={setTemplateFile} onSubmit={() => handleTemplate(true)} onDefault={() => handleDefault(true)} />}
    <DeliveryHistory history={history} current={state.value} workspaceId={workspaceId} />
    <DeliveryAudit value={state.value} />
  </section>;
}

function TemplateForm({ title, reissue = false, busy, templateId, file, onId, onFile, onSubmit, onDefault }: { title: string; reissue?: boolean; busy: boolean; templateId: string; file: File | null; onId: (value: string) => void; onFile: (value: File | null) => void; onSubmit: () => void; onDefault: () => void }) {
  const submit = (event: FormEvent) => { event.preventDefault(); onSubmit(); };
  return <section className="delivery-template"><h2>{title}</h2>
    <p>{reissue ? "A nova revisão será preparada com o laudo aprovado e as autoridades atuais. A entrega anterior fica preservada, sem transferir seus arquivos ou decisões para a nova." : "A entrega será criada a partir do laudo aprovado."}</p>
    <p>O modelo padrão utiliza o formato profissional configurado para esta perícia.</p>
    <button className="primary-action" type="button" disabled={busy} aria-busy={busy} onClick={onDefault}>Usar modelo padrão</button>
    {busy && <p role="status">Preparando a entrega com o modelo escolhido.</p>}
    <details className="delivery-template-custom"><summary>Usar outro modelo Word</summary>
      <p>O arquivo permanece nesta máquina. A formatação será a do modelo escolhido. O identificador deve corresponder à propriedade TEMPLATE_ID do arquivo.</p>
      <form onSubmit={submit}><label>Identificador do modelo<input required value={templateId} onChange={(event) => onId(event.target.value)}/></label><label>Modelo Word (.docx ou .docm)<input required type="file" accept=".docx,.docm,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-word.document.macroEnabled.12" onChange={(event) => onFile(event.target.files?.[0] ?? null)}/></label>
        {file && <p>Modelo escolhido: {file.name}</p>}
        <button className="secondary-action" type="submit" disabled={busy || !file || !templateId.trim()}>Usar este modelo e iniciar</button>
      </form>
    </details>
  </section>;
}
