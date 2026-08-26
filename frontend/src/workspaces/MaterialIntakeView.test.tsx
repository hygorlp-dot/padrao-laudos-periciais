import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { MaterialIntakeView } from "./MaterialIntakeView";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const CONTENT_ID = "22222222-2222-4222-8222-222222222222";
const ITEM = {
  workspace_id: WORKSPACE_ID,
  content_id: CONTENT_ID,
  original_filename: "Autos sintéticos.pdf",
  byte_size: 1024,
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

describe("material intake view", () => {
  test("shows an actionable empty state after loading", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, { items: [] })));
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    expect(screen.getByRole("status")).toHaveTextContent("Carregando materiais");
    expect(
      await screen.findByRole("heading", { name: "Nenhum documento importado" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Selecionar PDF")).toHaveAttribute("accept", ".pdf,application/pdf");
  });

  test("imports a PDF, exposes progress and renders a safe open action", async () => {
    let resolveImport: (response: Response) => void = () => undefined;
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { items: [] }))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveImport = resolve; }));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    const input = await screen.findByLabelText("Selecionar PDF");
    await user.upload(
      input,
      new File(["%PDF-1.7\nsynthetic\n%%EOF\n"], ITEM.original_filename, {
        type: "application/pdf",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Importar PDF" }));
    expect(screen.getByRole("button", { name: "Processando PDF…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Leitura local em andamento. OCR será usado somente nas páginas sem texto útil.",
    );

    resolveImport(jsonResponse(201, ITEM));
    expect(await screen.findByText(ITEM.original_filename)).toBeInTheDocument();
    expect(input).toHaveValue("");
    const open = screen.getByRole("link", { name: `Abrir ${ITEM.original_filename}` });
    expect(open).toHaveAttribute(
      "href",
      `/app-api/v1/workspaces/${WORKSPACE_ID}/materials/${CONTENT_ID}`,
    );
    expect(open).not.toHaveAttribute("href", expect.stringMatching(/file:|private/i));
    expect(screen.getByRole("link", { name: "Revisar dados extraídos" })).toHaveAttribute(
      "href",
      `/pericias/${WORKSPACE_ID}/processo`,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Importar PDF" })).toHaveFocus());
  });

  test("keeps a controlled retryable error without exposing backend details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(503, { error: { code: "PRIVATE_STORAGE_UNAVAILABLE", message: "C:/secret/token" } }),
      ),
    );
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Não foi possível carregar os materiais");
    expect(alert).not.toHaveTextContent(/secret|token|private|503/i);
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
  });
});
