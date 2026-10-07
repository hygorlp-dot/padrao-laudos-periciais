import { afterEach, describe, expect, test, vi } from "vitest";

import { WorkflowStatusError, getWorkflowStatus, parseWorkflowStatus } from "./workflowStatus";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";

function stage(overrides: Record<string, unknown> = {}) {
  return {
    stage: "processo", state: "NOT_STARTED", availability: "AVAILABLE", currency: "NOT_EVALUATED",
    decision: "NONE", reasons: [{ code: "NO_PROCESS_DATA" }], revision: null, updated_at: null, ...overrides,
  };
}

function json(status: number, value: unknown) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("workflow status data boundary", () => {
  test("reads only through GET on the bridge route, without local token", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(json(200, { workspace_id: ID, stages: [stage()] }));
    vi.stubGlobal("fetch", fetchSpy);

    const value = await getWorkflowStatus(ID);

    expect(value.stages[0].state).toBe("NOT_STARTED");
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/app-api/v1/workspaces/${ID}/workflow-status`);
    expect(init).toMatchObject({ method: "GET", cache: "no-store", credentials: "same-origin" });
    expect(init.headers).toBeUndefined();
    expect(init.body).toBeUndefined();
  });

  test("never accepts another workspace's answer", () => {
    expect(() => parseWorkflowStatus({ workspace_id: OTHER, stages: [stage()] }, ID)).toThrow(WorkflowStatusError);
  });

  test.each([
    ["unknown state", stage({ state: "DONE" })],
    ["stale shown as current", stage({ state: "RECORDED", currency: "STALE", revision: 2 })],
    ["stale shown as approved", stage({ state: "APPROVED", currency: "STALE", revision: 2 })],
    ["raw text reason", stage({ reasons: [{ code: "case analysis changed" }] })],
    ["extra reason field", stage({ reasons: [{ code: "X", detail: "y" }] })],
    ["fractional revision", stage({ revision: 1.5 })],
    ["review required on a current base", stage({ state: "REVIEW_REQUIRED", currency: "CURRENT", revision: 2 })],
    ["unverified stage claiming an available query", stage({ state: "UNAVAILABLE", availability: "AVAILABLE" })],
    ["available query labeled unverified", stage({ availability: "UNAVAILABLE" })],
    ["approval without the revision that supports it", stage({ state: "APPROVED", revision: null })],
  ])("rejects %s", (_label, value) => {
    expect(() => parseWorkflowStatus({ workspace_id: ID, stages: [value] }, ID)).toThrow(WorkflowStatusError);
  });

  test("rejects duplicated stages", () => {
    expect(() => parseWorkflowStatus({ workspace_id: ID, stages: [stage(), stage()] }, ID)).toThrow(WorkflowStatusError);
  });

  test.each([
    [404, "not-found"],
    [503, "unavailable"],
    [500, "unavailable"],
  ])("maps HTTP %s to %s instead of an empty status", async (status, kind) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(status, { error: { code: "X" } })));
    await expect(getWorkflowStatus(ID)).rejects.toMatchObject({ kind });
  });

  test("a network failure is unavailable, an abort stays an abort", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(getWorkflowStatus(ID)).rejects.toMatchObject({ kind: "unavailable" });

    const controller = new AbortController();
    controller.abort();
    const abort = new DOMException("aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abort));
    await expect(getWorkflowStatus(ID, controller.signal)).rejects.toBe(abort);
  });

  test("an invalid body is invalid, not empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 200 })));
    await expect(getWorkflowStatus(ID)).rejects.toMatchObject({ kind: "invalid-response" });
  });
});
