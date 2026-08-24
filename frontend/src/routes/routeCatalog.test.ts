import { describe, expect, test } from "vitest";

import { resolveRoute, workspacePath } from "./routeCatalog";

const ID = "11111111-1111-4111-8111-111111111111";

describe("workspace route catalog", () => {
  test("keeps the directory at the root without an implicit workspace", () => {
    expect(resolveRoute("/")).toMatchObject({ kind: "directory", workspaceId: undefined });
  });

  test("resolves workspace home and stage with identity carried by the URL", () => {
    expect(resolveRoute(`/pericias/${ID}`)).toMatchObject({
      kind: "workspace",
      workspaceId: ID,
      route: { kind: "home", label: "Início" },
    });
    expect(resolveRoute(`/pericias/${ID}/vistoria`)).toMatchObject({
      kind: "workspace",
      workspaceId: ID,
      route: { kind: "stage", label: "Vistoria" },
    });
  });

  test.each([
    "/pericias/not-a-uuid",
    `/pericias/${ID}/etapa-inexistente`,
    `/pericias/${ID}/vistoria/extra`,
    "/vistoria",
  ])("fails closed for an ambiguous route %s", (path) => {
    expect(resolveRoute(path)).toEqual({ kind: "missing", pathname: path });
  });

  test("builds canonical links without losing the active workspace", () => {
    expect(workspacePath(ID)).toBe(`/pericias/${ID}`);
    expect(workspacePath(ID, "vistoria")).toBe(`/pericias/${ID}/vistoria`);
    expect(() => workspacePath("NOT-A-UUID", "vistoria")).toThrow(/workspace/i);
  });
});
