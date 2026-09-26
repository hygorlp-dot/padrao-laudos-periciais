import { describe, expect, test } from "vitest";

import { WORKFLOW_ROUTES, WORKFLOW_STAGE_COUNT } from "../routes/routeCatalog";
import { actionLabel, authorityLabel, plural, roleLabel, stateLabel } from "./labels";

describe("first-layer labels", () => {
  test("translates lifecycle states into the expert's language", () => {
    expect(stateLabel("DRAFT")).toBe("Em elaboração");
    expect(stateLabel("READY_FOR_REVIEW")).toBe("Pronto para revisão");
    expect(stateLabel("REVIEWED")).toBe("Revisado");
    expect(stateLabel("APPROVED")).toBe("Aprovado");
    expect(stateLabel("FINALIZED")).toBe("Finalizado");
    expect(stateLabel("DELIVERED")).toBe("Entregue");
    expect(stateLabel("STALE")).toBe("Desatualizado");
    expect(stateLabel("SUPERSEDED")).toBe("Substituído");
  });

  test("never shows an unknown code as raw upper case", () => {
    expect(stateLabel("SOME_NEW_STATE")).toBe("Some new state");
    expect(stateLabel(null)).toBe("Não informado");
    expect(authorityLabel("AI_PROPOSAL")).toBe("Proposta automática");
    expect(actionLabel("APPROVE")).toBe("Aprovado");
    expect(roleLabel("PASSIVE")).toBe("Polo passivo");
  });

  test("pluralizes counts", () => {
    expect(plural(1, "revisão", "revisões")).toBe("1 revisão");
    expect(plural(3, "revisão", "revisões")).toBe("3 revisões");
  });
});

describe("route catalog", () => {
  test("derives the stage total from the canonical structure", () => {
    expect(WORKFLOW_STAGE_COUNT).toBe(WORKFLOW_ROUTES.filter((route) => route.kind === "stage").length);
    expect(WORKFLOW_STAGE_COUNT).toBe(13);
  });

  test("describes working stages in the present tense", () => {
    for (const route of WORKFLOW_ROUTES) {
      expect(route.description).not.toMatch(/\b(terá|terão|ficará|ficarão|será|serão|permanecerá)\b|futur/i);
    }
  });

  test("assigns every stage to one sidebar group without changing routes", () => {
    const stages = WORKFLOW_ROUTES.filter((route) => route.kind === "stage");
    expect(stages.every((route) => route.group !== undefined)).toBe(true);
    expect(stages.filter((route) => route.group === "Processo").map((route) => route.label)).toEqual(["Processo", "Materiais", "Análise"]);
    expect(stages.filter((route) => route.group === "Perícia").map((route) => route.label)).toEqual(["Planejamento", "Vistoria", "Evidências", "Constatações", "Análise técnica"]);
    expect(stages.filter((route) => route.group === "Laudo").map((route) => route.label)).toEqual(["Laudo", "Revisão", "Exportar"]);
    expect(stages.filter((route) => route.group === "Gestão").map((route) => route.label)).toEqual(["Orçamento", "Recuperação"]);
  });
});
