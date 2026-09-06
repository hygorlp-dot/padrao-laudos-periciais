import { useRef, useState } from "react";

import {
  discardRecovery,
  exportWorkspaceBackup,
  promoteRecovery,
  RecoveryApiError,
  stageRecovery,
  verifyBackup,
  type BackupSummary,
  type StagedRecovery,
} from "../data/workspaceRecovery";

type WorkspaceRecoveryViewProps = { workspaceId: string };

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
  | { kind: "promoting"; staged: StagedRecovery }
  | { kind: "promoted"; summary: BackupSummary }
  | { kind: "error"; message: string };

function message(error: unknown) {
  return error instanceof RecoveryApiError
    ? error.message
    : "Não foi possível concluir a operação local";
}

export function WorkspaceRecoveryView({ workspaceId }: WorkspaceRecoveryViewProps) {
  const [backup, setBackup] = useState<BackupState>({ kind: "idle" });
  const [restore, setRestore] = useState<RestoreState>({ kind: "idle" });
  const [selected, setSelected] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);

  async function onExport() {
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
      URL.revokeObjectURL(url);
      setBackup({ kind: "done", filename });
    } catch (error) {
      setBackup({ kind: "error", message: message(error) });
    }
  }

  async function onVerify() {
    if (!selected) return;
    setRestore({ kind: "verifying" });
    try {
      setRestore({ kind: "verified", summary: await verifyBackup(selected) });
    } catch (error) {
      setRestore({ kind: "error", message: message(error) });
    }
  }

  async function onStage(summary: BackupSummary) {
    if (!selected) return;
    setRestore({ kind: "staging", summary });
    try {
      setRestore({ kind: "staged", staged: await stageRecovery(selected) });
    } catch (error) {
      setRestore({ kind: "error", message: message(error) });
    }
  }

  async function onPromote(staged: StagedRecovery) {
    if (!confirmed) return;
    setRestore({ kind: "promoting", staged });
    try {
      const summary = await promoteRecovery(staged.recovery_id, { confirm: true });
      setConfirmed(false);
      setRestore({ kind: "promoted", summary });
    } catch (error) {
      setRestore({ kind: "error", message: message(error) });
    }
  }

  async function onDiscard(staged: StagedRecovery) {
    try {
      await discardRecovery(staged.recovery_id);
    } catch {
      // descartar é best-effort: a cópia isolada nunca fica ativa de qualquer forma
    }
    setConfirmed(false);
    setSelected(null);
    if (fileInput.current) fileInput.current.value = "";
    setRestore({ kind: "idle" });
  }

  function summaryList(summary: BackupSummary) {
    return (
      <dl className="recovery-summary">
        <div><dt>Perícia</dt><dd>{summary.workspace_name}</dd></div>
        <div><dt>Identidade</dt><dd><code>{summary.workspace_id}</code></dd></div>
        <div><dt>Criada em</dt><dd>{summary.workspace_created_at}</dd></div>
        <div><dt>Versão do produto</dt><dd>{summary.product_release}</dd></div>
        <div><dt>Revisões</dt><dd>{summary.artifact_revisions}</dd></div>
        <div><dt>Documentos privados</dt><dd>{summary.private_contents}</dd></div>
      </dl>
    );
  }

  return (
    <section className="workspace-stage" aria-labelledby="recuperacao-titulo">
      <h2 id="recuperacao-titulo">Backup e recuperação</h2>

      <section aria-labelledby="backup-titulo">
        <h3 id="backup-titulo">Criar backup</h3>
        <p>
          Gera um pacote com esta perícia — revisões, documentos e proveniência —
          para você guardar onde quiser. O pacote fica só na sua máquina.
        </p>
        <button type="button" onClick={onExport} disabled={backup.kind === "working"}>
          {backup.kind === "working" ? "Gerando backup…" : "Criar backup"}
        </button>
        {backup.kind === "done" ? (
          <p role="status">Backup gerado: {backup.filename}</p>
        ) : null}
        {backup.kind === "error" ? <p role="alert">{backup.message}</p> : null}
      </section>

      <section aria-labelledby="restaurar-titulo">
        <h3 id="restaurar-titulo">Restaurar de um backup</h3>
        <p>
          A restauração acontece em etapas. Um backup verificado <strong>não</strong> é
          uma perícia ativa, e a cópia recuperada fica <strong>isolada</strong> até você
          promovê-la explicitamente. Nada existente é sobrescrito.
        </p>

        <ol className="recovery-steps">
          <li>Verificar backup</li>
          <li>Preparar cópia recuperada</li>
          <li>Conferir</li>
          <li>Promover recuperação</li>
        </ol>

        <label htmlFor="backup-file">Arquivo de backup</label>
        <input
          id="backup-file"
          ref={fileInput}
          type="file"
          onChange={(event) => {
            setSelected(event.target.files?.[0] ?? null);
            setConfirmed(false);
            setRestore({ kind: "idle" });
          }}
        />

        {restore.kind === "idle" || restore.kind === "verifying" ? (
          <button
            type="button"
            onClick={onVerify}
            disabled={!selected || restore.kind === "verifying"}
          >
            {restore.kind === "verifying" ? "Verificando…" : "1. Verificar backup"}
          </button>
        ) : null}

        {restore.kind === "verified" || restore.kind === "staging" ? (
          <div>
            <p role="status">
              Backup verificado. Ele ainda <strong>não</strong> está ativo.
            </p>
            {summaryList(restore.summary)}
            <button
              type="button"
              onClick={() => onStage(restore.summary)}
              disabled={restore.kind === "staging"}
            >
              {restore.kind === "staging"
                ? "Preparando cópia isolada…"
                : "2. Preparar cópia recuperada"}
            </button>
          </div>
        ) : null}

        {restore.kind === "staged" || restore.kind === "promoting" ? (
          <div>
            <p role="status">
              Cópia recuperada preparada em área <strong>isolada</strong>. Ela não é a
              perícia ativa e não substituiu nada. Confira antes de promover.
            </p>
            {summaryList(restore.staged.summary)}
            <label>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              Confirmo que quero promover esta recuperação e torná-la a perícia ativa.
            </label>
            <button
              type="button"
              onClick={() => onPromote(restore.staged)}
              disabled={!confirmed || restore.kind === "promoting"}
            >
              {restore.kind === "promoting" ? "Promovendo…" : "4. Promover recuperação"}
            </button>
            <button type="button" onClick={() => onDiscard(restore.staged)}>
              Descartar recuperação preparada
            </button>
          </div>
        ) : null}

        {restore.kind === "promoted" ? (
          <div>
            <p role="status">
              Recuperação promovida. A perícia está ativa e pode ser aberta normalmente.
            </p>
            {summaryList(restore.summary)}
          </div>
        ) : null}

        {restore.kind === "error" ? <p role="alert">{restore.message}</p> : null}
      </section>
    </section>
  );
}
