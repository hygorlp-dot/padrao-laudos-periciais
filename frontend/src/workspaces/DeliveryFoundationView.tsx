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

type ViewState = { kind: "loading" } | { kind: "missing" } | { kind: "ready"; value: DeliveryEnvelope } | { kind: "error" };

export function DeliveryFoundationView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [templateId, setTemplateId] = useState("");
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [history, setHistory] = useState<DeliveryEnvelope[]>([]);
  const [supportingFile, setSupportingFile] = useState<File | null>(null);
  const [supportingRole, setSupportingRole] = useState<"ANNEX" | "PHOTO_APPENDIX" | "TECHNICAL_APPENDIX" | "SUPPORTING_FILE">("ANNEX");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getDeliverySnapshot(workspaceId, controller.signal), getDeliveryHistory(workspaceId, controller.signal)]).then(
      ([value, revisions]) => { setState({ kind: "ready", value }); setHistory(revisions); },
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof DeliveryApiError && error.kind === "not-found" ? "missing" : "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId]);

  const handleTemplate = async (reissue: boolean) => {
    if (!templateFile || !templateId.trim()) return;
    const format = templateFile.name.toLowerCase().endsWith(".docm") ? "DOCM" : "DOCX";
    setBusy(true);
    try {
      const metadata = await uploadDeliveryTemplate(workspaceId, templateFile);
      const manifest = templateManifest(templateId.trim(), format);
      const value = reissue && state.kind === "ready"
        ? await reissueDeliverySnapshot(workspaceId, state.value, metadata, manifest)
        : await startDeliverySnapshot(workspaceId, metadata, manifest);
      setState({ kind: "ready", value }); setTemplateFile(null); setTemplateId("");
    } catch { setState({ kind: "error" }); } finally { setBusy(false); }
  };

  const transition = async (action: "render" | "ready" | "approve" | "finalize" | "deliver" | "supersede") => {
    if (state.kind !== "ready") return;
    setBusy(true);
    try {
      const value = action === "render" ? await renderDeliveryPackage(workspaceId, state.value)
        : action === "ready" ? await reviewDeliverySnapshot(workspaceId, state.value, "MARK_READY_FOR_REVIEW", reason)
          : action === "approve" ? await reviewDeliverySnapshot(workspaceId, state.value, "APPROVE", reason)
            : action === "finalize" ? await finalizeDeliverySnapshot(workspaceId, state.value, reason)
              : action === "deliver" ? await deliverDeliverySnapshot(workspaceId, state.value, reason)
                : await reviewDeliverySnapshot(workspaceId, state.value, "SUPERSEDE", reason);
      setState({ kind: "ready", value }); setReason("");
    } catch { setState({ kind: "error" }); } finally { setBusy(false); }
  };
  const attachSupporting = async (event: FormEvent) => {
    event.preventDefault(); if (state.kind !== "ready" || !supportingFile) return; setBusy(true);
    try { const stored = await uploadDeliverySupportingFile(workspaceId, supportingFile); const value = await attachDeliveryPackageArtifact(workspaceId, state.value, stored.content_id, supportingRole); setState({ kind: "ready", value }); setSupportingFile(null); }
    catch { setState({ kind: "error" }); } finally { setBusy(false); }
  };

  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Verificando entrega</h2><p>Reabrindo snapshots e manifesto privado.</p></div></section>;
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível abrir a entrega</h2><p>A integridade local não pôde ser demonstrada. Nenhum status final foi alterado.</p></div></section>;
  if (state.kind === "missing") return <TemplateForm title="Iniciar entrega" busy={busy} templateId={templateId} file={templateFile} onId={setTemplateId} onFile={setTemplateFile} onSubmit={() => handleTemplate(false)} />;

  const { snapshot } = state.value;
  const stale = snapshot.state === "STALE";
  return <section className="delivery-workbench" aria-labelledby="delivery-title">
    <header className="delivery-header"><div><p className="eyebrow">Artefato exato · revisão {state.value.revision}</p><h2 id="delivery-title">Entrega e integridade</h2><p>Finalização local; protocolo judicial permanece fora deste escopo.</p></div><strong className={`delivery-state delivery-state--${snapshot.state.toLowerCase()}`}>{snapshot.state}</strong></header>
    {stale && <section className="analysis-inventory-warning" role="alert"><strong>Entrega desatualizada</strong><p>Uma autoridade vinculada mudou. Os bytes anteriores continuam preservados, mas não são apresentados como atuais.</p><ul>{snapshot.stale_reasons.map((item) => <li key={item}>{item}</li>)}</ul></section>}
    <section className="delivery-binding" aria-labelledby="binding-title"><h3 id="binding-title">Vínculo aprovado</h3><dl><dt>Laudo</dt><dd>{snapshot.binding.report_snapshot_id} · revisão {snapshot.binding.report_revision}</dd><dt>Aprovação</dt><dd>{snapshot.binding.report_approval_id}</dd><dt>Template</dt><dd>{snapshot.template_id} · {snapshot.template_format}</dd><dt>Renderizador</dt><dd>{snapshot.rendering_version}</dd></dl><details><summary>Auditoria dos hashes vinculados</summary><code>{snapshot.binding.report_digest}</code><code>{snapshot.template_digest}</code></details></section>
    <section className="delivery-package" aria-labelledby="package-title"><div><p className="eyebrow">Manifesto {snapshot.package.manifest_version}</p><h3 id="package-title">Pacote de entrega</h3></div>{snapshot.artifacts.length === 0 ? <p>Nenhum candidato renderizado. Renderizar não finaliza nem entrega.</p> : <ul>{snapshot.artifacts.map((artifact) => <li key={artifact.artifact_id}><div><strong>{artifact.filename}</strong><span>{artifact.role} · {artifact.format} · {artifact.byte_size.toLocaleString("pt-BR")} bytes</span><code>{artifact.checksum_sha256}</code></div><a className="text-action" href={artifactDownloadUrl(workspaceId, artifact.content_id)} download={artifact.filename}>Baixar {artifact.filename}</a></li>)}</ul>}</section>
    {snapshot.state === "DRAFT" && <form className="delivery-supporting" onSubmit={attachSupporting}><h3>Compor pacote explícito</h3><label>Função no pacote<select value={supportingRole} onChange={(event) => setSupportingRole(event.target.value as typeof supportingRole)}><option value="ANNEX">Anexo</option><option value="PHOTO_APPENDIX">Apêndice fotográfico</option><option value="TECHNICAL_APPENDIX">Apêndice técnico</option><option value="SUPPORTING_FILE">Arquivo de apoio</option></select></label><label>Arquivo privado<input type="file" required accept=".pdf,.docx,.docm,.jpg,.jpeg,.png" onChange={(event) => setSupportingFile(event.target.files?.[0] ?? null)}/></label><button type="submit" disabled={busy || !supportingFile}>Adicionar ao manifesto</button></form>}
    <details className="delivery-history"><summary>Histórico preservado · {history.length} revisões</summary><ol>{history.map((item) => <li key={`${item.snapshot.delivery_id}-${item.revision}`}><strong>Revisão {item.revision} · {item.snapshot.state}</strong><span>{item.snapshot.delivery_id}</span>{item.snapshot.artifacts.map((artifact) => <a key={artifact.artifact_id} href={artifactDownloadUrl(workspaceId, artifact.content_id)} download={artifact.filename}>Baixar {artifact.filename}</a>)}</li>)}</ol></details>
    {!stale && snapshot.state !== "SUPERSEDED" && <section className="delivery-actions"><h3>Decisão profissional explícita</h3>{snapshot.state === "DRAFT" && <button type="button" disabled={busy} onClick={() => transition("render")}>{snapshot.artifacts.length ? "Renderizar novos candidatos" : "Renderizar DOC e PDF"}</button>}<label>Fundamentação da decisão<textarea value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy}/></label>{snapshot.state === "DRAFT" && snapshot.artifacts.length > 0 && <button type="button" disabled={busy || !reason.trim()} onClick={() => transition("ready")}>Enviar para revisão</button>}{snapshot.state === "READY_FOR_REVIEW" && <button type="button" disabled={busy || !reason.trim()} onClick={() => transition("approve")}>Aprovar fonte da entrega</button>}{snapshot.state === "APPROVED" && <button type="button" disabled={busy || !reason.trim()} onClick={() => transition("finalize")}>Finalizar artefatos</button>}{snapshot.state === "FINALIZED" && <button type="button" disabled={busy || !reason.trim()} onClick={() => transition("deliver")}>Registrar como entregue</button>}{snapshot.state === "DELIVERED" && <button type="button" disabled={busy || !reason.trim()} onClick={() => transition("supersede")}>Marcar como substituída</button>}</section>}
    {(snapshot.state === "SUPERSEDED" || (stale && snapshot.stale_origin_state === "DELIVERED")) && <TemplateForm title="Emitir nova revisão" busy={busy} templateId={templateId} file={templateFile} onId={setTemplateId} onFile={setTemplateFile} onSubmit={() => handleTemplate(true)} />}
  </section>;
}

function TemplateForm({ title, busy, templateId, file, onId, onFile, onSubmit }: { title: string; busy: boolean; templateId: string; file: File | null; onId: (value: string) => void; onFile: (value: File | null) => void; onSubmit: () => void }) {
  const submit = (event: FormEvent) => { event.preventDefault(); onSubmit(); };
  return <section className="delivery-template"><h2>{title}</h2><p>O template fica no armazenamento privado local. A identidade deve coincidir com a propriedade TEMPLATE_ID do arquivo.</p><form onSubmit={submit}><label>Identidade do template<input required value={templateId} onChange={(event) => onId(event.target.value)}/></label><label>Template Word privado<input required type="file" accept=".docx,.docm,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-word.document.macroEnabled.12" onChange={(event) => onFile(event.target.files?.[0] ?? null)}/></label><button className="primary-action" type="submit" disabled={busy || !file || !templateId.trim()}>{busy ? "Preservando…" : "Preservar template e iniciar"}</button></form></section>;
}
