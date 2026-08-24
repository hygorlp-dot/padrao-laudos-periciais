import { useEffect, useRef, useState } from "react";

import {
  getProcessCase,
  ProcessCaseApiError,
  type ProcessCaseData,
  type ProcessCaseSnapshot,
  saveProcessCase,
} from "../data/processCase";

type ProcessCaseViewProps = {
  workspaceId: string;
};

const FIELDS: readonly {
  key: keyof ProcessCaseData;
  label: string;
  autoComplete?: string;
}[] = [
  { key: "numero_processo", label: "Número do processo" },
  { key: "tribunal", label: "Tribunal" },
  { key: "vara", label: "Vara" },
  { key: "comarca_municipio", label: "Comarca ou município" },
  { key: "uf", label: "UF" },
  { key: "parte_requerente", label: "Parte requerente" },
  { key: "parte_requerida", label: "Parte requerida" },
];

type ViewState =
  | { kind: "loading" }
  | {
      kind: "ready";
      workspaceId: string;
      snapshot: ProcessCaseSnapshot;
      draft: ProcessCaseData;
    }
  | { kind: "load-error"; workspaceId: string; message: string };

type SaveState =
  | { kind: "idle" }
  | { kind: "saving"; workspaceId: string }
  | { kind: "saved"; workspaceId: string }
  | { kind: "error"; workspaceId: string; message: string };

function errorMessage(error: unknown) {
  return error instanceof ProcessCaseApiError
    ? error.message
    : "Não foi possível concluir a operação local";
}

export function ProcessCaseView({ workspaceId }: ProcessCaseViewProps) {
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [saveState, setSaveState] = useState<SaveState>({ kind: "idle" });
  const [loadAttempt, setLoadAttempt] = useState(0);
  const activeSave = useRef<AbortController | null>(null);
  const saveButton = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getProcessCase(workspaceId, controller.signal).then(
      (snapshot) => {
        if (!controller.signal.aborted) {
          setState({
            kind: "ready",
            workspaceId,
            snapshot,
            draft: { ...snapshot.data },
          });
        }
      },
      (error) => {
        if (!controller.signal.aborted) {
          setState({
            kind: "load-error",
            workspaceId,
            message: errorMessage(error),
          });
        }
      },
    );
    return () => {
      controller.abort();
      const pendingSave = activeSave.current;
      if (pendingSave !== null) {
        pendingSave.abort();
        activeSave.current = null;
        setSaveState((current) =>
          current.kind === "saving" && current.workspaceId === workspaceId
            ? { kind: "idle" }
            : current,
        );
      }
    };
  }, [workspaceId, loadAttempt]);

  useEffect(() => {
    if (
      (saveState.kind === "saved" || saveState.kind === "error") &&
      saveState.workspaceId === workspaceId
    ) {
      saveButton.current?.focus();
    }
  }, [saveState, workspaceId]);

  function update(field: keyof ProcessCaseData, value: string) {
    setState((current) =>
      current.kind === "ready" && current.workspaceId === workspaceId
        ? { ...current, draft: { ...current.draft, [field]: value } }
        : current,
    );
    setSaveState({ kind: "idle" });
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const saving = saveState.kind === "saving" && saveState.workspaceId === workspaceId;
    if (state.kind !== "ready" || state.workspaceId !== workspaceId || saving) return;
    const controller = new AbortController();
    activeSave.current = controller;
    setSaveState({ kind: "saving", workspaceId });
    try {
      const snapshot = await saveProcessCase(
        workspaceId,
        state.draft,
        state.snapshot.revision,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setState({
          kind: "ready",
          workspaceId,
          snapshot,
          draft: { ...snapshot.data },
        });
        setSaveState({ kind: "saved", workspaceId });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setSaveState({ kind: "error", workspaceId, message: errorMessage(error) });
      }
    } finally {
      if (activeSave.current === controller) activeSave.current = null;
    }
  }

  const visibleState =
    state.kind !== "loading" && state.workspaceId !== workspaceId
      ? ({ kind: "loading" } as const)
      : state;
  const saving = saveState.kind === "saving" && saveState.workspaceId === workspaceId;
  const saveError =
    saveState.kind === "error" && saveState.workspaceId === workspaceId
      ? saveState.message
      : undefined;
  const saved = saveState.kind === "saved" && saveState.workspaceId === workspaceId;

  if (visibleState.kind === "loading") {
    return (
      <section className="status-state status-state--loading" role="status" aria-live="polite">
        <span className="state-rule" aria-hidden="true" />
        <div>
          <h2>Carregando dados do processo</h2>
          <p>Recuperando a identificação processual deste workspace.</p>
        </div>
      </section>
    );
  }

  if (visibleState.kind === "load-error") {
    return (
      <section className="status-state status-state--error" role="alert">
        <span className="state-mark" aria-hidden="true">!</span>
        <div>
          <h2>Não foi possível carregar os dados do processo</h2>
          <p>{visibleState.message}</p>
          <button
            className="text-action"
            type="button"
            onClick={() => {
              setState({ kind: "loading" });
              setLoadAttempt((attempt) => attempt + 1);
            }}
          >
            Tentar novamente
          </button>
        </div>
      </section>
    );
  }

  return (
    <form className="process-case-form" onSubmit={submit}>
      <div className="process-case-intro">
        <h2>Identificação do processo</h2>
        <p>Registre somente os dados conhecidos. Todos os campos podem permanecer em branco.</p>
      </div>
      <div className="process-case-fields">
        {FIELDS.map((field) => (
          <div className="field-group" key={field.key}>
            <label htmlFor={`process-case-${field.key}`}>{field.label}</label>
            <input
              id={`process-case-${field.key}`}
              name={field.key}
              type="text"
              value={visibleState.draft[field.key]}
              disabled={saving}
              onChange={(event) => update(field.key, event.currentTarget.value)}
            />
          </div>
        ))}
      </div>
      {saveError ? <p className="process-case-message process-case-message--error" role="alert">{saveError}</p> : null}
      {saved ? (
        <p className="process-case-message" role="status">
          <strong>Dados do processo salvos</strong>
          {visibleState.snapshot.revision === null ? null : (
            <span>Revisão {visibleState.snapshot.revision}</span>
          )}
        </p>
      ) : null}
      <div className="form-actions">
        <button ref={saveButton} className="primary-action" type="submit" disabled={saving}>
          {saving ? "Salvando…" : "Salvar dados do processo"}
        </button>
        {!saved && visibleState.snapshot.revision !== null ? (
          <span className="revision-note">Revisão atual {visibleState.snapshot.revision}</span>
        ) : null}
      </div>
    </form>
  );
}
