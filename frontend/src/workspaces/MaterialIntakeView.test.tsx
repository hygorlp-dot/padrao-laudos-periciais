import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { MaterialIntakeView } from "./MaterialIntakeView";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const CONTENT_ID = "22222222-2222-4222-8222-222222222222";
const ROOT = `/app-api/v1/workspaces/${WORKSPACE_ID}`;
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

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;

// Fetch roteado por metodo + URL: a tela consulta materiais, estado de leitura e
// inventario PJe em paralelo, entao a ordem das chamadas nao e um contrato.
function routedFetch(routes: Record<string, Handler>) {
  return vi.fn((url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const handler = routes[key];
    if (handler === undefined) return Promise.resolve(jsonResponse(404, { error: { code: "NOT_FOUND" } }));
    return Promise.resolve(handler(init));
  });
}

function processing(state: string) {
  return jsonResponse(200, { items: [{ content_id: CONTENT_ID, state }] });
}

async function choosePdf(user: ReturnType<typeof userEvent.setup>) {
  const input = await screen.findByLabelText("Selecionar PDF");
  await user.upload(input, new File(["%PDF-1.7\nsynthetic\n%%EOF\n"], ITEM.original_filename, { type: "application/pdf" }));
  return input;
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.useRealTimers());

describe("material intake view", () => {
  test("shows an actionable empty state after loading", async () => {
    vi.stubGlobal("fetch", routedFetch({
      [`GET ${ROOT}/materials`]: () => jsonResponse(200, { items: [] }),
      [`GET ${ROOT}/material-processing`]: () => jsonResponse(200, { items: [] }),
    }));
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    expect(screen.getByRole("status")).toHaveTextContent("Carregando materiais");
    expect(
      await screen.findByRole("heading", { name: "Nenhum documento importado" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Selecionar PDF")).toHaveAttribute("accept", ".pdf,application/pdf");
  });

  test("imports a PDF, exposes progress and renders a safe open action", async () => {
    let resolveImport: (response: Response) => void = () => undefined;
    vi.stubGlobal("fetch", routedFetch({
      [`GET ${ROOT}/materials`]: () => jsonResponse(200, { items: [] }),
      [`GET ${ROOT}/material-processing`]: () => processing("READY"),
      [`POST ${ROOT}/materials`]: () => new Promise<Response>((resolve) => { resolveImport = resolve; }),
    }));
    const user = userEvent.setup();
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    const input = await choosePdf(user);
    await user.click(screen.getByRole("button", { name: "Importar PDF" }));
    expect(screen.getByRole("button", { name: "Processando PDF…" })).toBeDisabled();
    expect(screen.getByText(
      "Leitura local em andamento. OCR será usado somente nas páginas sem texto útil.",
    )).toBeInTheDocument();

    resolveImport(jsonResponse(201, ITEM));
    expect(await screen.findByText(ITEM.original_filename)).toBeInTheDocument();
    expect(input).toHaveValue("");
    const open = screen.getByRole("link", { name: `Abrir ${ITEM.original_filename}` });
    expect(open).toHaveAttribute("href", `${ROOT}/materials/${CONTENT_ID}`);
    expect(open).not.toHaveAttribute("href", expect.stringMatching(/file:|private/i));
    expect(screen.getByRole("link", { name: "Revisar dados extraídos" })).toHaveAttribute(
      "href",
      `/pericias/${WORKSPACE_ID}/processo`,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Importar PDF" })).toHaveFocus());
    expect(screen.queryByText(/Processando conteúdo localmente/)).not.toBeInTheDocument();
  });

  test("an accepted document still being read shows an honest processing state until it is ready", async () => {
    let state = "PROCESSING";
    vi.stubGlobal("fetch", routedFetch({
      [`GET ${ROOT}/materials`]: () => jsonResponse(200, { items: [] }),
      [`GET ${ROOT}/material-processing`]: () => (state === "NONE" ? jsonResponse(200, { items: [] }) : processing(state)),
      [`POST ${ROOT}/materials`]: () => jsonResponse(202, ITEM),
    }));
    const user = userEvent.setup();
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    await choosePdf(user);
    await user.click(screen.getByRole("button", { name: "Importar PDF" }));
    expect(await screen.findByText("Documento recebido. Processando conteúdo localmente…")).toBeInTheDocument();
    // Um aceite nunca aparece como erro de armazenamento.
    expect(screen.queryByText(/indisponível/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    state = "READY";
    expect(await screen.findByText("Processamento concluído.", undefined, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText(/Processando conteúdo localmente/)).not.toBeInTheDocument();
  });

  test("one failed status check does not freeze the row in processing", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", routedFetch({
      [`GET ${ROOT}/materials`]: () => jsonResponse(200, { items: [ITEM] }),
      [`GET ${ROOT}/material-processing`]: () => {
        calls += 1;
        if (calls === 1) return processing("PROCESSING");
        if (calls === 2) return jsonResponse(503, { error: { code: "PRODUCT_BRIDGE_UNAVAILABLE" } });
        return processing("READY");
      },
    }));
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByText("Documento recebido. Processando conteúdo localmente…")).toBeInTheDocument();
    expect(await screen.findByText("Processamento concluído.", undefined, { timeout: 6000 })).toBeInTheDocument();
    expect(calls).toBeGreaterThanOrEqual(3);
  });

  test("a failed or interrupted reading offers an explicit retry on the same source", async () => {
    let state = "INTERRUPTED";
    const fetchSpy = routedFetch({
      [`GET ${ROOT}/materials`]: () => jsonResponse(200, { items: [ITEM] }),
      [`GET ${ROOT}/material-processing`]: () => processing(state),
      [`POST ${ROOT}/material-processing/${CONTENT_ID}`]: () => {
        state = "PROCESSING";
        return jsonResponse(202, { content_id: CONTENT_ID, state: "PROCESSING" });
      },
    });
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByText("A leitura deste documento foi interrompida antes de terminar.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: `Tentar novamente a leitura de ${ITEM.original_filename}` }));
    expect(await screen.findByText("Documento recebido. Processando conteúdo localmente…")).toBeInTheDocument();
    const retryCall = fetchSpy.mock.calls.find(([url, init]) => url === `${ROOT}/material-processing/${CONTENT_ID}` && init?.method === "POST");
    expect(retryCall?.[1]?.body).toBe("{}");
    // Nenhum byte e reenviado: a nova tentativa nao importa de novo.
    expect(fetchSpy.mock.calls.some(([url, init]) => url === `${ROOT}/materials` && init?.method === "POST")).toBe(false);

    state = "FAILED";
    expect(await screen.findByText("Não foi possível concluir a leitura deste documento.", undefined, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Tentar novamente a leitura de ${ITEM.original_filename}` })).toBeEnabled();
  });

  test("an unconfirmed import never claims storage failure and re-reads the list", async () => {
    let listed: object[] = [];
    vi.stubGlobal("fetch", routedFetch({
      [`GET ${ROOT}/materials`]: () => jsonResponse(200, { items: listed }),
      [`GET ${ROOT}/material-processing`]: () => (listed.length ? processing("PROCESSING") : jsonResponse(200, { items: [] })),
      [`POST ${ROOT}/materials`]: () => {
        // O transporte desistiu, mas a fonte ja tinha sido aceita.
        listed = [ITEM];
        return jsonResponse(503, { error: { code: "LOCAL_API_UNAVAILABLE", message: "C:/secret/token" } });
      },
    }));
    const user = userEvent.setup();
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    await choosePdf(user);
    await user.click(screen.getByRole("button", { name: "Importar PDF" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Não foi possível confirmar a importação");
    expect(alert).not.toHaveTextContent(/Armazenamento local indisponível|secret|token|503/i);
    expect(await screen.findByText(ITEM.original_filename)).toBeInTheDocument();
    expect(await screen.findByText("Documento recebido. Processando conteúdo localmente…")).toBeInTheDocument();
  });

  test("re-importing the same bytes keeps a single entry", async () => {
    vi.stubGlobal("fetch", routedFetch({
      [`GET ${ROOT}/materials`]: () => jsonResponse(200, { items: [ITEM] }),
      [`GET ${ROOT}/material-processing`]: () => processing("READY"),
      [`POST ${ROOT}/materials`]: () => jsonResponse(200, ITEM),
    }));
    const user = userEvent.setup();
    render(<MaterialIntakeView workspaceId={WORKSPACE_ID} />);

    await choosePdf(user);
    await user.click(screen.getByRole("button", { name: "Importar PDF" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Importar PDF" })).toBeDisabled());
    await act(async () => undefined);
    expect(screen.getAllByText(ITEM.original_filename)).toHaveLength(1);
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
