---
name: repository-safety-gate
description: Mapear impacto e executar os gates first-party do Core Pericial V1 congelado. Usar antes de entregar qualquer alteração material no repositório, especialmente em boundaries, invariantes, testes, schemas, fixtures, privacidade ou integrações.
---

# Repository Safety Gate

1. Identificar arquivos alterados com `git diff --name-only`.
2. Executar `python -m scripts.quality.change_impact <arquivos>` quando houver
   mudança material e consultar `config/core-invariants.json` e
   `config/core-boundaries.json`.
3. Auditar somente os boundaries tocados e os invariantes globais aplicáveis.
4. Executar primeiro os testes específicos indicados pelo mapa de impacto.
5. Executar `python -m scripts.quality.verify_core --full` antes da entrega do
   PR. Na CI, a suíte `tests/test_architecture_analyzer_v1.py` roda em etapa
   própria bloqueante, fora do orçamento cronometrado de 60s do
   `verify_core --full` (via `PYTEST_ADDOPTS` no workflow) — localmente ela
   continua incluída em `verify_core --full`, sem mudança.
6. Bloquear a entrega diante de P0/P1 material, configuração incompleta, teste
   não executado, referência privada rastreada ou egress desconhecido.
7. Reportar somente exceções que exijam decisão; nunca usar teste verde como
   prova única nem ignorar falha silenciosamente.

O Core V1 está congelado. Mudanças futuras não reabrem auditoria geral:
verificar boundaries tocados e invariantes globais. Bug novo reproduzível vira
Issue normal com RED, causa-raiz e correção própria. Não iniciar discovery sweep
repository-wide automaticamente.

Nunca acessar `referencias/privadas/`. Nunca autorizar provider externo sem
capability e política explícitas. AGENTS.md e os registros canônicos prevalecem.
