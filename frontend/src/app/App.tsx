import { useEffect } from "react";

import { resolveRoute, type ShellRoute } from "../routes/routeCatalog";
import { AppShell } from "../ui/AppShell";
import { PageHeader } from "../ui/PageHeader";
import { WorkspaceDirectory } from "../workspaces/WorkspaceDirectory";
import { WorkspaceView } from "../workspaces/WorkspaceView";
import { navigate, useCurrentPath } from "./router";

export function App() {
  const currentPath = useCurrentPath();
  const resolved = resolveRoute(currentPath);

  useEffect(() => {
    const label = resolved.kind === "missing" ? "Página não encontrada" : resolved.route.label;
    document.title = `Sistema Pericial — ${label}`;
    document.getElementById("main-content")?.focus();
  }, [currentPath, resolved]);

  if (resolved.kind === "directory") {
    return <WorkspaceDirectory />;
  }

  if (resolved.kind === "workspace") {
    return (
      <WorkspaceView
        key={resolved.workspaceId}
        currentPath={resolved.pathname}
        workspaceId={resolved.workspaceId}
        route={resolved.route}
      />
    );
  }

  const missingRoute: ShellRoute = {
    path: currentPath,
    index: "—",
    label: "Página não encontrada",
    description: "Este endereço não pertence à estrutura atual do ambiente pericial.",
    kind: "missing",
  };

  return (
    <AppShell currentPath={currentPath} currentRoute={missingRoute}>
      <article className="route-view" aria-labelledby="page-title">
        <PageHeader route={missingRoute} />
        <section className="status-state status-state--error" role="alert">
          <span className="state-mark" aria-hidden="true">!</span>
          <div>
            <h2>Não foi possível mostrar este endereço</h2>
            <p>Volte à lista de perícias e tente novamente.</p>
            <a className="text-action" href="/" onClick={navigate}>
              Voltar às perícias
            </a>
          </div>
        </section>
      </article>
    </AppShell>
  );
}
