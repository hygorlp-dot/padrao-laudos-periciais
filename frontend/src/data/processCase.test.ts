import { afterEach, describe, expect, test, vi } from "vitest";

import {
  ProcessCaseApiError,
  emptyProcessCaseData,
  getProcessCase,
  saveProcessCase,
} from "./processCase";

const ID = "11111111-1111-4111-8111-111111111111";
const DATA = {
  numero_processo: "0000001-00.2026.8.05.0001",
  ramo_justica: "Justiça Estadual",
  tribunal: "  Tribunal de Justiça da Bahia  ",
  vara: "2ª Vara Cível",
  comarca_municipio: "Salvador",
  uf: "BA",
  parte_requerente: "Pessoa requerente",
  parte_requerida: "Pessoa requerida",
};
const SNAPSHOT = {
  workspace_id: ID,
  revision: 2,
  updated_at: "2026-08-24T15:01:00+00:00",
  data: DATA,
};

function jsonResponse(status: number, value: object) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("process case data boundary", () => {
  test("gets the exact workspace-scoped snapshot without a browser token", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(200, SNAPSHOT));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(getProcessCase(ID)).resolves.toEqual(SNAPSHOT);
    expect(fetchSpy).toHaveBeenCalledWith(
      `/app-api/v1/workspaces/${ID}/process-case`,
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
    expect(fetchSpy.mock.calls[0][1].headers).not.toHaveProperty("X-Local-API-Token");
  });

  test("saves all eight exact text fields only after an explicit call", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(200, SNAPSHOT));
    vi.stubGlobal("fetch", fetchSpy);
    const draft = { ...DATA };

    expect(fetchSpy).not.toHaveBeenCalled();
    await expect(saveProcessCase(ID, draft, 1)).resolves.toEqual(SNAPSHOT);

    const [url, request] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/app-api/v1/workspaces/${ID}/process-case`);
    expect(request.method).toBe("POST");
    expect(request.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(request.body as string)).toEqual({ expected_revision: 1, data: DATA });
  });

  test.each(["GET", "POST"])("rejects a %s response bound to another workspace", async (method) => {
    const otherWorkspace = "22222222-2222-4222-8222-222222222222";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(200, { ...SNAPSHOT, workspace_id: otherWorkspace }),
      ),
    );

    const result =
      method === "GET"
        ? getProcessCase(ID)
        : saveProcessCase(ID, DATA, SNAPSHOT.revision);
    await expect(result).rejects.toMatchObject({ kind: "invalid-response" });
  });

  test.each([
    { ...SNAPSHOT, revision: 0 },
    { ...SNAPSHOT, updated_at: null },
    { ...SNAPSHOT, workspace_id: "not-a-uuid" },
    { ...SNAPSHOT, data: { ...DATA, uf: null } },
    { ...SNAPSHOT, data: { ...DATA, extra: "silently ignored" } },
    { ...SNAPSHOT, extra: true },
  ])("rejects malformed or expanded response %#", async (invalid) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, invalid)));
    await expect(getProcessCase(ID)).rejects.toMatchObject({ kind: "invalid-response" });
  });

  test("accepts the explicit never-saved state", async () => {
    const empty = {
      workspace_id: ID,
      revision: null,
      updated_at: null,
      data: emptyProcessCaseData(),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, empty)));
    await expect(getProcessCase(ID)).resolves.toEqual(empty);
  });

  test("maps failures to sanitized process errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(503, { error: { code: "SQLITE_BUSY", message: "token=secret" } }),
      ),
    );

    const error = await saveProcessCase(ID, DATA, 1).catch((value) => value);
    expect(error).toBeInstanceOf(ProcessCaseApiError);
    expect(error).toMatchObject({ kind: "unavailable" });
    expect(String(error)).not.toMatch(/sqlite|token|secret|503/i);
  });

  test("maps stale saves and load failures to operation-specific messages", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(409, { error: { code: "REPOSITORY_CONFLICT" } }))
      .mockResolvedValueOnce(jsonResponse(500, { error: { code: "BROKEN" } }));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(saveProcessCase(ID, DATA, 1)).rejects.toMatchObject({
      kind: "conflict",
      message: "Os dados foram alterados em outra sessão. Atualize a página antes de salvar novamente",
    });
    await expect(getProcessCase(ID)).rejects.toMatchObject({
      kind: "local-failure",
      message: "Não foi possível carregar os dados do processo",
    });
  });
});
