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
    expect(await screen.findByRole("heading", { name: "Entrega e integridade" })).toBeInTheDocument();
    expect(screen.getByText("DELIVERED")).toBeInTheDocument();
    expect(screen.getByText(/REPORT-1 · revisão 5/)).toBeInTheDocument();
    expect(screen.getByText("c".repeat(64))).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Baixar laudo.docm" })[0]).toHaveAttribute("href", expect.stringContaining("/delivery-snapshot/artifacts/"));
    expect(screen.queryByRole("button", { name: /protocolar|pje|enviar ao tribunal/i })).not.toBeInTheDocument();
  });

  test("fails visibly stale and does not offer finalization", async () => {
    const stale = { ...snapshot, state: "STALE", stale_origin_state: "DELIVERED", stale_reasons: ["REPORT_DIGEST_CHANGED"] };
    const item = { revision: 6, updated_at: "2026-08-31T12:00:00Z", snapshot: stale };
    vi.stubGlobal("fetch", vi.fn((input) => Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [item] }) : response(200, item))));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Entrega desatualizada");
    expect(screen.queryByRole("button", { name: "Finalizar artefatos" })).not.toBeInTheDocument();
  });

  test("requires a private Word template when no delivery exists", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response(404, {}))));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Iniciar entrega" })).toBeInTheDocument();
    expect(screen.getByLabelText("Template Word privado")).toBeRequired();
    expect(screen.getByRole("button", { name: "Preservar template e iniciar" })).toBeDisabled();
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
    expect(await screen.findByRole("button", { name: "Renderizar Word e PDF derivado" })).toBeEnabled();
    expect(screen.getByText(/Word\/DOCM é o artefato profissional autoritativo/)).toBeInTheDocument();
    expect(screen.getByText(/só aparece no pacote depois de convertido e validado/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /\.pdf$/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/PDF derivado do Word pelo Microsoft Word local/)).not.toBeInTheDocument();
  });

  test("distinguishes the authoritative Word from the derived PDF and downloads the persisted artifacts", async () => {
    serve(draftWith([word, pdf]));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByText(/Word autoritativo · DOCM/)).toBeInTheDocument();
    expect(screen.getByText(/PDF derivado · não autoritativo · PDF/)).toBeInTheDocument();
    expect(screen.getByText(/PDF derivado do Word pelo Microsoft Word local, convertido e validado/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Baixar laudo.pdf" })[0]).toHaveAttribute("href", expect.stringContaining(`/delivery-snapshot/artifacts/${pdf.content_id}`));
    expect(screen.getAllByRole("link", { name: "Baixar laudo.docm" })[0]).toHaveAttribute("href", expect.stringContaining(`/delivery-snapshot/artifacts/${word.content_id}`));
    expect(screen.getByRole("button", { name: "Renderizar novamente Word e PDF derivado" })).toBeEnabled();
  });

  test("reports an unavailable PDF as unavailable, never as success, and offers no PDF download", async () => {
    serve(draftWith([word]));
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByText(/PDF derivado indisponível nesta renderização/)).toBeInTheDocument();
    expect(screen.getByText(/o Word\/DOCM autoritativo continua válido/)).toBeInTheDocument();
    expect(screen.queryByText(/convertido e validado\. O Word/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /\.pdf$/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Baixar laudo.docm" }).length).toBeGreaterThan(0);
  });

  test("shows a busy render and an error, not success, when rendering fails", async () => {
    const item = { revision: 6, updated_at: "2026-08-31T12:00:00Z", snapshot: draftWith([]) };
    let fail: (value: Response) => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn((input, init) => {
      if (String(input).endsWith("/render") && (init as RequestInit | undefined)?.method === "POST") return new Promise<Response>((resolve) => { fail = resolve; });
      return Promise.resolve(String(input).endsWith("/history") ? response(200, { items: [item] }) : response(200, item));
    }));
    render(<DeliveryFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Renderizar Word e PDF derivado" }));
    const busy = await screen.findByRole("button", { name: "Renderizando Word e PDF derivado…" });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    fail(response(503, {}));
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível abrir a entrega");
    await waitFor(() => expect(screen.queryByText(/convertido e validado/)).not.toBeInTheDocument());
    expect(screen.queryByRole("link", { name: /\.pdf$/ })).not.toBeInTheDocument();
  });

  test("blocks rendering while the delivery is stale", async () => {
    serve({ ...draftWith([word, pdf]), state: "STALE", stale_origin_state: "DRAFT", stale_reasons: ["REPORT_DIGEST_CHANGED"] });
    render(<DeliveryFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Entrega desatualizada");
    expect(screen.queryByRole("button", { name: /Renderizar/ })).not.toBeInTheDocument();
  });
});
