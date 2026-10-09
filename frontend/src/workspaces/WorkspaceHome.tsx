import { navigate } from "../app/router";
import type { Workspace } from "../data/workspaces";
import type { WorkflowStageStatus, WorkflowStatus } from "../data/workflowStatus";
import { workspacePath } from "../routes/routeCatalog";
import { TechnicalDetails } from "../ui/TechnicalDetails";
import { formatDateTime } from "../ui/labels";
import {
  STAGE_STATE_SYMBOL,
  STAGE_STATE_TEXT,
  attentionItems,
  nextAction,
  stageReasonsText,
  stagesFromCatalog,
  stateSummaryText,
  type StageWithRoute,
} from "../ui/workflowStatusText";

export type WorkflowStatusView =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "ready"; value: WorkflowStatus };

type WorkspaceHomeProps = {
  workspace: Workspace;
  status: WorkflowStatusView;
  onRetry: () => void;
};

function StageState({ status, id }: { status: WorkflowStageStatus; id?: string }) {
  const symbol = STAGE_STATE_SYMBOL[status.state];
  return (
    <span className="stage-state" data-state={status.state} id={id}>
      {symbol ? <span className="stage-state-symbol" aria-hidden="true">{symbol}</span> : null}
      <span className="stage-state-text">{STAGE_STATE_TEXT[status.state]}</span>
      {status.reasons.length ? (
        <span className="stage-state-reasons">{stageReasonsText(status).join(" · ")}</span>
      ) : null}
    </span>
  );
}

export function WorkspaceHome({ workspace, status, onRetry }: WorkspaceHomeProps) {
  const stages = status.kind === "ready" ? stagesFromCatalog(status.value) : [];
  const attention = attentionItems(stages);
  const next = nextAction(stages);
  const counts = new Map<string, number>();
  for (const item of stages) counts.set(item.status.state, (counts.get(item.status.state) ?? 0) + 1);
  const stageHref = (item: StageWithRoute) => workspacePath(workspace.workspace_id, item.route.path.slice(1));

  return (
    <section className="workspace-home" aria-labelledby="active-workspace-name">
      <div className="workspace-home-header">
        <h2 id="active-workspace-name">{workspace.name}</h2>
        <time dateTime={workspace.created_at}>
          Criada em {new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(new Date(workspace.created_at))}
        </time>
      </div>

      {status.kind === "loading" ? (
        <p className="workspace-home-note" role="status" aria-live="polite">
          Verificando a situação das etapas.
        </p>
      ) : null}

      {status.kind === "unavailable" ? (
        <div className="workspace-home-unavailable" role="alert">
          <h3>Não foi possível verificar a situação das etapas</h3>
          <p>As etapas continuam acessíveis pela navegação ao lado. Nada foi alterado nesta perícia.</p>
          <button className="text-action" type="button" onClick={onRetry}>
            Verificar novamente
          </button>
        </div>
      ) : null}

      {status.kind === "ready" ? (
        <div className="workspace-home-body">
          <section className="workspace-home-block" aria-labelledby="home-situation">
            <h3 id="home-situation">Situação</h3>
            <p className="workspace-home-lead">
              {attention.length
                ? `${attention.length} ${attention.length === 1 ? "etapa precisa" : "etapas precisam"} da sua atenção.`
                : "Nenhuma etapa com pendência apontada pelas regras do sistema."}
            </p>
            <ul className="workspace-home-counts">
              {[...counts.entries()].map(([state, count]) => (
                <li key={state}>{stateSummaryText(state as WorkflowStageStatus["state"], count)}</li>
              ))}
            </ul>
          </section>

          <section className="workspace-home-block" aria-labelledby="home-attention">
            <h3 id="home-attention">Precisa de atenção</h3>
            {attention.length ? (
              <ul className="workspace-home-attention">
                {attention.map((item) => {
                  const descriptionId = `home-attention-${item.status.stage}`;
                  return (
                    <li key={item.status.stage}>
                      <a href={stageHref(item)} onClick={navigate} aria-describedby={descriptionId}>
                        {item.route.label}
                      </a>
                      <StageState status={item.status} id={descriptionId} />
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="workspace-home-note">Nada aguardando sua decisão neste momento.</p>
            )}
          </section>

          <section className="workspace-home-block" aria-labelledby="home-next">
            <h3 id="home-next">Próxima ação disponível</h3>
            {next ? (
              <div className="workspace-home-next">
                <a className="primary-action" href={stageHref(next)} onClick={navigate} aria-describedby="home-next-state">
                  Abrir {next.route.label}
                </a>
                <StageState status={next.status} id="home-next-state" />
              </div>
            ) : (
              <p className="workspace-home-note">
                As regras disponíveis não apontam ação pendente nas etapas técnicas. Isso não substitui sua revisão
                final.
              </p>
            )}
          </section>

          <TechnicalDetails summary="Detalhes técnicos da situação">
            <table className="workspace-home-technical">
              <caption className="visually-hidden">Situação de cada etapa, como informada pelo sistema</caption>
              <thead>
                <tr>
                  <th scope="col">Etapa</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Base</th>
                  <th scope="col">Decisão</th>
                  <th scope="col">Revisão</th>
                  <th scope="col">Códigos</th>
                </tr>
              </thead>
              <tbody>
                {stages.map((item) => (
                  <tr key={item.status.stage}>
                    <th scope="row">{item.route.label}</th>
                    <td>{item.status.state}</td>
                    <td>{item.status.currency}</td>
                    <td>{item.status.decision}</td>
                    <td>
                      {item.status.revision === null
                        ? "—"
                        : `${item.status.revision} · ${formatDateTime(item.status.updated_at)}`}
                    </td>
                    <td>
                      {item.status.reasons
                        .map((reason) => (reason.count === undefined ? reason.code : `${reason.code}=${reason.count}`))
                        .join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TechnicalDetails>
        </div>
      ) : null}
    </section>
  );
}
