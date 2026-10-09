# SKILL_ROUTING_V3

O roteamento seleciona o conjunto mínimo de Skills; não instala, executa,
carrega código, acessa rede, altera egress nem decide domínio ou merge.

Precedência: `AGENTS.md > FIRST_PARTY_SKILL > APPROVED_PRODUCT_PRINCIPLE >
PINNED_THIRD_PARTY_SKILL`. O manifesto `.agents/skill-router.json` é pequeno,
declarativo e validado por schema. Contexto material desconhecido falha com
`UNMAPPED_SKILL_CONTEXT`; nunca carrega todas as Skills por conveniência.
`repository_mutation` é distinto de claims periciais materiais e de reviews
read-only. Toda mutação de repositório é material para o roteador, exige profile
mapeado e herda o bundle obrigatório de engenharia.

As famílias F1–F6 permanecem as definidas no SKILL_ROUTING_V2. Skills de
review terminal só entram por condição explícita e `using-superpowers`,
`claim-audit` e `proposition-audit` permanecem referências subordinadas.

`NEW_SKILL_REQUIRED = 0`; não há novo MCP, plugin, provider ou trust plane.

## Skills pinadas da PROFESSIONAL_UX_V1 (#276)

| Categoria | Skill | Rota |
|---|---|---|
| Descoberta de produto/UX | `brainstorming` | `engineering`/`ui` → `product_discovery` |
| Fluxo de engenharia | `using-git-worktrees`, `dispatching-parallel-agents`, `subagent-driven-development`, `finishing-a-development-branch` | `engineering` → `isolated_workspace`, `parallel_independent_tasks`, `subagent_plan_execution`, `branch_completion` |
| Performance React | `vercel-react-best-practices` | `ui` → `react_performance` |
| Composição | `vercel-composition-patterns` | `ui` → `component_composition` |
| QA de navegador | `playwright-cli` | `ui` → `browser_qa` (sem nova dependência do produto) |
| Descoberta de Skills | `find-skills` | `reference_only` (rede negada por padrão) |
| Diretrizes de interface | `web-design-guidelines` | `reference_only` (regras remotas; rede negada por padrão) |

Nenhuma delas entra no perfil por padrão: o conjunto mínimo continua o do
profile, e cada Skill só é selecionada pela condição explícita.

