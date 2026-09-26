import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { findRoute } from "../routes/routeCatalog";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

describe("shell position", () => {
  test("states the real stage position out of every stage", () => {
    render(<TopBar currentRoute={findRoute("/laudo")} workspaceName="Perícia" />);
    expect(screen.getByText("Etapa 9 de 13")).toBeInTheDocument();
    expect(screen.queryByText(/de 10/)).not.toBeInTheDocument();
  });

  test("groups the rail into labelled lists and keeps every stage link", () => {
    render(<Sidebar currentPath="/pericias/11111111-1111-4111-8111-111111111111/laudo" workspaceId="11111111-1111-4111-8111-111111111111" />);
    for (const group of ["Processo", "Perícia", "Laudo", "Gestão"]) {
      expect(screen.getByRole("list", { name: group })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("link").filter((link) => link.classList.contains("workflow-link"))).toHaveLength(14);
    expect(screen.getByRole("link", { current: "page" })).toHaveTextContent("Laudo");
  });
});
