import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { emptyProcessCaseData } from "../data/processCase";
import { ProcessCaseView } from "./ProcessCaseView";

vi.mock("./ParticipantsPanel", () => ({ ParticipantsPanel: () => null }));
vi.mock("./PropertyPanel", () => ({ PropertyPanel: () => null }));
vi.mock("./ExpertProfileSetup", () => ({ ExpertProfilePanel: () => null }));

const ID = "11111111-1111-4111-8111-111111111111";
const MAIN = "1234567-11.2024.4.05.0001";
const CITED = "7000000-22.2019.4.05.0001";
const FIELDS = ["numero_processo", "ramo_justica", "tribunal", "vara", "municipio_sede", "subsecao_judiciaria", "comarca_municipio", "uf", "parte_requerente", "parte_requerida"];

function evidence(value: string, page: number) {
  return {
    workspace_id: ID, document_id: "33333333-3333-4333-8333-333333333333", field_name: "numero_processo", extracted_value: value,
    source_page: page, extraction_method: "LOCAL_PDF_TEXT_V1", extraction_timestamp: "2026-08-26T12:30:00+00:00", source_filename: "autos.pdf",
    normalized_text_span: value, evidence_id: "e".repeat(64), source_text: "", source_start: 0, requires_source_selection: false,
    source_role: "UNKNOWN_SOURCE_CONTEXT", derivation_authority: "", derivation_reference: "", extraction_mode: "NATIVE_TEXT",
    ocr_engine: "", engine_version: "", model_version: "", ocr_confidence: null, bounding_box: null,
  };
}

function json(value: object, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

function routes(classification: object | null) {
  return vi.fn((url: string) => {
    if (url.endsWith("/process-case")) return Promise.resolve(json({ workspace_id: ID, revision: null, updated_at: null, data: emptyProcessCaseData() }));
    if (url.endsWith("/process-metadata")) {
      return Promise.resolve(json({
        workspace_id: ID, state: "PARTIAL", confirmed_revision: null, extraction_fingerprint: "f".repeat(64), documents: [],
        fields: Object.fromEntries(FIELDS.map((field) => [field, field === "numero_processo"
          ? { state: "AMBIGUOUS", value: "", evidence: [evidence(MAIN, 1), evidence(CITED, 4)] }
          : { state: "NOT_FOUND", value: "", evidence: [] }])),
      }));
    }
    if (url.endsWith("/process-number")) return Promise.resolve(classification === null ? json({ error: {} }, 503) : json(classification));
    return Promise.resolve(json({ items: [] }));
  });
}

afterEach(() => vi.unstubAllGlobals());

test("the number field shows the classified primary instead of equal buttons per number (#286)", async () => {
  vi.stubGlobal("fetch", routes({
    resolution: "RESOLVED", primary_value: MAIN, confidence: "HIGH", unresolved_reason: null,
    candidates: [
      { value: MAIN, classification: "PRIMARY", primary_evidence: true, occurrence_count: 1, document_count: 1, occurrences: [{ filename: "autos.pdf", page: 1, excerpt: `Número: ${MAIN}`, source_start: 8, source_end: 33, extraction_mode: "NATIVE_TEXT", context: "PJE_COVER", logical_document_id: null }] },
      { value: CITED, classification: "CITED_CASE", primary_evidence: false, occurrence_count: 1, document_count: 1, occurrences: [{ filename: "autos.pdf", page: 4, excerpt: `TRF5, AC ${CITED}, Rel. Des.`, source_start: 9, source_end: 34, extraction_mode: "NATIVE_TEXT", context: "CITATION", logical_document_id: null }] },
    ],
    pending_documents: [], unread_pages: [], invalid_occurrences: [],
  }));
  render(<ProcessCaseView workspaceId={ID} />);
  const field = await screen.findByRole("textbox", { name: "Número do processo" });
  await screen.findByText("Número principal identificado");
  expect(screen.queryByRole("button", { name: new RegExp(`Usar ${CITED}`) })).not.toBeInTheDocument();
  expect(field).toHaveValue("");
  await userEvent.click(screen.getByRole("button", { name: "Usar este número" }));
  expect(field).toHaveValue(MAIN);
  expect(screen.getByText("Em uso no campo")).toBeInTheDocument();
});

test("when the classification is unavailable the unclassified list says so", async () => {
  vi.stubGlobal("fetch", routes(null));
  render(<ProcessCaseView workspaceId={ID} />);
  expect(await screen.findByText(/Não foi possível separar o número principal/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: new RegExp(`Usar ${CITED}`) })).toBeInTheDocument();
});
