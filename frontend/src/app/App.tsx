import { findRoute } from "../routes/routeCatalog";
import { AppShell } from "../ui/AppShell";
import { PageHeader } from "../ui/PageHeader";
import { StatusState } from "../ui/StatusState";
import { navigate, useCurrentPath } from "./router";

function ForwardMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M4 10h11M11 5l5 5-5 5" />
    </svg>
  );
}

export function App() {
  const currentPath = useCurrentPath();
  const route = findRoute(currentPath);

  return (
    <AppShell currentPath={currentPath} currentRoute={route}>
      {route ? (
        <article className="route-view" aria-labelledby="page-title">
          <PageHeader route={route} />
          {route.kind === "home" ? (
            <StatusState kind="empty" onNavigate={navigate} />
          ) : (
            <StatusState kind="ready" stage={route.label} />
          )}
          {route.next ? (
            <a
              className="primary-action"
              href={route.next.path}
              onClick={navigate}
            >
              <span>Avançar para {route.next.label}</span>
              <ForwardMark />
            </a>
          ) : null}
        </article>
      ) : (
        <article className="route-view" aria-labelledby="page-title">
          <PageHeader
            route={{
              path: currentPath,
              index: "—",
              label: "Página não encontrada",
              description:
                "Este endereço não pertence à estrutura atual do ambiente pericial.",
              kind: "missing",
            }}
          />
          <StatusState kind="error" onNavigate={navigate} />
        </article>
      )}
    </AppShell>
  );
}
