# PROFESSIONAL_UX_V1 — skills vendorizadas

Este arquivo registra a proveniência exata das skills adicionadas para preparar o ciclo PROFESSIONAL_UX_V1.

## Política

- Skills externas são fixadas a um commit exato; não seguem `main` implicitamente.
- A instalação é somente de instruções/referências para agentes. Ela não adiciona dependência de runtime ao produto.
- Dependências de desenvolvimento sugeridas por uma skill (por exemplo Playwright) só podem entrar no projeto em uma mudança própria, com lockfile, testes e gates do repositório.
- Skills já existentes no projeto continuam prevalecendo quando forem mais específicas ao domínio pericial.

## Fontes

### Superpowers
- Repositório: `obra/superpowers`
- Commit: `8ca22dba9a94f28898bbce59f2537ff4d87c747d`
- Licença: MIT; cópia já presente em `.agents/third-party/superpowers/LICENSE`.
- Adicionadas:
  - `brainstorming`
  - `using-git-worktrees`
  - `subagent-driven-development`
  - `dispatching-parallel-agents`
  - `finishing-a-development-branch`

### Vercel Agent Skills
- Repositório: `vercel-labs/agent-skills`
- Commit: `063bee94c3f4df8453406c830b0a7df0f2860278`
- Licença declarada no repositório/skills: MIT.
- Autor declarado nos metadados das skills: Vercel.
- Adicionadas:
  - `vercel-react-best-practices` — `SKILL.md` + documento compilado `AGENTS.md`
  - `vercel-composition-patterns` — `SKILL.md` + documento compilado `AGENTS.md`
  - `web-design-guidelines`
- Os arquivos individuais de `rules/` não foram duplicados porque os respectivos `AGENTS.md` são a compilação completa publicada pelo upstream.

### Find Skills
- Repositório: `vercel-labs/skills`
- Commit: `18f96ea131dab3b0fcc9b27cf7c6f6cbb6174680`
- Adicionada:
  - `find-skills`

### Playwright CLI
- Repositório: `microsoft/playwright-cli`
- Commit: `b85c7a736bb473bf55b584e54a09ffa698d6d871`
- Licença: Apache-2.0; cópia em `.agents/third-party/playwright-cli/LICENSE`.
- Adicionada:
  - `playwright-cli` e todas as referências publicadas pela skill.
- Observação: a skill está disponível para o agente; o executável Playwright não foi adicionado às dependências do produto nesta instalação.

## Composição prevista para PROFESSIONAL_UX_V1

1. `brainstorming` — objetivo, audiência, fluxos e critérios de sucesso.
2. `impeccable shape` + `ui-pericial` — arquitetura de informação e fluxo profissional.
3. `writing-plans` — plano executável.
4. `using-git-worktrees` — isolamento.
5. `subagent-driven-development` / `dispatching-parallel-agents` — execução eficiente quando houver independência real.
6. `test-driven-development` — RED/GREEN/REFACTOR.
7. `vercel-composition-patterns` — componentes React escaláveis sem proliferação de flags.
8. `vercel-react-best-practices` — performance, re-render, bundle e JavaScript.
9. `frontend-design` + `impeccable` — qualidade visual.
10. `web-design-guidelines` — segunda auditoria de interface e acessibilidade.
11. `playwright-cli` — jornadas reais no navegador quando o executável estiver disponível no ambiente.
12. `systematic-debugging`, `repository-safety-gate`, reviewers independentes e `verification-before-completion` — fechamento.
