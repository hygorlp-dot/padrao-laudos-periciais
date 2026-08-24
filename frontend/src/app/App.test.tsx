import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { App } from "./App";

const ID = "11111111-1111-4111-8111-111111111111";
const WORKSPACE = {
  workspace_id: ID,
  name: "Perícia de teste",
  created_at: "2026-08-24T12:30:00+00:00",
};

function jsonResponse(status: number, value: object) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(200, { items: [] }))),
  );
});

describe("pericia directory", () => {
  test("announces loading before showing the real empty state", async () => {
    let resolveRequest: (response: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((resolve) => {
          resolveRequest = resolve;
        }),
      ),
    );

    render(<App />);

    expect(screen.getByRole("status")).toHaveTextContent("Carregando perícias locais");
    resolveRequest(jsonResponse(200, { items: [] }));
    expect(
      await screen.findByRole("heading", { name: "Nenhuma perícia cadastrada" }),
    ).toBeInTheDocument();
  });

  test("offers one clear action when no workspace exists", async () => {
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Nenhuma perícia cadastrada" }),
    ).toBeInTheDocument();
    expect(document.activeElement).toBe(document.body);
    expect(screen.getByRole("button", { name: "Nova perícia" })).toBeInTheDocument();
    expect(screen.queryByText(/dashboard|progresso|status/i)).not.toBeInTheDocument();
  });

  test("lists only persisted facts and opens an existing workspace", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { items: [WORKSPACE] }))
      .mockResolvedValueOnce(jsonResponse(200, WORKSPACE));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText(WORKSPACE.name)).toBeInTheDocument();
    expect(screen.getByRole("time")).toHaveAttribute("dateTime", WORKSPACE.created_at);
    expect(screen.queryByText(ID)).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: `Abrir ${WORKSPACE.name}` }));

    await waitFor(() => expect(window.location.pathname).toBe(`/pericias/${ID}`));
    expect(await screen.findByRole("heading", { name: WORKSPACE.name })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveTextContent(WORKSPACE.name);
  });

  test("creates with one labeled field and enters the persisted workspace", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { items: [] }))
      .mockResolvedValueOnce(jsonResponse(201, WORKSPACE))
      .mockResolvedValueOnce(jsonResponse(200, WORKSPACE));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Nova perícia" }));
    const input = screen.getByRole("textbox", { name: "Nome da perícia" });
    await user.type(input, WORKSPACE.name);
    await user.click(screen.getByRole("button", { name: "Criar perícia" }));

    await waitFor(() => expect(window.location.pathname).toBe(`/pericias/${ID}`));
    expect(await screen.findByRole("heading", { name: WORKSPACE.name })).toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    expect(fetchSpy.mock.calls[1][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ name: WORKSPACE.name }),
    });
  });

  test("does not let a stale creation completion replace a newer route", async () => {
    let resolveCreate: (response: Response) => void = () => undefined;
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { items: [] }))
      .mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          resolveCreate = resolve;
        }),
      );
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Nova perícia" }));
    await user.type(screen.getByRole("textbox", { name: "Nome da perícia" }), WORKSPACE.name);
    await user.click(screen.getByRole("button", { name: "Criar perícia" }));

    window.history.pushState(null, "", "/teste-inexistente");
    act(() => window.dispatchEvent(new PopStateEvent("popstate")));
    expect(await screen.findByRole("heading", { name: "Página não encontrada" })).toBeInTheDocument();
    expect(fetchSpy.mock.calls[1][1]).toMatchObject({ signal: expect.any(AbortSignal) });
    expect((fetchSpy.mock.calls[1][1] as RequestInit).signal).toHaveProperty("aborted", true);

    await act(async () => resolveCreate(jsonResponse(201, WORKSPACE)));
    expect(window.location.pathname).toBe("/teste-inexistente");
  });

  test("rejects whitespace locally and associates the error with the name field", async () => {
    const fetchSpy = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse(200, { items: [] })));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Nova perícia" }));
    const input = screen.getByRole("textbox", { name: "Nome da perícia" });
    await user.type(input, "   ");
    await user.click(screen.getByRole("button", { name: "Criar perícia" }));

    const error = screen.getByText("Informe o nome da perícia");
    expect(error).toHaveAttribute("id");
    expect(input).toHaveAttribute("aria-describedby", error.id);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  test("restores focus after a failed creation and after canceling", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { items: [] }))
      .mockResolvedValueOnce(
        jsonResponse(503, { error: { code: "SERVICE_UNAVAILABLE", message: "internal" } }),
      );
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Nova perícia" }));
    const input = screen.getByRole("textbox", { name: "Nome da perícia" });
    await user.type(input, WORKSPACE.name);
    await user.click(screen.getByRole("button", { name: "Criar perícia" }));

    await screen.findByText("Armazenamento local indisponível");
    await waitFor(() => expect(input).toHaveFocus());
    expect(input).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.getByRole("button", { name: "Nova perícia" })).toHaveFocus();
  });

  test("shows a sanitized recoverable API error instead of an endless spinner", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(503, { error: { code: "SQLITE_BUSY", message: "token secret" } }),
      ),
    );
    render(<App />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Armazenamento local indisponível");
    expect(alert).not.toHaveTextContent(/sqlite|token|http|503/i);
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
  });
});

