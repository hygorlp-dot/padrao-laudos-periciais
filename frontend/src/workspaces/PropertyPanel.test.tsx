import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { PropertyPanel } from "./PropertyPanel";
import { getPropertyRecord, getPropertyProposals, savePropertyRecord } from "../data/propertyRecord";
vi.mock("../data/propertyRecord", async (original) => ({ ...await original<object>(), getPropertyRecord: vi.fn(), getPropertyProposals: vi.fn(), savePropertyRecord: vi.fn() }));
vi.mock("../data/siteLocation", async (original) => ({ ...await original<object>(), getSiteLocation: vi.fn().mockResolvedValue({ revision: 1, location: { state: "CONFIRMED", latitude: -12.5, longitude: -38.5 } }) }));
const record = { revision: 1, updated_at: null, record: { schema_version: "1.0.0" as const, workspace_id: "11111111-1111-4111-8111-111111111111", values: [{ field: "owner", value: "Proprietário confirmado", evidence: null, confirmed_by: "EXPERT-1", confirmed_at: "2026-09-28T12:00:00Z" }] }, fields: [{ field: "owner", label: "Proprietário do imóvel", kind: "text" as const }], stale_fields: [] as string[] };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(getPropertyRecord).mockResolvedValue(record); });
it("keeps confirmed values when extracting and requires an explicit choice before save", async () => {
  const evidence = { document_id: "d", document_sha256: "a".repeat(64), filename: "documento.pdf", page: 2, excerpt: "Proprietário: Outra pessoa", method: "LABEL_NATIVE_TEXT_V1", confidence: null, source_value: "Outra pessoa" };
  vi.mocked(getPropertyProposals).mockResolvedValue({ proposals: [{ proposal_id: "source-token", workspace_id: "11111111-1111-4111-8111-111111111111", field: "owner", value: "Outra pessoa", evidence, state: "CONFLICTING" }], pendingDocuments: [] });
  vi.mocked(savePropertyRecord).mockResolvedValue(record);
  render(<PropertyPanel workspaceId="11111111-1111-4111-8111-111111111111" />);
  fireEvent.click(screen.getByText("Imóvel"));
  const input = await screen.findByLabelText("Proprietário do imóvel");
  fireEvent.click(screen.getByRole("button", { name: "Buscar informações nos documentos" }));
  await screen.findByText("Outra pessoa");
  expect(input).toHaveValue("Proprietário confirmado");
  expect(savePropertyRecord).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Usar esta proposta" }));
  expect(input).toHaveValue("Outra pessoa");
  fireEvent.click(screen.getByRole("button", { name: "Confirmar dados do imóvel" }));
  await waitFor(() => expect(savePropertyRecord).toHaveBeenCalledWith("11111111-1111-4111-8111-111111111111", 1, [{ field: "owner", value: "Outra pessoa", proposal_id: "source-token" }]));
});
it("reuses the record as a read-only summary without writable duplicate fields", async () => {
  render(<PropertyPanel workspaceId="11111111-1111-4111-8111-111111111111" readOnly />);
  await screen.findByText("Proprietário confirmado");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirmar dados do imóvel" })).not.toBeInTheDocument();
});
it("keeps unsaved typing when the property panel is collapsed and reopened", async () => {
  render(<PropertyPanel workspaceId="11111111-1111-4111-8111-111111111111" />);
  fireEvent.click(screen.getByText("Imóvel"));
  const input = await screen.findByLabelText("Proprietário do imóvel");
  fireEvent.change(input, { target: { value: "Ainda em edição" } });
  fireEvent.click(screen.getByText("Imóvel"));
  fireEvent.click(screen.getByText("Imóvel"));
  await waitFor(() => expect(input).toHaveValue("Ainda em edição"));
  expect(getPropertyRecord).toHaveBeenCalledTimes(1);
  expect(screen.getByText("12,500000° S, 38,500000° O")).toBeInTheDocument();
});
it("flags a confirmed value whose source page the professional excluded, in both views, and only that field", async () => {
  const stale = { ...record, record: { ...record.record, values: [...record.record.values, { field: "street", value: "Rua manual", evidence: null, confirmed_by: "EXPERT-1", confirmed_at: "2026-09-28T12:00:00Z" }] }, fields: [...record.fields, { field: "street", label: "Logradouro", kind: "text" as const }], stale_fields: ["owner"] };
  vi.mocked(getPropertyRecord).mockResolvedValue(stale);
  const { unmount } = render(<PropertyPanel workspaceId="11111111-1111-4111-8111-111111111111" />);
  fireEvent.click(screen.getByText("Imóvel"));
  await screen.findByLabelText("Proprietário do imóvel");
  const alerts = screen.getAllByRole("alert");
  expect(alerts).toHaveLength(1);
  expect(alerts[0]).toHaveTextContent("A peça que sustentava este valor foi excluída da análise");
  unmount();
  render(<PropertyPanel workspaceId="11111111-1111-4111-8111-111111111111" readOnly />);
  await screen.findByText("Proprietário confirmado");
  expect(screen.getAllByText(/fonte excluída da análise/)).toHaveLength(1);
});
it("treats an envelope without the exclusion list as unavailable, not as 'nothing excluded'", async () => {
  const { getPropertyRecord: real } = await vi.importActual<typeof import("../data/propertyRecord")>("../data/propertyRecord");
  const legacy: Partial<typeof record> = { ...record };
  delete legacy.stale_fields;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(legacy), { status: 200, headers: { "Content-Type": "application/json" } })));
  await expect(real("11111111-1111-4111-8111-111111111111")).rejects.toMatchObject({ kind: "unavailable" });
  vi.unstubAllGlobals();
});
it("never claims the information is absent when nothing was proposed (#269)", async () => {
  vi.mocked(getPropertyProposals).mockResolvedValue({ proposals: [], pendingDocuments: ["anexo.pdf"] });
  render(<PropertyPanel workspaceId="11111111-1111-4111-8111-111111111111" />);
  fireEvent.click(screen.getByText("Imóvel"));
  await screen.findByLabelText("Proprietário do imóvel");
  fireEvent.click(screen.getByRole("button", { name: "Buscar informações nos documentos" }));
  expect(await screen.findByText(/Nenhuma proposta foi encontrada automaticamente. As informações ainda podem existir nos documentos/)).toBeInTheDocument();
  expect(screen.getByText(/Leitura em andamento: anexo.pdf/)).toBeInTheDocument();
  expect(screen.queryByText(/Não foram encontrados campos explícitos/)).not.toBeInTheDocument();
});
it("labels a weak contextual match as a possible information, never as a fact", async () => {
  const evidence = { document_id: "d", document_sha256: "a".repeat(64), filename: "contrato.pdf", page: 4, excerpt: "Endereço: Rua da Cláusula, nº 77", method: "DOCUMENT_PATTERN_NATIVE_TEXT_V2", confidence: null, source_value: "Rua da Cláusula" };
  vi.mocked(getPropertyProposals).mockResolvedValue({ proposals: [{ proposal_id: "weak", workspace_id: "11111111-1111-4111-8111-111111111111", field: "owner", value: "Rua da Cláusula", evidence, state: "PROPOSED", strength: "POSSIBLE" }], pendingDocuments: [] });
  render(<PropertyPanel workspaceId="11111111-1111-4111-8111-111111111111" />);
  fireEvent.click(screen.getByText("Imóvel"));
  await screen.findByLabelText("Proprietário do imóvel");
  fireEvent.click(screen.getByRole("button", { name: "Buscar informações nos documentos" }));
  expect(await screen.findByText("Possível informação encontrada — confira a fonte")).toBeInTheDocument();
  expect(savePropertyRecord).not.toHaveBeenCalled();
});
const WS = "11111111-1111-4111-8111-111111111111";
function proposal(id: string, value: string, filename: string, rank: string) {
  return { proposal_id: id, workspace_id: WS, field: "owner", value, state: "PROPOSED" as const, strength: "STRONG" as const, source_rank: rank, piece_id: null,
    evidence: { document_id: filename, document_sha256: "a".repeat(64), filename, page: 1, excerpt: `Proprietário: ${value}`, method: "LABEL_NATIVE_TEXT_V1", confidence: null, source_value: value } };
}
function cluster(id: string, items: ReturnType<typeof proposal>[], overrides: object = {}) {
  return { cluster_id: id, field: "owner", canonical_value: items[0].value, display_value: items[0].value, normalized_value: items[0].value.toLowerCase(),
    confidence: "HIGH" as const, strength: "STRONG" as const, best_rank: items[0].source_rank, source_count: items.length, document_count: items.length,
    evidences: items, conflicting_cluster_ids: [] as string[], ...overrides };
}
it("groups repeated values into one proposal with counts and saves the best evidence (#288)", async () => {
  const items = [proposal("p-contrato", "Fulana Sintética", "contrato.pdf", "B"), proposal("p-inicial", "FULANA SINTÉTICA", "inicial.pdf", "E")];
  vi.mocked(getPropertyProposals).mockResolvedValue({ proposals: items, clusters: [cluster("PVC-1", items)], pendingDocuments: [] });
  vi.mocked(savePropertyRecord).mockResolvedValue(record);
  render(<PropertyPanel workspaceId={WS} />);
  fireEvent.click(screen.getByText("Imóvel"));
  await screen.findByLabelText("Proprietário do imóvel");
  fireEvent.click(screen.getByRole("button", { name: "Buscar informações nos documentos" }));
  expect(await screen.findByText("2 ocorrências · 2 peças")).toBeInTheDocument();
  expect(screen.getByText(/Consistência documental: alta · melhor fonte: contrato/)).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Usar esta proposta" })).toHaveLength(1);
  expect(screen.queryByText(/Valores divergentes/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Usar esta proposta" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirmar dados do imóvel" }));
  await waitFor(() => expect(savePropertyRecord).toHaveBeenCalledWith(WS, 1, [{ field: "owner", value: "Fulana Sintética", proposal_id: "p-contrato" }]));
});
it("shows divergent values side by side and never picks one as the main proposal (#288)", async () => {
  const left = [proposal("p-a", "Fulana Sintética", "contrato.pdf", "B")];
  const right = [proposal("p-b", "Beltrana Sintética", "matricula.pdf", "A")];
  vi.mocked(getPropertyProposals).mockResolvedValue({ proposals: [...left, ...right], clusters: [
    cluster("PVC-B", right, { confidence: "MEDIUM", conflicting_cluster_ids: ["PVC-A"] }),
    cluster("PVC-A", left, { confidence: "MEDIUM", conflicting_cluster_ids: ["PVC-B"] }),
  ], pendingDocuments: [] });
  render(<PropertyPanel workspaceId={WS} />);
  fireEvent.click(screen.getByText("Imóvel"));
  await screen.findByLabelText("Proprietário do imóvel");
  fireEvent.click(screen.getByRole("button", { name: "Buscar informações nos documentos" }));
  const group = await screen.findByRole("group", { name: "Valores divergentes encontrados" });
  expect(group).toHaveTextContent("Fulana Sintética");
  expect(group).toHaveTextContent("Beltrana Sintética");
  expect(screen.queryByRole("button", { name: "Usar esta proposta" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Usar este valor" })).toHaveLength(2);
});
it("a possible-only value is never shown with high confidence and other values stay listed (#288)", async () => {
  const strong = [proposal("p-s", "Fulana Sintética", "contrato.pdf", "B")];
  const weak = [{ ...proposal("p-w", "Outra Pessoa", "despacho.pdf", "H"), strength: "POSSIBLE" as const }];
  vi.mocked(getPropertyProposals).mockResolvedValue({ proposals: [...strong, ...weak], clusters: [
    cluster("PVC-S", strong),
    cluster("PVC-W", weak, { confidence: "LOW", strength: "POSSIBLE" }),
  ], pendingDocuments: [] });
  render(<PropertyPanel workspaceId={WS} />);
  fireEvent.click(screen.getByText("Imóvel"));
  await screen.findByLabelText("Proprietário do imóvel");
  fireEvent.click(screen.getByRole("button", { name: "Buscar informações nos documentos" }));
  expect(await screen.findByText("Outros valores encontrados (1)")).toBeInTheDocument();
  expect(screen.getByText(/Consistência documental: baixa · melhor fonte: contexto possível/)).toBeInTheDocument();
});
