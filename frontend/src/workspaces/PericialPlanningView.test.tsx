import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { PericialPlanningView } from "./PericialPlanningView";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const provenance = [{ workspace_id: WORKSPACE_ID, source_document_id: "DOC-001", source_document_sha256: "a".repeat(64), page_or_span: "p. 3", source_revision: 4, occurrence_id: "OCC-001" }];
const derivation = { rationale: "Derivado do objeto e do quesito pertinentes.", case_analysis_item_ids: ["OBJECT-001"], source_provenance: provenance, question_ids: [], pericial_object_ids: ["OBJECT-001"], court_decision_ids: [], technical_document_reference_ids: [], gap_or_conflict_ids: [] };
const item = (item_id: string, title: string) => ({ item_id, title, description: `${title} como proposta profissionalmente revisável.`, priority: "HIGH", derivation, proposal_status: "PROPOSED", professional_review_status: "PENDING" });
const SNAPSHOT = {
  schema_version: "1.0.0", snapshot_id: "PLANNING-SNAPSHOT-001", workspace_id: WORKSPACE_ID,
  plan: { plan_id: "PERICIAL-PLAN-001", title: "Plano sintético", workspace_id: WORKSPACE_ID, case_analysis_snapshot_id: "ANALYSIS-001", case_analysis_revision: 1, case_analysis_source_revision: 4, case_analysis_digest: "d".repeat(64) },
  objectives: [item("PLAN-OBJECTIVE-001", "Preparar o exame")],
  issues: [item("PLAN-ISSUE-001", "Controvérsia documental")],
  question_links: [{ ...item("PLAN-QUESTION-001", "Quesito orientador"), question_id: "QUESTION-001", linked_item_ids: ["PLAN-DOCUMENT-001"], dependency_item_ids: [] }],
  required_documents: [{ ...item("PLAN-DOCUMENT-001", "Documento necessário"), document_description: "Anexo", required_before: "INSPECTION" }],
  required_information: [{ ...item("PLAN-INFORMATION-001", "Informação necessária"), information_description: "Acesso", requested_from: "Responsável" }],
  inspection_requirements: [{ ...item("PLAN-INSPECTION-001", "Item de inspeção"), inspection_target: "Objeto", field_observations_needed: ["Condição aparente"] }],
  measurement_requirements: [{ ...item("PLAN-MEASUREMENT-001", "Medição proposta"), quantity: "dimensão", unit: "mm", purpose: "Análise posterior" }],
  photo_requirements: [{ ...item("PLAN-PHOTO-001", "Fotografia proposta"), subject: "Objeto", purpose: "Contexto futuro" }],
  equipment_requirements: [{ ...item("PLAN-EQUIPMENT-001", "Equipamento candidato"), equipment: "Instrumento", purpose: "Medição futura" }],
  access_requirements: [{ ...item("PLAN-ACCESS-001", "Acesso necessário"), access_type: "PHYSICAL", target: "Local", responsible_contact: "A definir" }],
  method_candidates: [{ ...item("PLAN-METHOD-001", "Método candidato"), method_name: "Método dimensional", purpose: "Obter dado", applicability_rationale: "Sujeito a revisão", required_inputs: ["Acesso"], limitations: ["Não conclui"], normative_references: [] }],
  procedure_candidates: [{ ...item("PLAN-PROCEDURE-001", "Procedimento candidato"), procedure_name: "Sequência", purpose: "Organizar", planned_steps: ["Preparar"], limitations: ["Sujeito ao campo"] }],
  sampling_candidates: [{ ...item("PLAN-SAMPLING-001", "Amostragem candidata"), population: "Elementos", candidate_strategy: "A definir", limitations: ["Não adotada"] }],
  safety_requirements: [{ ...item("PLAN-SAFETY-001", "Segurança"), hazard: "Condição desconhecida", precaution: "Avaliar antes" }],
  external_support_requirements: [{ ...item("PLAN-SUPPORT-001", "Apoio externo"), support_type: "A definir", purpose: "Viabilizar" }],
  risks: [{ ...item("PLAN-RISK-001", "Risco documental"), risk: "Fonte ausente", mitigation: "Solicitar" }],
  gaps: [{ ...item("PLAN-GAP-001", "Lacuna documental"), gap: "Anexo ausente", consequence: "Revisar plano" }],
  decisions: [],
  coverage: { material_items_total: 17, reviewed_items: 0, pending_items: 17, approved_items: 0, rejected_items: 0, modified_items: 0, deferred_items: 0, readiness: "PARTIAL", readiness_reasons: ["Itens aguardam revisão profissional."] },
  upstream_stale: false, upstream_stale_reasons: [],
};

