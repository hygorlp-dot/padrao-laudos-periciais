import { afterEach, expect, test, vi } from "vitest";
import { createDefaultTemplate, renderDeliveryPackage, templateManifest, type DeliveryEnvelope } from "./deliverySnapshot";

const ID = "11111111-1111-4111-8111-111111111111";
const json = (value: object) => new Response(JSON.stringify(value), { status: 200 });
afterEach(() => vi.unstubAllGlobals());

test.each(["PRODUCT-DEFAULT-REPORT-V1", "PRODUCT-DEFAULT-REPORT-V2"])("accepts the authoritative professional %s manifest", async (id) => {
  const base = templateManifest(id, "DOCX");
  const fields = id.endsWith("V1") ? ["EXPERT_COVER_NAME", "PARTICIPANTS_ACTIVE", "PARTICIPANTS_PASSIVE", "ACTION_TYPE", "PROTOCOL_OPENING", "REPORT_CITY_DATE"] : ["ACTION_TYPE", "PROTOCOL_OPENING", "REPORT_CITY_DATE"];
  const manifest = { ...base, bindings: [...base.bindings, ...fields.map((field) => ({ field, placeholder: `[[${field}]]` }))] };
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json({ template: { content_id: "CONTENT-1" }, manifest }))));
  expect((await createDefaultTemplate(ID)).manifest).toEqual(manifest);
});

test.each([true, false])("reopened default delivery renders the bound Report's professional=%s variant", async (professional) => {
  const value = { revision: 7, snapshot: { schema_version: "1.0.0", workspace_id: ID, template_id: "PRODUCT-DEFAULT-REPORT-V2", template_format: "DOCX", binding: { workspace_id: ID, report_snapshot_id: "REPORT-1", report_revision: 4 }, artifacts: [], decisions: [], stale_reasons: [] } } as unknown as DeliveryEnvelope;
  const calls: RequestInit[] = [];
  vi.stubGlobal("fetch", vi.fn((url, init?: RequestInit) => {
    if (String(url).endsWith("/report-snapshot")) return Promise.resolve(json({ revision: 4, snapshot: { report_id: "REPORT-1", ...(professional ? { presentation: { captured_revision: 4 } } : {}) } }));
    calls.push(init!); return Promise.resolve(json(value));
  }));
  await renderDeliveryPackage(ID, value);
  const manifest = JSON.parse(String(calls[0].body)).manifest;
  expect(manifest.bindings.map((b: { field: string }) => b.field).includes("ACTION_TYPE")).toBe(professional);
});

test("a changed Report cannot select a manifest for the old delivery", async () => {
  const value = { revision: 7, snapshot: { template_id: "PRODUCT-DEFAULT-REPORT-V2", template_format: "DOCX", binding: { report_snapshot_id: "OLD", report_revision: 4 } } } as unknown as DeliveryEnvelope;
  const fetcher = vi.fn((url: unknown) => { expect(String(url)).toContain("/report-snapshot"); return Promise.resolve(json({ revision: 5, snapshot: { report_id: "NEW", presentation: {} } })); });
  vi.stubGlobal("fetch", fetcher);
  await expect(renderDeliveryPackage(ID, value)).rejects.toThrow();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(String(fetcher.mock.calls[0]?.[0])).toContain("/report-snapshot");
});
