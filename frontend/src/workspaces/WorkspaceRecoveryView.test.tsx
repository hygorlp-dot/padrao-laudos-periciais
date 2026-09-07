import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WorkspaceRecoveryView } from "./WorkspaceRecoveryView";

const WORKSPACE = "11111111-1111-4111-8111-111111111111";
const RECOVERY = "22222222-2222-4222-8222-222222222222";

const SUMMARY = {
  workspace_id: WORKSPACE,
  workspace_name: "Caso 42",
  workspace_created_at: "2026-09-01T12:00:00+00:00",
  product_release: "1.0.0",
  storage_schema_version: 1,
  artifact_revisions: 3,
  private_contents: 1,
  backup_sha256: "a".repeat(64),
};

function jsonResponse(value: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => "application/json; charset=utf-8" },
    json: async () => value,
    blob: async () => new Blob(["x"]),
  } as unknown as Response;
}

function backupFile() {
  return new File([new Uint8Array([1, 2, 3])], "pericia.backup");
}

function selectFile() {
  const input = screen.getByLabelText("Arquivo de backup") as HTMLInputElement;
  fireEvent.change(input, { target: { files: [backupFile()] } });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:local"),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WorkspaceRecoveryView", () => {
  it("exporta o backup pela Local API e entrega o download ao usuário", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: { get: () => "application/octet-stream" },
      blob: async () => new Blob([new Uint8Array([1, 2, 3])]),
    } as unknown as Response);

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    fireEvent.click(screen.getByRole("button", { name: "Criar backup" }));

    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Backup gerado"),
    );
    expect(fetchMock.mock.calls[0][0]).toBe(`/app-api/v1/workspaces/${WORKSPACE}/backup`);
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("verificar NÃO ativa nada: nenhuma chamada de staging ou promoção", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(SUMMARY));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));

    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("não"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/app-api/v1/recovery/verify");
    expect(
      screen.queryByRole("button", { name: "4. Promover recuperação" }),
    ).toBeNull();
  });

  it("preparar staging não promove e deixa claro que a cópia está isolada", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      );

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));

    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("isolada"),
    );
    expect(fetchMock.mock.calls[1][0]).toBe("/app-api/v1/recovery/staging");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("a promoção exige confirmação explícita antes de ficar disponível", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      );

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));

    const promote = await screen.findByRole("button", { name: "4. Promover recuperação" });
    expect(promote).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "4. Promover recuperação" })).toBeEnabled();
  });

  it("promove somente após a confirmação e reporta a perícia ativa", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      )
      .mockResolvedValueOnce(jsonResponse(SUMMARY));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "4. Promover recuperação" });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "4. Promover recuperação" }));

    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("promovida"),
    );
    expect(fetchMock.mock.calls[2][0]).toBe(`/app-api/v1/recovery/${RECOVERY}/promote`);
    expect((fetchMock.mock.calls[2][1] as RequestInit).body).toBe(
      JSON.stringify({ confirm: true }),
    );
  });

  it("descartar a recuperação preparada volta ao início sem promover", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      )
      .mockResolvedValueOnce(jsonResponse({ recovery_id: RECOVERY }));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "Descartar recuperação preparada" });
    fireEvent.click(screen.getByRole("button", { name: "Descartar recuperação preparada" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "4. Promover recuperação" })).toBeNull(),
    );
    expect(fetchMock.mock.calls[2][0]).toBe(`/app-api/v1/recovery/${RECOVERY}/discard`);
  });

  it("mostra a falha sanitizada quando o backup é inválido", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ error: { code: "INVALID_BACKUP", message: "x" } }, 400),
    );

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("não é um backup íntegro");
    expect(
      screen.queryByRole("button", { name: "2. Preparar cópia recuperada" }),
    ).toBeNull();
  });

  it("recusa promover quando o conflito de identidade é reportado", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      )
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "WORKSPACE_CONFLICT", message: "x" } }, 409),
      );

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "4. Promover recuperação" });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "4. Promover recuperação" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Já existe uma perícia com esta identidade");
  });

  it("oferece saída depois de uma promoção falha, sem deixar o usuário preso", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      )
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "WORKSPACE_CONFLICT", message: "x" } }, 409),
      )
      .mockResolvedValueOnce(jsonResponse({ recovery_id: RECOVERY }));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "4. Promover recuperação" });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "4. Promover recuperação" }));

    // A saída existe, mas passa pelo descarte EXPLÍCITO: enquanto a cópia
    // isolada estiver no disco, "recomeçar" seria abandoná-la em silêncio.
    await screen.findByRole("alert");
    fireEvent.click(
      screen.getByRole("button", { name: "Descartar recuperação preparada" }),
    );
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByRole("button", { name: "1. Verificar backup" })).toBeDisabled();
  });
  it("staging não promovível continua descartável: a cópia isolada existe em disco", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            recovery_id: RECOVERY,
            summary: SUMMARY,
            promotable: false,
            resuming: false,
            not_promotable_reason: "ja_existe_pericia_com_esta_identidade",
          },
          201,
        ),
      )
      .mockResolvedValueOnce(jsonResponse({ recovery_id: RECOVERY }));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));

    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("Já existe uma perícia com esta identidade");
    expect(
      screen.queryByRole("button", { name: "4. Promover recuperação" }),
    ).toBeNull();

    const descartar = screen.getByRole("button", {
      name: "Descartar recuperação preparada",
    });
    fireEvent.click(descartar);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2][0]).toBe(`/app-api/v1/recovery/${RECOVERY}/discard`);
  });

  it("promoção falha não abandona a cópia isolada: ela segue descartável", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      )
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "WORKSPACE_CONFLICT", message: "x" } }, 409),
      )
      .mockResolvedValueOnce(jsonResponse({ recovery_id: RECOVERY }));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "4. Promover recuperação" });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "4. Promover recuperação" }));

    await screen.findByRole("alert");
    fireEvent.click(
      screen.getByRole("button", { name: "Descartar recuperação preparada" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(fetchMock.mock.calls[3][0]).toBe(`/app-api/v1/recovery/${RECOVERY}/discard`);
  });

  it("descarte retido é dito com honestidade e pode ser tentado de novo", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      )
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "RECOVERY_RETAINED", message: "x" } }, 409),
      )
      .mockResolvedValueOnce(jsonResponse({ recovery_id: RECOVERY }));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "4. Promover recuperação" });
    fireEvent.click(
      screen.getByRole("button", { name: "Descartar recuperação preparada" }),
    );

    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("segue isolada");
    expect(screen.queryByRole("button", { name: "Recomeçar" })).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Descartar recuperação preparada" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  });
  it("promoção incompleta oferece RETOMAR e não oferece descartar", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "RECOVERY_PROMOTION_INCOMPLETE", message: "x" } },
          409,
        ),
      )
      .mockResolvedValueOnce(jsonResponse(SUMMARY));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "4. Promover recuperação" });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "4. Promover recuperação" }));

    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("retomada");
    // Descartar aqui apagaria a autoridade de retomada: não pode ser oferecido.
    expect(
      screen.queryByRole("button", { name: "Descartar recuperação preparada" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Recomeçar" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retomar promoção" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Recuperação promovida"),
    );
    expect(fetchMock.mock.calls[3][0]).toBe(`/app-api/v1/recovery/${RECOVERY}/promote`);
  });

  it("nunca afirma que nada foi promovido quando a promoção ficou incompleta", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse({ recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false }, 201),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "RECOVERY_PROMOTION_INCOMPLETE", message: "x" } },
          409,
        ),
      );

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "4. Promover recuperação" });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "4. Promover recuperação" }));

    await screen.findByRole("alert");
    expect(document.body.textContent).not.toContain("Nada foi promovido");
    expect(document.body.textContent).not.toContain("Nenhuma perícia existente foi alterada");
  });
  it("sem perícia, a tela é só restauração: não oferece criar backup", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ recoveries: [] }));
    render(<WorkspaceRecoveryView />);
    expect(screen.queryByRole("button", { name: "Criar backup" })).toBeNull();
    expect(screen.getByLabelText("Arquivo de backup")).toBeTruthy();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  });
  it("descarte que falha preserva o motivo: a tela não volta a mentir", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse(
          { recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false },
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "RECOVERY_PROMOTION_INCOMPLETE", message: "x" } },
          409,
        ),
      );

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "4. Promover recuperação" });
    fireEvent.click(
      screen.getByRole("button", { name: "Descartar recuperação preparada" }),
    );

    await screen.findByRole("alert");
    expect(document.body.textContent).not.toContain("Nada foi promovido");
    expect(screen.getByRole("button", { name: "Retomar promoção" })).toBeTruthy();
  });

  it("retomada nunca afirma que não substituiu nada", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse(
          { recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: true },
          201,
        ),
      );

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));

    await screen.findByRole("button", { name: "4. Promover recuperação" });
    expect(document.body.textContent).not.toContain("não substituiu nada");
    expect(document.body.textContent).toContain("RETOMADA");
    // Descartar uma retomada apagaria a autoridade: não é oferecido aqui.
    expect(
      screen.queryByRole("button", { name: "Descartar recuperação preparada" }),
    ).toBeNull();
  });

  it("promoção irretomável devolve a saída: abandono explícito fica disponível", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(
        jsonResponse(
          { recovery_id: RECOVERY, summary: SUMMARY, promotable: true, resuming: false },
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "RECOVERY_UNRESUMABLE", message: "x" } }, 409),
      )
      .mockResolvedValueOnce(jsonResponse({ recovery_id: RECOVERY }));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    await screen.findByRole("button", { name: "2. Preparar cópia recuperada" });
    fireEvent.click(screen.getByRole("button", { name: "2. Preparar cópia recuperada" }));
    await screen.findByRole("button", { name: "4. Promover recuperação" });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "4. Promover recuperação" }));

    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("não pode mais ser concluída");
    expect(screen.queryByRole("button", { name: "Retomar promoção" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Abandonar cópia de recuperação" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(fetchMock.mock.calls[3][0]).toBe(`/app-api/v1/recovery/${RECOVERY}/abandon`);
  });

  it("redescobre staging após reinício sem exigir reenvio do backup", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      recoveries: [{
        recovery_id: RECOVERY,
        state: "STAGED",
        summary: SUMMARY,
        reason: null,
        allowed_actions: ["PROMOTE", "DISCARD"],
      }],
    }));

    render(<WorkspaceRecoveryView />);

    expect(await screen.findByRole("heading", { name: "Recuperações pendentes" })).toBeTruthy();
    expect(screen.getByText("Caso 42")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Conferir recuperação preparada" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Descartar recuperação preparada" })).toBeTruthy();
    expect(fetch).toHaveBeenCalledWith(
      "/app-api/v1/recovery",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("journal corrompido reaparece com abandono explícito e motivo honesto", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse({
        recoveries: [{
          recovery_id: RECOVERY,
          state: "RECOVERY_UNRESUMABLE",
          summary: SUMMARY,
          reason: "promotion_journal_unreadable_or_unsupported",
          allowed_actions: ["ABANDON"],
        }],
      }))
      .mockResolvedValueOnce(jsonResponse({ recovery_id: RECOVERY }));

    render(<WorkspaceRecoveryView />);

    const abandon = await screen.findByRole("button", {
      name: "Abandonar cópia de recuperação",
    });
    expect(document.body.textContent).toContain("estado da promoção não pôde ser lido");
    fireEvent.click(abandon);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe(`/app-api/v1/recovery/${RECOVERY}/abandon`);
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({
      confirm_abandon: true,
    });
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Recuperações pendentes" })).toBeNull(),
    );
  });

  it("reenvio de recuperação irretomável nunca oculta a ação de abandono", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(SUMMARY))
      .mockResolvedValueOnce(jsonResponse({
        recovery_id: RECOVERY,
        summary: SUMMARY,
        promotable: false,
        resuming: true,
        not_promotable_reason: "promotion_journal_unreadable_or_unsupported",
      }, 201));

    render(<WorkspaceRecoveryView workspaceId={WORKSPACE} />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "1. Verificar backup" }));
    fireEvent.click(await screen.findByRole("button", { name: "2. Preparar cópia recuperada" }));

    expect(await screen.findByRole("button", {
      name: "Abandonar cópia de recuperação",
    })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retomar promoção" })).toBeNull();
  });
});
