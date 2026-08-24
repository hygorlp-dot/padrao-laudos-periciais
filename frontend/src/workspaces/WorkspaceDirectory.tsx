import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import {
  WorkspaceApiError,
  createWorkspace,
  listWorkspaces,
  type Workspace,
} from "../data/workspaces";
import { navigate, navigateTo } from "../app/router";
import { DIRECTORY_ROUTE, workspacePath } from "../routes/routeCatalog";
import { AppShell } from "../ui/AppShell";
import { PageHeader } from "../ui/PageHeader";

type DirectoryState =
  | { kind: "loading" }
  | { kind: "ready"; workspaces: Workspace[] }
  | { kind: "error"; message: string };

const DATE_FORMAT = new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" });

function errorMessage(error: unknown) {
  return error instanceof WorkspaceApiError
    ? error.message
    : "Não foi possível carregar as perícias locais";
}

export function WorkspaceDirectory() {
  const [state, setState] = useState<DirectoryState>({ kind: "loading" });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const createButtonRef = useRef<HTMLButtonElement>(null);
  const wasCreating = useRef(false);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    listWorkspaces().then(
      (workspaces) => setState({ kind: "ready", workspaces }),
      (error) => setState({ kind: "error", message: errorMessage(error) }),
    );
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    listWorkspaces(controller.signal).then(
      (workspaces) => setState({ kind: "ready", workspaces }),
      (error) => {
        if (!controller.signal.aborted) {
          setState({ kind: "error", message: errorMessage(error) });
        }
      },
    );
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (creating) {
      inputRef.current?.focus();
    } else if (wasCreating.current) {
      createButtonRef.current?.focus();
    }
    wasCreating.current = creating;
  }, [creating]);

  useEffect(() => {
    if (formError && !submitting) inputRef.current?.focus();
  }, [formError, submitting]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      setFormError("Informe o nome da perícia");
      inputRef.current?.focus();
      return;
    }
    setSubmitting(true);
    setFormError("");
    try {
      const workspace = await createWorkspace(name);
      navigateTo(workspacePath(workspace.workspace_id));
    } catch (error) {
      setFormError(errorMessage(error));
      setSubmitting(false);
    }
  }

  function cancelCreation() {
    setCreating(false);
    setName("");
    setFormError("");
  }

  return (
    <AppShell currentPath="/" currentRoute={DIRECTORY_ROUTE}>
      <article className="route-view" aria-labelledby="page-title">
        <PageHeader route={DIRECTORY_ROUTE} />

        {state.kind === "loading" ? (
          <section className="status-state status-state--loading" role="status" aria-live="polite">
            <span className="state-rule" aria-hidden="true" />
            <div>
              <h2>Carregando perícias locais</h2>
              <p>Consultando o armazenamento deste computador.</p>
            </div>
          </section>
        ) : null}

        {state.kind === "error" ? (
          <section className="status-state status-state--error" role="alert">
            <span className="state-mark" aria-hidden="true">!</span>
            <div>
              <h2>Não foi possível carregar as perícias</h2>
              <p>{state.message}</p>
              <button className="text-action" type="button" onClick={() => load()}>
                Tentar novamente
              </button>
            </div>
          </section>
        ) : null}

        {state.kind === "ready" ? (
          <section className="workspace-directory" aria-labelledby="workspace-directory-title">
            {state.workspaces.length === 0 ? (
              <div className="directory-empty">
                <span className="empty-sheet" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
                <div>
                  <h2 id="workspace-directory-title">Nenhuma perícia cadastrada</h2>
                  <p>Crie uma perícia para iniciar um workspace técnico local.</p>
                </div>
              </div>
            ) : (
              <div>
                <h2 id="workspace-directory-title">Perícias locais</h2>
                <ul className="workspace-list">
                  {state.workspaces.map((workspace) => (
                    <li key={workspace.workspace_id}>
                      <div>
                        <strong>{workspace.name}</strong>
                        <time dateTime={workspace.created_at}>
                          Criada em {DATE_FORMAT.format(new Date(workspace.created_at))}
                        </time>
                      </div>
                      <a
                        className="text-action"
                        href={workspacePath(workspace.workspace_id)}
                        onClick={navigate}
                        aria-label={`Abrir ${workspace.name}`}
                      >
                        Abrir
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {creating ? (
              <form className="workspace-form" onSubmit={submit} noValidate>
                <div className="field-group">
                  <label htmlFor="workspace-name">Nome da perícia</label>
                  <input
                    id="workspace-name"
                    ref={inputRef}
                    value={name}
                    onChange={(event) => {
                      setName(event.target.value);
                      if (formError) setFormError("");
                    }}
                    aria-describedby={formError ? "workspace-name-error" : undefined}
                    aria-invalid={Boolean(formError)}
                    disabled={submitting}
                  />
                  {formError ? (
                    <p id="workspace-name-error" className="field-error" role="alert">
                      {formError}
                    </p>
                  ) : null}
                </div>
                <div className="form-actions">
                  <button className="primary-action" type="submit" disabled={submitting}>
                    {submitting ? "Criando perícia" : "Criar perícia"}
                  </button>
                  <button className="text-action" type="button" onClick={cancelCreation} disabled={submitting}>
                    Cancelar
                  </button>
                </div>
              </form>
            ) : (
              <button
                ref={createButtonRef}
                className="primary-action"
                type="button"
                onClick={() => setCreating(true)}
              >
                Nova perícia
              </button>
            )}
          </section>
        ) : null}
      </article>
    </AppShell>
  );
}
