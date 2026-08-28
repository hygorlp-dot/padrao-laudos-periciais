import { afterEach, describe, expect, test, vi } from "vitest";

import {
  confirmProcessMetadataSourceSpan,
  getProcessMetadataReview,
  ProcessMetadataApiError,
} from "./processMetadata";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const DOCUMENT_ID = "22222222-2222-4222-8222-222222222222";
const FIELD_NAMES = [
  "numero_processo",
  "ramo_justica",
  "tribunal",
  "vara",
  "comarca_municipio",
  "uf",
  "parte_requerente",
  "parte_requerida",
] as const;

function emptyFields() {
  return Object.fromEntries(FIELD_NAMES.map((name) => [name, {
    state: "NOT_FOUND",
    value: "",
    evidence: [],
  }]));
}

const REVIEW = {
  workspace_id: WORKSPACE_ID,
  state: "PARTIAL",
  confirmed_revision: null,
  extraction_fingerprint: "f".repeat(64),
  documents: [{
    document_id: DOCUMENT_ID,
    source_filename: "autos.pdf",
    text_state: "AVAILABLE",
  }],
  fields: {
    ...emptyFields(),
    numero_processo: {
      state: "CONFIDENT",
      value: "7654321-55.2025.4.05.0001",
      evidence: [{
        workspace_id: WORKSPACE_ID,
        document_id: DOCUMENT_ID,
        field_name: "numero_processo",
        extracted_value: "7654321-55.2025.4.05.0001",
        source_page: 1,
        extraction_method: "LOCAL_OCR_V1",
        extraction_timestamp: "2026-08-26T12:30:00+00:00",
        source_filename: "autos.pdf",
        normalized_text_span: "PROCESSO 7654321-55.2025.4.05.0001",
        evidence_id: "e".repeat(64),
        source_text: "PROCESSO 7654321-55.2025.4.05.0001",
        source_start: 0,
        requires_source_selection: false,
        extraction_mode: "OCR",
        ocr_engine: "RapidOCR/ONNXRuntime",
        engine_version: "3.9.2",
        model_version: "PP-OCRv5-latin-rec",
        ocr_confidence: 0.98 as number | null,
        bounding_box: [80, 100, 1100, 180] as [number, number, number, number] | null,
      }],
    },
  },
};

function response(value: object, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("process metadata review boundary", () => {
  test("loads exact field provenance without browser token or private path", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(response(REVIEW));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(getProcessMetadataReview(WORKSPACE_ID)).resolves.toEqual(REVIEW);
    expect(fetchSpy).toHaveBeenCalledWith(
      `/app-api/v1/workspaces/${WORKSPACE_ID}/process-metadata`,
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
    expect(fetchSpy.mock.calls[0][1].headers).not.toHaveProperty("X-Local-API-Token");
  });

  test("confirms a source span by offsets without sending the selected value", async () => {
    const snapshot = {
      workspace_id: WORKSPACE_ID,
      revision: 1,
      updated_at: "2026-08-28T18:05:00+00:00",
      data: Object.fromEntries(FIELD_NAMES.map((field) => [
        field,
        field === "parte_requerente" ? "PARTE ALFA" : "",
      ])),
    };
    const fetchSpy = vi.fn().mockResolvedValue(response(snapshot));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(confirmProcessMetadataSourceSpan(WORKSPACE_ID, {
      field_name: "parte_requerente",
      evidence_id: "e".repeat(64),
      source_start: 7,
      source_end: 17,
      expected_source_revision: "f".repeat(64),
      expected_revision: null,
    })).resolves.toEqual(snapshot);

    expect(fetchSpy).toHaveBeenCalledWith(
      `/app-api/v1/workspaces/${WORKSPACE_ID}/process-metadata/source-span-confirmations`,
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
    const request = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(request).toEqual({
      field_name: "parte_requerente",
      evidence_id: "e".repeat(64),
      source_start: 7,
      source_end: 17,
      expected_source_revision: "f".repeat(64),
      expected_revision: null,
    });
    expect(request).not.toHaveProperty("value");
    expect(fetchSpy.mock.calls[0][1].headers).not.toHaveProperty("X-Local-API-Token");
  });

  test("accepts OCR evidence without a bounding box when no exact locator is available", async () => {
    const withoutBox = structuredClone(REVIEW);
    withoutBox.fields.numero_processo.evidence[0].bounding_box = null;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(withoutBox)));

    await expect(getProcessMetadataReview(WORKSPACE_ID)).resolves.toEqual(withoutBox);
  });

  test.each([
    { ...REVIEW, workspace_id: "22222222-2222-4222-8222-222222222222" },
    { ...REVIEW, state: "MADE_UP" },
    { ...REVIEW, fields: { ...REVIEW.fields, extra: emptyFields().uf } },
    {
      ...REVIEW,
      fields: {
        ...REVIEW.fields,
        numero_processo: {
          ...REVIEW.fields.numero_processo,
          evidence: [{ ...REVIEW.fields.numero_processo.evidence[0], path: "C:/private" }],
        },
      },
    },
  ])("rejects malformed or expanded provenance %#", async (invalid) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(invalid)));
    await expect(getProcessMetadataReview(WORKSPACE_ID)).rejects.toMatchObject({
      kind: "invalid-response",
    });
  });

  test("maps unavailable extraction to a sanitized local error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      error: { code: "PROCESS_METADATA_UNAVAILABLE", message: "C:/private token=secret" },
    }, 503)));

    const error = await getProcessMetadataReview(WORKSPACE_ID).catch((value) => value);
    expect(error).toBeInstanceOf(ProcessMetadataApiError);
    expect(String(error)).not.toMatch(/private|token|secret|503/i);
  });

  test("preserves a controlled textless-document state without storage paths", async () => {
    const textless = {
      ...REVIEW,
      documents: [{
        document_id: DOCUMENT_ID,
        source_filename: "imagem-digitalizada.pdf",
        text_state: "TEXT_EXTRACTION_UNAVAILABLE",
      }],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(textless)));

    await expect(getProcessMetadataReview(WORKSPACE_ID)).resolves.toEqual(textless);
  });

  test("accepts exact legacy native evidence and a controlled partial document", async () => {
    const legacy = structuredClone(REVIEW);
    legacy.documents[0].text_state = "PARTIAL";
    const evidence = legacy.fields.numero_processo.evidence[0];
    evidence.extraction_method = "LOCAL_PDF_TEXT_V1";
    evidence.extraction_mode = "NATIVE_TEXT";
    evidence.ocr_engine = "";
    evidence.engine_version = "";
    evidence.model_version = "";
    evidence.ocr_confidence = null;
    evidence.bounding_box = null;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(legacy)));

    await expect(getProcessMetadataReview(WORKSPACE_ID)).resolves.toEqual(legacy);
  });
});
