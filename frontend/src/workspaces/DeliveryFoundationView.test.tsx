import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { DeliveryFoundationView } from "./DeliveryFoundationView";

const ID = "11111111-1111-4111-8111-111111111111";
const snapshot = {
  schema_version: "1.0.0", delivery_id: "DELIVERY-001", revision: 6, workspace_id: ID,
  binding: { workspace_id: ID, professional_id: "EXPERT-1", report_snapshot_id: "REPORT-1", report_revision: 5, report_digest: "a".repeat(64), report_approval_id: "APPROVAL-1" },
  template_id: "TEMPLATE-1", template_content_id: "22222222-2222-4222-8222-222222222222", template_format: "DOCM", template_revision: 1, template_digest: "b".repeat(64), rendering_version: "delivery-renderer/1.2.0",
  artifacts: [{ artifact_id: "ART-1", role: "MAIN_REPORT", format: "DOCM", filename: "laudo.docm", content_id: "33333333-3333-4333-8333-333333333333", media_type: "application/vnd.ms-word.document.macroEnabled.12", byte_size: 321, checksum_sha256: "c".repeat(64) }],
  package: { manifest_version: "1.0.0", artifact_ids: ["ART-1"] }, decisions: [], state: "DELIVERED", stale_reasons: [], stale_origin_state: null, supersedes_delivery_id: null,
};
const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("delivery foundation workbench", () => {
  test("shows explicit lifecycle, exact bindings, manifest hashes and local download without court filing", async () => {
    const item = { revision: 6, updated_at: "2026-08-31T12:00:00Z", snapshot };
    vi.stubGlobal("fetch", vi.fn((input) => Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [item] }) : response(200, item))));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Entrega do laudo" })).toBeInTheDocument();
    expect(screen.getByText("Entregue")).toBeInTheDocument();
    expect(screen.queryByText("DELIVERED")).not.toBeInTheDocument();
    expect(screen.getByText(/Revisão 5, aprovada/)).toBeInTheDocument();
    // Identidades e hashes continuam auditáveis, fora da primeira camada.
    expect(screen.getByText("REPORT-1").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText(`SHA-256 ${"c".repeat(64)}`).closest("details")).not.toBeNull();
    expect(screen.getAllByRole("link", { name: "Baixar Word" })[0]).toHaveAttribute("href", expect.stringContaining("/delivery-snapshot/artifacts/"));
    expect(screen.getByRole("heading", { name: "Assinatura" })).toBeInTheDocument();
    expect(screen.getByText(/O sistema não assina o laudo/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /protocolar|pje|enviar ao tribunal/i })).not.toBeInTheDocument();
  });

  test("fails visibly stale and does not offer finalization", async () => {
    const stale = { ...snapshot, state: "STALE", stale_origin_state: "DELIVERED", stale_reasons: ["REPORT_DIGEST_CHANGED"] };
    const item = { revision: 6, updated_at: "2026-08-31T12:00:00Z", snapshot: stale };
    vi.stubGlobal("fetch", vi.fn((input) => Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [item] }) : response(200, item))));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Entrega desatualizada");
    expect(screen.queryByRole("button", { name: "Finalizar arquivos" })).not.toBeInTheDocument();
  });

  test("requires a private Word template when no delivery exists", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response(404, {}))));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Iniciar entrega" })).toBeInTheDocument();
    expect(screen.getByLabelText("Modelo Word (.docx ou .docm)")).toBeRequired();
    expect(screen.getByRole("button", { name: "Usar este modelo e iniciar" })).toBeDisabled();
  });

  const word = snapshot.artifacts[0];
  const pdf = { artifact_id: "ART-2", role: "DERIVED_PDF", format: "PDF", filename: "laudo.pdf", content_id: "44444444-4444-4444-8444-444444444444", media_type: "application/pdf", byte_size: 654, checksum_sha256: "d".repeat(64) };
  const draftWith = (artifacts: object[]) => ({ ...snapshot, state: "DRAFT", artifacts, package: { manifest_version: "1.0.0", artifact_ids: artifacts.map((item) => (item as { artifact_id: string }).artifact_id) } });
  const serve = (value: object) => {
    const item = { revision: 6, updated_at: "2026-08-31T12:00:00Z", snapshot: value };
    vi.stubGlobal("fetch", vi.fn((input) => Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [item] }) : response(200, item))));
  };

  test("offers Word rendering with a derived PDF and states which artifact is authoritative", async () => {
    serve(draftWith([]));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("button", { name: "Gerar Word e PDF" })).toBeEnabled();
    expect(screen.getByText(/O Word é gerado a partir do laudo aprovado e é o documento oficial/)).toBeInTheDocument();
    expect(screen.getByText(/só aparece depois de conferido/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Baixar PDF" })).not.toBeInTheDocument();
    expect(screen.queryByText(/conferido contra ele/)).not.toBeInTheDocument();
  });

  test("distinguishes the authoritative Word from the derived PDF and downloads the persisted artifacts", async () => {
    serve(draftWith([word, pdf]));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByText("Laudo em Word · documento oficial")).toBeInTheDocument();
    expect(screen.getByText("Laudo em PDF · derivado do Word")).toBeInTheDocument();
    expect(screen.getByText(/PDF gerado a partir do Word pelo Microsoft Word desta máquina e conferido contra ele/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Baixar PDF" })[0]).toHaveAttribute("href", expect.stringContaining(`/delivery-snapshot/artifacts/${pdf.content_id}`));
    expect(screen.getAllByRole("link", { name: "Baixar Word" })[0]).toHaveAttribute("href", expect.stringContaining(`/delivery-snapshot/artifacts/${word.content_id}`));
    expect(screen.getByRole("button", { name: "Gerar novamente Word e PDF" })).toBeEnabled();
  });

  test("reports an unavailable PDF as unavailable, never as success, and offers no PDF download", async () => {
    serve(draftWith([word]));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByText("Não foi possível gerar o PDF.")).toBeInTheDocument();
    expect(screen.getByText("O documento Word continua válido e pode ser baixado.")).toBeInTheDocument();
    expect(screen.queryByText(/conferido contra ele/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Baixar PDF" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Baixar Word" }).length).toBeGreaterThan(0);
    // Recuperação oferecida no próprio lugar: tentar de novo e ver os detalhes.
    expect(screen.getAllByRole("button", { name: "Tentar novamente" }).length).toBeGreaterThan(0);
    expect(screen.getByText("Ver detalhes")).toBeInTheDocument();
  });

  test("shows a busy render and an error, not success, when rendering fails", async () => {
    const item = { revision: 6, updated_at: "2026-08-31T12:00:00Z", snapshot: draftWith([]) };
    let fail: (value: Response) => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn((input, init) => {
      if (String(input).endsWith("/render") && (init as RequestInit | undefined)?.method === "POST") return new Promise<Response>((resolve) => { fail = resolve; });
      return Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [item] }) : response(200, item));
    }));
    render(<DeliveryFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Gerar Word e PDF" }));
    const busy = await screen.findByRole("button", { name: "Gerando Word e PDF…" });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    fail(response(503, {}));
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível gerar o Word desta entrega.");
    // A falha não apaga a tela: o contexto da entrega continua visível e recuperável.
    expect(screen.getByRole("heading", { name: "Entrega do laudo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeEnabled();
    await waitFor(() => expect(screen.queryByText(/conferido contra ele/)).not.toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "Baixar PDF" })).not.toBeInTheDocument();
  });

  test("blocks rendering while the delivery is stale", async () => {
    serve({ ...draftWith([word, pdf]), state: "STALE", stale_origin_state: "DRAFT", stale_reasons: ["REPORT_DIGEST_CHANGED"] });
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Entrega desatualizada");
    expect(screen.queryByRole("button", { name: /Gerar/ })).not.toBeInTheDocument();
  });
});
