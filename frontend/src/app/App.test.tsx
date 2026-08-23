import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { App } from "./App";
import { StatusState } from "../ui/StatusState";

const ROUTES = [
  ["/", "Início"],
  ["/processo", "Processo"],
  ["/analise", "Análise"],
  ["/planejamento", "Planejamento"],
  ["/vistoria", "Vistoria"],
  ["/evidencias", "Evidências"],
  ["/constatacoes", "Constatações"],
  ["/analise-tecnica", "Análise técnica"],
  ["/laudo", "Laudo"],
  ["/revisao", "Revisão"],
  ["/exportar", "Exportar"],
] as const;

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
});

describe("application shell routing", () => {
  test.each(ROUTES)("renders the canonical route %s", (path, heading) => {
    window.history.replaceState(null, "", path);

    render(<App />);

    expect(
      screen.getByRole("heading", { level: 1, name: heading }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: heading, current: "page" }),
    ).toHaveAttribute("href", path);
  });

  test("renders a controlled fallback for an unknown route", () => {
    window.history.replaceState(null, "", "/rota-inexistente");

    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Página não encontrada" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Voltar ao início" })).toHaveAttribute(
      "href",
      "/",
    );
  });

  test("activates workflow links with the keyboard and updates the route", async () => {
    const user = userEvent.setup();
    render(<App />);
    const processLink = screen.getByRole("link", { name: "Processo" });

    processLink.focus();
    await user.keyboard("{Enter}");

    expect(window.location.pathname).toBe("/processo");
    expect(
      screen.getByRole("heading", { level: 1, name: "Processo" }),
    ).toBeInTheDocument();
    expect(processLink).toHaveAttribute("aria-current", "page");
  });

  test("restores the matching view when browser history changes", () => {
    render(<App />);
    window.history.pushState(null, "", "/vistoria");

    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    expect(
      screen.getByRole("heading", { level: 1, name: "Vistoria" }),
    ).toBeInTheDocument();
  });

  test("announces route changes and updates the document title", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("link", { name: "Processo" }));

    expect(screen.getByRole("status")).toHaveTextContent("Rota atual: Processo");
    expect(document.title).toBe("Processo — ARCD");
  });

  test("renders semantic landmarks and a working skip link", () => {
    render(<App />);

    expect(screen.getByRole("navigation", { name: "Fluxo pericial" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("link", { name: "Ir para o conteúdo" })).toHaveAttribute(
      "href",
      "#main-content",
    );
  });

  test("does not start a network request while rendering or navigating", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("link", { name: "Processo" }));

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("presentation states", () => {
  test("loading is announced without fabricated progress", () => {
    render(<StatusState kind="loading" />);

    expect(screen.getByRole("status")).toHaveTextContent("Preparando esta etapa");
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  test("empty state gives one clear next action", () => {
    render(<StatusState kind="empty" />);

    expect(screen.getByRole("heading", { name: "Nenhuma perícia selecionada" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Conhecer o fluxo" })).toHaveAttribute(
      "href",
      "/processo",
    );
  });

  test("error state is actionable and contains no internal detail", () => {
    render(<StatusState kind="error" />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Não foi possível mostrar esta etapa");
    expect(alert).toHaveTextContent("Volte ao início e tente novamente");
    expect(alert).not.toHaveTextContent(/sqlite|traceback|exception|token/i);
  });

  test("ready state identifies the current workflow stage", () => {
    render(<StatusState kind="ready" stage="Vistoria" />);

    expect(screen.getByText("Vistoria está pronta para receber o fluxo futuro.")).toBeInTheDocument();
  });
});
