import type { ReactNode } from "react";

import type { ShellRoute } from "../routes/routeCatalog";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

type AppShellProps = {
  currentPath: string;
  currentRoute?: ShellRoute;
  workspaceId?: string;
  workspaceName?: string;
  children: ReactNode;
};

export function AppShell({
  currentPath,
  currentRoute,
  workspaceId,
  workspaceName,
  children,
}: AppShellProps) {
  const routeLabel = currentRoute?.label ?? "Página não encontrada";

  return (
    <>
      <a className="skip-link" href="#main-content">
        Ir para o conteúdo
      </a>
      <div className="app-shell">
        <p className="visually-hidden" aria-live="polite" aria-atomic="true">
          Rota atual: {routeLabel}
        </p>
        <Sidebar currentPath={currentPath} workspaceId={workspaceId} workspaceName={workspaceName} />
        <div className="workspace-shell">
          <TopBar currentRoute={currentRoute} workspaceName={workspaceName} />
          <main id="main-content" tabIndex={-1}>
            {children}
          </main>
        </div>
      </div>
    </>
  );
}
