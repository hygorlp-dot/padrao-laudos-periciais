import type { ShellRoute } from "../routes/routeCatalog";

type PageHeaderProps = {
  route: ShellRoute;
};

export function PageHeader({ route }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div className="page-title-row">
        <span className="page-index" aria-hidden="true">
          {route.index}
        </span>
        <h1 id="page-title">{route.label}</h1>
      </div>
      <p>{route.description}</p>
    </div>
  );
}
