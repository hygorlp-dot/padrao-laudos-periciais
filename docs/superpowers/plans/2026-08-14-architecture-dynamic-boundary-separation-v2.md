# Architecture Dynamic Boundary Separation V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redelimitar o PR #50 como executor protegido e analisador de arquitetura estritamente estático, preservando integralmente os quatro P1 no futuro capability boundary.

**Architecture:** Remover do Architecture Analyzer a interpretação semântica de execução/importação dinâmica, sem tocar no executor protegido. Um registro fechado preserva provenance, reproducers e closure conditions para o PR-C/CAPABILITY_ANALYZER_V1.

**Tech Stack:** Python 3, AST, JSON, pytest, Git object plumbing, GitHub Actions.

## Global Constraints

- Issue #49 e branch `feat/architecture-analyzer-blocking-v1` somente.
- PR #44 permanece congelado e nunca será mergeado.
- `GENERAL_DYNAMIC_SEMANTIC_ENUMERATION = EXHAUSTED`; nenhuma quarta correção dessa abordagem.
- TDD RED antes da mudança de produção; executor protegido e pins permanecem fail-closed.
- Sem whitelist ampla, suppression ou mudança do Core pericial.

---

### Task 1: Contrato e transferência exata

**Files:**
- Create: `docs/arquitetura/decisoes/ADR-architecture-dynamic-boundary-separation-v2.md`
- Create: `config/architecture-capability-transfers-v2.json`
- Create: `tests/test_architecture_dynamic_boundary_v2.py`

**Interfaces:**
- Consumes: quatro artifacts terminais do HEAD `9a7815a`.
- Produces: registro fechado com `findingId`, reproducer, severity, source review, original HEAD, destination e closure condition.

- [ ] Escrever o teste que exige quatro transferências exatas e nenhuma whitelist.
- [ ] Executar o teste e confirmar RED porque o Architecture Analyzer ainda emite decisão dinâmica.
- [ ] Persistir ADR e registro sem reclassificar severidade nem fechar findings.

### Task 2: Analisador estritamente estático

**Files:**
- Modify: `scripts/quality/architecture_analyzer.py`
- Modify: `tests/test_architecture_analyzer_v1.py`
- Test: `tests/test_architecture_dynamic_boundary_v2.py`

**Interfaces:**
- Consumes: AST e policy de arquitetura do Git tree exato.
- Produces: somente findings estruturais pertencentes ao boundary estático.

- [ ] Remover detecção/propagação de identities de capability do analyzer.
- [ ] Preservar imports ordinários, ownership, edges, layers, SCCs, baseline e falhas fail-closed.
- [ ] Converter testes antigos de capability em verificações do registro de transferência, sem apagá-los.
- [ ] Executar testes focados até GREEN e fazer sweep de confusão entre boundaries.

### Task 3: Garantia e entrega

**Files:** somente reparos reproduzidos dentro do novo boundary.

**Interfaces:**
- Consumes: impact map, gates first-party e HEAD remoto.
- Produces: HEAD terminal revisado ou finding bloqueante novo.

- [ ] Executar change-impact, testes focados, regressão completa e `python -m scripts.quality.verify_core --full`.
- [ ] Commitar e publicar HEAD exato; aguardar CI exato.
- [ ] Executar PR Reviewer e Systemic Auditor frescos; reparar P0/P1 apenas dentro do novo orçamento.
- [ ] Executar Claude somente no HEAD terminal estável.
- [ ] Merge commit apenas com todos os gates verdes; validar main e iniciar PR dedicado de ativação bloqueante.

