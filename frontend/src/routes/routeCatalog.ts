export type ShellRoute = {
  path: string;
  index: string;
  label: string;
  description: string;
  kind: "home" | "stage" | "missing";
  group?: WorkflowGroup;
  next?: {
    path: string;
    label: string;
  };
};

// Agrupamento apenas visual do trilho; as rotas e a sequência não mudam.
export type WorkflowGroup = "Processo" | "Perícia" | "Laudo" | "Gestão";

export type ResolvedRoute =
  | { kind: "directory"; pathname: "/"; workspaceId?: undefined; route: ShellRoute }
  | { kind: "workspace"; pathname: string; workspaceId: string; route: ShellRoute }
  // A recuperação existe FORA de qualquer perícia: base vazia é o cenário dela.
  | { kind: "recovery"; pathname: "/recuperacao"; workspaceId?: undefined; route: ShellRoute }
  | { kind: "missing"; pathname: string };

const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export const DIRECTORY_ROUTE: ShellRoute = {
  path: "/",
  index: "00",
  label: "Perícias",
  description:
    "Abra uma perícia técnica existente ou inicie um novo workspace local.",
  kind: "home",
};

export const WORKFLOW_ROUTES: readonly ShellRoute[] = [
  {
    path: "/",
    index: "00",
    label: "Início",
    description:
      "Acompanhe a perícia etapa por etapa e retome o trabalho de onde parou.",
    kind: "home",
  },
  {
    path: "/processo",
    index: "01",
    label: "Processo",
    description:
      "Registre a identificação processual básica vinculada a esta perícia.",
    kind: "stage",
    group: "Processo",
    next: { path: "/materiais", label: "Materiais" },
  },
  {
    path: "/materiais",
    index: "02",
    label: "Materiais",
    description:
      "Importe e consulte os documentos recebidos sem expor o armazenamento privado.",
    kind: "stage",
    group: "Processo",
    next: { path: "/analise", label: "Análise" },
  },
  {
    path: "/analise",
    index: "03",
    label: "Análise",
    description:
      "Organize partes, alegações, quesitos e documentos a partir dos autos, com a fonte de cada item.",
    kind: "stage",
    group: "Processo",
    next: { path: "/planejamento", label: "Planejamento" },
  },
  {
    path: "/planejamento",
    index: "04",
    label: "Planejamento",
    description:
      "Defina o objeto, as questões materiais e o que verificar em campo antes da vistoria.",
    kind: "stage",
    group: "Perícia",
    next: { path: "/vistoria", label: "Vistoria" },
  },
  {
    path: "/vistoria",
    index: "05",
    label: "Vistoria",
    description:
      "Registre observações, medições, fotografias e declarações da atividade de campo.",
    kind: "stage",
    group: "Perícia",
    next: { path: "/evidencias", label: "Evidências" },
  },
  {
    path: "/evidencias",
    index: "06",
    label: "Evidências",
    description:
      "Revise as evidências, escolha o método e decida sobre cada proposta técnica.",
    kind: "stage",
    group: "Perícia",
    next: { path: "/constatacoes", label: "Constatações" },
  },
  {
    path: "/constatacoes",
    index: "07",
    label: "Constatações",
    description:
      "Consulte os achados técnicos efetivos, cada um com sua evidência, método e decisão.",
    kind: "stage",
    group: "Perícia",
    next: { path: "/analise-tecnica", label: "Análise técnica" },
  },
  {
    path: "/analise-tecnica",
    index: "08",
    label: "Análise técnica",
    description:
      "Analise as manifestações construtivas e registre a decisão profissional sobre cada uma.",
    kind: "stage",
    group: "Perícia",
    next: { path: "/laudo", label: "Laudo" },
  },
  {
    path: "/laudo",
    index: "09",
    label: "Laudo",
    description:
      "Componha e revise o laudo técnico antes da entrega.",
    kind: "stage",
    group: "Laudo",
    next: { path: "/revisao", label: "Revisão" },
  },
  {
    path: "/revisao",
    index: "10",
    label: "Revisão",
    description:
      "Confira a completude do laudo e registre a revisão profissional antes da entrega.",
    kind: "stage",
    group: "Laudo",
    next: { path: "/exportar", label: "Exportar" },
  },
  {
    path: "/exportar",
    index: "11",
    label: "Exportar",
    description:
      "Gere o Word do laudo, obtenha o PDF derivado e registre a entrega.",
    kind: "stage",
    group: "Laudo",
    next: { path: "/orcamento", label: "Orçamento" },
  },
  {
    path: "/orcamento",
    index: "12",
    label: "Orçamento",
    description:
      "Controle propostas, decisões judiciais, despesas e recebimentos desta perícia.",
    kind: "stage",
    group: "Gestão",
    next: { path: "/recuperacao", label: "Recuperação" },
  },
  {
    path: "/recuperacao",
    index: "13",
    label: "Recuperação",
    description:
      "Gere um backup desta perícia e restaure a partir de um pacote, com promoção explícita.",
    kind: "stage",
    group: "Gestão",
  },
];

// Total derivado da estrutura canônica: nenhuma contagem escrita à mão.
export const WORKFLOW_STAGE_COUNT = WORKFLOW_ROUTES.filter((route) => route.kind === "stage").length;

export function findRoute(pathname: string) {
  return WORKFLOW_ROUTES.find((route) => route.path === pathname);
}

export function workspacePath(workspaceId: string, stage?: string) {
  if (!CANONICAL_UUID.test(workspaceId)) {
    throw new Error("workspace identity is not canonical");
  }
  if (stage === undefined) {
    return `/pericias/${workspaceId}`;
  }
  const route = WORKFLOW_ROUTES.find(
    (candidate) => candidate.kind === "stage" && candidate.path === `/${stage}`,
  );
  if (!route) {
    throw new Error("workspace stage is not canonical");
  }
  return `/pericias/${workspaceId}/${stage}`;
}

export const RECOVERY_ROUTE: ShellRoute = {
  path: "/recuperacao",
  index: "00",
  label: "Recuperação",
  description:
    "Restaure uma perícia a partir de um pacote de backup, com promoção explícita.",
  kind: "home",
};

export function resolveRoute(pathname: string): ResolvedRoute {
  if (pathname === "/recuperacao") {
    // Máquina nova, disco trocado, banco perdido: não há perícia de onde
    // partir. Amarrar a restauração a uma perícia existente a tornaria
    // inalcançável exatamente quando ela é necessária.
    return {
      kind: "recovery",
      pathname: "/recuperacao",
      workspaceId: undefined,
      route: RECOVERY_ROUTE,
    };
  }
  if (pathname === "/") {
    return {
      kind: "directory",
      pathname: "/",
      workspaceId: undefined,
      route: DIRECTORY_ROUTE,
    };
  }

  const segments = pathname.split("/");
  if (
    segments[0] !== "" ||
    segments[1] !== "pericias" ||
    !CANONICAL_UUID.test(segments[2] ?? "")
  ) {
    return { kind: "missing", pathname };
  }
  const workspaceId = segments[2];
  if (segments.length === 3) {
    return {
      kind: "workspace",
      pathname,
      workspaceId,
      route: WORKFLOW_ROUTES[0],
    };
  }
  if (segments.length === 4) {
    const route = WORKFLOW_ROUTES.find(
      (candidate) =>
        candidate.kind === "stage" && candidate.path === `/${segments[3]}`,
    );
    if (route) {
      return { kind: "workspace", pathname, workspaceId, route };
    }
  }
  return { kind: "missing", pathname };
}
