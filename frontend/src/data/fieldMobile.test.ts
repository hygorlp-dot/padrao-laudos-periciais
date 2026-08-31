import { afterEach, describe, expect, it, vi } from "vitest";
import { prepareOfflineInspection, syncOfflineInspection, updateOfflineInspection } from "./fieldMobile";

const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

describe("field mobile data boundary", () => {
  afterEach(() => vi.restoreAllMocks());
  it("prepares a workspace-scoped package without exposing a private path or token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response(201, { device_id: "DEVICE-1", package: { package_id: "PACKAGE-1", package_revision: 1, device_sequence: 1 } }));
    const result = await prepareOfflineInspection("11111111-1111-4111-8111-111111111111", "SESSION-1");
    expect(result.package.package_id).toBe("PACKAGE-1");
    expect(fetchMock.mock.calls[0][0]).toContain("/offline-inspection");
    expect(JSON.stringify(fetchMock.mock.calls[0][1])).not.toMatch(/token|private.*path/i);
  });
  it("returns visible 409 conflicts instead of treating them as transport failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response(409, { accepted: false, revision: null, conflicts: [{ code: "STALE_PLAN", message: "Plano mudou", record_ids: [], requires_explicit_review: true }] }));
    const result = await syncOfflineInspection("11111111-1111-4111-8111-111111111111", "PACKAGE-1");
    expect(result.accepted).toBe(false);
    expect(result.conflicts[0].code).toBe("STALE_PLAN");
  });
  it("persists capture as a new offline revision", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response(201, { device_id: "DEVICE-1", package: { package_id: "PACKAGE-2", package_revision: 2, device_sequence: 2, inspection_snapshot: {} } }));
    await updateOfflineInspection("11111111-1111-4111-8111-111111111111", "PACKAGE-1", 1, {} as never);
    expect(fetchMock.mock.calls[0][1]?.method).toBe("PUT");
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).expected_package_revision).toBe(1);
  });
});
