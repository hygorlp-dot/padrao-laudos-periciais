import { afterEach, describe, expect, test, vi } from "vitest";

import { WORKSPACE_MUTATED, installMutationSignal, mutatedWorkspace } from "./mutationSignal";

const ID = "11111111-1111-4111-8111-111111111111";
const BASE = "http://127.0.0.1:5173/pericias";

afterEach(() => vi.unstubAllGlobals());

describe("workspace mutation signal", () => {
  test.each([
    ["POST", `/app-api/v1/workspaces/${ID}/process-case`, ID],
    ["PUT", `/app-api/v1/workspaces/${ID}/report-snapshot`, ID],
    ["GET", `/app-api/v1/workspaces/${ID}/process-case`, null],
    ["HEAD", `/app-api/v1/workspaces/${ID}/process-case`, null],
    ["POST", "/app-api/v1/workspaces", null],
    ["POST", `/outra-coisa/v1/workspaces/${ID}/x`, null],
    ["POST", `http://outro.local/app-api/v1/workspaces/${ID}/x`, null],
  ])("%s %s → %s", (method, url, expected) => {
    expect(mutatedWorkspace(url, { method }, BASE)).toBe(expected);
  });

  test("signals only successful writes, once installed, without touching the request", async () => {
    const original = vi.fn().mockResolvedValueOnce(new Response("{}", { status: 200 })).mockResolvedValueOnce(new Response("{}", { status: 409 }));
    vi.stubGlobal("fetch", original);
    installMutationSignal(window);
    installMutationSignal(window);
    const events: string[] = [];
    const listener = (event: Event) => events.push((event as CustomEvent<string>).detail);
    window.addEventListener(WORKSPACE_MUTATED, listener);
    const init = { method: "POST", body: "{}" };
    await window.fetch(`/app-api/v1/workspaces/${ID}/process-case`, init);
    await window.fetch(`/app-api/v1/workspaces/${ID}/process-case`, init);
    window.removeEventListener(WORKSPACE_MUTATED, listener);
    expect(events).toEqual([ID]);
    expect(original).toHaveBeenCalledTimes(2);
    expect(original.mock.calls[0][1]).toBe(init);
  });
});
