import { beforeEach, describe, expect, test, vi } from "vitest";

import {
  importCaseDocument,
  listCaseDocuments,
  materialUrl,
  MaterialApiError,
} from "./materials";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const CONTENT_ID = "22222222-2222-4222-8222-222222222222";
const PDF = new File(["%PDF-1.7\nsynthetic\n%%EOF\n"], "Autos sintéticos.pdf", {
  type: "application/pdf",
});
const ITEM = {
  workspace_id: WORKSPACE_ID,
  content_id: CONTENT_ID,
  original_filename: PDF.name,
  byte_size: PDF.size,
  checksum_sha256: "a".repeat(64),
  media_type: "application/pdf",
  imported_at: "2026-08-25T12:30:00+00:00",
  origin: "USER_IMPORT",
};

function jsonResponse(status: number, value: object) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

beforeEach(() => vi.unstubAllGlobals());

describe("case material data boundary", () => {
  test("lists exact workspace-bound safe metadata", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(200, { items: [ITEM] }));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(listCaseDocuments(WORKSPACE_ID)).resolves.toEqual([ITEM]);
    expect(fetchSpy).toHaveBeenCalledWith(
      `/app-api/v1/workspaces/${WORKSPACE_ID}/materials`,
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
  });

  test("uploads raw PDF bytes with encoded filename and no browser token", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(201, ITEM));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(importCaseDocument(WORKSPACE_ID, PDF)).resolves.toEqual(ITEM);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/app-api/v1/workspaces/${WORKSPACE_ID}/materials`);
    expect(init).toMatchObject({ method: "POST", body: PDF, credentials: "same-origin" });
    expect(init.headers).toEqual({
      "Content-Type": "application/pdf",
      "X-Document-Filename": "Autos%20sint%C3%A9ticos.pdf",
    });
    expect(JSON.stringify(init)).not.toMatch(/token|private.*path/i);
  });

  test("accepts a PDF filename when the browser omits the MIME type", async () => {
    const file = new File(["%PDF-1.7\nsynthetic\n%%EOF\n"], "autos.pdf");
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(201, {
      ...ITEM,
      original_filename: file.name,
      byte_size: file.size,
    }));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(importCaseDocument(WORKSPACE_ID, file)).resolves.toMatchObject({
      original_filename: "autos.pdf",
    });
    expect(fetchSpy).toHaveBeenCalledOnce();
  });

  test("accepts exactly 128 MiB and rejects one byte above before fetch", async () => {
    const accepted = new File(["x"], "limite.pdf", { type: "application/pdf" });
    Object.defineProperty(accepted, "size", { value: 134_217_728 });
    const rejected = new File(["x"], "acima.pdf", { type: "application/pdf" });
    Object.defineProperty(rejected, "size", { value: 134_217_729 });
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(201, {
      ...ITEM,
      original_filename: accepted.name,
      byte_size: accepted.size,
    }));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(importCaseDocument(WORKSPACE_ID, accepted)).resolves.toMatchObject({
      byte_size: 134_217_728,
    });
    await expect(importCaseDocument(WORKSPACE_ID, rejected)).rejects.toMatchObject({
      kind: "too-large",
    });
    expect(fetchSpy).toHaveBeenCalledOnce();
  });

  test.each([
    new File(["plain"], "notes.txt", { type: "text/plain" }),
    new File([], "empty.pdf", { type: "application/pdf" }),
  ])("rejects unsupported or empty input before fetch", async (file) => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    await expect(importCaseDocument(WORKSPACE_ID, file)).rejects.toBeInstanceOf(
      MaterialApiError,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("rejects malformed browser-facing metadata fail closed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, { items: [{ ...ITEM, storage_path: "C:/secret" }] })),
    );

    await expect(listCaseDocuments(WORKSPACE_ID)).rejects.toMatchObject({
      kind: "invalid-response",
    });
  });

  test("builds only canonical same-origin material URLs", () => {
    expect(materialUrl(WORKSPACE_ID, CONTENT_ID)).toBe(
      `/app-api/v1/workspaces/${WORKSPACE_ID}/materials/${CONTENT_ID}`,
    );
    expect(() => materialUrl(WORKSPACE_ID, "../secret")).toThrow(/material/i);
  });
});