describe("workspace-aware routing", () => {
  test("renders the real process case form as the only primary action on Processo", async () => {
    window.history.replaceState(null, "", `/pericias/${ID}/processo`);
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, WORKSPACE))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          workspace_id: ID,
          revision: null,
          updated_at: null,
          data: {
            numero_processo: "",
            tribunal: "",
            vara: "",
            comarca_municipio: "",
            uf: "",
            parte_requerente: "",
            parte_requerida: "",
          },
        }),
      );
    vi.stubGlobal("fetch", fetchSpy);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Identificação do processo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar dados do processo" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Avançar para Análise" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /salvar dados do processo/i })).toHaveLength(1);
  });

  test("deep-links to a real workspace with the active stage and title", async () => {
    window.history.replaceState(null, "", `/pericias/${ID}/vistoria`);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, WORKSPACE)));

    render(<App />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Vistoria" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveTextContent(WORKSPACE.name);
    expect(screen.getByRole("link", { name: "Vistoria", current: "page" })).toHaveAttribute(
      "href",
      `/pericias/${ID}/vistoria`,
    );
    expect(screen.getByRole("link", { name: "Processo" })).toHaveAttribute(
      "href",
      `/pericias/${ID}/processo`,
    );
    expect(screen.getByRole("link", { name: "Todas as perícias" })).toHaveAttribute("href", "/");
    expect(document.title).toBe("Sistema Pericial — Vistoria");
  });

  test("keeps the workspace identity through browser history changes", async () => {
    window.history.replaceState(null, "", `/pericias/${ID}/processo`);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, WORKSPACE)));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Processo" })).toBeInTheDocument();

    window.history.pushState(null, "", `/pericias/${ID}/vistoria`);
    act(() => window.dispatchEvent(new PopStateEvent("popstate")));
    expect(await screen.findByRole("heading", { name: "Vistoria" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveTextContent(WORKSPACE.name);
  });

  test("renders a controlled workspace-not-found state", async () => {
    window.history.replaceState(null, "", `/pericias/${ID}/vistoria`);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(404, { error: { code: "WORKSPACE_NOT_FOUND", message: "internal" } }),
      ),
    );

    render(<App />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Perícia não encontrada");
    expect(alert).not.toHaveTextContent(/uuid|workspace|internal|http/i);
    expect(document.title).toBe("Sistema Pericial — Perícia não encontrada");
    expect(screen.getByRole("link", { name: "Voltar às perícias" })).toHaveAttribute(
      "href",
      "/",
    );

    window.history.pushState(null, "", `/pericias/${ID}/processo`);
    act(() => window.dispatchEvent(new PopStateEvent("popstate")));
    expect(screen.getByRole("heading", { level: 1, name: "Perícia não encontrada" })).toBeInTheDocument();
    expect(document.title).toBe("Sistema Pericial — Perícia não encontrada");
  });

  test("keeps a distinct controlled fallback for an invalid route", () => {
    window.history.replaceState(null, "", "/teste-inexistente");
    render(<App />);

    expect(screen.getByRole("heading", { name: "Página não encontrada" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Voltar às perícias" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("shell invariants", () => {
  test("keeps neutral descriptor, semantic landmarks and skip link", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Nenhuma perícia cadastrada" });

    expect(screen.getByLabelText("Sistema Pericial")).toBeInTheDocument();
    expect(screen.queryByText(/arcd/i)).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Fluxo pericial" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("link", { name: "Ir para o conteúdo" })).toHaveAttribute(
      "href",
      "#main-content",
    );
  });
});
