import { afterEach, describe, expect, test, vi } from "vitest";

import { getProcessMetadataReview, ProcessMetadataApiError } from "./processMetadata";

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
        extraction_method: "LOCAL_PDF_TEXT_V1",
        extraction_timestamp: "2026-08-26T12:30:00+00:00",
        source_filename: "autos.pdf",
        normalized_text_span: "PROCESSO 7654321-55.2025.4.05.0001",
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
});
