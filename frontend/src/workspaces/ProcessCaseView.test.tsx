import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { emptyProcessCaseData } from "../data/processCase";
import { ProcessCaseView } from "./ProcessCaseView";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "22222222-2222-4222-8222-222222222222";
const DATA = {
  numero_processo: "0000001-00.2026.8.05.0001",
  ramo_justica: "Justiça Estadual",
  tribunal: "Tribunal de Justiça da Bahia",
  vara: "2ª Vara Cível",
  comarca_municipio: "Salvador",
  uf: "BA",
  parte_requerente: "Pessoa requerente",
  parte_requerida: "Pessoa requerida",
};
const FIELD_NAMES = Object.keys(DATA) as (keyof typeof DATA)[];

function review(
  state = "WAITING_FOR_DOCUMENTS",
  values: Partial<typeof DATA> = {},
  workspaceId = ID,
  documents: object[] = [],
) {
  return {
    workspace_id: workspaceId,
    state,
    confirmed_revision: state === "CONFIRMED" ? 1 : null,
    documents,
    fields: Object.fromEntries(FIELD_NAMES.map((field) => [field, values[field] ? {
      state: "CONFIDENT",
      value: values[field],
      evidence: [{
        workspace_id: workspaceId,
        document_id: "33333333-3333-4333-8333-333333333333",
        field_name: field,
        extracted_value: values[field],
        source_page: 1,
        extraction_method: "LOCAL_PDF_TEXT_V1",
        extraction_timestamp: "2026-08-26T12:30:00+00:00",
        source_filename: "autos.pdf",
        normalized_text_span: `${field}: ${values[field]}`,
        extraction_mode: "NATIVE_TEXT",
        ocr_engine: "",
        engine_version: "6.16.2",
        model_version: "",
        ocr_confidence: null as number | null,
        bounding_box: null as [number, number, number, number] | null,
      }],
    } : { state: "NOT_FOUND", value: "", evidence: [] }])),
  };
}

function snapshot(
  data = emptyProcessCaseData(),
  revision: number | null = null,
  workspaceId = ID,
) {
  return {
    workspace_id: workspaceId,
    revision,
    updated_at: revision === null ? null : "2026-08-24T15:01:00+00:00",
    data,
  };
}

