import type { ShellRoute } from "../routes/routeCatalog";

type TopBarProps = {
  currentRoute?: ShellRoute;
};

export function TopBar({ currentRoute }: TopBarProps) {
  const routePosition =
    currentRoute?.kind === "stage"
      ? `Etapa ${currentRoute.index} de 10`
      : "Visão geral";

  return (
    <header className="topbar">
      <div>
        <span className="topbar-label">Contexto de trabalho</span>
        <strong>Nenhuma perícia selecionada</strong>
      </div>
      <span className="route-position">{routePosition}</span>
    </header>
  );
}
