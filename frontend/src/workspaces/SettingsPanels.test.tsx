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

function stubSettingsFetch(fetchSpy: (url: string, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => url.endsWith("/expert-profile")
    ? Promise.resolve(json(404, {})) : fetchSpy(url, init));
}

const CAPTURED = {
  reason: "WORKSPACE_CREATED", assets: [{ role: "PRIMARY_LOGO", filename: "logo-capturado.png" }],
  editorial_profile: { profile_id: "CUSTOM", font_family: "Arial", body_font_pt: 12, line_spacing: 1.5, first_line_indent_cm: 1.25 },
  branding: { primary_color: "#112233", secondary_color: "#334455", rule_color: "#556677", heading_color: "#112233" },
  template_selection: { mode: "PRODUCT_DEFAULT", template_sha256: null },
  presentation: { cover: { enabled: true, title: "CAPA CAPTURADA V1" }, header: { enabled: true }, footer: { page_numbering: "PAGE_X_OF_Y" }, watermark: { enabled: false }, background: { kind: "WHITE" } },
  legal_editorial: { profile_id: "SISTEMA_PERICIAL_CNJ_TRF5_V1" },
};

const SOURCES = [
  { name: "Recomendação CNJ nº 144/2023 (linguagem simples)", nature: "RECOMMENDATORY" },
  { name: "Lei nº 15.263/2025, art. 5º", nature: "MANDATORY" },
];

describe("pré-verificação jurídico-editorial (#272)", () => {
  test("a clean preflight from another revision is unavailable for the current document", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, { report_revision: 1, profile_id: "P", profile_label: "Sintético", blocking: false, sources: [], findings: [] })));
    render(<ReportPreflightPanel workspaceId={ID} reportRevision={2} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível conferir o texto agora");
    expect(screen.queryByText(/Nenhuma pendência editorial aberta/)).not.toBeInTheDocument();
  });
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
    expect(await screen.findByText(/Nenhuma pendência editorial aberta\. Nenhum aviso de linguagem\./)).toBeInTheDocument();
  });
});

describe("configurações desta perícia (#270)", () => {
  test("the captured document and assets remain visible when global settings cannot be read", async () => {
    stubSettingsFetch(vi.fn().mockResolvedValueOnce(json(200, { revision: 1, updated_at: "2026-10-01T12:00:00+00:00", snapshot: CAPTURED, differences: null })));
    render(<WorkspaceSettingsPanel workspaceId={ID} />);
    const panel = await screen.findByRole("region", { name: "Configurações desta perícia" });
    expect(within(panel).getByText(/CAPA CAPTURADA V1/)).toBeInTheDocument();
    expect(within(panel).getByText(/logo-capturado.png/)).toBeInTheDocument();
    expect(within(panel).getByText(/Arial 12 pt/)).toBeInTheDocument();
    expect(within(panel).getByText("Modelo padrão do sistema")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Atualizar a partir das configurações" })).not.toBeInTheDocument();
  });

  test("an interrupted refresh reads the persisted result without claiming the old snapshot survived", async () => {
    const view = { revision: 1, updated_at: "2026-10-01T12:00:00+00:00", snapshot: CAPTURED, differences: { snapshot_revision: 1, profile_revision: 1, settings_changes: ["ASSET:PRIMARY_LOGO"], profile_changes: [] } };
    const updated = { ...view, revision: 2, snapshot: { ...CAPTURED, assets: [{ role: "PRIMARY_LOGO", filename: "novo-logo-v2.png" }] }, differences: { ...view.differences, snapshot_revision: 2, settings_changes: [] } };
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, view)).mockRejectedValueOnce(new TypeError("connection closed after commit")).mockResolvedValueOnce(json(200, updated));
    stubSettingsFetch(fetchSpy);
    const user = userEvent.setup();
    render(<WorkspaceSettingsPanel workspaceId={ID} />);
    await user.click(await screen.findByRole("button", { name: "Atualizar a partir das configurações" }));
    await user.click(screen.getByRole("button", { name: "Confirmar atualização" }));
    expect(await screen.findByText(/novo-logo-v2.png/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/recarregad/);
    expect(screen.queryByText(/continua com as configurações anteriores/)).not.toBeInTheDocument();
    expect(fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  test("a refresh with an unreadable result cannot be repeated until the case authority is observed", async () => {
    const view = { revision: 1, updated_at: "2026-10-01T12:00:00+00:00", snapshot: CAPTURED, differences: { snapshot_revision: 1, profile_revision: 1, settings_changes: ["ASSET:PRIMARY_LOGO"], profile_changes: [] } };
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, view)).mockRejectedValueOnce(new TypeError("timeout")).mockResolvedValueOnce(json(503, {})).mockResolvedValueOnce(json(200, view));
    stubSettingsFetch(fetchSpy);
    const user = userEvent.setup();
    render(<WorkspaceSettingsPanel workspaceId={ID} />);
    await user.click(await screen.findByRole("button", { name: "Atualizar a partir das configurações" }));
    await user.click(screen.getByRole("button", { name: "Confirmar atualização" }));
    expect(await screen.findByRole("button", { name: "Recarregar configurações desta perícia" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Confirmar atualização" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Recarregar configurações desta perícia" }));
    expect(await screen.findByText(/Confira o resultado da atualização/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Atualizar a partir das configurações" })).toBeEnabled();
    expect(fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  test("switching cases never carries a captured professional profile or an update confirmation across them", async () => {
    let profileA!: (response: Response) => void;
    const other = "22222222-2222-4222-8222-222222222222";
    const view = { revision: 1, updated_at: "2026-10-01T12:00:00+00:00", snapshot: CAPTURED, differences: { snapshot_revision: 1, profile_revision: 1, settings_changes: ["ASSET:PRIMARY_LOGO"], profile_changes: [] } };
    vi.stubGlobal("fetch", (url: string) => url.endsWith("/expert-profile") ? url.includes(ID)
      ? new Promise<Response>((resolve) => { profileA = resolve; })
      : Promise.resolve(json(200, { revision: 1, profile: { profile_id: "PROFILE-B", revision: 1, full_name: "Perita da perícia B", professional_title: "Engenheira", registration: "SINTÉTICO", court_registration: "", contact_line: "" } }))
      : Promise.resolve(json(200, view)));
    const user = userEvent.setup();
    const { rerender } = render(<WorkspaceSettingsPanel workspaceId={ID} />);
    await user.click(await screen.findByRole("button", { name: "Atualizar a partir das configurações" }));
    rerender(<WorkspaceSettingsPanel workspaceId={other} />);
    expect(await screen.findByText(/Perita da perícia B/)).toBeInTheDocument();
    profileA(json(200, { revision: 1, profile: { profile_id: "PROFILE-A", full_name: "Perita da perícia A" } }));
    expect(screen.queryByRole("button", { name: "Confirmar atualização" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Perita da perícia A/)).not.toBeInTheDocument();
  });
  test("differences are shown and nothing changes until the expert confirms", async () => {
    const view = { revision: 1, updated_at: "2026-10-01T12:00:00+00:00", snapshot: { reason: "WORKSPACE_CREATED", assets: [] }, differences: { snapshot_revision: 1, profile_revision: 1, settings_changes: ["ASSET:PRIMARY_LOGO"], profile_changes: ["full_name"] } };
    const updated = { ...view, revision: 2, differences: { snapshot_revision: 2, profile_revision: 2, settings_changes: [], profile_changes: [] } };
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, view)).mockResolvedValueOnce(json(200, updated));
    stubSettingsFetch(fetchSpy);
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
    stubSettingsFetch(fetchSpy);
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
