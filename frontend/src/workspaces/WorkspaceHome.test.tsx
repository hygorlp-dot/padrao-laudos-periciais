import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { App } from "../app/App";
import { navigateTo } from "../app/router";
import { WORKFLOW_ROUTES } from "../routes/routeCatalog";

const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";
const STAGE_KEYS = WORKFLOW_ROUTES.filter((route) => route.kind === "stage").map((route) => route.path.slice(1));

function json(status: number, value: unknown) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json; charset=utf-8" } });
}

function workspace(id: string, name: string) {
  return { workspace_id: id, name, created_at: "2026-10-07T12:00:00+00:00" };
}

type Stage = { state: string; reasons?: { code: string; count?: number }[]; currency?: string; decision?: string; revision?: number | null };

function workflow(id: string, stages: Record<string, Stage> = {}) {
  return {
    workspace_id: id,
    stages: STAGE_KEYS.map((stage) => {
      const value = stages[stage] ?? { state: stage === "recuperacao" ? "NOT_TRACKED" : "NOT_STARTED" };
      return {
        stage, state: value.state, availability: value.state === "UNAVAILABLE" ? "UNAVAILABLE" : "AVAILABLE",
        currency: value.currency ?? (value.state === "REVIEW_REQUIRED" ? "STALE" : "NOT_EVALUATED"),
        decision: value.decision ?? "NONE", reasons: value.reasons ?? [], revision: value.revision ?? null, updated_at: null,
      };
    }),
  };
}

type Handler = () => Response | Promise<Response>;

