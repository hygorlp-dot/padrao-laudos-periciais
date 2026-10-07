import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";

import { ExpertIdentityProvider } from "../data/expertIdentity";
import { getWorkspace, WorkspaceApiError, type Workspace } from "../data/workspaces";
import { getWorkflowStatus } from "../data/workflowStatus";
import type { SidebarStageStatus } from "../ui/Sidebar";
import { WorkspaceHome, type WorkflowStatusView } from "./WorkspaceHome";
import { navigate } from "../app/router";
import { workspacePath, type ShellRoute } from "../routes/routeCatalog";
import { AppShell } from "../ui/AppShell";
import { PageHeader } from "../ui/PageHeader";
import { StatusState } from "../ui/StatusState";
import { ProcessCaseView } from "./ProcessCaseView";
import { MaterialIntakeView } from "./MaterialIntakeView";
import { CaseAnalysisView } from "./CaseAnalysisView";
import { PericialPlanningView } from "./PericialPlanningView";
import { InspectionSessionView } from "./InspectionSessionView";
import { PhotoLibraryPanel } from "./PhotoLibraryPanel";
import { TechnicalFindingsView } from "./TechnicalFindingsView";
import { ConstructionDefectAnalysisView } from "./ConstructionDefectAnalysisView";
import { ReportFoundationView } from "./ReportFoundationView";
import { DeliveryFoundationView } from "./DeliveryFoundationView";
import { BudgetFoundationView } from "./BudgetFoundationView";
import { WorkspaceRecoveryView } from "./WorkspaceRecoveryView";
import { FindingsLedgerView } from "./FindingsLedgerView";
import { ReportReviewView } from "./ReportReviewView";
import { WorkspaceSettingsPanel } from "./WorkspaceSettingsPanel";

const IMPLEMENTED_STAGE_PATHS = ["/processo", "/materiais", "/analise", "/planejamento", "/vistoria", "/evidencias", "/constatacoes", "/analise-tecnica", "/laudo", "/revisao", "/exportar", "/orcamento", "/recuperacao"];

type WorkspaceViewProps = {
  currentPath: string;
  workspaceId: string;
  route: ShellRoute;
};

type ViewState =
  | { kind: "loading" }
  | { kind: "ready"; workspace: Workspace }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

