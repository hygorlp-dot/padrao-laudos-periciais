export type ShellRoute = {
  path: string;
  index: string;
  label: string;
  description: string;
  kind: "home" | "stage" | "missing";
  next?: {
    path: string;
    label: string;
  };
};

export type ResolvedRoute =
  | { kind: "directory"; pathname: "/"; workspaceId?: undefined; route: ShellRoute }
  | { kind: "workspace"; pathname: string; workspaceId: string; route: ShellRoute }
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
      "Um ponto de partida claro para acompanhar o trabalho pericial, etapa por etapa.",
    kind: "home",
  },
  {
    path: "/processo",
    index: "01",
    label: "Processo",
    description:
      "Ponto de entrada do fluxo. A identificação e o contexto do trabalho ocuparão esta etapa.",
    kind: "stage",
    next: { path: "/analise", label: "Análise" },
  },
  {
    path: "/analise",
    index: "02",
    label: "Análise",
    description:
      "A leitura inicial e a organização do material recebido ficarão reunidas aqui.",
    kind: "stage",
    next: { path: "/planejamento", label: "Planejamento" },
  },
  {
    path: "/planejamento",
    index: "03",
    label: "Planejamento",
    description:
      "A preparação técnica do trabalho terá uma etapa própria, antes da atividade de campo.",
    kind: "stage",
    next: { path: "/vistoria", label: "Vistoria" },
  },
  {
    path: "/vistoria",
    index: "04",
    label: "Vistoria",
    description:
      "O registro organizado da atividade de campo será apresentado neste espaço.",
    kind: "stage",
    next: { path: "/evidencias", label: "Evidências" },
  },
  {
    path: "/evidencias",
    index: "05",
    label: "Evidências",
    description:
      "As fontes e os materiais relacionados ao trabalho terão navegação dedicada nesta etapa.",
    kind: "stage",
    next: { path: "/constatacoes", label: "Constatações" },
  },
  {
    path: "/constatacoes",
    index: "06",
    label: "Constatações",
    description:
      "O que for efetivamente observado será organizado sem antecipar inferências ou conclusões.",
    kind: "stage",
    next: { path: "/analise-tecnica", label: "Análise técnica" },
  },
  {
    path: "/analise-tecnica",
    index: "07",
    label: "Análise técnica",
    description:
      "A etapa de raciocínio técnico permanecerá distinta do material observado e das conclusões.",
    kind: "stage",
    next: { path: "/laudo", label: "Laudo" },
  },
  {
    path: "/laudo",
    index: "08",
    label: "Laudo",
    description:
      "A composição do documento técnico terá seu próprio espaço no fluxo futuro.",
    kind: "stage",
    next: { path: "/revisao", label: "Revisão" },
  },
  {
    path: "/revisao",
    index: "09",
    label: "Revisão",
    description:
      "A conferência final será tratada como etapa explícita antes de qualquer exportação.",
    kind: "stage",
    next: { path: "/exportar", label: "Exportar" },
  },
  {
    path: "/exportar",
    index: "10",
    label: "Exportar",
    description:
      "A saída do trabalho ficará separada da elaboração e dependerá de um fluxo posterior.",
    kind: "stage",
  },
];

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

export function resolveRoute(pathname: string): ResolvedRoute {
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
