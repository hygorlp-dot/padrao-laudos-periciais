import { navigate } from "../app/router";
import { WORKFLOW_ROUTES, workspacePath } from "../routes/routeCatalog";

type SidebarProps = {
  currentPath: string;
  workspaceId?: string;
  workspaceName?: string;
};

export function Sidebar({ currentPath, workspaceId, workspaceName }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand-block" aria-label="Sistema Pericial">
        <span className="brand-mark">Sistema Pericial</span>
        <span className="brand-description">Engenharia pericial</span>
      </div>

      <nav className="workflow-nav" aria-label="Fluxo pericial">
        <ol>
          {WORKFLOW_ROUTES.map((route) => {
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
          })}
        </ol>
      </nav>

      <p className="sidebar-note">
        {workspaceName ? `Perícia ativa · ${workspaceName}` : "Estrutura local · nenhuma perícia ativa"}
      </p>
    </aside>
  );
}