function jsonResponse(status: number, value: object) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("process case form", () => {
  test("explains a controlled local OCR failure without claiming it was skipped", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockResolvedValueOnce(jsonResponse(200, snapshot()))
        .mockResolvedValueOnce(jsonResponse(200, review("PARTIAL", {}, ID, [{
          document_id: "33333333-3333-4333-8333-333333333333",
          source_filename: "imagem-digitalizada.pdf",
          text_state: "TEXT_EXTRACTION_UNAVAILABLE",
        }]))),
    );

    render(<ProcessCaseView workspaceId={ID} />);

    expect(await screen.findByText(/OCR local não conseguiu obter texto utilizável/i)).toBeInTheDocument();
    expect(screen.queryByText(/OCR não foi executado/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/C:\\|\/private|token/i)).not.toBeInTheDocument();
  });

  test("loads eight real fields and confirms only through the explicit primary action", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot()))
      .mockResolvedValueOnce(jsonResponse(200, review()))
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ProcessCaseView workspaceId={ID} />);

    expect(screen.getByRole("status")).toHaveTextContent("Carregando dados do processo");
    const number = await screen.findByRole("textbox", { name: "Número do processo" });
    expect(screen.getAllByRole("textbox")).toHaveLength(8);
    await user.type(number, DATA.numero_processo);
    await user.type(screen.getByRole("textbox", { name: "Ramo da Justiça" }), DATA.ramo_justica);
    await user.type(screen.getByRole("textbox", { name: "Tribunal" }), DATA.tribunal);
    await user.type(screen.getByRole("textbox", { name: "Vara" }), DATA.vara);
    await user.type(
      screen.getByRole("textbox", { name: "Comarca ou município" }),
      DATA.comarca_municipio,
    );
    await user.type(screen.getByRole("textbox", { name: "UF" }), DATA.uf);
    await user.type(screen.getByRole("textbox", { name: "Parte requerente" }), DATA.parte_requerente);
    await user.type(screen.getByRole("textbox", { name: "Parte requerida" }), DATA.parte_requerida);

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const save = screen.getByRole("button", { name: "Confirmar dados do processo" });
    await user.click(save);

    expect(await screen.findByText("Dados do processo confirmados")).toBeInTheDocument();
    expect(screen.getByText("Revisão 1")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(3);
    expect(JSON.parse(fetchSpy.mock.calls[2][1].body)).toEqual({
      expected_revision: null,
      data: DATA,
    });
    expect(save).toHaveFocus();
  });

  test("loads persisted values and records an explicit correction", async () => {
    const corrected = { ...DATA, vara: "3ª Vara Cível" };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)))
      .mockResolvedValueOnce(jsonResponse(200, review("CONFIRMED", DATA)))
      .mockResolvedValueOnce(jsonResponse(200, snapshot(corrected, 2)));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ProcessCaseView workspaceId={ID} />);

    const vara = await screen.findByRole("textbox", { name: "Vara" });
    expect(vara).toHaveValue(DATA.vara);
    await user.clear(vara);
    await user.type(vara, corrected.vara);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("button", { name: "Confirmar dados do processo" }));

    expect(await screen.findByText("Revisão 2")).toBeInTheDocument();
    expect(JSON.parse(fetchSpy.mock.calls[2][1].body).expected_revision).toBe(1);
    expect(JSON.parse(fetchSpy.mock.calls[2][1].body).data.vara).toBe(corrected.vara);
  });

  test("keeps the draft and exposes a sanitized retryable save failure", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot()))
      .mockResolvedValueOnce(jsonResponse(200, review()))
      .mockResolvedValueOnce(
        jsonResponse(503, { error: { code: "SQLITE_BUSY", message: "token=secret" } }),
      );
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ProcessCaseView workspaceId={ID} />);

    const tribunal = await screen.findByRole("textbox", { name: "Tribunal" });
    await user.type(tribunal, DATA.tribunal);
    await user.click(screen.getByRole("button", { name: "Confirmar dados do processo" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Armazenamento local indisponível");
    expect(alert).not.toHaveTextContent(/sqlite|token|secret|503/i);
    expect(tribunal).toHaveValue(DATA.tribunal);
    const save = screen.getByRole("button", { name: "Confirmar dados do processo" });
    expect(save).toBeEnabled();
    expect(save).toHaveFocus();
  });

  test("recovers a sanitized load failure through an explicit retry", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(503, { error: { code: "SQLITE_BUSY", message: "private path" } }),
      )
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)))
      .mockResolvedValueOnce(jsonResponse(200, review("CONFIRMED", DATA)));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ProcessCaseView workspaceId={ID} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Armazenamento local indisponível");
    expect(alert).not.toHaveTextContent(/sqlite|private|503/i);
    await user.click(screen.getByRole("button", { name: "Tentar novamente" }));

    expect(await screen.findByRole("textbox", { name: "Número do processo" })).toHaveValue(
      DATA.numero_processo,
    );
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  test("never exposes one workspace draft while another workspace is loading", async () => {
    let resolveOther: (response: Response) => void = () => undefined;
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)))
      .mockResolvedValueOnce(jsonResponse(200, review("CONFIRMED", DATA)))
      .mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          resolveOther = resolve;
        }),
      );
    vi.stubGlobal("fetch", fetchSpy);
    const { rerender } = render(<ProcessCaseView workspaceId={ID} />);

    expect(await screen.findByRole("textbox", { name: "Tribunal" })).toHaveValue(DATA.tribunal);
    rerender(<ProcessCaseView workspaceId={OTHER_ID} />);

    expect(screen.getByRole("status")).toHaveTextContent("Carregando dados do processo");
    expect(screen.queryByDisplayValue(DATA.tribunal)).not.toBeInTheDocument();
    resolveOther(
      jsonResponse(200, {
        ...snapshot(),
        workspace_id: OTHER_ID,
      }),
    );
    fetchSpy.mockResolvedValueOnce(jsonResponse(200, review("WAITING_FOR_DOCUMENTS", {}, OTHER_ID)));
    expect(await screen.findByRole("textbox", { name: "Tribunal" })).toHaveValue("");
  });

  test("does not leave the next workspace disabled when a previous save is aborted", async () => {
    let pendingSaveSignal: AbortSignal | undefined;
    const pendingSave = new Promise<Response>(() => undefined);
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)))
      .mockResolvedValueOnce(jsonResponse(200, review("CONFIRMED", DATA)))
      .mockImplementationOnce((_url: string, init: RequestInit) => {
        pendingSaveSignal = init.signal as AbortSignal;
        return pendingSave;
      })
      .mockResolvedValueOnce(jsonResponse(200, snapshot(undefined, null, OTHER_ID)))
      .mockResolvedValueOnce(jsonResponse(200, review("WAITING_FOR_DOCUMENTS", {}, OTHER_ID)))
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1, ID)))
      .mockResolvedValueOnce(jsonResponse(200, review("CONFIRMED", DATA, ID)));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    const { rerender } = render(<ProcessCaseView workspaceId={ID} />);

    await screen.findByRole("textbox", { name: "Tribunal" });
    await user.click(screen.getByRole("button", { name: "Confirmar dados do processo" }));
    expect(screen.getByRole("button", { name: "Confirmando…" })).toBeDisabled();

    rerender(<ProcessCaseView workspaceId={OTHER_ID} />);

    expect(pendingSaveSignal?.aborted).toBe(true);
    expect(await screen.findByRole("textbox", { name: "Tribunal" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Confirmar dados do processo" })).toBeEnabled();

    rerender(<ProcessCaseView workspaceId={ID} />);

    expect(await screen.findByRole("textbox", { name: "Tribunal" })).toHaveValue(DATA.tribunal);
    expect(screen.getByRole("textbox", { name: "Tribunal" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Confirmar dados do processo" })).toBeEnabled();
  });

  test("prefills confident extraction, shows provenance and keeps every field editable", async () => {
    const extracted = { ...DATA, vara: "1ª Vara Federal" };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot()))
      .mockResolvedValueOnce(jsonResponse(200, review("EXTRACTED", extracted))));

    render(<ProcessCaseView workspaceId={ID} />);

    expect(await screen.findByRole("textbox", { name: "Número do processo" })).toHaveValue(DATA.numero_processo);
    expect(screen.getByRole("textbox", { name: "Vara" })).toHaveValue("1ª Vara Federal");
    expect(screen.getAllByText(/Extraído de autos\.pdf, página 1/).length).toBeGreaterThan(0);
    expect(screen.getByText("Dados extraídos para revisão")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirmar dados do processo" })).toBeEnabled();
  });

  test("identifies OCR-derived provenance without exposing implementation paths", async () => {
    const extracted = review("PARTIAL", { numero_processo: DATA.numero_processo });
    extracted.fields.numero_processo.evidence[0] = {
      ...extracted.fields.numero_processo.evidence[0],
      extraction_method: "LOCAL_OCR_V1",
      extraction_mode: "OCR",
      ocr_engine: "RapidOCR/ONNXRuntime",
      engine_version: "3.9.2",
      model_version: "PP-OCRv5-latin-rec",
      ocr_confidence: 0.98,
      bounding_box: [80, 100, 1100, 180],
    };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot()))
      .mockResolvedValueOnce(jsonResponse(200, extracted)));

    render(<ProcessCaseView workspaceId={ID} />);

    expect(await screen.findByText(/Extraído por OCR local de autos\.pdf, página 1/)).toBeInTheDocument();
    expect(screen.queryByText(/RapidOCR|ONNX|C:\\|\/private/)).not.toBeInTheDocument();
  });

  test("does not overwrite manual data and offers an explicit extracted replacement", async () => {
    const extracted = { ...DATA, vara: "1ª Vara Federal" };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot(DATA, 1)))
      .mockResolvedValueOnce(jsonResponse(200, review("PARTIAL", extracted))));
    const user = userEvent.setup();

    render(<ProcessCaseView workspaceId={ID} />);

    const vara = await screen.findByRole("textbox", { name: "Vara" });
    expect(vara).toHaveValue(DATA.vara);
    expect(screen.getByText(/Valor informado difere do documento/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Usar valor extraído para Vara" }));
    expect(vara).toHaveValue("1ª Vara Federal");
  });

  test("renders import-first waiting state instead of forcing transcription", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot()))
      .mockResolvedValueOnce(jsonResponse(200, review())));

    render(<ProcessCaseView workspaceId={ID} />);

    expect(await screen.findByText("Aguardando documentos do processo")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Importar documentos" })).toHaveAttribute(
      "href",
      `/pericias/${ID}/materiais`,
    );
  });
});
