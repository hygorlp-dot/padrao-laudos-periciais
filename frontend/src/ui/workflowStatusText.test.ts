import { describe, expect, test } from "vitest";

import type { WorkflowStageState, WorkflowStatus } from "../data/workflowStatus";
import { WORKFLOW_ROUTES } from "../routes/routeCatalog";
import { attentionItems, nextAction, reasonText, stageDescription, stageReasonsText, stagesFromCatalog } from "./workflowStatusText";

const ID = "11111111-1111-4111-8111-111111111111";
const STAGE_KEYS = WORKFLOW_ROUTES.filter((route) => route.kind === "stage").map((route) => route.path.slice(1));

function status(states: Partial<Record<string, WorkflowStageState>>, fallback: WorkflowStageState = "RECORDED"): WorkflowStatus {
  return {
    workspaceId: ID,
    stages: STAGE_KEYS.map((stage) => ({
      stage, state: states[stage] ?? fallback, availability: states[stage] === "UNAVAILABLE" ? "UNAVAILABLE" : "AVAILABLE",
      currency: states[stage] === "REVIEW_REQUIRED" ? "STALE" : "NOT_EVALUATED", decision: "NONE", reasons: [],
      revision: 1, updated_at: null,
    })),
  };
}

describe("workflow status rules shown to the expert", () => {
  test("stages come from the real catalog, in catalog order, without fixed counts", () => {
    const stages = stagesFromCatalog(status({}));
    expect(stages.map((item) => item.route.path.slice(1))).toEqual(STAGE_KEYS);
  });

  test("a catalog stage missing from the answer is unverified, never complete", () => {
    const partial = status({});
    partial.stages = partial.stages.filter((item) => item.stage !== "vistoria");
    const vistoria = stagesFromCatalog(partial).find((item) => item.status.stage === "vistoria");
    expect(vistoria?.status.state).toBe("UNAVAILABLE");
  });

  test("next action is the first technical stage with something to do; management is never imposed", () => {
    const stages = stagesFromCatalog(status({ laudo: "IN_PROGRESS", orcamento: "NOT_STARTED" }));
    expect(nextAction(stages)?.route.label).toBe("Laudo");

    const onlyManagement = stagesFromCatalog(status({ orcamento: "NOT_STARTED" }));
    expect(nextAction(onlyManagement)).toBeUndefined();
  });

  test.each(["REVIEW_REQUIRED", "UNAVAILABLE", "AWAITING_REVIEW", "ATTENTION", "PROCESSING", "NOT_STARTED"] as const)(
    "a stage in %s is never treated as settled", (state) => {
      const stages = stagesFromCatalog(status({ laudo: state }));
      expect(nextAction(stages)?.route.label).toBe("Laudo");
    },
  );

  test("attention is ordered by severity, then catalog order", () => {
    const stages = stagesFromCatalog(status({
      materiais: "PROCESSING", analise: "AWAITING_REVIEW", planejamento: "REVIEW_REQUIRED", laudo: "UNAVAILABLE", exportar: "ATTENTION",
    }));
    // Processando não pede decisão: fica fora da lista de atenção.
    expect(attentionItems(stages).map((item) => item.route.label)).toEqual([
      "Laudo", "Exportar", "Planejamento", "Análise",
    ]);
  });

  test("a historical approval over a changed base is never read as current", () => {
    const [laudo] = stagesFromCatalog(status({ laudo: "REVIEW_REQUIRED" })).filter((item) => item.route.label === "Laudo");
    const stale = { ...laudo.status, reasons: [{ code: "UPSTREAM_CHANGED", count: 2 }, { code: "REPORT_APPROVED" }] };
    expect(stageReasonsText(stale)).toEqual(["Uma etapa anterior mudou depois deste registro", "Antes da mudança: laudo aprovado"]);
    expect(stageReasonsText({ ...stale, currency: "CURRENT", state: "APPROVED" })[1]).toBe("Laudo aprovado");
  });

  test("reasons are translated with counts; unknown codes stay generic", () => {
    expect(reasonText({ code: "ITEMS_AWAITING_REVIEW", count: 1 })).toBe("1 item aguarda sua decisão");
    expect(reasonText({ code: "ITEMS_AWAITING_REVIEW", count: 16 })).toBe("16 itens aguardam sua decisão");
    expect(reasonText({ code: "PDF_ABSENT" })).toMatch(/entrega parcial/);
    expect(reasonText({ code: "GATE_BLOQUEADO_PARA_REDACAO" })).toBe("Situação para redação: bloqueado para redação");
    expect(reasonText({ code: "FINANCIAL_PARTIALLY_RECEIVED" })).toBe("Orçamento recebido em parte");
    expect(reasonText({ code: "SOMETHING_NEW" })).toBe("Outro detalhe registrado");
  });

  test("descriptions never claim completion or percentages", () => {
    for (const state of ["RECORDED", "READY", "NOT_STARTED", "IN_PROGRESS"] as const) {
      const text = stageDescription({ ...status({})["stages"][0], state });
      expect(text).not.toMatch(/conclu|%|score|pontua/i);
    }
  });
});
