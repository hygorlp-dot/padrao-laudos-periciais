import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ReportProfessionalPresentation } from "./ReportProfessionalPresentation";

test("captures professional document inputs without posting upstream payloads or calculating repairs", async () => {
  const save = vi.fn();
  render(<ReportProfessionalPresentation capture={{ sources: [{ private: "captured upstream" }], details: {}, repair_budget: null, sheet_figures: [] }} figures={[]} pathologies={[]} editable busy={false} save={save} />);
  await userEvent.click(screen.getByText("Apresentação profissional do documento"));
  await userEvent.type(screen.getByLabelText("Objetivo"), "Objetivo sintético informado pelo perito.");
  await userEvent.click(screen.getByRole("button", { name: "Salvar apresentação" }));
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ details: expect.objectContaining({ objective: "Objetivo sintético informado pelo perito." }), repair_budget: null, sheet_figures: [] }));
  expect(save.mock.calls[0][0]).not.toHaveProperty("sources");
});
