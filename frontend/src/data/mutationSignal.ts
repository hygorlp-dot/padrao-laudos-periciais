// Sinal de gravação concluída numa perícia (#291).
//
// A situação do fluxo é uma leitura do backend; depois que uma etapa grava
// algo, a navegação não pode continuar mostrando a situação de antes (por
// exemplo, "Laudo aprovado" logo depois de alterar a análise). Este observador
// só OLHA as respostas: não altera pedidos, não cria rotas, não guarda nada.

export const WORKSPACE_MUTATED = "pericial:workspace-mutated";

const WORKSPACE_PATH = /^\/app-api\/v1\/workspaces\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\//;
const MARK = Symbol.for("pericial.mutationSignal");

type Fetcher = typeof globalThis.fetch;

export function mutatedWorkspace(input: RequestInfo | URL, init: RequestInit | undefined, base: string): string | null {
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  if (method === "GET" || method === "HEAD") return null;
  const raw = input instanceof Request ? input.url : String(input);
  let url: URL;
  try {
    url = new URL(raw, base);
  } catch {
    return null;
  }
  if (url.origin !== new URL(base).origin) return null;
  return WORKSPACE_PATH.exec(url.pathname)?.[1] ?? null;
}

export function installMutationSignal(target: Window = window) {
  const current = target.fetch as Fetcher & { [MARK]?: true };
  if (current[MARK]) return;
  const original = current.bind(target);
  const observed = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await original(input, init);
    const workspaceId = response.ok ? mutatedWorkspace(input, init, target.location.href) : null;
    if (workspaceId) target.dispatchEvent(new CustomEvent(WORKSPACE_MUTATED, { detail: workspaceId }));
    return response;
  }) as Fetcher & { [MARK]?: true };
  observed[MARK] = true;
  target.fetch = observed;
}
