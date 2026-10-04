import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { parseProcessNumberClassification, type ProcessNumberCandidate, type ProcessNumberClassification } from "../data/processNumber";
import { ProcessNumberProposal } from "./ProcessNumberProposal";

const MAIN = "1234567-11.2024.4.05.0001";
const CITED = "7000000-22.2019.4.05.0001";
const OTHER = "7654321-33.2024.4.05.0001";

function candidate(value: string, classification: ProcessNumberCandidate["classification"], overrides: Partial<ProcessNumberCandidate> = {}): ProcessNumberCandidate {
  return {
    value, classification, primary_evidence: classification === "PRIMARY", occurrence_count: 1, document_count: 1,
    occurrences: [{ filename: "capa.pdf", page: 1, excerpt: `Número: ${value}`, source_start: 8, source_end: 33, extraction_mode: "NATIVE_TEXT", context: classification === "PRIMARY" ? "PJE_COVER" : "CITATION", logical_document_id: null }],
    ...overrides,
  };
}

function classification(overrides: Partial<ProcessNumberClassification> = {}): ProcessNumberClassification {
  return {
    resolution: "RESOLVED", primary_value: MAIN, confidence: "HIGH", unresolved_reason: null,
    candidates: [candidate(MAIN, "PRIMARY", { occurrence_count: 3, document_count: 2 }), candidate(CITED, "CITED_CASE", { occurrence_count: 20 })],
    pending_documents: [], unread_pages: [], invalid_occurrences: [], ...overrides,
  };
}

describe("process number proposal (#286)", () => {
  test("shows the primary number apart from cited cases and only fills the field on request", async () => {
    const onUse = vi.fn();
    render(<ProcessNumberProposal classification={classification()} current="" disabled={false} onUse={onUse} />);
    const primary = screen.getByText("Número principal identificado").closest("div")!;
    expect(within(primary).getByText(MAIN)).toBeInTheDocument();
    expect(within(primary).getByText(/Confiança documental: alta · 3 ocorrências · 2 documentos/)).toBeInTheDocument();
    expect(within(primary).getByText(/Capa do PJe — capa.pdf, p. 1/)).toBeInTheDocument();
    expect(onUse).not.toHaveBeenCalled();
    await userEvent.click(within(primary).getByRole("button", { name: "Usar este número" }));
    expect(onUse).toHaveBeenCalledWith(MAIN);
    const others = screen.getByText("Outros processos citados nos autos (1)").closest("details")!;
    expect(within(others).getByText(CITED)).toBeInTheDocument();
    expect(within(others).getByText("Precedente citado")).toBeInTheDocument();
    // Precedente não ganha botão de uso: o perito digita se precisar.
    expect(within(others).queryByRole("button")).not.toBeInTheDocument();
  });

  test("an unresolved conflict is an alert, lists both contenders and fills nothing", () => {
    render(<ProcessNumberProposal classification={classification({
      resolution: "UNRESOLVED", primary_value: null, confidence: null, unresolved_reason: "CONFLICTING_PRIMARY_SOURCES",
      candidates: [candidate(MAIN, "UNKNOWN", { primary_evidence: true }), candidate(OTHER, "UNKNOWN", { primary_evidence: true })],
    })} current="" disabled={false} onUse={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("mais de um número principal");
    expect(screen.queryByText("Número principal identificado")).not.toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Números com indício de principal" });
    expect(within(list).getAllByRole("button")).toHaveLength(2);
  });

  test("incomplete reading and unavailable sources are said, never shown as nothing found", () => {
    const { rerender } = render(<ProcessNumberProposal classification={classification({ unread_pages: [{ filename: "capa.pdf", page: 2 }] })} current="" disabled={false} onUse={vi.fn()} />);
    expect(screen.getByText(/Leitura incompleta/)).toBeInTheDocument();
    rerender(<ProcessNumberProposal classification={classification({ resolution: "UNRESOLVED", primary_value: null, confidence: null, unresolved_reason: "SOURCES_UNAVAILABLE", candidates: [] })} current="" disabled={false} onUse={vi.fn()} />);
    expect(screen.getByText(/Não foi possível reler os documentos agora/)).toBeInTheDocument();
  });

  test("the number already in the field is marked instead of offered again", () => {
    render(<ProcessNumberProposal classification={classification()} current={MAIN} disabled={false} onUse={vi.fn()} />);
    expect(screen.getByText("Em uso no campo")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usar este número" })).not.toBeInTheDocument();
  });

  test("parser rejects a resolved answer without a primary value", () => {
    expect(() => parseProcessNumberClassification({ ...classification(), primary_value: null })).toThrow();
    expect(parseProcessNumberClassification(classification()).primary_value).toBe(MAIN);
  });
});

describe("process number proposal — review (#286)", () => {
  test("not found and invalid check digits are said instead of an empty box", () => {
    render(<ProcessNumberProposal classification={classification({ resolution: "NOT_FOUND", primary_value: null, confidence: null, candidates: [], invalid_occurrences: [{ filename: "capa.pdf", page: 1 }] })} current="" disabled={false} onUse={vi.fn()} />);
    expect(screen.getByText(/Nenhum número de processo válido/)).toBeInTheDocument();
    expect(screen.getByText(/dígito verificador inválido .* capa.pdf, p. 1/)).toBeInTheDocument();
  });

  test("parser rejects unknown reasons, contexts and a resolved answer without its primary candidate", () => {
    expect(() => parseProcessNumberClassification({ ...classification({ resolution: "UNRESOLVED", primary_value: null, confidence: null }), unresolved_reason: "WHATEVER" })).toThrow();
    const bad = classification();
    expect(() => parseProcessNumberClassification({ ...bad, candidates: [{ ...bad.candidates[0], occurrences: [{ ...bad.candidates[0].occurrences[0], context: "NOPE" }] }] })).toThrow();
    expect(() => parseProcessNumberClassification({ ...bad, candidates: bad.candidates.slice(1) })).toThrow();
    expect(() => parseProcessNumberClassification({ ...bad, primary_value: OTHER })).toThrow();
  });
});
