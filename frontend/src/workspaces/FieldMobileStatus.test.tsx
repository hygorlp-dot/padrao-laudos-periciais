import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

  it("offers explicit replacement only after device revocation", async () => {
    const user = userEvent.setup();
    const onReplace = vi.fn();
    render(<FieldMobileStatus
      online
      pendingCaptures={0}
      conflicts={[]}
      onCapture={vi.fn()}
      onPrepare={vi.fn()}
      onSync={vi.fn()}
      onRevoke={vi.fn()}
      deviceRevoked
      onReplace={onReplace}
    />);
    await user.click(screen.getByRole("button", { name: "Cadastrar novo dispositivo" }));
    expect(onReplace).toHaveBeenCalledOnce();
  });
});
