import { navigate } from "../app/router";
import { WORKFLOW_ROUTES, workspacePath, type ShellRoute, type WorkflowGroup } from "../routes/routeCatalog";
import type { WorkflowStageStatus } from "../data/workflowStatus";
import { STAGE_STATE_SYMBOL, STAGE_STATE_TEXT, stageDescription } from "./workflowStatusText";

// Situação das etapas vinda da projeção do backend. Enquanto carrega, nada é
// afirmado; se a consulta falha, cada etapa diz "não verificada" e os links
// continuam funcionando normalmente.
export type SidebarStageStatus =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "ready"; stages: ReadonlyMap<string, WorkflowStageStatus> };

type SidebarProps = {
  currentPath: string;
  workspaceId?: string;
  workspaceName?: string;
  stageStatus?: SidebarStageStatus;
};

const GROUP_ORDER: readonly WorkflowGroup[] = ["Processo", "Perícia", "Laudo", "Gestão"];

export function Sidebar({ currentPath, workspaceId, workspaceName, stageStatus }: SidebarProps) {
  const home = WORKFLOW_ROUTES.filter((route) => route.kind === "home");
  const groups = GROUP_ORDER.map((group) => ({
    group,
    routes: WORKFLOW_ROUTES.filter((route) => route.kind === "stage" && route.group === group),
  }));

  const renderLink = (route: ShellRoute) => {
    const href = workspaceId
      ? workspacePath(workspaceId, route.kind === "stage" ? route.path.slice(1) : undefined)
      : route.kind === "home"
        ? "/"
        : undefined;
    const isActive = href === currentPath;
    const stage = workspaceId && route.kind === "stage" ? route.path.slice(1) : undefined;
    const status = stage && stageStatus?.kind === "ready" ? stageStatus.stages.get(stage) : undefined;
    const description = !stage || !stageStatus || stageStatus.kind === "loading"
      ? undefined
      : status
        ? stageDescription(status)
        : STAGE_STATE_TEXT.UNAVAILABLE;
    const state = status?.state ?? (description ? "UNAVAILABLE" : undefined);
    const descriptionId = description ? `workflow-state-${stage}` : undefined;
    const content = (
      <>
        <span className="workflow-index" aria-hidden="true">
          {route.index}
        </span>
        <span>{route.label}</span>
        {state && STAGE_STATE_SYMBOL[state] ? (
          <span className="workflow-state-mark" data-state={state} aria-hidden="true" title={STAGE_STATE_TEXT[state]}>
            {STAGE_STATE_SYMBOL[state]}
          </span>
        ) : null}
      </>
    );
    return (
      <li key={route.path}>
        {href ? (
          <a
            className="workflow-link"
            data-active={isActive || undefined}
            href={href}
            aria-current={isActive ? "page" : undefined}
            aria-describedby={descriptionId}
            onClick={navigate}
          >
            {content}
          </a>
        ) : (
          <span className="workflow-link" data-disabled>
            {content}
          </span>
        )}
        {descriptionId ? (
          <span id={descriptionId} className="visually-hidden">
            {description}
          </span>
        ) : null}
      </li>
    );
  };

  return (
    <aside className="sidebar">
      <div className="brand-block" aria-label="Sistema Pericial">
        <span className="brand-mark">Sistema Pericial</span>
        <span className="brand-description">Engenharia pericial</span>
      </div>

      {workspaceId ? (
        <a className="directory-link" href="/" onClick={navigate}>
          Todas as perícias
        </a>
      ) : null}

      <nav className="workflow-nav" aria-label="Fluxo pericial">
        <ol>{home.map(renderLink)}</ol>
        {groups.map(({ group, routes }) => (
          <div className="workflow-group" key={group}>
            <p className="workflow-group-title" id={`workflow-group-${group}`}>{group}</p>
            <ol aria-labelledby={`workflow-group-${group}`}>{routes.map(renderLink)}</ol>
          </div>
        ))}
      </nav>

      {/* Fora do fluxo de uma perícia: padrões da instalação. */}
      <a
        className="settings-link"
        href="/configuracoes"
        aria-current={currentPath === "/configuracoes" ? "page" : undefined}
        data-active={currentPath === "/configuracoes" || undefined}
        onClick={navigate}
      >
        Configurações
      </a>

      <p className="sidebar-note">
        {workspaceName ? `Perícia ativa · ${workspaceName}` : "Estrutura local · nenhuma perícia ativa"}
      </p>
    </aside>
  );
}
