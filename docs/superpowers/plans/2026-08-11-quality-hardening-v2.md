# Quality Hardening V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fortalecer mecanicamente o Core V1 congelado com mutações históricas, propriedades de domínio, fault injection, contratos de versão, métricas objetivas e Safety Gate V2.

**Architecture:** O hardening será uma camada first-party em `scripts/quality/` alimentada por registros JSON canônicos. A suíte histórica será pequena e determinística no FULL; o piloto profundo ficará separado e manual, usando `mutmut` somente como dependência dev. Nenhuma semântica funcional do Core será alterada nesta Issue.

**Tech Stack:** Python 3.14, pytest 9.1.1, Hypothesis 6.165.3, mutmut 3.7.0, coverage.py 7.15.4 e biblioteca padrão (`ast`, `json`, `subprocess`).

## Global Constraints

- Base obrigatória: `15e77be13fa5aae96325d20fab322809e40e816f`.
- Não acessar `referencias/privadas/`.
- Não implementar AI Gateway, multimodal, UI ou automação Word/PDF.
- Bug P0/P1 funcional descoberto bloqueia este PR e recebe Issue/PR próprios.
- `core-safety` mantém nome, execução first-party e tempo FULL ideal abaixo de 30 segundos.

---

### Task 1: Registros canônicos e testes RED da infraestrutura

**Files:**
- Create: `config/historical-bugs.json`
- Create: `config/schema-versions.json`
- Create: `config/quality-baseline.json`
- Create: `tests/test_quality_hardening_v2.py`
- Modify: `config/core-invariants.json`
- Modify: `config/core-boundaries.json`
- Modify: `config/core-registry-lock.json`

- [ ] Escrever testes que rejeitem bug sem regressão/mutação, proteção crítica ausente, versão sem política, configuração stale e migração destrutiva.
- [ ] Executar o arquivo de teste e confirmar RED por módulos/registros ausentes.
- [ ] Criar os três registros com IDs, boundaries, invariantes, testes e políticas explícitas.
- [ ] Adicionar `SCHEMA_VERSION_FIDELITY` e `MIGRATION_NO_SILENT_LOSS`, atualizar fingerprints e confirmar GREEN.

### Task 2: Suíte histórica de mutações críticas

**Files:**
- Create: `scripts/quality/historical_mutations.py`
- Create: `tests/test_historical_mutations.py`
- Modify: `scripts/quality/verify_core.py`

- [ ] Criar RED para MUT-001 a MUT-010, exigindo que cada mutante aplique uma alteração real e seja morto por teste identificável.
- [ ] Implementar runner isolado em diretório temporário, sem modificar a árvore de trabalho e sem rede.
- [ ] Integrar a suíte rápida ao FULL e testar mutante sobrevivente/tool indisponível como falha fechada.

### Task 3: Property-based testing V2

**Files:**
- Create: `tests/test_core_properties_v2.py`

- [ ] Criar estratégias de domínio válido para PJe, Motor, coverage, Redação e egress.
- [ ] Separar testes de input inválido/schema e provar as propriedades metamórficas críticas.
- [ ] Executar com Hypothesis e corrigir somente falhas da infraestrutura; bug funcional material abre Issue separada.

### Task 4: Fault injection e versionamento

**Files:**
- Create: `scripts/quality/schema_versions.py`
- Create: `tests/test_fault_injection.py`
- Create: `tests/test_schema_versions.py`

- [ ] Criar RED para JSON truncado, falta de arquivo/referência/catálogo, subprocesso/timeout/provider/cache/migração e producer bloqueado.
- [ ] Implementar validação mecânica da matriz de versões e migrações existentes.
- [ ] Exigir fail-closed, ausência de artefato parcial, ausência de recovery silencioso e preservação material.

### Task 5: Cobertura, complexidade e supply chain

**Files:**
- Create: `scripts/quality/metrics.py`
- Create: `docs/padroes/quality-hardening-v2.md`
- Create: `docs/terceiros/quality-tooling-v2.md`
- Modify: `requirements-dev.txt`

- [ ] Pin `mutmut==3.7.0` e `coverage==7.15.4`; documentar origem, licença, dependências, egress, telemetria e runtime=NÃO.
- [ ] Medir linha/branch nos targets críticos e complexidade AST, persistindo baseline e ranking objetivo.
- [ ] Executar piloto profundo em escopo seletivo e registrar score/sobreviventes; não integrar campanha profunda ao FULL.
- [ ] Refatorar no máximo três hotspots somente se a métrica e testes demonstrarem ganho; caso contrário registrar zero refactors.

### Task 6: Safety Gate V2, CI e guards

**Files:**
- Modify: `scripts/quality/verify_core.py`
- Modify: `.github/workflows/core-safety.yml` somente se necessário
- Create: `.github/workflows/quality-depth.yml`
- Modify: `tests/test_repository_safety_gate.py`

- [ ] Manter FAST compatível e acrescentar ao FULL histórico, properties V2, fault injection, versões e métricas de non-regression.
- [ ] Criar workflow manual/agendado `quality-depth`, sem secrets/deploy/dados privados, chamando comando first-party.
- [ ] Testar que CI não duplica lógica e que config truncada/stale não burla o gate.

### Task 7: Verificação, revisão e entrega

**Files:**
- Create: `docs/reviews/issue-11-quality-hardening-v2-<sha>.md` após revisão

- [ ] Executar FAST, FULL, pytest integral, schemas, compileall, diff-check, privacy e piloto profundo.
- [ ] Executar revisão independente read-only do HEAD final e persistir matriz ligada ao SHA.
- [ ] Fazer staging cirúrgico, commit(s), push e abrir um único PR draft com `Closes #11` e todos os campos exigidos.
- [ ] Aguardar `core-safety=SUCCESS` e parar antes do merge.
