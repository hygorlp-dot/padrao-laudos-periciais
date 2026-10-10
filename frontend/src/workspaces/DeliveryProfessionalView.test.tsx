import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";
import { templateManifest, type DeliveryArtifact, type DeliveryEnvelope, type DeliveryState } from "../data/deliverySnapshot";
import { DeliveryFoundationView } from "./DeliveryFoundationView";

const ID = "11111111-1111-4111-8111-111111111111";
const word = { artifact_id: "ART-1", role: "MAIN_REPORT", format: "DOCX" as const, filename: "laudo.docx", content_id: "33333333-3333-4333-8333-333333333333", media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", byte_size: 4096, checksum_sha256: "a".repeat(64) };
const pdf = { ...word, artifact_id: "ART-2", role: "DERIVED_PDF", format: "PDF" as const, filename: "laudo.pdf", content_id: "44444444-4444-4444-8444-444444444444", media_type: "application/pdf" };
const annex = { ...pdf, artifact_id: "ART-3", role: "ANNEX", filename: "anexo.pdf", content_id: "55555555-5555-4555-8555-555555555555" };
function delivery(state: DeliveryState = "DRAFT", artifacts: DeliveryArtifact[] = [word]): DeliveryEnvelope {
  return { revision: 7, updated_at: "2026-10-09T12:00:00Z", snapshot: {
    schema_version: "1.0.0", delivery_id: "DELIVERY-CURRENT", revision: 7, workspace_id: ID,
    binding: { workspace_id: ID, professional_id: "EXPERT-1", report_snapshot_id: "REPORT-1", report_revision: 4, report_digest: "b".repeat(64), report_approval_id: "APPROVAL-1" },
    template_id: "PRODUCT-DEFAULT-REPORT-V1", template_content_id: "22222222-2222-4222-8222-222222222222", template_format: "DOCX", template_revision: 1, template_digest: "c".repeat(64), rendering_version: "delivery-renderer/1.2.0",
    artifacts, package: { manifest_version: "1.0.0", artifact_ids: artifacts.map((a) => a.artifact_id) }, decisions: [], state,
    stale_reasons: state === "STALE" ? ["REPORT_DIGEST_CHANGED"] : [], stale_origin_state: state === "STALE" ? "DELIVERED" : null, supersedes_delivery_id: null,
  } };
}
const response = (status: number, body: object) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function serve(item: DeliveryEnvelope, history = [item]) {
  vi.stubGlobal("fetch", vi.fn((url) => Promise.resolve(String(url).endsWith("/history") ? response(200, { items: history }) : response(200, item))));
}
afterEach(() => vi.unstubAllGlobals());

describe("professional delivery desk", () => {
  test.each([
    ["DRAFT", false, "Preparando arquivos", "Gerar arquivos do laudo"],
    ["DRAFT", true, "Preparando arquivos", "Enviar para conferência"],
    ["READY_FOR_REVIEW", true, "Pronta para conferência", "Aprovar entrega"],
    ["APPROVED", true, "Entrega aprovada", "Finalizar arquivos"],
    ["FINALIZED", true, "Arquivos finalizados", "Registrar como entregue"],
  ] as const)("%s Word=%s has one primary action and professional status", async (state, rendered, label, action) => {
    serve(delivery(state, rendered ? [word] : []));
    const { container } = render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Entrega do laudo" })).toBeInTheDocument();
    expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    const buttons = container.querySelectorAll("button.primary-action");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveTextContent(action);
    expect(screen.queryByText(state)).not.toBeInTheDocument();
    if (state === "DRAFT") expect(screen.getByRole("button", { name: "Adicionar ao pacote" })).toBeInTheDocument();
    else expect(screen.queryByRole("button", { name: "Adicionar ao pacote" })).not.toBeInTheDocument();
  });

  test.each(["DELIVERED", "SUPERSEDED", "STALE"] as const)("%s cannot continue an old lifecycle", async (state) => {
    serve(delivery(state));
    render(<DeliveryFoundationView workspaceId={ID} />);
    await screen.findByRole("heading", { name: "Entrega do laudo" });
    for (const name of ["Gerar arquivos do laudo", "Enviar para conferência", "Aprovar entrega", "Finalizar arquivos", "Registrar como entregue", "Adicionar ao pacote"]) expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Fundamentação da decisão")).not.toBeInTheDocument();
  });

  test("Word, derived PDF and supporting files have separate roles and technical audit", async () => {
    serve(delivery("DRAFT", [word, pdf, annex]));
    render(<DeliveryFoundationView workspaceId={ID} />);
    const official = await screen.findByRole("region", { name: "Documento oficial" });
    expect(within(official).getByText("Laudo em Word")).toBeInTheDocument();
    expect(within(official).getByRole("link", { name: "Baixar Word" })).toHaveAttribute("download", word.filename);
    const derived = screen.getByRole("region", { name: "PDF derivado do Word" });
    expect(within(derived).getByText("Conferido")).toBeInTheDocument();
    expect(within(derived).getByText(/Gerado a partir deste Word e conferido pelo sistema/)).toBeInTheDocument();
    const additional = screen.getByRole("region", { name: /Anexos e arquivos de apoio/ });
    expect(within(additional).getByText("Anexo")).toBeInTheDocument();
    expect(within(additional).queryByRole("link", { name: "Baixar Word" })).not.toBeInTheDocument();
    expect(screen.getByText(/não são fontes do processo/)).toBeInTheDocument();
    for (const label of screen.getAllByText("PRODUCT-DEFAULT-REPORT-V1")) expect(label.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText(word.content_id).closest("details")).not.toHaveAttribute("open");
  });

  test("no PDF never invalidates or hides ready Word", async () => {
    serve(delivery()); render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByText("Word pronto")).toBeInTheDocument();
    expect(screen.getByText("PDF indisponível")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Baixar PDF" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Baixar Word" }).length).toBeGreaterThan(0);
  });

  test("reason appears only with the decision using it and preserves reason command", async () => {
    const item = delivery("READY_FOR_REVIEW"); const calls: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn((url, init?: RequestInit) => {
      if (init?.method === "POST") { calls.push(init); return Promise.resolve(response(200, delivery("APPROVED"))); }
      return Promise.resolve(String(url).endsWith("/history") ? response(200, { items: [item] }) : response(200, item));
    }));
    render(<DeliveryFoundationView workspaceId={ID} />);
    const button = await screen.findByRole("button", { name: "Aprovar entrega" }); expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Motivo da aprovação"), { target: { value: "Conferência profissional concluída" } });
    fireEvent.click(button);
    await screen.findByLabelText("Registro da finalização");
    expect(JSON.parse(String(calls[0].body))).toMatchObject({ action: "APPROVE", reason: "Conferência profissional concluída", expected_revision: 7 });
  });

  test("stale shows origin, preserved downloads and only allowed reissue", async () => {
    serve(delivery("STALE", [word, pdf])); render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Esta entrega ficou desatualizada.");
    expect(screen.getByText(/Antes da alteração: registrada como entregue/i)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Baixar Word" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Emitir nova revisão" })).toBeInTheDocument();
  });

  test("history separates delivery/report revisions, dates, roles and predecessor", async () => {
    const old = delivery("DELIVERED", [word, pdf, annex]); old.revision = 6; old.snapshot.revision = 6; old.snapshot.delivery_id = "DELIVERY-OLD";
    const current = delivery("DRAFT", []); current.snapshot.supersedes_delivery_id = old.snapshot.delivery_id;
    serve(current, [old, current]); render(<DeliveryFoundationView workspaceId={ID} />);
    await screen.findByRole("heading", { name: "Entrega do laudo" });
    expect(screen.getByText("Laudo aprovado · revisão 4")).toBeInTheDocument();
    expect(screen.getByText("Entrega · revisão 7")).toBeInTheDocument();
    expect(screen.getByText(/Substitui entrega anterior · revisão 6/)).toBeInTheDocument();
    const ledger = screen.getByText(/Histórico preservado/).closest("details")!;
    expect(ledger).not.toHaveAttribute("open");
    expect(within(ledger).getByText("Histórica · substituída por nova revisão")).toBeInTheDocument();
    expect(within(ledger).getByText(/Word disponível · PDF disponível · 1 anexo/)).toBeInTheDocument();
    expect(ledger.querySelectorAll("time")).toHaveLength(2);
  });

  test("history not-found cannot become a false empty delivery", async () => {
    vi.stubGlobal("fetch", vi.fn((url) => Promise.resolve(String(url).endsWith("/history") ? response(404, {}) : response(200, delivery()))));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível verificar os arquivos desta entrega.");
    expect(screen.queryByRole("heading", { name: "Preparar entrega" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Baixar Word" })).not.toBeInTheDocument();
  });

  test("backend unavailable is distinct from missing", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response(503, {}))));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível verificar os arquivos desta entrega.");
    expect(screen.queryByRole("button", { name: "Usar modelo padrão" })).not.toBeInTheDocument();
  });

  test("empty state uses default while custom Word remains advanced", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response(404, {}))));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Preparar entrega" })).toBeInTheDocument();
    expect(screen.getByText("A entrega será criada a partir do laudo aprovado.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Usar modelo padrão" })).toHaveClass("primary-action");
    expect(screen.getByText("Usar outro modelo Word").closest("details")).not.toHaveAttribute("open");
  });

  test("generation retains button accessible name and focus with real busy status", async () => {
    const user = userEvent.setup(); let resolve: (r: Response) => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn((url, init?: RequestInit) => {
      if (String(url).endsWith("/report-snapshot")) return Promise.resolve(response(200, { revision: 4, snapshot: { report_id: "REPORT-1", presentation: {} } }));
      return init?.method === "POST" ? new Promise<Response>((r) => { resolve = r; }) : Promise.resolve(String(url).endsWith("/history") ? response(200, { items: [] }) : response(200, delivery("DRAFT", [])));
    }));
    render(<DeliveryFoundationView workspaceId={ID} />);
    const button = await screen.findByRole("button", { name: "Gerar arquivos do laudo" });
    button.focus(); await user.keyboard("{Enter}");
    expect(button).toHaveFocus(); expect(button).toHaveAccessibleName("Gerar arquivos do laudo"); expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Gerando Word e PDF");
    resolve(response(503, {}));
    await waitFor(() => expect(button).not.toHaveAttribute("aria-busy", "true"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível confirmar a geração do Word.");
  });

  test("a lost render response is recovered by reading, never repeating the command", async () => {
    let rendered = false; let commands = 0;
    vi.stubGlobal("fetch", vi.fn((url, init?: RequestInit) => {
      if (String(url).endsWith("/report-snapshot")) return Promise.resolve(response(200, { revision: 4, snapshot: { report_id: "REPORT-1", presentation: {} } }));
      if (init?.method === "POST") { commands += 1; rendered = true; return Promise.resolve(response(503, {})); }
      const item = delivery("DRAFT", rendered ? [word, pdf] : []);
      return Promise.resolve(String(url).endsWith("/history") ? response(200, { items: [item] }) : response(200, item));
    }));
    render(<DeliveryFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Gerar arquivos do laudo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível confirmar a geração");
    expect(screen.queryByRole("button", { name: "Tentar novamente" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Verificar entrega" }));
    expect(await screen.findByText("Conferido", { exact: true })).toBeInTheDocument();
    expect(commands).toBe(1);
  });

  test("attachment uses supporting route, actual role and reports success without replacing Word", async () => {
    const user = userEvent.setup(); const item = delivery(); const commands: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn((url, init?: RequestInit) => {
      commands.push({ url: String(url), init });
      if (String(url).endsWith("/delivery-supporting-files")) return Promise.resolve(response(201, { content_id: annex.content_id }));
      if (String(url).endsWith("/package-artifacts")) return Promise.resolve(response(200, delivery("DRAFT", [word, annex])));
      return Promise.resolve(String(url).endsWith("/history") ? response(200, { items: [item] }) : response(200, item));
    }));
    render(<DeliveryFoundationView workspaceId={ID} />);
    await screen.findByRole("heading", { name: "Entrega do laudo" });
    fireEvent.click(screen.getByText("Adicionar arquivos ao pacote"));
    const file = new File(["synthetic"], "anexo.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Arquivo", { exact: true }), file);
    // JSDOM's native required-file validation does not observe userEvent's
    // synthetic FileList; exercise the form handler after the real selection.
    fireEvent.submit(screen.getByRole("button", { name: "Adicionar ao pacote" }).closest("form")!);
    expect(await screen.findByText("Arquivo adicionado ao pacote da entrega.")).toBeInTheDocument();
    const attach = commands.find((c) => c.url.endsWith("/package-artifacts"));
    expect(JSON.parse(String(attach?.init?.body))).toEqual({ expected_revision: 7, content_id: annex.content_id, role: "ANNEX" });
    expect(screen.getByRole("region", { name: "Documento oficial" })).toHaveTextContent(word.filename);
    expect(screen.getByRole("button", { name: "Adicionar ao pacote" })).toBeDisabled();
  });

  test("reissue sends exact predecessor revision and starts a clean draft while retaining history", async () => {
    const old = delivery("STALE", [word, pdf]); const next = delivery("DRAFT", []); next.revision = 8; next.snapshot.revision = 8; next.snapshot.delivery_id = "DELIVERY-NEW"; next.snapshot.supersedes_delivery_id = old.snapshot.delivery_id;
    const calls: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn((url, init?: RequestInit) => {
      if (String(url).endsWith("/delivery-templates/default")) return Promise.resolve(response(201, { template: { content_id: old.snapshot.template_content_id }, manifest: templateManifest("PRODUCT-DEFAULT-REPORT-V1", "DOCX") }));
      if (String(url).endsWith("/reissue")) { calls.push(init!); return Promise.resolve(response(201, next)); }
      return Promise.resolve(String(url).endsWith("/history") ? response(200, { items: [old, next] }) : response(200, old));
    }));
    render(<DeliveryFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Usar modelo padrão" }));
    expect(await screen.findByRole("button", { name: "Gerar arquivos do laudo" })).toBeInTheDocument();
    expect(JSON.parse(String(calls[0].body))).toMatchObject({ expected_revision: 7, template_content_id: old.snapshot.template_content_id });
    expect(screen.getByRole("region", { name: "Documento oficial" })).toHaveTextContent("Word ainda não gerado");
    expect(screen.getByText(/Substitui entrega anterior · revisão 7/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Baixar Word" })).toHaveLength(1);
  });
});
