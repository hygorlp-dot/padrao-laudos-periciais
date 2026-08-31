import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FieldMobileStatus } from "./FieldMobileStatus";

describe("FieldMobileStatus", () => {
  it("keeps offline capture useful and makes sync conflicts visible", () => {
    render(<FieldMobileStatus online={false} pendingCaptures={3} conflicts={[{ code: "STALE_PLAN", message: "O plano mudou." }]} />);
    expect(screen.getByText("Modo offline")).toBeInTheDocument();
    expect(screen.getByText("3 registros aguardam sincronização")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("O plano mudou.");
    expect(screen.getByRole("button", { name: "Registrar observação" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adicionar medição" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Associar foto" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preparar uso offline" })).toBeDisabled();
    expect(screen.queryByText(/conclusão profissional/i)).not.toBeInTheDocument();
  });
});