function response(status: number, value: object) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json; charset=utf-8" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("pericial planning view", () => {
  test("presents readiness, preparation groups and exact derivation without findings", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { revision: 1, updated_at: "2026-08-30T19:00:00-03:00", snapshot: SNAPSHOT })));

    render(<PericialPlanningView workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByRole("heading", { name: "Plano da perícia" })).toBeInTheDocument();
    expect(screen.getByText("Planejamento parcial")).toBeInTheDocument();
    for (const heading of ["Objeto e questões", "Documentos e informações", "Vistoria", "Medições e fotografias", "Equipamentos e métodos", "Acesso, apoio e segurança", "Lacunas e riscos", "Decisões profissionais"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Derivado do objeto e do quesito pertinentes.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Objetos periciais: OBJECT-001").length).toBeGreaterThan(0);
    expect(screen.getByText("Método proposto — não aprovado")).toBeInTheDocument();
    expect(screen.queryByText(/constatação técnica|resposta ao quesito|conclusão pericial/i)).not.toBeInTheDocument();
  });

  test("shows an honest empty state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(404, { error: { code: "ARTIFACT_REVISION_NOT_FOUND" } })));
    render(<PericialPlanningView workspaceId={WORKSPACE_ID} />);
    expect(await screen.findByRole("heading", { name: "Planejamento ainda não disponível" })).toBeInTheDocument();
  });

  test("starts proposal-only planning from reviewed analysis", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(404, { error: { code: "ARTIFACT_REVISION_NOT_FOUND" } }))
      .mockResolvedValueOnce(response(201, { revision: 1, updated_at: "2026-08-31T12:00:00+00:00", snapshot: SNAPSHOT }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<PericialPlanningView workspaceId={WORKSPACE_ID} />);
    await user.click(await screen.findByRole("button", { name: "Iniciar planejamento" }));
    await screen.findByRole("heading", { name: "Plano da perícia" });
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({ title: "Plano da perícia" });
  });

  test("returns focus to the originating review action after cancel", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { revision: 1, updated_at: "2026-08-30T19:00:00-03:00", snapshot: SNAPSHOT })));
    const user = userEvent.setup();
    render(<PericialPlanningView workspaceId={WORKSPACE_ID} />);
    const trigger = await screen.findByRole("button", { name: "Revisar Controvérsia documental" });

    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(trigger).toHaveFocus();
  });

  test("sends explicit professional identity, reason and modification", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(200, { revision: 1, updated_at: "2026-08-30T19:00:00-03:00", snapshot: SNAPSHOT }))
      .mockResolvedValueOnce(response(200, { revision: 2, updated_at: "2026-08-30T19:05:00-03:00", snapshot: SNAPSHOT }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<PericialPlanningView workspaceId={WORKSPACE_ID} />);
    await screen.findByRole("heading", { name: "Plano da perícia" });

    await user.click(screen.getByRole("button", { name: "Revisar Controvérsia documental" }));
    expect(screen.getByLabelText("Identificação do perito")).toHaveFocus();
    await user.selectOptions(screen.getByLabelText("Decisão profissional"), "MODIFY");
    await user.type(screen.getByLabelText("Identificação do perito"), "PERITO-SYNTHETIC");
    await user.type(screen.getByLabelText("Motivo da decisão"), "Ajuste profissional explícito.");
    await user.type(screen.getByLabelText("Texto modificado"), "Controvérsia será verificada documentalmente.");
    await user.click(screen.getByRole("button", { name: "Registrar decisão" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      expected_revision: 1, target_item_id: "PLAN-ISSUE-001", action: "MODIFY",
      reviewer: "PERITO-SYNTHETIC", reason: "Ajuste profissional explícito.",
      decided_value: "Controvérsia será verificada documentalmente.",
    });
  });
});
