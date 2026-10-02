import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { InstallationOverview } from "../data/installationSettings";
import { SettingsView } from "./SettingsView";

const EDITORIAL = { profile_id: "JUSTICA_PLURAL_CHAPTER_4", font_family: "Arial", body_font_pt: 11, table_font_pt: 10, caption_font_pt: 9, alignment: "JUSTIFIED", line_spacing: 1.15, first_line_indent_cm: 1.25, page_size: "A4", margin_top_cm: 2, margin_bottom_cm: 2, margin_left_cm: 3, margin_right_cm: 2, hyphenation: false, overrides: [] };
const PRESENTATION = {
  cover: { enabled: true, show_logo: true, title: "LAUDO PERICIAL", subtitle: null, show_expert: true, show_city_year: true, city: null },
  header: { enabled: true, show_logo: true, show_name: true, show_title: true, logo_width_cm: 2.5, alignment: "LEFT", separator_enabled: true, separator_thickness_pt: 0.75 },
  footer: { page_numbering: "PAGE_X_OF_Y", institutional_text: null },
  watermark: { enabled: false, kind: "SYMBOL", text: null, opacity: 0.08, scale: 0.5, rotation_degrees: 0, apply_cover: false, apply_body: true, apply_attachments: false },
  background: { kind: "WHITE", color: null, apply_cover: false, apply_body: false },
};
const LEGAL = { profile_id: "SISTEMA_PERICIAL_CNJ_TRF5_V1", check_acronyms: true, check_latinisms: true, check_foreign_terms: true, check_jargon: true, check_long_sentences: true, check_long_paragraphs: true, long_sentence_words: 45, long_paragraph_words: 180 };

function unset<T>(payload: T) {
  return { configured: false, revision: null, created_at: null, payload, product_default: payload };
}

function overview(changes: Partial<InstallationOverview> = {}): InstallationOverview {
  const empty = { revision: null, asset: null };
  return {
    settings: {
      EXPERT_PROFILE_DEFAULT_V1: unset(null),
      EDITORIAL_PROFILE_DEFAULT_V1: unset(EDITORIAL),
      BRANDING_PROFILE_V1: unset({ primary_color: "#1F3A4D", secondary_color: "#5B7083", rule_color: "#9AAAB8", heading_color: "#1F3A4D" }),
      DOCUMENT_PRESENTATION_PROFILE_V1: unset(PRESENTATION),
      LEGAL_EDITORIAL_PROFILE_V1: unset(LEGAL),
      DEFAULT_TEMPLATE_SELECTION_V1: unset({ mode: "PRODUCT_DEFAULT", template_sha256: null }),
    },
    assets: { PRIMARY_LOGO: empty, SYMBOL: empty, WATERMARK: empty, SIGNATURE_IMAGE: empty, PROFESSIONAL_SEAL: empty, BACKGROUND: empty, DEFAULT_WORD_TEMPLATE: empty },
    readiness: { expert_profile: "MISSING", branding: "PRODUCT_DEFAULT", document: "PRODUCT_DEFAULT", editorial: "PRESET", legal_editorial: "CNJ_TRF5", template: "PRODUCT_DEFAULT" },
    ...changes,
  } as InstallationOverview;
}

