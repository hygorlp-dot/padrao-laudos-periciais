import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ReportPreflightPanel } from "./ReportPreflightPanel";
import { WorkspaceSettingsPanel } from "./WorkspaceSettingsPanel";

const ID = "11111111-1111-4111-8111-111111111111";

function json(status: number, value: object) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

const SOURCES = [
  { name: "Recomendação CNJ nº 144/2023 (linguagem simples)", nature: "RECOMMENDATORY" },
  { name: "Lei nº 15.263/2025, art. 5º", nature: "MANDATORY" },
];

describe("pré-verificação jurídico-editorial (#272)", () => {
  test("an open pending marker is stated as blocking emission, with the exact excerpt", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, {
      report_revision: 3, profile_id: "SISTEMA_PERICIAL_CNJ_TRF5_V1", profile_label: "Sistema Pericial — CNJ/TRF5", blocking: true, sources: SOURCES,
      findings: [
        { code: "PENDING_MARKER", severity: "BLOCKING", section_id: "S", location_id: "CLAIM-1", excerpt: "[INFORMAÇÃO NECESSÁRIA: área]", message: "Pendência aberta no texto.", suggestion: "Complete a informação." },
        { code: "LATINISM", severity: "WARNING", section_id: "S", location_id: "CLAIM-2", excerpt: "…vistoria in loco…", message: "Expressão latina “in loco”.", suggestion: "Prefira “no local”." },
      ],
    })));
    render(<ReportPreflightPanel workspaceId={ID} reportRevision={3} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("O Word final não é emitido");
    expect(screen.getByText("[INFORMAÇÃO NECESSÁRIA: área]")).toBeInTheDocument();
    expect(screen.getByText(/Perfil editorial de referência: Sistema Pericial — CNJ\/TRF5/)).toBeInTheDocument();
    expect(screen.getByText(/natureza recomendatória/)).toBeInTheDocument();
    expect(screen.queryByText(/formatação obrigatória/i)).not.toBeInTheDocument();
  });

  test("a clean report says so and counts warnings", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, { report_revision: 1, profile_id: "P", profile_label: "Sistema Pericial — CNJ/TRF5", blocking: false, sources: SOURCES, findings: [] })));
    render(<ReportPreflightPanel workspaceId={ID} reportRevision={1} />);
    expect(await screen.findByText(/Nenhuma pendência aberta\. Nenhum aviso de linguagem\./)).toBeInTheDocument();
  });
});

describe("configurações desta perícia (#270)", () => {
  test("differences are shown and nothing changes until the expert confirms", async () => {
    const view = { revision: 1, updated_at: "2026-10-01T12:00:00+00:00", snapshot: { reason: "WORKSPACE_CREATED", assets: [] }, differences: { snapshot_revision: 1, profile_revision: 1, settings_changes: ["ASSET:PRIMARY_LOGO"], profile_changes: ["full_name"] } };
    const updated = { ...view, revision: 2, differences: { snapshot_revision: 2, profile_revision: 2, settings_changes: [], profile_changes: [] } };
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, view)).mockResolvedValueOnce(json(200, updated));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<WorkspaceSettingsPanel workspaceId={ID} />);
    const panel = await screen.findByRole("region", { name: "Configurações desta perícia" });
    expect(within(panel).getByText("Logotipo")).toBeInTheDocument();
    expect(within(panel).getByText(/Perfil profissional: nome/)).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Atualizar a partir das configurações" }));
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    await user.click(within(panel).getByLabelText(/Atualizar também o perfil profissional/));
    await user.click(within(panel).getByRole("button", { name: "Confirmar atualização" }));
    expect(await within(panel).findByText(/Um laudo já aprovado precisa ser revisado de novo/)).toBeInTheDocument();
    expect(JSON.parse(fetchSpy.mock.calls[1][1].body)).toEqual({ include_profile: true, expected_snapshot_revision: 1, expected_profile_revision: 1 });
    expect(within(panel).getByText("Igual às configurações atuais.")).toBeInTheDocument();
  });

  test("updating only the settings says the professional profile of the case did not change", async () => {
    const view = { revision: 1, updated_at: "2026-10-01T12:00:00+00:00", snapshot: { reason: "WORKSPACE_CREATED", assets: [] }, differences: { snapshot_revision: 1, profile_revision: 1, settings_changes: ["ASSET:PRIMARY_LOGO"], profile_changes: ["full_name"] } };
    const updated = { ...view, revision: 2, differences: { snapshot_revision: 2, profile_revision: 1, settings_changes: [], profile_changes: ["full_name"] } };
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, view)).mockResolvedValueOnce(json(200, updated));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<WorkspaceSettingsPanel workspaceId={ID} />);
    const panel = await screen.findByRole("region", { name: "Configurações desta perícia" });
    await user.click(within(panel).getByRole("button", { name: "Atualizar a partir das configurações" }));
    await user.click(within(panel).getByRole("button", { name: "Confirmar atualização" }));
    expect(await within(panel).findByText(/o perfil profissional desta perícia não mudou/)).toBeInTheDocument();
    expect(JSON.parse(fetchSpy.mock.calls[1][1].body)).toEqual({ include_profile: false, expected_snapshot_revision: 1, expected_profile_revision: null });
    // Só o perfil difere e a caixa está desmarcada: confirmar não faria nada.
    await user.click(within(panel).getByRole("button", { name: "Atualizar a partir das configurações" }));
    expect(within(panel).getByRole("button", { name: "Confirmar atualização" })).toBeDisabled();
  });

  test("without the installation settings the case keeps its snapshot and says so", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, { revision: 2, updated_at: "2026-10-01T12:00:00+00:00", snapshot: { reason: "WORKSPACE_CREATED", assets: [] }, differences: null })));
    render(<WorkspaceSettingsPanel workspaceId={ID} />);
    const panel = await screen.findByRole("region", { name: "Configurações desta perícia" });
    expect(within(panel).getByRole("status")).toHaveTextContent("Esta perícia continua com a cópia dela");
    expect(within(panel).queryByRole("button", { name: "Atualizar a partir das configurações" })).not.toBeInTheDocument();
  });
});
