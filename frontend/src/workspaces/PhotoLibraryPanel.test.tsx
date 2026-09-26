import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { PhotoLibraryPanel } from "./PhotoLibraryPanel";

const ID = "11111111-1111-4111-8111-111111111111";
const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const entry = (index: number, overrides: Record<string, unknown> = {}) => ({
  photo_id: `PHOTO-00000000-0000-4000-8000-00000000000${index}`, content_id: `0000000${index}-0000-4000-8000-000000000000`, original_sha256: String(index).repeat(64).slice(0, 64),
  original_filename: `foto-${index}.jpg`, media_type: "image/jpeg", width: 1200, height: 900, captured_at: "2026-09-20T14:05:33", camera: null, has_embedded_location: index === 1,
  imported_at: "2026-09-26T13:00:00+00:00", caption: null, tags: [], report_section: null, report_order: null, ...overrides,
});
const library = (revision: number, photos: object[]) => ({ revision, updated_at: "2026-09-26T13:00:00Z", library: { schema_version: "1.0.0", workspace_id: ID, photos } });

afterEach(() => vi.unstubAllGlobals());

describe("photo library (Vistoria)", () => {
  test("a batch import skips bytes already in the library before uploading them", async () => {
    const existing = entry(1);
    const known = new File([new Uint8Array([1, 2, 3])], "repetida.jpg", { type: "image/jpeg" });
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await known.arrayBuffer())), (byte) => byte.toString(16).padStart(2, "0")).join("");
    const uploads: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/inspection-photos")) { uploads.push(String((init?.headers as Record<string, string>)["X-Document-Filename"])); return Promise.resolve(response(201, { content_id: "00000002-0000-4000-8000-000000000000", checksum_sha256: "2".repeat(64) })); }
      if (url.endsWith("/photo-library/photos")) return Promise.resolve(response(201, library(2, [{ ...existing, original_sha256: digest }, entry(2)])));
      return Promise.resolve(response(200, library(1, [{ ...existing, original_sha256: digest }])));
    }));
    render(<PhotoLibraryPanel workspaceId={ID} />);
    const input = (await screen.findByText("Importar fotos")).querySelector("input")!;
    fireEvent.change(input, { target: { files: [known, new File([new Uint8Array([9, 9])], "nova.jpg", { type: "image/jpeg" })] } });
    expect(await screen.findByText("1 foto importada; 1 repetida ignorada.")).toBeInTheDocument();
    expect(uploads).toEqual(["nova.jpg"]);
    expect(screen.getByText(/localização embutida \(não copiada\)/)).toBeInTheDocument();
  });

  test("a photo enters the report only with a caption and keeps the chosen order", async () => {
    const bodies: unknown[] = [];
    const first = entry(1, { caption: "Fissura", report_section: "INSPECTION", report_order: 1 });
    const second = entry(2, { caption: "Mancha" });
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/photo-library/selection")) { bodies.push(JSON.parse(String(init?.body))); return Promise.resolve(response(200, library(4, [first, { ...second, report_section: "INSPECTION", report_order: 2 }]))); }
      return Promise.resolve(response(200, library(3, [first, second, entry(3)])));
    }));
    render(<PhotoLibraryPanel workspaceId={ID} />);
    const cards = await screen.findAllByRole("listitem");
    expect(within(cards[2]).getByRole("checkbox", { name: /Usar no laudo/ })).toBeDisabled();
    expect(within(cards[2]).getByText("Escreva e salve a legenda para usar no laudo.")).toBeInTheDocument();
    fireEvent.click(within(cards[1]).getByRole("checkbox", { name: /Usar no laudo/ }));
    await waitFor(() => expect(bodies).toEqual([{ expected_revision: 3, selection: [{ photo_id: first.photo_id, section: "INSPECTION" }, { photo_id: second.photo_id, section: "INSPECTION" }] }]));
    expect(await screen.findByText(/figura 2 de 2/)).toBeInTheDocument();
  });
});