function json(status: number, value: object) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("Configurações da instalação (#270)", () => {
  test("shows readiness honestly and says existing cases never change", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, overview())));
    render(<SettingsView />);
    expect(await screen.findByText("Falta preencher")).toBeInTheDocument();
    expect(screen.getByText(/Cada perícia guarda uma cópia das configurações/)).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Seções das configurações" })).toBeInTheDocument();
    expect(screen.getByText(/Modelos Word personalizados preservam a identidade visual e a formatação existentes no arquivo\./)).toBeInTheDocument();
    expect(screen.queryByText(/obrigatória CNJ/i)).not.toBeInTheDocument();
    expect(screen.getByText("Natureza: recomendatória")).toBeInTheDocument();
  });

  test("saves the professional profile with the expected revision and no residential data", async () => {
    const saved = overview({ readiness: { ...overview().readiness, expert_profile: "CONFIGURED" } });
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, overview())).mockResolvedValueOnce(json(200, saved));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<SettingsView />);
    const section = await screen.findByRole("region", { name: "Perfil profissional" });
    await user.type(within(section).getByLabelText("Nome completo"), "Perita Sintética");
    await user.type(within(section).getByLabelText("Título profissional"), "Engenheira civil");
    await user.type(within(section).getByLabelText("Registro no conselho"), "CREA-PE 000000");
    await user.click(within(section).getByRole("button", { name: "Adicionar cadastro" }));
    await user.type(within(section).getByLabelText("Tribunal"), "TRF5");
    await user.type(within(section).getByLabelText("Número do cadastro"), "001");
    await user.type(within(section).getByLabelText("E-mail"), "perita@exemplo.invalid");
    await user.click(within(section).getByRole("button", { name: "Salvar perfil profissional" }));
    await screen.findByText(/Perfil profissional salvo/);
    const [url, init] = fetchSpy.mock.calls[1];
    expect(url).toBe("/app-api/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1");
    const body = JSON.parse(init.body);
    expect(body.expected_revision).toBeNull();
    expect(body.payload).toMatchObject({ full_name: "Perita Sintética", court_registration: "TRF5 — 001", contact_line: "perita@exemplo.invalid", court_registrations: [{ court: "TRF5", registration: "001", active: true, legacy: false }] });
    expect(JSON.stringify(body.payload)).not.toMatch(/cpf|rg|resid/i);
    expect(screen.getByText(/Não informe CPF, RG nem endereço residencial/)).toBeInTheDocument();
  });

  test("an incomplete profile is explained before anything is sent", async () => {
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, overview()));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<SettingsView />);
    const section = await screen.findByRole("region", { name: "Perfil profissional" });
    await user.click(within(section).getByRole("button", { name: "Salvar perfil profissional" }));
    expect(within(section).getByRole("alert")).toHaveTextContent("Informe nome, título profissional e registro no conselho.");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  test("a rejected image names the reason and the recovery", async () => {
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, overview())).mockResolvedValueOnce(json(422, { error: { code: "ASSET_FORMAT_MISMATCH" } }));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<SettingsView />);
    const input = await screen.findByLabelText("Arquivo para logotipo");
    await user.upload(input, new File(["x"], "logo.png", { type: "image/png" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("O conteúdo do arquivo não corresponde à extensão");
    const [url, init] = fetchSpy.mock.calls[1];
    expect(url).toBe("/app-api/v1/installation/assets/PRIMARY_LOGO");
    expect(init.headers["X-Expected-Revision"]).toBe("none");
  });

  test("a heavy watermark warns and an illegible heading color cannot be saved", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, overview())));
    const user = userEvent.setup();
    render(<SettingsView />);
    const document = await screen.findByRole("region", { name: "Documento Word" });
    await user.click(within(document).getByLabelText("Usar marca d'água"));
    fireEvent.change(within(document).getByLabelText(/Intensidade/), { target: { value: "20" } });
    expect(within(document).getByText(/Acima de 15% a marca d'água pode atrapalhar/)).toBeInTheDocument();
    const identity = screen.getByRole("region", { name: "Identidade visual" });
    fireEvent.change(within(identity).getByLabelText("Títulos"), { target: { value: "#dddddd" } });
    expect(within(identity).getByRole("alert")).toHaveTextContent("não tem contraste suficiente");
    expect(within(identity).getByRole("button", { name: "Salvar cores" })).toBeDisabled();
  });

  test("a conflict reloads the saved state and asks to review", async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(200, overview()))
      .mockResolvedValueOnce(json(409, { error: { code: "REPOSITORY_CONFLICT" } }))
      .mockResolvedValueOnce(json(200, overview()));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<SettingsView />);
    const legal = await screen.findByRole("region", { name: "Linguagem jurídica" });
    await user.click(within(legal).getByRole("button", { name: "Salvar linguagem jurídica" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("mudou em outra janela");
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(3));
  });

  test("the test document is downloaded from the real renderer and failures are said", async () => {
    const created = vi.fn(() => "blob:teste");
    vi.stubGlobal("URL", { ...URL, createObjectURL: created, revokeObjectURL: vi.fn() });
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(200, overview()))
      .mockResolvedValueOnce(new Response("docx", { status: 200 }))
      .mockResolvedValueOnce(json(422, { error: { code: "TEST_DOCUMENT_REJECTED" } }));
    vi.stubGlobal("fetch", fetchSpy);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<SettingsView />);
    await user.click(await screen.findByRole("button", { name: "Gerar documento de teste" }));
    expect(await screen.findByText("Documento de teste baixado.")).toBeInTheDocument();
    expect(fetchSpy.mock.calls[1][0]).toBe("/app-api/v1/installation/test-document");
    expect(click).toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Gerar documento de teste" }));
    expect(await screen.findByText(/não geraram um Word válido/)).toBeInTheDocument();
    click.mockRestore();
  });

  test("a custom template in use cannot be swapped, and a DOCM template downloads a .docm test document", async () => {
    const base = overview();
    const asset = { asset_id: "ASSET-1", role: "DEFAULT_WORD_TEMPLATE", filename: "escritorio.docm", media_type: "application/vnd.ms-word.document.macroEnabled.12", byte_size: 10, sha256: "a".repeat(64), width: null, height: null };
    const custom = {
      ...base,
      settings: { ...base.settings, DEFAULT_TEMPLATE_SELECTION_V1: { ...base.settings.DEFAULT_TEMPLATE_SELECTION_V1, configured: true, revision: 1, payload: { mode: "CUSTOM", template_sha256: "a".repeat(64) } } },
      assets: { ...base.assets, DEFAULT_WORD_TEMPLATE: { revision: 1, asset } },
      readiness: { ...base.readiness, template: "CUSTOM" },
    } as InstallationOverview;
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:teste"), revokeObjectURL: vi.fn() });
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(200, custom))
      .mockResolvedValueOnce(new Response("docm", { status: 200, headers: { "Content-Type": "application/vnd.ms-word.document.macroEnabled.12" } }));
    vi.stubGlobal("fetch", fetchSpy);
    const downloads: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { downloads.push(this.download); });
    const user = userEvent.setup();
    render(<SettingsView />);
    const swap = await screen.findByRole("button", { name: "Trocar modelo Word (escritorio.docm)" });
    expect(swap).toBeDisabled();
    expect(swap).toHaveAccessibleDescription(/escolha antes o modelo padrão do produto/);
    await user.click(screen.getByRole("button", { name: "Gerar documento de teste" }));
    await screen.findByText("Documento de teste baixado.");
    expect(downloads).toEqual(["documento-de-teste.docm"]);
    click.mockRestore();
  });

  test("load failure is recoverable", async () => {
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(503, {})).mockResolvedValueOnce(json(200, overview()));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<SettingsView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível abrir as configurações");
    await user.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(await screen.findByText("Falta preencher")).toBeInTheDocument();
  });

  test("the legacy approved geometry is an explicit choice, saved as a custom profile", async () => {
    const legacy = { ...EDITORIAL, profile_id: "CUSTOM", margin_top_cm: 2.54, margin_bottom_cm: 2.54, margin_left_cm: 3, margin_right_cm: 2.54 };
    const base = overview();
    const withLegacy = { ...base, settings: { ...base.settings, EDITORIAL_PROFILE_DEFAULT_V1: { ...base.settings.EDITORIAL_PROFILE_DEFAULT_V1, legacy_geometry: legacy } } } as InstallationOverview;
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, withLegacy)).mockResolvedValueOnce(json(200, withLegacy));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<SettingsView />);
    const editorial = await screen.findByRole("region", { name: "Perfil editorial" });
    await user.click(within(editorial).getByRole("button", { name: "Aplicar geometria do laudo legado aprovado" }));
    await screen.findByText("Perfil editorial salvo.");
    const body = JSON.parse(fetchSpy.mock.calls[1][1].body);
    expect(body.payload).toMatchObject({ profile_id: "CUSTOM", margin_top_cm: 2.54, margin_left_cm: 3 });
  });
});
