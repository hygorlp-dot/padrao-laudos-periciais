# Padrão de governança de desenvolvimento

## Regra aprovada

Toda correção, melhoria, nova função, refatoração material, integração ou
alteração de infraestrutura deve seguir:

`Issue → Branch → Implementação → Testes → Auditoria → Commit → Push da branch → Pull Request → CI → Review → Merge → Build/Deploy/Release, quando aplicável`.

`main` é estável. Desenvolvimento direto em `main` é proibido, salvo exceção
emergencial expressa; mesmo nesse caso, criar Issue retrospectiva antes de
merge ou release.

Depois que o usuário autoriza expressamente um objetivo de engenharia, item
de roadmap ou Issue existente, esta sequência inteira — Issue → Branch →
Implementação → Testes → Auditoria → Commit → Push → Pull Request → CI →
Review → Merge → Issue concluída — pode ser executada autonomamente pelo
agente, sem confirmação humana passo a passo, nas condições e com os limites
exatos definidos em `docs/padroes/protocolo-autonomia-agente.md`. Isso não
altera a sequência em si, nem os limites humano-apenas ali definidos
(segurança/administração, operação destrutiva, nova trust boundary, decisão
de produto/profissional, desvio estrutural).

## Antes de alterar o repositório

1. Ler `AGENTS.md` e os padrões aplicáveis.
2. Localizar ou criar a Issue, sem duplicá-la.
3. Criar branch a partir de `main` sincronizada.
4. Limitar a implementação ao escopo da Issue.
5. Testar e auditar proporcionalmente ao risco.
6. Fazer staging cirúrgico e commits coerentes.
7. Abrir PR que referencie a Issue e informe impacto de deploy.

## Issue

Cada Issue registra contexto, objetivo, escopo, fora de escopo, critérios de
aceite, dependências, segurança/privacidade, testes e impacto em deploy. A
fonte canônica do backlog é o GitHub. Uma Issue somente termina quando seus
critérios forem cumpridos, o PR aprovado e o merge realizado.

## Branches e commits

Usar `feat/<issue>-<slug>`, `fix/<issue>-<slug>`,
`improve/<issue>-<slug>`, `refactor/<issue>-<slug>`,
`chore/<issue>-<slug>` ou `docs/<issue>-<slug>`.

Adotar Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
`chore:`, `ci:` e `perf:`. Evitar commits gigantes e mudanças fora da Issue.

## Pull Requests

- Preferir `1 Issue → 1 branch → 1 PR`.
- Usar `Closes #N` somente quando a entrega concluir integralmente a Issue;
  caso contrário, usar `Refs #N`.
- Informar escopo, testes, auditoria, privacidade e impacto de deploy.
- Review compara `EXPECTED` com `ACTUAL` e rejeita conteúdo privado ou fora do
  escopo.

## Ambientes e entrega

- `LOCAL`: desenvolvimento.
- `PR / PREVIEW`: CI e build/preview quando disponíveis.
- `MAIN / INTEGRATION`: integração estável.
- `RELEASE`: artefato aprovado e versionado por SemVer.

Feature branch nunca publica em produção. Nesta fase a política é documental;
deploy e release ainda não foram implementados.

## Simplicidade operacional

O usuário final não deve operar Git, GitHub, branch, commit, PR, schema, SQL,
API, Python, npm, Tauri ou React. Erros internos devem ser traduzidos em ação
compreensível. A interface futura terá três níveis: simples, técnico e
auditoria, sem expor complexidade avançada no fluxo normal.

## UI, motion e operações assíncronas

Consultar as Skills `ui-pericial`, `frontend-design` e
`design-motion-principles`, nessa ordem. Movimento é funcional, não decorativo.
Interações frequentes e por teclado devem ter pouco
ou nenhum movimento; entradas são curtas e saídas mais sutis. Respeitar
`prefers-reduced-motion` e preferir `transform`, `opacity` e `filter`.

Operações assíncronas devem informar, conforme aplicável, `IDLE`, `QUEUED`,
`LOADING`, `PROGRESS`, `SUCCESS`, `ERROR` ou `CANCELLED`, além de skeleton,
lazy loading, empty state, retry e cancelamento. Mostrar progresso real quando
mensurável; nunca fabricar porcentagem.

## Ferramentas futuras

- ArchContract: avaliar e instalar pinado quando houver workspace TypeScript.
- Biome, Commitlint, Knip e Stryker: instalar somente com consumidor real.
- Playwright e Codecov: integrar na Issue de testes.
- OpenTelemetry: instrumentação canônica vendor-neutral.
- Sentry, Datadog e New Relic: exporters configuráveis, nunca todos ativos por
  padrão.

Nenhuma dessas dependências é instalada por este padrão.

## Terceiros

Toda incorporação registra repositório, commit/tag, licença, arquivos, modo de
integração, integridade, dependências, risco e política de atualização. Uma
atualização exige Issue própria, auditoria, branch e PR; nunca atualizar
silenciosamente.

## Gate de publicação

`PRE_PUBLICATION_HISTORY_SCAN = REQUIRED`. Antes de publicar branch, PR,
release ou outro ref remoto, executar os scanners first-party de árvore
rastreada e de todo o histórico alcançável. A ausência atual de um arquivo não
saneia conteúdo que permaneça alcançável no Git.

Fixtures versionadas devem declarar `provenance: SYNTHETIC` no registro global.
Fixture derivada, transcrita, anonimizada ou adaptada de caso real é proibida;
anonimização não converte material real em sintético. O scanner nunca imprime
o conteúdo encontrado e `referencias/privadas/` não deve ser aberto durante o
gate.

## Autoridade de domínio e privacidade

O Core Pericial é a autoridade do domínio; IA é auxiliar e UI não contém
lógica pericial material. Não versionar dados reais nem enviar PII ou conteúdo
de `referencias/privadas/` sem autorização expressa.