// Fetch por ROTA e MÉTODO: nada depende da ordem em que os componentes pedem dados.
function routeFetch(routes: Record<string, Handler>) {
  const calls: string[] = [];
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(input)}`;
    calls.push(key);
    const handler = routes[key];
    if (handler) return Promise.resolve(handler());
    return Promise.resolve(json(503, { error: { code: "UNAVAILABLE_IN_TEST", message: "indisponível" } }));
  });
  vi.stubGlobal("fetch", spy);
  return { spy, calls };
}

const workspaceRoute = (id: string) => `GET /app-api/v1/workspaces/${id}`;
const statusRoute = (id: string) => `GET /app-api/v1/workspaces/${id}/workflow-status`;

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

function sidebarLink(name: string) {
  return within(screen.getByRole("navigation", { name: "Fluxo pericial" })).getByRole("link", { name });
}

describe("Início da perícia (#291)", () => {
  test("first open: name as h2, every catalog stage described, next action is the first technical stage", async () => {
    window.history.replaceState(null, "", `/pericias/${A}`);
    routeFetch({ [workspaceRoute(A)]: () => json(200, workspace(A, "Perícia Alfa")), [statusRoute(A)]: () => json(200, workflow(A)) });
    render(<App />);

    expect(await screen.findByRole("heading", { level: 2, name: "Perícia Alfa" })).toBeInTheDocument();
    const next = await screen.findByRole("link", { name: "Abrir Processo" });
    expect(next).toHaveAttribute("href", `/pericias/${A}/processo`);
    expect(next).toHaveAccessibleDescription(/Não iniciada/);
    expect(screen.getByText("Nada aguardando sua decisão neste momento.")).toBeInTheDocument();

    for (const route of WORKFLOW_ROUTES.filter((item) => item.kind === "stage")) {
      const link = sidebarLink(route.label);
      // Nome acessível estável: só o nome da etapa; a situação vem pela descrição.
      expect(link).toHaveAccessibleName(route.label);
      expect(link).toHaveAccessibleDescription(/\S/);
      expect(link).not.toHaveAttribute("aria-current");
    }
    expect(sidebarLink("Recuperação")).toHaveAccessibleDescription(/Sem situação de etapa/);
    expect(within(screen.getByRole("navigation", { name: "Fluxo pericial" })).getByRole("link", { name: "Início" }))
      .toHaveAttribute("aria-current", "page");
    expect(document.body.textContent).not.toMatch(/%|score|pontuação|concluíd/i);
  });

  test("partial data, processing, awaiting review and stale approval are shown separately", async () => {
    window.history.replaceState(null, "", `/pericias/${A}`);
    routeFetch({
      [workspaceRoute(A)]: () => json(200, workspace(A, "Perícia Alfa")),
      [statusRoute(A)]: () => json(200, workflow(A, {
        processo: { state: "AWAITING_REVIEW", reasons: [{ code: "METADATA_AWAITING_CONFIRMATION" }], revision: 2 },
        materiais: { state: "PROCESSING", reasons: [{ code: "MATERIALS_READY", count: 1 }, { code: "MATERIALS_PROCESSING", count: 2 }] },
        laudo: { state: "REVIEW_REQUIRED", decision: "APPROVED", reasons: [{ code: "UPSTREAM_CHANGED", count: 2 }, { code: "REPORT_APPROVED" }], revision: 7 },
        exportar: { state: "APPROVED", currency: "CURRENT", decision: "APPROVED", reasons: [{ code: "WORD_PRESENT" }, { code: "PDF_ABSENT" }], revision: 3 },
      })),
    });
    render(<App />);

    const attention = await screen.findByRole("region", { name: "Precisa de atenção" });
    const items = within(attention).getAllByRole("link").map((link) => link.textContent);
    expect(items).toEqual(["Laudo", "Processo"]);
    expect(within(attention).getByRole("link", { name: "Laudo" })).toHaveAccessibleDescription(/Revisão necessária.*etapa anterior mudou/);
    expect(sidebarLink("Materiais")).toHaveAccessibleDescription(/^Processando.*1 material pronto.*2 materiais em processamento/);
    expect(within(attention).getByRole("link", { name: "Laudo" })).toHaveAccessibleDescription(/Antes da mudança: laudo aprovado/);
    expect(sidebarLink("Laudo")).toHaveAccessibleDescription(/^Revisão necessária/);
    expect(sidebarLink("Laudo")).not.toHaveAccessibleDescription(/^Aprovada/);
    // Entrega parcial é dita explicitamente.
    expect(sidebarLink("Exportar")).toHaveAccessibleDescription(/PDF ainda não gerado: entrega parcial/);
    expect(screen.getByText("2 etapas precisam da sua atenção.")).toBeInTheDocument();
    // Próxima ação: primeira etapa técnica com algo a fazer.
    expect(screen.getByRole("link", { name: "Abrir Processo" })).toBeInTheDocument();
  });

  test("status unavailable never blocks the stages and can be retried", async () => {
    window.history.replaceState(null, "", `/pericias/${A}`);
    let available = false;
    const { calls } = routeFetch({
      [workspaceRoute(A)]: () => json(200, workspace(A, "Perícia Alfa")),
      [statusRoute(A)]: () => (available ? json(200, workflow(A)) : json(503, { error: { code: "LOCAL_API_UNAVAILABLE" } })),
    });
    const user = userEvent.setup();
    render(<App />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Não foi possível verificar a situação das etapas");
    expect(screen.queryByRole("region", { name: "Precisa de atenção" })).not.toBeInTheDocument();
    expect(sidebarLink("Vistoria")).toHaveAttribute("href", `/pericias/${A}/vistoria`);
    expect(sidebarLink("Vistoria")).toHaveAccessibleDescription("Não verificada");

    available = true;
    await user.click(within(alert).getByRole("button", { name: "Verificar novamente" }));
    expect(await screen.findByRole("link", { name: "Abrir Processo" })).toBeInTheDocument();
    expect(calls.filter((call) => call === statusRoute(A))).toHaveLength(2);
  });

  test("a late answer from the previous perícia never reaches the next one", async () => {
    window.history.replaceState(null, "", `/pericias/${A}`);
    let releaseA: (response: Response) => void = () => undefined;
    routeFetch({
      [workspaceRoute(A)]: () => json(200, workspace(A, "Perícia Alfa")),
      [statusRoute(A)]: () => new Promise<Response>((resolve) => { releaseA = resolve; }),
      [workspaceRoute(B)]: () => json(200, workspace(B, "Perícia Beta")),
      [statusRoute(B)]: () => json(200, workflow(B)),
    });
    render(<App />);
    expect(await screen.findByRole("heading", { level: 2, name: "Perícia Alfa" })).toBeInTheDocument();

    act(() => navigateTo(`/pericias/${B}`));
    expect(await screen.findByRole("heading", { level: 2, name: "Perícia Beta" })).toBeInTheDocument();
    await act(async () => {
      releaseA(json(200, workflow(A, { processo: { state: "ATTENTION", reasons: [{ code: "METADATA_CONFLICT" }], revision: 1 } })));
    });
    await waitFor(() => expect(sidebarLink("Processo")).toHaveAccessibleDescription(/^Não iniciada/));
    expect(screen.queryByText(/valores divergentes/)).not.toBeInTheDocument();
  });

  test("an answer labeled with another perícia is refused as unverified", async () => {
    window.history.replaceState(null, "", `/pericias/${A}`);
    routeFetch({ [workspaceRoute(A)]: () => json(200, workspace(A, "Perícia Alfa")), [statusRoute(A)]: () => json(200, workflow(B)) });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível verificar a situação das etapas");
  });

  test("a long perícia name is kept whole", async () => {
    const longName = `Perícia ${"muito longa ".repeat(18)}fim`;
    window.history.replaceState(null, "", `/pericias/${A}`);
    routeFetch({ [workspaceRoute(A)]: () => json(200, workspace(A, longName)), [statusRoute(A)]: () => json(200, workflow(A)) });
    render(<App />);
    expect(await screen.findByRole("heading", { level: 2, name: longName.replace(/\s+/g, " ").trim() })).toBeInTheDocument();
  });

  test("recorded facts are not promoted: no action pending is not 'completed'", async () => {
    window.history.replaceState(null, "", `/pericias/${A}`);
    const settled = Object.fromEntries(STAGE_KEYS.map((key) => [key, { state: key === "recuperacao" ? "NOT_TRACKED" : "RECORDED", revision: 1 }]));
    routeFetch({ [workspaceRoute(A)]: () => json(200, workspace(A, "Perícia Alfa")), [statusRoute(A)]: () => json(200, workflow(A, settled)) });
    render(<App />);
    expect(await screen.findByText(/não apontam ação pendente nas etapas técnicas/)).toBeInTheDocument();
    expect(sidebarLink("Laudo")).toHaveAccessibleDescription(/^Registros presentes/);
    expect(document.body.textContent).not.toMatch(/Aprovada|concluíd|100/i);
  });

  test("the status is refreshed on navigation and aria-current follows the route only", async () => {
    window.history.replaceState(null, "", `/pericias/${A}`);
    const { calls } = routeFetch({ [workspaceRoute(A)]: () => json(200, workspace(A, "Perícia Alfa")), [statusRoute(A)]: () => json(200, workflow(A)) });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("link", { name: "Abrir Processo" });

    await user.click(sidebarLink("Orçamento"));
    await waitFor(() => expect(sidebarLink("Orçamento")).toHaveAttribute("aria-current", "page"));
    expect(sidebarLink("Processo")).not.toHaveAttribute("aria-current");
    await waitFor(() => expect(calls.filter((call) => call === statusRoute(A)).length).toBeGreaterThanOrEqual(2));
    expect(calls.every((call) => !call.startsWith("POST") && !call.startsWith("PUT"))).toBe(true);
  });
});
