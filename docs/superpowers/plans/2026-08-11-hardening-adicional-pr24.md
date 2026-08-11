# Hardening adicional do PR #24 — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` para executar este plano por ciclos RED→GREEN, observando `AGENTS.md` e `engenharia-seguranca-pericial`.

**Goal:** Eliminar os bloqueadores adicionais de classificação PJe, capabilities, validação, imagens, regras causais e integrações de terceiros sem ampliar o escopo funcional do Core Pericial.

**Architecture:** Classificadores passam a usar regras explícitas e resultados conservadores; tipos periciais são ligados a um registry first-party de capabilities; validators e integrações externas falham fechados. Taxonomias probatórias tornam-se fonte única e associações de imagens passam a ser geométricas e determinísticas.

**Tech Stack:** Python padrão do repositório, `unittest`, JSON Schema, Git e stack PDF já instalada.

## Global Constraints

- Permanecer na Issue #23, branch `fix/23-core-pericial-p0` e PR #24 em draft.
- Não criar feature, dependência, CI, novo PR ou merge.
- Não acessar nem versionar `referencias/privadas/`.
- Cada tarefa segue reprodução → teste RED → causa-raiz → correção mínima → adversarial/metamórfico → regressão.

---

### Task 1: Classificadores documentais e periciais

**Files:** `scripts/extracao_pje/regras_classificacao.py`, `scripts/extracao_pje/classificar_documentos.py`, `scripts/triagem_pericial/classificar_tipo.py`, testes PJe/ADV.

- [ ] Reproduzir ART por substring, empate de tipo e critérios com uma única fonte.
- [ ] Criar testes RED para EXACT/PHRASE/TOKEN/REGEX, ambiguidade e invariância à ordem.
- [ ] Implementar matching explícito, score agregado sem desempate por ordem e critérios baseados nas fontes reais.
- [ ] Validar fluxo PJe sintético e todos os nove tipos.

### Task 2: Registry de capabilities e validator fail-closed

**Files:** novo módulo first-party de capabilities, delimitação, planejamento, `validar_plano.py`, testes ADV.

- [ ] Criar testes RED para seis tipos sem perfil e `OUTRO` genérico explícito.
- [ ] Implementar registry dos nove tipos sem criar motores novos; bloquear perfil especializado ausente.
- [ ] Criar tabela adversarial de JSON/schema/relações malformadas e confirmar ausência de traceback.
- [ ] Implementar validação em camadas, capturando somente erros esperados.

### Task 3: Associação geométrica de imagens

**Files:** `scripts/extracao_pje/catalogar_imagens.py`, testes unitários/PDF sintético.

- [ ] Reproduzir rótulo global e escrever casos RED 1:1, 2:2, ambíguo, decorativo, órfão e reordenação.
- [ ] Associar bbox de imagem e bbox de legenda por regra espacial determinística, com fallback conservador.
- [ ] Expandir PDF sintético quando a stack atual permitir, sem dependência nova.

### Task 4: Fonte única causal

**Files:** novo módulo canônico, `motor_vicios/regras.py`, `auditoria_pericial/detector.py`, `deep_audit.py`, testes ADV.

- [ ] Criar teste RED que injeta aspecto na taxonomia canônica e observa inferência e auditorias.
- [ ] Centralizar dimensões/divergências e predicates sem alterar critérios aprovados.
- [ ] Remover cópias locais e executar regressão causal.

### Task 5: Terceiros — trust, egress e atualização

**Files:** `scripts/terceiros/catalogar_repositorios.py`, `verificar_atualizacoes.py`, política first-party e testes locais.

- [ ] Reproduzir trust por nome, egress falso-negativo e `ls-remote --heads origin HEAD` inconclusivo.
- [ ] Separar decisão de governança de evidência calculada; default `UNREVIEWED/UNKNOWN`.
- [ ] Implementar egress `YES/NO_VERIFIED/UNKNOWN` conservador e impedir uso privado em UNKNOWN.
- [ ] Testar atualização com repositório bare local e tip da branch upstream real.

### Task 6: Datas, ADV e E2E cumulativo

**Files:** inventário de extratores temporais e testes ADV/PDF/E2E.

- [ ] Inventariar funções/testes de data e registrar `NOT_REPRODUCED` se nenhum defeito material for reproduzido.
- [ ] Cobrir todos os IDs adversariais solicitados e metamórficos.
- [ ] Reexecutar E2E canônico PDF→laudo, gates Motor/Redação e validações contratuais.

### Task 7: Verificação, revisão e checkpoint

**Files:** somente artefatos desta rodada e review package do PR.

- [ ] Executar suíte integral, ADV, schemas/fixtures, compileall, guards, privacidade e diff-check.
- [ ] Solicitar revisão independente cumulativa do PR #24 e corrigir todo P0/P1 material.
- [ ] Criar commits atômicos por causa-raiz, push normal e atualizar PR mantendo draft.
- [ ] Confirmar worktree limpa, privados ausentes e merge não realizado.
