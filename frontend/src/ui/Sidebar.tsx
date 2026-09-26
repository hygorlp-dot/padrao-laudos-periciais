import { navigate } from "../app/router";
import { WORKFLOW_ROUTES, workspacePath, type ShellRoute, type WorkflowGroup } from "../routes/routeCatalog";

type SidebarProps = {
  currentPath: string;
  workspaceId?: string;
  workspaceName?: string;
};

const GROUP_ORDER: readonly WorkflowGroup[] = ["Processo", "Perícia", "Laudo", "Gestão"];

export function Sidebar({ currentPath, workspaceId, workspaceName }: SidebarProps) {
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
    const content = (
      <>
        <span className="workflow-index" aria-hidden="true">
          {route.index}
        </span>
        <span>{route.label}</span>
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
            onClick={navigate}
          >
            {content}
          </a>
        ) : (
          <span className="workflow-link" data-disabled>
            {content}
          </span>
        )}
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

      <p className="sidebar-note">
        {workspaceName ? `Perícia ativa · ${workspaceName}` : "Estrutura local · nenhuma perícia ativa"}
      </p>
    </aside>
  );
}
