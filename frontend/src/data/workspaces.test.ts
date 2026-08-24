import { afterEach, describe, expect, test, vi } from "vitest";

import {
  WorkspaceApiError,
  createWorkspace,
  getWorkspace,
  listWorkspaces,
} from "./workspaces";

const WORKSPACE = {
  workspace_id: "11111111-1111-4111-8111-111111111111",
  name: "Perícia de teste",
  created_at: "2026-08-24T12:30:00+00:00",
} as const;

function jsonResponse(status: number, value: object) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("workspace data boundary", () => {
  test("lists workspaces through the only browser-facing relative endpoint", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(200, { items: [WORKSPACE] }));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(listWorkspaces()).resolves.toEqual([WORKSPACE]);
    expect(fetchSpy).toHaveBeenCalledWith(
      "/app-api/v1/workspaces",
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
    const request = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(request.headers).not.toHaveProperty("X-Local-API-Token");
  });

  test("creates without silently normalizing the caller name or supplying identity", async () => {
    const callerName = "  Perícia técnica  ";
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(jsonResponse(201, { ...WORKSPACE, name: callerName }));
    vi.stubGlobal("fetch", fetchSpy);

    const created = await createWorkspace(callerName);

    expect(created.name).toBe(callerName);
    const [url, request] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/app-api/v1/workspaces");
    expect(request.method).toBe("POST");
    expect(JSON.parse(request.body as string)).toEqual({ name: callerName });
    expect(request.body).not.toContain("workspace_id");
    expect(request.body).not.toContain("created_at");
    expect(request.headers).toEqual({ "Content-Type": "application/json" });
  });

  test("gets one workspace through a canonical URL segment", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(200, WORKSPACE));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(getWorkspace(WORKSPACE.workspace_id)).resolves.toEqual(WORKSPACE);
    expect(fetchSpy).toHaveBeenCalledWith(
      `/app-api/v1/workspaces/${WORKSPACE.workspace_id}`,
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
  });

  test.each([
    [404, "not-found", "Perícia não encontrada"],
    [409, "conflict", "Não foi possível criar a perícia por conflito local"],
    [503, "unavailable", "Armazenamento local indisponível"],
    [500, "local-failure", "Não foi possível concluir a operação local"],
  ] as const)("maps status %s to a sanitized %s error", async (status, kind, message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(status, {
          error: { code: "INTERNAL_DETAIL", message: "SQLite C:\\private token=secret" },
        }),
      ),
    );

    const error = await getWorkspace(WORKSPACE.workspace_id).catch((value) => value);

    expect(error).toBeInstanceOf(WorkspaceApiError);
    expect(error).toMatchObject({ kind, message });
    expect(String(error)).not.toMatch(/sqlite|token|private|internal_detail/i);
  });

  test.each([
    { ...WORKSPACE, workspace_id: "NOT-A-UUID" },
    { ...WORKSPACE, created_at: "not-a-timestamp" },
    { ...WORKSPACE, name: "" },
    { ...WORKSPACE, unexpected: true },
  ])("rejects a malformed or expanded workspace response %#", async (invalid) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, invalid)));

    await expect(getWorkspace(WORKSPACE.workspace_id)).rejects.toMatchObject({
      kind: "invalid-response",
    });
  });

  test("rejects a malformed list envelope instead of silently dropping data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, { items: [WORKSPACE], next: "ignored" })),
    );

    await expect(listWorkspaces()).rejects.toMatchObject({ kind: "invalid-response" });
  });
});
