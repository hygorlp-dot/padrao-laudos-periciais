import { navigate } from "../app/router";
import { WORKFLOW_ROUTES } from "../routes/routeCatalog";

type SidebarProps = {
  currentPath: string;
};

export function Sidebar({ currentPath }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand-block" aria-label="ARCD Engenharia pericial">
        <span className="brand-mark">ARCD</span>
        <span className="brand-description">Engenharia pericial</span>
      </div>

      <nav className="workflow-nav" aria-label="Fluxo pericial">
        <ol>
          {WORKFLOW_ROUTES.map((route) => {
            const isActive = route.path === currentPath;
            return (
              <li key={route.path}>
                <a
                  className="workflow-link"
                  data-active={isActive || undefined}
                  href={route.path}
                  aria-current={isActive ? "page" : undefined}
                  onClick={navigate}
                >
                  <span className="workflow-index" aria-hidden="true">
                    {route.index}
                  </span>
                  <span>{route.label}</span>
                </a>
              </li>
            );
          })}
        </ol>
      </nav>

      <p className="sidebar-note">Estrutura local · nenhum caso ativo</p>
    </aside>
  );
}
