import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { acceptCaseQuestions, confirmDocumentInventory, getCaseIntake, type CaseAnalysisEnvelope } from "../data/caseAnalysis";
import { CaseIntakePanel } from "./CaseIntakePanel";
vi.mock("../data/caseAnalysis", () => ({ acceptCaseQuestions: vi.fn(), confirmDocumentInventory: vi.fn(), getCaseIntake: vi.fn() }));

test("imports exact question without transcription and keeps not-found separate from confirmed absence", async () => {
  const envelope = { revision: 2, snapshot: { source_inventory_stale: false, stale_document_ids: [], questions: [], documents: [{ document_id: "DOC-1", raw_type: "Quesitos sintéticos", content_available: true }] } } as unknown as CaseAnalysisEnvelope;
  vi.mocked(getCaseIntake).mockResolvedValue({ revision: 2, questions: [{ proposal_id: "proposal", document_id: "DOC-1", text: "Há umidade?", source: { origin: "CLAIMANT", original_number: "01)", page_start: 2, page_end: 2, excerpt: "01) Há umidade?", method: "NUMBERED_NATIVE_TEXT_V1" } }], inventory: [{ category: "HABITE_SE", label: "Habite-se", state: "NOT_FOUND_IN_CURRENT_INGESTED_MATERIAL", matches: [] }] });
  vi.mocked(acceptCaseQuestions).mockResolvedValue(envelope);
  vi.mocked(confirmDocumentInventory).mockResolvedValue(envelope);
  const user = userEvent.setup();
  render(<CaseIntakePanel workspaceId="11111111-1111-4111-8111-111111111111" envelope={envelope} onSaved={vi.fn()}/>);
  await user.click(screen.getByText("Importar quesitos e conferir documentos usuais"));
  await user.click(screen.getByRole("button", { name: "Buscar nos documentos importados" }));
  await user.click(await screen.findByLabelText("Parte autora · quesito 01)"));
  await user.click(screen.getByRole("button", { name: "Adicionar quesitos selecionados à análise" }));
  await waitFor(() => expect(acceptCaseQuestions).toHaveBeenCalledWith(expect.any(String), 2, ["proposal"]));
  expect(confirmDocumentInventory).not.toHaveBeenCalled();
  await user.click(screen.getByText("Habite-se · não encontrado no material importado"));
  expect(screen.getByLabelText("Resultado da conferência")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Resultado da conferência"), { target: { value: "PROFESSIONALLY_CONFIRMED_ABSENT_FROM_CASE" } });
  fireEvent.change(screen.getByLabelText("Fundamentação da conferência"), { target: { value: "Autos sintéticos conferidos." } });
  await user.click(screen.getByRole("button", { name: "Confirmar situação do documento" }));
  await waitFor(() => expect(confirmDocumentInventory).toHaveBeenCalledWith(expect.any(String), 2, { category: "HABITE_SE", status: "PROFESSIONALLY_CONFIRMED_ABSENT_FROM_CASE", source_document_ids: [], reason: "Autos sintéticos conferidos." }));
});
