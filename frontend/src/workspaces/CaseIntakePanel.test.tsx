import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { acceptCaseQuestions, confirmDocumentInventory, getCaseIntake, type CaseAnalysisEnvelope } from "../data/caseAnalysis";
import { CaseIntakePanel } from "./CaseIntakePanel";
vi.mock("../data/caseAnalysis", () => ({ CASE_ANALYSIS_TEXT_MAX: 4096, acceptCaseQuestions: vi.fn(), confirmDocumentInventory: vi.fn(), getCaseIntake: vi.fn() }));

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
  // Lista parcial nunca parece completa: o aviso aparece mesmo com propostas.
  expect(screen.getByText(/Confira com os autos/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Adicionar quesitos selecionados à análise" }));
  await waitFor(() => expect(acceptCaseQuestions).toHaveBeenCalledWith(expect.any(String), 2, [{ proposal_id: "proposal", origin: "CLAIMANT" }]));
  expect(confirmDocumentInventory).not.toHaveBeenCalled();
  await user.click(screen.getByText("Habite-se · não encontrado no material importado"));
  expect(screen.getByLabelText("Resultado da conferência")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Resultado da conferência"), { target: { value: "PROFESSIONALLY_CONFIRMED_ABSENT_FROM_CASE" } });
  // O servidor recusa texto acima do limite do schema; a UI nao deixa digitar alem dele.
  expect(screen.getByLabelText("Fundamentação da conferência")).toHaveAttribute("maxLength", "4096");
  fireEvent.change(screen.getByLabelText("Fundamentação da conferência"), { target: { value: "Autos sintéticos conferidos." } });
  await user.click(screen.getByRole("button", { name: "Confirmar situação do documento" }));
  await waitFor(() => expect(confirmDocumentInventory).toHaveBeenCalledWith(expect.any(String), 2, { category: "HABITE_SE", status: "PROFESSIONALLY_CONFIRMED_ABSENT_FROM_CASE", source_document_ids: [], reason: "Autos sintéticos conferidos." }));
});

test("deduplication follows the server: same literal evidence is already added whatever the origin", async () => {
  // Paridade com o servidor: a evidencia literal identifica o quesito; a origem e decisao do perito.
  const stored = { origin: "CLAIMANT" as const, original_number: "1.", page_start: 1, page_end: 1, excerpt: "1. Há fissuras?", method: "NUMBERED_NATIVE_TEXT_V1" };
  const envelope = { revision: 3, snapshot: { source_inventory_stale: false, stale_document_ids: [], documents: [{ document_id: "DOC-1", raw_type: "Quesitos sintéticos", content_available: true }],
    questions: [{ item_id: "Q-1", text: "Há fissuras?", source_question: stored, provenance: [{ source_document_id: "DOC-1" }] }] } } as unknown as CaseAnalysisEnvelope;
  vi.mocked(getCaseIntake).mockResolvedValue({ revision: 3, inventory: [], questions: [
    { proposal_id: "same-evidence", document_id: "DOC-1", text: "Há fissuras?", source: { ...stored, origin: "COURT" as const } },
    { proposal_id: "other-page", document_id: "DOC-1", text: "Há fissuras?", source: { ...stored, origin: "COURT" as const, page_start: 2, page_end: 2 } },
  ] });
  const user = userEvent.setup();
  render(<CaseIntakePanel workspaceId="11111111-1111-4111-8111-111111111111" envelope={envelope} onSaved={vi.fn()}/>);
  await user.click(screen.getByText("Importar quesitos e conferir documentos usuais"));
  await user.click(screen.getByRole("button", { name: "Buscar nos documentos importados" }));
  const boxes = await screen.findAllByRole("checkbox");
  expect(boxes[0]).toBeDisabled();
  expect(boxes[1]).toBeEnabled();
});

test("the professional confirms or corrects the origin before accepting and sees the heading and what follows", async () => {
  const envelope = { revision: 4, snapshot: { source_inventory_stale: false, stale_document_ids: [], questions: [], documents: [{ document_id: "DOC-1", raw_type: "Quesitos sintéticos", content_available: true }] } } as unknown as CaseAnalysisEnvelope;
  vi.mocked(getCaseIntake).mockResolvedValue({ revision: 4, inventory: [], questions: [{
    proposal_id: "p", document_id: "DOC-1", text: "Seguiu o projeto?", section_heading: "QUESITOS DO JUÍZO", section_page: 1, context_after: "2. Houve manutenção?",
    source: { origin: "COURT", original_number: "1.", page_start: 1, page_end: 1, excerpt: "1. Seguiu o projeto?", method: "NUMBERED_NATIVE_TEXT_V1" },
  }] });
  vi.mocked(acceptCaseQuestions).mockResolvedValue(envelope);
  const user = userEvent.setup();
  render(<CaseIntakePanel workspaceId="11111111-1111-4111-8111-111111111111" envelope={envelope} onSaved={vi.fn()}/>);
  await user.click(screen.getByText("Importar quesitos e conferir documentos usuais"));
  await user.click(screen.getByRole("button", { name: "Buscar nos documentos importados" }));
  expect(await screen.findByText(/Origem sugerida pelo título “QUESITOS DO JUÍZO” \(página 1\)/)).toBeInTheDocument();
  expect(screen.getByText("2. Houve manutenção?")).toBeInTheDocument();
  await user.click(screen.getByLabelText("Juízo · quesito 1."));
  await user.selectOptions(screen.getByLabelText("Origem do quesito (confirme com os autos)"), "DEFENDANT");
  await user.click(screen.getByRole("button", { name: "Adicionar quesitos selecionados à análise" }));
  await waitFor(() => expect(acceptCaseQuestions).toHaveBeenCalledWith(expect.any(String), 4, [{ proposal_id: "p", origin: "DEFENDANT" }]));
});
