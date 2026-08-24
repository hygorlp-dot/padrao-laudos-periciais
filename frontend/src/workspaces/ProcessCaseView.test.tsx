import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { emptyProcessCaseData } from "../data/processCase";
import { ProcessCaseView } from "./ProcessCaseView";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "22222222-2222-4222-8222-222222222222";
const DATA = {
  numero_processo: "0000001-00.2026.8.05.0001",
  tribunal: "Tribunal de Justiça da Bahia",
  vara: "2ª Vara Cível",
  comarca_municipio: "Salvador",
  uf: "BA",
  parte_requerente: "Pessoa requerente",
  parte_requerida: "Pessoa requerida",
};

function snapshot(
  data = emptyProcessCaseData(),
  revision: number | null = null,
  workspaceId = ID,
) {
  return {
    workspace_id: workspaceId,
    revision,
    updated_at: revision === null ? null : "2026-08-24T15:01:00+00:00",
    data,
  };
}

function jsonResponse(status: number, value: object) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("process case form", () => {
  test("loads seven real fields and saves only through the explicit primary action", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot()))
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ProcessCaseView workspaceId={ID} />);

    expect(screen.getByRole("status")).toHaveTextContent("Carregando dados do processo");
    const number = await screen.findByRole("textbox", { name: "Número do processo" });
    expect(screen.getAllByRole("textbox")).toHaveLength(7);
    await user.type(number, DATA.numero_processo);
    await user.type(screen.getByRole("textbox", { name: "Tribunal" }), DATA.tribunal);
    await user.type(screen.getByRole("textbox", { name: "Vara" }), DATA.vara);
    await user.type(
      screen.getByRole("textbox", { name: "Comarca ou município" }),
      DATA.comarca_municipio,
    );
    await user.type(screen.getByRole("textbox", { name: "UF" }), DATA.uf);
    await user.type(screen.getByRole("textbox", { name: "Parte requerente" }), DATA.parte_requerente);
    await user.type(screen.getByRole("textbox", { name: "Parte requerida" }), DATA.parte_requerida);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const save = screen.getByRole("button", { name: "Salvar dados do processo" });
    await user.click(save);

    expect(await screen.findByText("Dados do processo salvos")).toBeInTheDocument();
    expect(screen.getByText("Revisão 1")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(JSON.parse(fetchSpy.mock.calls[1][1].body)).toEqual({
      expected_revision: null,
      data: DATA,
    });
    expect(save).toHaveFocus();
  });

  test("loads persisted values and records an explicit correction", async () => {
    const corrected = { ...DATA, vara: "3ª Vara Cível" };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)))
      .mockResolvedValueOnce(jsonResponse(200, snapshot(corrected, 2)));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ProcessCaseView workspaceId={ID} />);

    const vara = await screen.findByRole("textbox", { name: "Vara" });
    expect(vara).toHaveValue(DATA.vara);
    await user.clear(vara);
    await user.type(vara, corrected.vara);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Salvar dados do processo" }));

    expect(await screen.findByText("Revisão 2")).toBeInTheDocument();
    expect(JSON.parse(fetchSpy.mock.calls[1][1].body).expected_revision).toBe(1);
    expect(JSON.parse(fetchSpy.mock.calls[1][1].body).data.vara).toBe(corrected.vara);
  });

  test("keeps the draft and exposes a sanitized retryable save failure", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot()))
      .mockResolvedValueOnce(
        jsonResponse(503, { error: { code: "SQLITE_BUSY", message: "token=secret" } }),
      );
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ProcessCaseView workspaceId={ID} />);

    const tribunal = await screen.findByRole("textbox", { name: "Tribunal" });
    await user.type(tribunal, DATA.tribunal);
    await user.click(screen.getByRole("button", { name: "Salvar dados do processo" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Armazenamento local indisponível");
    expect(alert).not.toHaveTextContent(/sqlite|token|secret|503/i);
    expect(tribunal).toHaveValue(DATA.tribunal);
    const save = screen.getByRole("button", { name: "Salvar dados do processo" });
    expect(save).toBeEnabled();
    expect(save).toHaveFocus();
  });

  test("recovers a sanitized load failure through an explicit retry", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(503, { error: { code: "SQLITE_BUSY", message: "private path" } }),
      )
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ProcessCaseView workspaceId={ID} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Armazenamento local indisponível");
    expect(alert).not.toHaveTextContent(/sqlite|private|503/i);
    await user.click(screen.getByRole("button", { name: "Tentar novamente" }));

    expect(await screen.findByRole("textbox", { name: "Número do processo" })).toHaveValue(
      DATA.numero_processo,
    );
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  test("never exposes one workspace draft while another workspace is loading", async () => {
    let resolveOther: (response: Response) => void = () => undefined;
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)))
      .mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          resolveOther = resolve;
        }),
      );
    vi.stubGlobal("fetch", fetchSpy);
    const { rerender } = render(<ProcessCaseView workspaceId={ID} />);

    expect(await screen.findByRole("textbox", { name: "Tribunal" })).toHaveValue(DATA.tribunal);
    rerender(<ProcessCaseView workspaceId={OTHER_ID} />);

    expect(screen.getByRole("status")).toHaveTextContent("Carregando dados do processo");
    expect(screen.queryByDisplayValue(DATA.tribunal)).not.toBeInTheDocument();
    resolveOther(
      jsonResponse(200, {
        ...snapshot(),
        workspace_id: OTHER_ID,
      }),
    );
    expect(await screen.findByRole("textbox", { name: "Tribunal" })).toHaveValue("");
  });

  test("does not leave the next workspace disabled when a previous save is aborted", async () => {
    let pendingSaveSignal: AbortSignal | undefined;
    const pendingSave = new Promise<Response>(() => undefined);
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)))
      .mockImplementationOnce((_url: string, init: RequestInit) => {
        pendingSaveSignal = init.signal as AbortSignal;
        return pendingSave;
      })
      .mockResolvedValueOnce(jsonResponse(200, snapshot(undefined, null, OTHER_ID)))
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1, ID)));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    const { rerender } = render(<ProcessCaseView workspaceId={ID} />);

    await screen.findByRole("textbox", { name: "Tribunal" });
    await user.click(screen.getByRole("button", { name: "Salvar dados do processo" }));
    expect(screen.getByRole("button", { name: "Salvando…" })).toBeDisabled();

    rerender(<ProcessCaseView workspaceId={OTHER_ID} />);

    expect(pendingSaveSignal?.aborted).toBe(true);
    expect(await screen.findByRole("textbox", { name: "Tribunal" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Salvar dados do processo" })).toBeEnabled();

    rerender(<ProcessCaseView workspaceId={ID} />);

    expect(await screen.findByRole("textbox", { name: "Tribunal" })).toHaveValue(DATA.tribunal);
    expect(screen.getByRole("textbox", { name: "Tribunal" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Salvar dados do processo" })).toBeEnabled();
  });
});
