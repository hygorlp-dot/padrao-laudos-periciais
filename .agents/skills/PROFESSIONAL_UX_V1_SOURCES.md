# PROFESSIONAL_UX_V1 — skills vendorizadas

Este arquivo registra a proveniência das skills adicionadas para preparar o
ciclo PROFESSIONAL_UX_V1 (#276): **fonte upstream + allowlist local +
capacidades excluídas**. Ele não declara cópia byte-idêntica onde houve
restrição intencional.

## Política

- Skills externas são fixadas a um commit exato; não seguem `main` implicitamente.
- A integridade é fixada por blob Git, arquivo a arquivo, no mecanismo first-party:
  - Superpowers: `docs/terceiros/superpowers-manifest.json` (`skill_trees`, `blobs`,
    `tree_sources`), verificado por `scripts/terceiros/verificar_superpowers.py`;
  - Vercel e Playwright: `docs/terceiros/professional-ux-v1-blobs.json`, verificado
    por `scripts/terceiros/verificar_professional_ux.py` (manifesto pinado por SHA-256).

  Alterar silenciosamente qualquer arquivo vendorizado falha esses verificadores.
- A instalação é somente de instruções/referências para agentes. Ela não adiciona
  dependência de runtime nem de desenvolvimento ao produto.
- Dependências sugeridas por uma skill (por exemplo Playwright) só entram no
  projeto em UOW TDD própria, com lockfile, testes e gates do repositório.
- Roteamento mínimo e condicional em `.agents/skill-router.json`; nenhuma skill
  desta lista entra por padrão em profile algum. `AGENTS.md` prevalece.
- Egress negado por padrão: skills que dependem de rede ficam `reference_only`.

## Fontes

### Superpowers — integração restrita

- Repositório: `obra/superpowers`
- Commit: `8ca22dba9a94f28898bbce59f2537ff4d87c747d`. As 8 árvores anteriores
  seguem no commit `3dcbd5c` (v6.2.0); `tree_sources` registra o commit de cada
  árvore nova.
- Licença: MIT; cópia em `.agents/third-party/superpowers/LICENSE`.

| Skill | Integração | Rota |
|---|---|---|
| `brainstorming` | **RESTRITA** | `engineering`/`ui` → `product_discovery` |
| `using-git-worktrees` | byte-idêntica | `engineering` → `isolated_workspace` |
| `subagent-driven-development` | byte-idêntica | `engineering` → `subagent_plan_execution` |
| `dispatching-parallel-agents` | byte-idêntica | `engineering` → `parallel_independent_tasks` |
| `finishing-a-development-branch` | byte-idêntica | `engineering` → `branch_completion` |

**`brainstorming`: TEXTUAL / SPECIFICATION / PRODUCT DISCOVERY ONLY.**

Decisão humana na #276: `BRAINSTORMING_POLICY = TEXTUAL_AND_LOCAL_ONLY`.

- Allowlist local: `SKILL.md` e `spec-document-reviewer-prompt.md`.
- Excluídos do upstream: `scripts/` (`server.cjs`, `helper.js`,
  `frame-template.html`, `start-server.sh`, `stop-server.sh`) e
  `visual-companion.md`.
- Capacidades excluídas, também em `.agents/superpowers-policy.json`:
  - `brainstorming-server`: **NO VISUAL SERVER**;
  - `remote-brand-image`: **NO REMOTE BRAND IMAGE**.
- Modificação local: em `SKILL.md`, o passo e a seção "Visual Companion"
  passam a declarar a capacidade indisponível neste repositório. O blob
  upstream original fica registrado no manifesto.

O `using-git-worktrees` sugere `npm install`/`pip install` no setup. Aqui vale
só o comando pinado do repositório (`npm ci`, `pip install --require-hashes`),
conforme `AGENTS.md`.

### Vercel Agent Skills

- Repositório: `vercel-labs/agent-skills`
- Commit: `063bee94c3f4df8453406c830b0a7df0f2860278`
- Licença: MIT, declarada no README do upstream e no frontmatter das skills. O
  upstream não publica arquivo `LICENSE`.

| Skill | Upstream | Integração | Rota |
|---|---|---|---|
| `vercel-react-best-practices` | `skills/react-best-practices` | subconjunto: `SKILL.md` + `AGENTS.md` | `ui` → `react_performance` |
| `vercel-composition-patterns` | `skills/composition-patterns` | subconjunto: `SKILL.md` + `AGENTS.md` | `ui` → `component_composition` |
| `web-design-guidelines` | `skills/web-design-guidelines` | byte-idêntica | `reference_only` |

Nos dois subconjuntos foram omitidos `README.md`, `metadata.json` e `rules/`,
porque o `AGENTS.md` é a compilação upstream de `rules/`.

`web-design-guidelines` manda buscar regras remotas por WebFetch e por isso
fica somente como referência.

### Find Skills

- Repositório: `vercel-labs/skills`
- Commit: `18f96ea131dab3b0fcc9b27cf7c6f6cbb6174680`
- Licença: MIT; cópia em `.agents/third-party/vercel-skills/LICENSE`.
- `find-skills` (byte-idêntica): `reference_only`. Depende de `npx skills`
  (registro remoto) e não é executada.

### Playwright CLI

- Repositório: `microsoft/playwright-cli`
- Commit: `b85c7a736bb473bf55b584e54a09ffa698d6d871`
- Licença: Apache-2.0; cópia byte-idêntica em
  `.agents/third-party/playwright-cli/LICENSE`.
- `playwright-cli` (byte-idêntica, com todas as referências): `ui` → `browser_qa`.
  Vale só com executável já disponível no ambiente e contra a origem local.
  `PLAYWRIGHT_PRODUCT_DEPENDENCY = FALSE`: nenhum pacote, devDependency, download
  de navegador ou script de instalação.

## Composição prevista para PROFESSIONAL_UX_V1

Cada etapa usa o conjunto mínimo aplicável (`MINIMUM_APPLICABLE_SKILL_SET`).

1. `brainstorming`: só se houver descoberta real de produto/UX. É textual,
   e não se repete com escopo já decidido.
2. `impeccable shape` + `ui-pericial`: arquitetura de informação e fluxo profissional.
3. `writing-plans`: plano executável.
4. `using-git-worktrees`: isolamento.
5. `subagent-driven-development` / `dispatching-parallel-agents`: quando houver
   independência real.
6. `test-driven-development`: RED/GREEN/REFACTOR.
7. `vercel-composition-patterns`: componentes React sem proliferação de flags.
8. `vercel-react-best-practices`: performance, re-render, bundle.
9. `frontend-design` + `impeccable`: qualidade visual.
10. `playwright-cli`: jornadas no navegador quando o executável estiver disponível
    e a origem for local.
11. `systematic-debugging`, `repository-safety-gate`, revisores independentes e
    `verification-before-completion`: fechamento.

`web-design-guidelines` e `find-skills` não entram como requisito, porque são
somente referência.
