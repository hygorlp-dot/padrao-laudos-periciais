import { WORKFLOW_STAGE_COUNT, type ShellRoute } from "../routes/routeCatalog";

type TopBarProps = {
  currentRoute?: ShellRoute;
  workspaceName?: string;
};

export function TopBar({ currentRoute, workspaceName }: TopBarProps) {
  const routePosition =
    currentRoute?.kind === "stage"
      ? `Etapa ${Number(currentRoute.index)} de ${WORKFLOW_STAGE_COUNT}`
      : "Visão geral";

  return (
    <header className="topbar">
      <div>
        <span className="topbar-label">Contexto de trabalho</span>
        <strong>{workspaceName ?? "Nenhuma perícia selecionada"}</strong>
      </div>
      <span className="route-position">{routePosition}</span>
    </header>
  );
}
