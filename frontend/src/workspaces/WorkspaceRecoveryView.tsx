import { useEffect, useRef, useState } from "react";
import { navigate } from "../app/router";
import { workspacePath } from "../routes/routeCatalog";
import { TechnicalDetails } from "../ui/TechnicalDetails";
import "../styles/recovery-editorial.css";

import {
  abandonRecovery,
  discardRecovery,
  exportWorkspaceBackup,
  listPendingRecoveries,
  promoteRecovery,
  notPromotableMessage,
  RecoveryApiError,
  stageRecovery,
  verifyBackup,
  type BackupSummary,
  type PendingRecovery,
  type StagedRecovery,
} from "../data/workspaceRecovery";

/** Sem `workspaceId` a tela é SÓ restauração: é o caso da base vazia. */
type WorkspaceRecoveryViewProps = { workspaceId?: string };

type BackupState =
  | { kind: "idle" }
  | { kind: "working" }
  | { kind: "done"; filename: string }
  | { kind: "error"; message: string };

/**
 * A restauração é deliberadamente uma SEQUÊNCIA, não um botão.
 *
 *   1. Verificar backup      → VERIFICADO != ATIVO
 *   2. Preparar cópia        → STAGING != WORKSPACE PROMOVIDO
 *   3. Conferir              → o usuário lê o que foi recuperado
 *   4. Promover recuperação  → único passo autoritativo, confirmação explícita
 */
type RestoreState =
  | { kind: "idle" }
  | { kind: "verifying" }
  | { kind: "verified"; summary: BackupSummary }
  | { kind: "staging"; summary: BackupSummary }
  | { kind: "staged"; staged: StagedRecovery }
  | { kind: "review"; staged: StagedRecovery }
  | { kind: "promoting"; staged: StagedRecovery }
  | { kind: "discarding"; staged: StagedRecovery }
  | { kind: "promoted"; summary: BackupSummary }
  // A falha PRESERVA a recuperação preparada quando ela existe: a cópia isolada
  // continua no disco e precisa continuar alcançável para descarte.
  | {
      kind: "error";
      message: string;
      staged?: StagedRecovery;
      incomplete?: boolean;
      unresumable?: boolean;
      uncertain?: boolean;
      invalid?: boolean;
      resuming?: boolean;
    };

function message(error: unknown) {
  return error instanceof RecoveryApiError
    ? error.message
    : "Não foi possível concluir a operação local";
}

/** A promoção já tocou o armazenamento vivo? Só o backend sabe; ele diz. */
function isIncomplete(error: unknown) {
  return error instanceof RecoveryApiError && error.kind === "promotion-incomplete";
}

/** Retomar virou impossível: descartar volta a ser a saída legítima. */
function isUnresumable(error: unknown) {
  return error instanceof RecoveryApiError && error.kind === "unresumable";
}

