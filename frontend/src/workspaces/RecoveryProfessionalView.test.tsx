import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WorkspaceRecoveryView } from "./WorkspaceRecoveryView";

const ID = "11111111-1111-4111-8111-111111111111";
const RECOVERY = "22222222-2222-4222-8222-222222222222";
const SUMMARY = { workspace_id: ID, workspace_name: "Perícia sintética de recuperação",
  workspace_created_at: "2026-10-01T12:00:00+00:00", product_release: "1.0.0",
  storage_schema_version: 1, artifact_revisions: 32, private_contents: 7, backup_sha256: "a".repeat(64) };
const STAGED = { recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
function select(name = "pericia-sintetica.backup") {
  fireEvent.change(screen.getByLabelText("Arquivo de backup"), { target: { files: [new File(["synthetic"], name)] } });
}
function primary() { expect(document.querySelectorAll(".primary-action, .authority-action").length).toBeLessThanOrEqual(1); }
async function verify() {
  select(); fireEvent.click(screen.getByRole("button", { name: "Verificar backup" }));
  await screen.findByText("Backup válido"); primary();
}
async function stage() {
  await verify(); fireEvent.click(screen.getByRole("button", { name: "Preparar recuperação" }));
  await screen.findByText("Recuperação preparada para revisão"); primary();
}
async function review() {
  await stage(); fireEvent.click(screen.getByRole("button", { name: "Revisar recuperação" }));
  await screen.findByText("Este é o conteúdo que será promovido."); primary();
}
function commands() { return vi.mocked(fetch).mock.calls.map(([url]) => String(url)).filter((url) => /\/promote$/.test(url)); }
beforeEach(() => {
  window.history.replaceState(null, "", "/recuperacao");
  vi.stubGlobal("fetch", vi.fn(async (url) => {
    if (url === "/app-api/v1/recovery") return response({ recoveries: [] });
    if (String(url).endsWith("/verify")) return response(SUMMARY);
    if (String(url).endsWith("/staging")) return response(STAGED, 201);
    if (String(url).endsWith("/promote")) return response(SUMMARY);
    return response({ recovery_id: RECOVERY });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Recuperação profissional 3C", () => {
  it("inicia globalmente sem perícia com uma ação de seleção", async () => {
    render(<WorkspaceRecoveryView />);
    expect(screen.getByRole("heading", { name: "Recuperar uma perícia" })).toBeTruthy();
    expect(screen.getByText("Selecione um backup criado pelo Sistema Pericial. Nada será substituído nesta etapa.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Selecionar backup" })).toBeTruthy(); primary();
    await waitFor(() => expect(fetch).toHaveBeenCalled());
  });
  it("mostra nome e tamanho sem usar lastModified como data de backup", () => {
    render(<WorkspaceRecoveryView />); select();
    expect(screen.getByText("pericia-sintetica.backup")).toBeTruthy();
    expect(screen.getByText("9 bytes")).toBeTruthy(); primary();
    expect(screen.queryByText("Data do backup")).toBeNull();
  });
  it("verificação longa conserva nome e foco e bloqueia seleção e clique repetido", async () => {
    let finish!: (value: Response) => void;
    vi.mocked(fetch).mockImplementation(async (url) => url === "/app-api/v1/recovery" ? response({ recoveries: [] }) : new Promise((resolve) => { finish = resolve; }));
    render(<WorkspaceRecoveryView />); select();
    const button = screen.getByRole("button", { name: "Verificar backup" }); button.focus(); fireEvent.click(button); fireEvent.click(button);
    expect(screen.getByText("Verificando backup…")).toBeTruthy();
    expect(button).toHaveAttribute("aria-disabled", "true"); expect(button).toHaveFocus();
    expect(screen.getByLabelText("Arquivo de backup")).toBeDisabled(); primary();
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/verify"))).toHaveLength(1);
    finish(response(SUMMARY)); await screen.findByText("Backup válido");
  });
  it("verify PASS não prepara nem promove; resumo não expõe IDs sem disclosure", async () => {
    render(<WorkspaceRecoveryView />); await verify();
    expect(commands()).toHaveLength(0);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith("/staging"))).toBe(false);
    expect(screen.getByText(ID).closest("details")).toBeTruthy();
    expect(screen.getByText("32")).toBeTruthy(); expect(screen.getByText("7")).toBeTruthy();
  });
  it("backup inválido falha fechado com mensagem segura e sem promoção", async () => {
    vi.mocked(fetch).mockImplementation(async (url) => url === "/app-api/v1/recovery" ? response({ recoveries: [] }) : response({ error: { code: "INVALID_BACKUP" } }, 400));
    render(<WorkspaceRecoveryView />); select(); fireEvent.click(screen.getByRole("button", { name: "Verificar backup" }));
    expect(await screen.findByText("Este backup não pode ser usado com segurança.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Promover recuperação" })).toBeNull(); expect(commands()).toHaveLength(0); primary();
  });
  it("preparação longa mantém ação estável e não promove", async () => {
    let finish!: (value: Response) => void;
    vi.mocked(fetch).mockImplementation(async (url) => String(url).endsWith("/staging") ? new Promise((resolve) => { finish = resolve; }) : url === "/app-api/v1/recovery" ? response({ recoveries: [] }) : response(SUMMARY));
    render(<WorkspaceRecoveryView />); await verify();
    const button = screen.getByRole("button", { name: "Preparar recuperação" }); button.focus(); fireEvent.click(button);
    expect(screen.getByText("Preparando recuperação…")).toBeTruthy(); expect(button).toHaveFocus(); primary(); expect(commands()).toHaveLength(0);
    finish(response(STAGED, 201)); await screen.findByText("Recuperação preparada para revisão");
  });
  it("stage PASS não promove nem oferece navegação pela cópia isolada", async () => {
    render(<WorkspaceRecoveryView />); await stage(); expect(commands()).toHaveLength(0);
    expect(screen.queryByRole("link", { name: "Abrir perícia recuperada" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Promover recuperação" })).toBeNull();
  });
  it("abrir review não promove; foco chega ao título da revisão", async () => {
    render(<WorkspaceRecoveryView />); await review(); expect(commands()).toHaveLength(0);
    expect(screen.getByRole("heading", { name: "Revisar recuperação" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Promover recuperação" })).toBeDisabled();
  });
  it("confirmar não promove; somente comando explícito envia confirm true", async () => {
    render(<WorkspaceRecoveryView />); await review(); fireEvent.click(screen.getByRole("checkbox"));
    expect(commands()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Promover recuperação" }));
    await screen.findByText("Perícia recuperada"); expect(commands()).toHaveLength(1);
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("/promote"))!;
    expect(JSON.parse(call[1]!.body as string)).toEqual({ confirm: true }); primary();
  });
  it("promoção longa mantém foco/nome e impede comando duplicado", async () => {
    let finish!: (value: Response) => void;
    vi.mocked(fetch).mockImplementation(async (url) => String(url).endsWith("/promote") ? new Promise((resolve) => { finish = resolve; }) : url === "/app-api/v1/recovery" ? response({ recoveries: [] }) : response(String(url).endsWith("/staging") ? STAGED : SUMMARY));
    render(<WorkspaceRecoveryView />); await review(); fireEvent.click(screen.getByRole("checkbox"));
    const button = screen.getByRole("button", { name: "Promover recuperação" }); button.focus(); fireEvent.click(button); fireEvent.click(button);
    expect(screen.getByText("Promovendo recuperação…")).toBeTruthy(); expect(button).toHaveFocus(); expect(commands()).toHaveLength(1); primary();
    finish(response(SUMMARY)); await screen.findByText("Perícia recuperada");
  });
  it("promoted oferece abrir pelo endereço normal sem restart", async () => {
    render(<WorkspaceRecoveryView />); await review(); fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByRole("button", { name: "Promover recuperação" }));
    const link = await screen.findByRole("link", { name: "Abrir perícia recuperada" });
    expect(link).toHaveAttribute("href", `/pericias/${ID}`); primary();
  });
  it("reopen navega pelo router normal", async () => {
    render(<WorkspaceRecoveryView />); await review(); fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByRole("button", { name: "Promover recuperação" }));
    fireEvent.click(await screen.findByRole("link", { name: "Abrir perícia recuperada" }));
    expect(window.location.pathname).toBe(`/pericias/${ID}`);
  });
  it("unavailable da lista não vira nenhuma recuperação e permite retry", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: {} }, 503)); render(<WorkspaceRecoveryView />);
    expect(await screen.findByText("Não foi possível verificar a recuperação.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Verificar recuperação" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull()); primary();
  });
  it("falha de transporte na promoção não afirma nada promovido nem repete comando", async () => {
    vi.mocked(fetch).mockImplementation(async (url) => String(url).endsWith("/promote") ? response({ error: {} }, 503) : url === "/app-api/v1/recovery" ? response({ recoveries: [] }) : response(String(url).endsWith("/staging") ? STAGED : SUMMARY));
    render(<WorkspaceRecoveryView />); await review(); fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByRole("button", { name: "Promover recuperação" }));
    await screen.findByRole("alert"); expect(document.body.textContent).not.toContain("Nada foi promovido");
    expect(screen.queryByRole("button", { name: "Promover recuperação" })).toBeNull(); expect(commands()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Verificar recuperação" })).toBeTruthy();
  });
  it("restart redescobre staging, abre review e exige nova confirmação", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ recoveries: [{ recovery_id: RECOVERY, summary: SUMMARY, state: "STAGED", reason: null, allowed_actions: ["PROMOTE", "DISCARD"] }] }));
    render(<WorkspaceRecoveryView />);
    fireEvent.click(await screen.findByRole("button", { name: "Conferir recuperação preparada" }));
    expect(screen.getByRole("button", { name: "Promover recuperação" })).toBeDisabled(); expect(commands()).toHaveLength(0); primary();
  });
  it("conteúdo longo permanece textual e detalhes técnicos são disclosure nativo", async () => {
    render(<WorkspaceRecoveryView />); select("backup-" + "nome-longo-".repeat(80) + ".backup");
    fireEvent.click(screen.getByRole("button", { name: "Verificar backup" })); await screen.findByText("Backup válido");
    expect(screen.getByText("Detalhes técnicos").tagName).toBe("SUMMARY"); primary();
  });
  it("confirmação acessível por teclado não dispara promoção ao receber foco", async () => {
    render(<WorkspaceRecoveryView />); await review(); const checkbox = screen.getByRole("checkbox"); checkbox.focus();
    expect(checkbox).toHaveFocus(); expect(checkbox).toHaveAccessibleName(/Confirmo/);
    expect(commands()).toHaveLength(0); primary();
  });
  it("retomada longa mantém nome e foco da ação escolhida", async () => {
    let finish!: (value: Response) => void;
    let calls = 0;
    vi.mocked(fetch).mockImplementation(async (url) => {
      if (String(url).endsWith("/promote")) {
        calls += 1;
        return calls === 1 ? response({ error: { code: "RECOVERY_PROMOTION_INCOMPLETE" } }, 409) : new Promise((resolve) => { finish = resolve; });
      }
      return url === "/app-api/v1/recovery" ? response({ recoveries: [] }) : response(String(url).endsWith("/staging") ? STAGED : SUMMARY);
    });
    render(<WorkspaceRecoveryView />); await review(); fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByRole("button", { name: "Promover recuperação" }));
    const resume = await screen.findByRole("button", { name: "Retomar promoção" }); resume.focus(); fireEvent.click(resume);
    expect(screen.getByRole("button", { name: "Retomar promoção" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Retomar promoção" })).toHaveAttribute("aria-disabled", "true"); primary();
    finish(response(SUMMARY)); await screen.findByText("Perícia recuperada");
  });
  it("quarentena ilegível no restart não se apresenta como conteúdo verificado", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ recoveries: [{ recovery_id: RECOVERY, summary: null, state: "RECOVERY_UNRESUMABLE", reason: "quarantine_marker_unreadable", allowed_actions: ["ABANDON"] }] }));
    render(<WorkspaceRecoveryView />); await screen.findByRole("button", { name: "Abandonar cópia de recuperação" });
    expect(screen.queryByText(/Cópia verificada e preparada/)).toBeNull();
  });
});
