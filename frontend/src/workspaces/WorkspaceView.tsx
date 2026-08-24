import { useCallback, useEffect, useState } from "react";

import { getWorkspace, WorkspaceApiError, type Workspace } from "../data/workspaces";
import { navigate } from "../app/router";
import { workspacePath, type ShellRoute } from "../routes/routeCatalog";
import { AppShell } from "../ui/AppShell";
import { PageHeader } from "../ui/PageHeader";
import { StatusState } from "../ui/StatusState";
import { ProcessCaseView } from "./ProcessCaseView";

type WorkspaceViewProps = {
  currentPath: string;
  workspaceId: string;
  route: ShellRoute;
};

type ViewState =
  | { kind: "loading" }
  | { kind: "ready"; workspace: Workspace }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

export function WorkspaceView({ currentPath, workspaceId, route }: WorkspaceViewProps) {
  const [state, setState] = useState<ViewState>({ kind: "loading" });

  const load = useCallback(
    () => {
      setState({ kind: "loading" });
      getWorkspace(workspaceId).then(
        (workspace) => setState({ kind: "ready", workspace }),
        (error) => {
          if (error instanceof WorkspaceApiError && error.kind === "not-found") {
            setState({ kind: "not-found" });
            return;
          }
          setState({
            kind: "error",
            message:
              error instanceof WorkspaceApiError
                ? error.message
                : "Não foi possível carregar a perícia",
          });
        },
      );
    },
    [workspaceId],
  );

  useEffect(() => {
    const controller = new AbortController();
    getWorkspace(workspaceId, controller.signal).then(
      (workspace) => setState({ kind: "ready", workspace }),
      (error) => {
        if (controller.signal.aborted) return;
        if (error instanceof WorkspaceApiError && error.kind === "not-found") {
          setState({ kind: "not-found" });
          return;
        }
        setState({
          kind: "error",
          message:
            error instanceof WorkspaceApiError
              ? error.message
              : "Não foi possível carregar a perícia",
        });
      },
    );
    return () => controller.abort();
  }, [workspaceId]);

  useEffect(() => {
    if (state.kind === "not-found") {
      document.title = "Sistema Pericial — Perícia não encontrada";
    }
  }, [state.kind]);

  if (state.kind === "not-found") {
    const missingRoute: ShellRoute = {
      path: currentPath,
      index: "—",
      label: "Perícia não encontrada",
      description: "A perícia indicada neste endereço não está disponível no armazenamento local.",
      kind: "missing",
    };
    return (
      <AppShell currentPath={currentPath} currentRoute={missingRoute}>
        <article className="route-view" aria-labelledby="page-title">
          <PageHeader route={missingRoute} />
          <section className="status-state status-state--error" role="alert">
            <span className="state-mark" aria-hidden="true">!</span>
            <div>
              <h2>Perícia não encontrada</h2>
              <p>Volte à lista e escolha uma perícia disponível.</p>
              <a className="text-action" href="/" onClick={navigate}>
                Voltar às perícias
              </a>
            </div>
          </section>
        </article>
      </AppShell>
    );
  }

  const workspace = state.kind === "ready" ? state.workspace : undefined;
  return (
    <AppShell
      currentPath={currentPath}
      currentRoute={route}
      workspaceId={workspaceId}
      workspaceName={workspace?.name}
    >
      <article className="route-view" aria-labelledby="page-title">
        <PageHeader route={route} />
        {state.kind === "loading" ? (
          <section className="status-state status-state--loading" role="status" aria-live="polite">
            <span className="state-rule" aria-hidden="true" />
            <div>
              <h2>Carregando perícia</h2>
              <p>Recuperando o contexto local deste workspace.</p>
            </div>
          </section>
        ) : null}
        {state.kind === "error" ? (
          <section className="status-state status-state--error" role="alert">
            <span className="state-mark" aria-hidden="true">!</span>
            <div>
              <h2>Não foi possível carregar a perícia</h2>
              <p>{state.message}</p>
              <button className="text-action" type="button" onClick={() => load()}>
                Tentar novamente
              </button>
            </div>
          </section>
        ) : null}
        {state.kind === "ready" && route.kind === "home" ? (
          <section className="workspace-ready" aria-labelledby="active-workspace-name">
            <span className="state-mark" aria-hidden="true">✓</span>
            <div>
              <h2 id="active-workspace-name">{state.workspace.name}</h2>
              <p>Esta perícia está pronta para percorrer o fluxo técnico.</p>
              <time dateTime={state.workspace.created_at}>
                Criada em {new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(new Date(state.workspace.created_at))}
              </time>
            </div>
          </section>
        ) : null}
        {state.kind === "ready" && route.path === "/processo" ? (
          <ProcessCaseView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.kind === "stage" && route.path !== "/processo" ? (
          <StatusState kind="ready" stage={route.label} />
        ) : null}
        {state.kind === "ready" && route.next && route.path !== "/processo" ? (
          <a
            className="primary-action"
            href={workspacePath(workspaceId, route.next.path.slice(1))}
            onClick={navigate}
          >
            Avançar para {route.next.label}
          </a>
        ) : null}
      </article>
    </AppShell>
  );
}
