import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { PjeDocumentAvailability } from "./PjeDocumentAvailability";

const ID = "11111111-1111-4111-8111-111111111111";
const inventory = (revision: number, available: boolean) => ({ revision, inventory: { schema_version: "1.0.0", workspace_id: ID, documents: [{ document_id: "DOC-PJE-001", id_pje: "900001", title: "Petição sintética", raw_type: "PETICAO", normalized_type: "PETICAO_INICIAL", page_start: 2, page_end: 3, available }] } });
const response = (value: object) => new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

test("lets the professional keep a logical PJe document unavailable without entering an internal id", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response(inventory(1, true))).mockResolvedValueOnce(response(inventory(2, false)));
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  render(<PjeDocumentAvailability workspaceId={ID} refreshKey={0} />);
  const checkbox = await screen.findByRole("checkbox", { name: "Disponível para análise" });
  expect(screen.getByText("Petição sintética")).toBeInTheDocument();
  await user.click(checkbox);
  expect(await screen.findByRole("checkbox", { name: "Disponível para análise" })).not.toBeChecked();
  expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining("/pje-intake/availability"), expect.objectContaining({ method: "POST" }));
});