export function WorkspaceView({ currentPath, workspaceId, route }: WorkspaceViewProps) {
  const [state, setState] = useState<ViewState>({ kind: "loading" });

  const load = useCallback(
    () => {
      setState({ kind: "loading" });
      getWorkspace(workspaceId).then(
        (workspace) => setState({ kind: "ready", workspace }),
        (error) => {
          if (error instanceof WorkspaceApiError && error.kind === "not-found") {
            setState({ kind: "not-found" });
            return;
          }
          setState({
            kind: "error",
            message:
              error instanceof WorkspaceApiError
                ? error.message
                : "Não foi possível carregar a perícia",
          });
        },
      );
    },
    [workspaceId],
  );

  useEffect(() => {
    const controller = new AbortController();
    getWorkspace(workspaceId, controller.signal).then(
      (workspace) => setState({ kind: "ready", workspace }),
      (error) => {
        if (controller.signal.aborted) return;
        if (error instanceof WorkspaceApiError && error.kind === "not-found") {
          setState({ kind: "not-found" });
          return;
        }
        setState({
          kind: "error",
          message:
            error instanceof WorkspaceApiError
              ? error.message
              : "Não foi possível carregar a perícia",
        });
      },
    );
    return () => controller.abort();
  }, [workspaceId]);

  // Situação das etapas (#291): consultada de novo a cada troca de rota, para
  // refletir o que acabou de ser feito. O componente é recriado por perícia
  // (`key`), então uma resposta nunca chega a outra perícia; a resposta de
  // uma requisição abortada é descartada.
  const [workflow, setWorkflow] = useState<WorkflowStatusView>({ kind: "loading" });
  const [workflowAttempt, setWorkflowAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getWorkflowStatus(workspaceId, controller.signal).then(
      (value) => setWorkflow({ kind: "ready", value }),
      () => {
        if (!controller.signal.aborted) setWorkflow({ kind: "unavailable" });
      },
    );
    return () => controller.abort();
  }, [workspaceId, currentPath, workflowAttempt]);
  const retryWorkflow = useCallback(() => {
    setWorkflow({ kind: "loading" });
    setWorkflowAttempt((value) => value + 1);
  }, []);
  const stageStatus = useMemo<SidebarStageStatus>(
    () =>
      workflow.kind === "ready"
        ? { kind: "ready", stages: new Map(workflow.value.stages.map((item) => [item.stage, item])) }
        : workflow,
    [workflow],
  );

  useLayoutEffect(() => {
    if (state.kind === "not-found") {
      document.title = "Sistema Pericial — Perícia não encontrada";
    }
  }, [state.kind]);

  if (state.kind === "not-found") {
    const missingRoute: ShellRoute = {
      path: currentPath,
      index: "—",
      label: "Perícia não encontrada",
      description: "A perícia indicada neste endereço não está disponível no armazenamento local.",
      kind: "missing",
    };
    return (
      <AppShell currentPath={currentPath} currentRoute={missingRoute}>
        <article className="route-view" aria-labelledby="page-title">
          <PageHeader route={missingRoute} />
          <section className="status-state status-state--error" role="alert">
            <span className="state-mark" aria-hidden="true">!</span>
            <div>
              <h2>Perícia não encontrada</h2>
              <p>Volte à lista e escolha uma perícia disponível.</p>
              <a className="text-action" href="/" onClick={navigate}>
                Voltar às perícias
              </a>
            </div>
          </section>
        </article>
      </AppShell>
    );
  }

  const workspace = state.kind === "ready" ? state.workspace : undefined;
  return (
    <AppShell
      currentPath={currentPath}
      currentRoute={route}
      workspaceId={workspaceId}
      workspaceName={workspace?.name}
      stageStatus={stageStatus}
    >
      <ExpertIdentityProvider workspaceId={workspaceId}>
      <article className="route-view" aria-labelledby="page-title">
        <PageHeader route={route} />
        {state.kind === "loading" ? (
          <section className="status-state status-state--loading" role="status" aria-live="polite">
            <span className="state-rule" aria-hidden="true" />
            <div>
              <h2>Carregando perícia</h2>
              <p>Recuperando os dados locais desta perícia.</p>
            </div>
          </section>
        ) : null}
        {state.kind === "error" ? (
          <section className="status-state status-state--error" role="alert">
            <span className="state-mark" aria-hidden="true">!</span>
            <div>
              <h2>Não foi possível carregar a perícia</h2>
              <p>{state.message}</p>
              <button className="text-action" type="button" onClick={() => load()}>
                Tentar novamente
              </button>
            </div>
          </section>
        ) : null}
        {state.kind === "ready" && route.kind === "home" ? (
          <WorkspaceHome workspace={state.workspace} status={workflow} onRetry={retryWorkflow} />
        ) : null}
        {state.kind === "ready" && route.kind === "home" ? <WorkspaceSettingsPanel workspaceId={workspaceId} /> : null}
        {state.kind === "ready" && route.path === "/processo" ? (
          <ProcessCaseView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/materiais" ? (
          <MaterialIntakeView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/analise" ? (
          <CaseAnalysisView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/planejamento" ? (
          <PericialPlanningView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/vistoria" ? (
          <>
            <InspectionSessionView key={workspaceId} workspaceId={workspaceId} />
            <PhotoLibraryPanel key={`photos-${workspaceId}`} workspaceId={workspaceId} />
          </>
        ) : null}
        {state.kind === "ready" && route.path === "/evidencias" ? (
          <TechnicalFindingsView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/constatacoes" ? (
          <FindingsLedgerView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/revisao" ? (
          <ReportReviewView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/analise-tecnica" ? (
          <ConstructionDefectAnalysisView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/laudo" ? (
          <ReportFoundationView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/exportar" ? (
          <DeliveryFoundationView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/orcamento" ? (
          <BudgetFoundationView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.path === "/recuperacao" ? (
          <WorkspaceRecoveryView workspaceId={workspaceId} />
        ) : null}
        {state.kind === "ready" && route.kind === "stage" && !IMPLEMENTED_STAGE_PATHS.includes(route.path) ? (
          <StatusState kind="ready" stage={route.label} />
        ) : null}
        {state.kind === "ready" && route.next && !IMPLEMENTED_STAGE_PATHS.includes(route.path) ? (
          <a
            className="primary-action"
            href={workspacePath(workspaceId, route.next.path.slice(1))}
            onClick={navigate}
          >
            Avançar para {route.next.label}
          </a>
        ) : null}
      </article>
      </ExpertIdentityProvider>
    </AppShell>
  );
}