export function WorkspaceRecoveryView({ workspaceId }: WorkspaceRecoveryViewProps) {
  const [backup, setBackup] = useState<BackupState>({ kind: "idle" });
  const [restore, setRestore] = useState<RestoreState>({ kind: "idle" });
  const [selected, setSelected] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState<PendingRecovery[]>([]);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const operation = useRef(false);
  const stageTitle = useRef<HTMLHeadingElement | null>(null);
  const busy = ["verifying", "staging", "promoting", "discarding"].includes(restore.kind) || (restore.kind === "error" && restore.resuming === true);

  useEffect(() => {
    if (!operation.current && ["verified", "staged", "review", "promoted", "error"].includes(restore.kind)) stageTitle.current?.focus();
  }, [restore.kind]);

  useEffect(() => {
    if (workspaceId) return;
    const controller = new AbortController();
    listPendingRecoveries(controller.signal)
      .then((items) => {
        setPending(items);
        setPendingError(null);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setPendingError(message(error));
      });
    return () => controller.abort();
  }, [workspaceId]);

  async function onExport() {
    if (!workspaceId || operation.current) return;
    operation.current = true;
    setBackup({ kind: "working" });
    try {
      const { blob, filename } = await exportWorkspaceBackup(workspaceId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      // Revogar no mesmo tick aborta o download em alguns motores: o navegador
      // ainda não leu o blob. Solta na próxima volta do laço de eventos.
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setBackup({ kind: "done", filename });
    } catch (error) {
      setBackup({ kind: "error", message: message(error) });
    } finally {
      operation.current = false;
    }
  }

  async function onVerify() {
    if (!selected || operation.current) return;
    operation.current = true;
    setRestore({ kind: "verifying" });
    try {
      setRestore({ kind: "verified", summary: await verifyBackup(selected) });
    } catch (error) {
      setRestore({ kind: "error", message: message(error), invalid: error instanceof RecoveryApiError && ["invalid-backup", "incompatible-backup"].includes(error.kind) });
    } finally {
      operation.current = false;
    }
  }

  async function onStage(summary: BackupSummary) {
    if (!selected || operation.current) return;
    operation.current = true;
    setRestore({ kind: "staging", summary });
    try {
      setRestore({ kind: "staged", staged: await stageRecovery(selected) });
    } catch (error) {
      setRestore({ kind: "error", message: message(error), uncertain: true });
    } finally {
      operation.current = false;
    }
  }

  async function onPromote(staged: StagedRecovery) {
    if (!confirmed || operation.current || !staged.promotable) return;
    operation.current = true;
    setRestore({ kind: "promoting", staged });
    try {
      const summary = await promoteRecovery(staged.recovery_id, { confirm: true });
      setConfirmed(false);
      setPending((items) => items.filter((item) => item.recovery_id !== staged.recovery_id));
      setRestore({ kind: "promoted", summary });
    } catch (error) {
      setRestore({
        kind: "error",
        message: message(error),
        staged,
        incomplete: isIncomplete(error),
        unresumable: isUnresumable(error),
        uncertain: !(error instanceof RecoveryApiError) || ["unavailable", "invalid-response", "local-failure"].includes(error.kind),
      });
    } finally {
      operation.current = false;
    }
  }

  /** Retomada: a confirmação explícita já foi dada quando a promoção começou. */
  async function onResume(staged: StagedRecovery) {
    if (operation.current) return;
    operation.current = true;
    setRestore({ kind: "error", message: "A promoção interrompida está sendo retomada.", staged, incomplete: true, resuming: true });
    try {
      const summary = await promoteRecovery(staged.recovery_id, { confirm: true });
      setConfirmed(false);
      setPending((items) => items.filter((item) => item.recovery_id !== staged.recovery_id));
      setRestore({ kind: "promoted", summary });
    } catch (error) {
      setRestore({
        kind: "error",
        message: message(error),
        staged,
        incomplete: isIncomplete(error),
        unresumable: isUnresumable(error),
        uncertain: !(error instanceof RecoveryApiError) || ["unavailable", "invalid-response", "local-failure"].includes(error.kind),
      });
    } finally {
      operation.current = false;
    }
  }

  function resetRestore() {
    setConfirmed(false);
    setSelected(null);
    if (fileInput.current) fileInput.current.value = "";
    setRestore({ kind: "idle" });
  }

  async function onDiscard(staged: StagedRecovery, acceptIncomplete?: true) {
    if (operation.current) return;
    operation.current = true;
    setRestore({ kind: "discarding", staged });
    try {
      await discardRecovery(
        staged.recovery_id,
        acceptIncomplete ? { acceptIncomplete } : undefined,
      );
    } catch (error) {
      // A cópia isolada nunca fica ativa, mas também não podemos afirmar que
      // sumiu. Mantemos a recuperação para que o descarte possa ser repetido —
      // e o motivo tem de sobreviver, senão a tela volta a mentir e some com a
      // retomada.
      setRestore({
        kind: "error",
        message: message(error),
        staged,
        incomplete: isIncomplete(error),
        unresumable: isUnresumable(error),
      });
      return;
    } finally {
      operation.current = false;
    }
    setPending((items) => items.filter((item) => item.recovery_id !== staged.recovery_id));
    resetRestore();
  }

  async function onAbandon(staged: StagedRecovery) {
    if (operation.current) return;
    operation.current = true;
    setRestore({ kind: "discarding", staged });
    try {
      await abandonRecovery(staged.recovery_id);
    } catch (error) {
      setRestore({
        kind: "error",
        message: message(error),
        staged,
        unresumable: true,
      });
      return;
    } finally {
      operation.current = false;
    }
    setPending((items) => items.filter((item) => item.recovery_id !== staged.recovery_id));
    resetRestore();
  }

  async function actOnPending(item: PendingRecovery, action: "DISCARD" | "ABANDON") {
    if (operation.current) return;
    operation.current = true;
    setPendingAction(item.recovery_id);
    setPendingError(null);
    try {
      if (action === "ABANDON") await abandonRecovery(item.recovery_id);
      else await discardRecovery(item.recovery_id);
      setPending((current) => current.filter((entry) => entry.recovery_id !== item.recovery_id));
    } catch (error) {
      setPendingError(message(error));
    } finally {
      setPendingAction(null);
      operation.current = false;
    }
  }

  function pendingMessage(item: PendingRecovery) {
    if (item.reason === "promotion_journal_unreadable_or_unsupported") {
      return "O estado da promoção não pôde ser lido ou pertence a outra versão. A cópia continua em quarentena e só será removida se você a abandonar explicitamente.";
    }
    if (item.reason === "promotion_cannot_converge" || item.reason === "staging_identity_mismatch") {
      return "Esta promoção não pode mais convergir. Abandonar remove somente a cópia preparada; a perícia ativa permanece como está.";
    }
    if (item.state === "RECOVERY_UNRESUMABLE" || (item.state === "FAILED_RECOVERABLE" && item.reason !== null)) {
      return "Não foi possível validar o estado desta recuperação. A cópia foi preservada e só será removida por abandono explícito.";
    }
    if (item.state === "FAILED_RECOVERABLE") {
      return "Uma promoção foi interrompida. A cópia preservada permite retomar o que falta.";
    }
    if (item.state === "RECOVERY_RETAINED") {
      return "Uma limpeza anterior não terminou. A cópia segue em quarentena e a mesma ação pode ser repetida.";
    }
    return "Cópia verificada e preparada, ainda isolada da perícia ativa.";
  }

  function openPending(item: PendingRecovery) {
    if (item.summary === null || operation.current) return;
    setConfirmed(false);
    setRestore({
      kind: "review",
      staged: {
        recovery_id: item.recovery_id,
        summary: item.summary,
        promotable: item.allowed_actions.includes("PROMOTE"),
        resuming: item.state === "FAILED_RECOVERABLE",
        ...(item.reason ? { not_promotable_reason: item.reason } : {}),
      },
    });
  }

  function discardButton(staged: StagedRecovery, disabled = false) {
    return (
      <button className="text-action" type="button" onClick={() => onDiscard(staged)} disabled={disabled}>
        Descartar recuperação preparada
      </button>
    );
  }

  async function refreshRecovery() {
    if (operation.current) return;
    operation.current = true;
    setPendingAction("refresh");
    try {
      const items = await listPendingRecoveries();
      setPending(items);
      setPendingError(null);
      resetRestore();
    } catch (error) {
      setPendingError(message(error));
    } finally {
      setPendingAction(null);
      operation.current = false;
    }
  }

  function summaryList(summary: BackupSummary) {
    return <>
      <dl className="recovery-summary">
        <div><dt>Perícia</dt><dd>{summary.workspace_name}</dd></div>
        <div><dt>Criada em</dt><dd><time dateTime={summary.workspace_created_at}>{new Date(summary.workspace_created_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</time></dd></div>
        <div><dt>Revisões preservadas</dt><dd>{summary.artifact_revisions}</dd></div>
        <div><dt>Documentos e arquivos privados</dt><dd>{summary.private_contents}</dd></div>
      </dl>
      <TechnicalDetails><dl className="recovery-summary">
        <div><dt>Identidade da perícia</dt><dd><code>{summary.workspace_id}</code></dd></div>
        <div><dt>SHA-256 do backup</dt><dd><code>{summary.backup_sha256}</code></dd></div>
        <div><dt>Versão do produto</dt><dd>{summary.product_release}</dd></div>
        <div><dt>Versão do armazenamento</dt><dd>{summary.storage_schema_version}</dd></div>
      </dl></TechnicalDetails>
    </>;
  }

  const reviewing = restore.kind === "review" || restore.kind === "promoting";
  const staged = "staged" in restore ? restore.staged : undefined;
  const phaseTitle = restore.kind === "verifying" ? "Verificar integridade"
    : restore.kind === "verified" || restore.kind === "staging" ? "Preparar recuperação"
    : restore.kind === "staged" ? "Recuperação preparada para revisão"
    : reviewing ? "Revisar recuperação"
    : restore.kind === "promoted" ? "Perícia recuperada"
    : restore.kind === "error" ? restore.invalid ? "Backup não pôde ser validado" : "Não foi possível concluir esta etapa"
    : selected ? "Verificar integridade" : "Selecionar backup";

  return <section className="workspace-stage recovery-editorial" aria-labelledby="recuperacao-titulo" aria-busy={busy || pendingAction !== null}>
    <h2 id="recuperacao-titulo">Recuperar uma perícia</h2>
    <p>Selecione um backup criado pelo Sistema Pericial. Nada será substituído nesta etapa.</p>

    {workspaceId && <details className="recovery-backup"><summary>Criar backup desta perícia</summary>
      <p>Gera um pacote com as revisões, documentos e proveniência desta perícia. O pacote fica só na sua máquina.</p>
      <button className="text-action" type="button" onClick={onExport} aria-disabled={busy || backup.kind === "working" || pendingAction !== null}>Criar backup</button>
      {backup.kind === "working" && <p role="status">Gerando backup…</p>}
      {backup.kind === "done" && <p role="status">Backup gerado: {backup.filename}</p>}
      {backup.kind === "error" && <p role="alert">{backup.message}</p>}
    </details>}

    {restore.kind === "idle" && pending.length > 0 && <section className="recovery-pending" aria-labelledby="recuperacoes-pendentes-titulo">
      <h3 id="recuperacoes-pendentes-titulo">Recuperações pendentes</h3>
      <p>Estas cópias sobreviveram ao fechamento ou a uma interrupção. A situação de cada promoção está indicada abaixo.</p>
      <ul>{pending.map((item) => <li key={item.recovery_id}>
        <p>{pendingMessage(item)}</p>
        {item.summary ? summaryList(item.summary) : <p>Resumo indisponível.</p>}
        {item.allowed_actions.includes("PROMOTE") && item.summary && <button className="text-action" type="button" aria-disabled={pendingAction !== null} onClick={() => openPending(item)}>{item.state === "STAGED" ? "Conferir recuperação preparada" : "Retomar promoção"}</button>}
        {(item.allowed_actions.includes("DISCARD") || item.allowed_actions.includes("RETRY_DISCARD")) && <button className="text-action" type="button" disabled={pendingAction !== null} onClick={() => actOnPending(item, "DISCARD")}>Descartar recuperação preparada</button>}
        {(item.allowed_actions.includes("ABANDON") || item.allowed_actions.includes("RETRY_ABANDON")) && <button className="text-action" type="button" disabled={pendingAction !== null} onClick={() => actOnPending(item, "ABANDON")}>Abandonar cópia de recuperação</button>}
      </li>)}</ul>
    </section>}

    {pendingError && <div className="recovery-alert" role="alert"><p>Não foi possível verificar a recuperação.</p><p>{pendingError}</p>
      <button className="text-action" type="button" aria-disabled={pendingAction !== null} onClick={refreshRecovery}>Verificar recuperação</button>
    </div>}

    <section className="recovery-phase" aria-labelledby="recovery-phase-title">
      <h3 id="recovery-phase-title" ref={stageTitle} tabIndex={-1}>{phaseTitle}</h3>
      <label className="visually-hidden" htmlFor="backup-file">Arquivo de backup</label>
      <input id="backup-file" className="visually-hidden" ref={fileInput} type="file" tabIndex={-1}
        disabled={busy || backup.kind === "working" || pendingAction !== null || !["idle", "verified", "error"].includes(restore.kind)}
        onChange={(event) => {
          if (operation.current || !["idle", "verified", "error"].includes(restore.kind) || (restore.kind === "error" && restore.staged)) return;
          setSelected(event.target.files?.[0] ?? null); setConfirmed(false); setRestore({ kind: "idle" });
        }} />

      {selected && ["idle", "verifying", "verified", "staging"].includes(restore.kind) && <div className="recovery-selected"><strong>{selected.name}</strong><span>{selected.size.toLocaleString("pt-BR")} bytes</span></div>}
      {restore.kind === "idle" && !selected && <button className="primary-action" type="button" aria-disabled={backup.kind === "working" || pendingAction !== null} onClick={() => { if (!operation.current) fileInput.current?.click(); }}>Selecionar backup</button>}
      {(restore.kind === "idle" && selected || restore.kind === "verifying") && <>
        {restore.kind === "verifying" && <p role="status">Verificando backup…</p>}
        <button className="primary-action" type="button" aria-disabled={busy || backup.kind === "working" || pendingAction !== null} onClick={onVerify}>Verificar backup</button>
        {!busy && <button className="text-action" type="button" onClick={() => fileInput.current?.click()}>Selecionar outro backup</button>}
      </>}

      {(restore.kind === "verified" || restore.kind === "staging") && <>
        <p role="status">{restore.kind === "staging" ? "Preparando recuperação…" : "Backup válido"}</p>
        {summaryList(restore.summary)}
        <p>Os dados serão preparados em uma área separada para revisão.</p>
        <button className="primary-action" type="button" aria-disabled={busy} onClick={() => onStage(restore.summary)}>Preparar recuperação</button>
      </>}

      {staged && ["staged", "review", "promoting", "discarding"].includes(restore.kind) && <>
        <p role="status">{restore.kind === "promoting" ? "Promovendo recuperação…" : restore.kind === "discarding" ? "Descartando recuperação preparada…" : staged.resuming
          ? "Esta é a RETOMADA de uma promoção interrompida: parte da perícia já foi gravada nesta instalação. A cópia preservada guarda o que falta."
          : "Os dados estão preparados em área isolada. A cópia ainda não é a perícia ativa."}</p>
        {summaryList(staged.summary)}
        {!staged.promotable ? <p role="alert">{notPromotableMessage(staged.not_promotable_reason)}</p>
          : restore.kind === "staged" ? <button className="primary-action" type="button" onClick={() => { setConfirmed(false); setRestore({ kind: "review", staged }); }}>Revisar recuperação</button>
          : reviewing && <>
            <p>Este é o conteúdo que será promovido.</p>
            <div className="recovery-confirmation"><h4>Confirmar promoção</h4>
              <p>Promover esta recuperação tornará os dados preparados disponíveis como perícia recuperada. A promoção será executada somente após sua confirmação.</p>
              <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} />Confirmo que quero promover esta recuperação.</label>
            </div>
            <button className="authority-action" type="button" disabled={!confirmed} aria-disabled={busy} onClick={() => onPromote(staged)}>Promover recuperação</button>
          </>}
        {!staged.promotable && staged.resuming ? <button className="text-action" type="button" disabled={busy} onClick={() => onAbandon(staged)}>Abandonar cópia de recuperação</button> : !staged.resuming && discardButton(staged, busy)}
      </>}

      {restore.kind === "promoted" && <>
        <p role="status">Recuperação promovida. A perícia pode ser aberta normalmente.</p>
        {summaryList(restore.summary)}
        <a className="primary-action" href={workspacePath(restore.summary.workspace_id)} onClick={navigate}>Abrir perícia recuperada</a>
      </>}

      {restore.kind === "error" && <>
        <div className={restore.resuming ? "recovery-status" : "recovery-alert"} role={restore.resuming ? "status" : "alert"}><p>{restore.resuming ? "Retomando promoção…" : restore.invalid ? "Este backup não pode ser usado com segurança." : restore.uncertain ? "Não foi possível verificar a recuperação." : "A operação não foi concluída."}</p><p>{restore.message}</p></div>
        {restore.uncertain ? <>
          <p>O resultado da operação não foi confirmado. Verifique as recuperações preservadas antes de enviar outro comando. Uma promoção concluída também pode ser encontrada na lista de perícias.</p>
          <button className="primary-action" type="button" onClick={refreshRecovery} aria-disabled={pendingAction !== null}>Verificar recuperação</button>
          <a className="text-action" href="/" onClick={navigate}>Ver perícias</a>
        </> : restore.incomplete && restore.staged ? <>
          <p>Parte da perícia já foi gravada nesta instalação. A cópia preservada guarda o que falta: retome a promoção para concluir.</p>
          {summaryList(restore.staged.summary)}
          <button className="primary-action" type="button" aria-disabled={busy} onClick={() => onResume(restore.staged!)}>Retomar promoção</button>
          <TechnicalDetails summary="Opção de descarte excepcional"><p>O descarte remove a cópia que permite terminar esta promoção. A perícia poderá permanecer incompleta.</p><button type="button" onClick={() => onDiscard(restore.staged!, true)}>Descartar mesmo assim, aceitando a perícia incompleta</button></TechnicalDetails>
        </> : restore.unresumable && restore.staged ? <>
          <p>A perícia desta instalação divergiu do pacote, então esta promoção não converge mais. A cópia preparada pode ser abandonada.</p>
          {summaryList(restore.staged.summary)}<button className="primary-action" type="button" onClick={() => onAbandon(restore.staged!)}>Abandonar cópia de recuperação</button>
        </> : restore.staged ? <>
          <p>A cópia recuperada preparada continua isolada. Enquanto ela existir, a saída é descartá-la explicitamente.</p>
          {summaryList(restore.staged.summary)}{discardButton(restore.staged)}
        </> : <button className="primary-action" type="button" onClick={resetRestore}>Selecionar outro backup</button>}
      </>}
    </section>
  </section>;
}
