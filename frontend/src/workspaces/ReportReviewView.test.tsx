import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { getReportSnapshot, type ReportEnvelope } from "../data/reportSnapshot";
import { ReportReviewView } from "./ReportReviewView";
vi.mock("../data/reportSnapshot", async (original) => ({ ...await original<object>(), getReportSnapshot: vi.fn() }));

test.each(["APPROVED", "DRAFT"])("stale historical approval is not shown as approved for delivery (%s)", async (state) => {
  const snapshot = { state, upstream_stale: true, review_decisions: [], coverage: { context_present_fields: 6, context_required_fields: 6, cpc473_present_sections: 8, cpc473_required_sections: 8, material_claims: 8, traceable_claims: 8, answers: 1, traceable_answers: 1, reasons: [] } };
  vi.mocked(getReportSnapshot).mockResolvedValue({ revision: 1, snapshot } as unknown as ReportEnvelope);
  render(<ReportReviewView workspaceId="11111111-1111-4111-8111-111111111111" />);
  expect(await screen.findByText(state === "APPROVED" ? "Aprovado antes da alteração" : "Base desatualizada")).toBeVisible();
  expect(screen.getByText("Revisão necessária")).toBeVisible();
  expect(screen.queryByText("Aprovado para entrega")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Ir para a entrega" })).not.toBeInTheDocument();
});

test("shows the backend's incomplete process identity and keeps approval unavailable", async () => {
  const snapshot = {
    state: "REVIEWED", upstream_stale: false, review_decisions: [],
    coverage: { context_present_fields: 6, context_required_fields: 6, cpc473_present_sections: 8, cpc473_required_sections: 8, material_claims: 8, traceable_claims: 8, answers: 1, traceable_answers: 1, reasons: ["captured process identity incomplete"] },
  };
  vi.mocked(getReportSnapshot).mockResolvedValue({ revision: 1, updated_at: "2026-09-28T12:00:00Z", snapshot } as unknown as ReportEnvelope);
  render(<ReportReviewView workspaceId="11111111-1111-4111-8111-111111111111" />);
  await screen.findByText("Identificação capturada do processo");
  fireEvent.change(screen.getByLabelText("Fundamentação da revisão"), { target: { value: "Conferência sintética" } });
  expect(screen.getByRole("button", { name: "Aprovar laudo" })).toBeDisabled();
  expect(screen.getByText(/Complete o número do processo e o juízo/)).toBeVisible();
});
