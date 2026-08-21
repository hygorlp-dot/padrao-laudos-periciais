# Integrações externas de agentes

| Projeto | URL | Commit auditado | Licença | Integração | Código incorporado |
|---|---|---|---|---|---|
| Impeccable | [repositório upstream](https://github.com/pbakaus/impeccable) | `2ab054d1f400c5ec085133352232ffc2617f0d54` | Apache-2.0 | `THIRD_PARTY_PINNED`; `FULL_PINNED_COPY` do subtree da Skill, sem hooks | Skill completa, LICENSE e NOTICE; sem instalador |
| Claim Audit | [repositório upstream](https://github.com/mhalle/claim-audit) | `f09c72ef22119692667dce2b288fc51a24534db5` | MIT | `THIRD_PARTY_PINNED`; wrapper pericial separado; `INTEGRACAO_METODOLOGICA_ADAPTADA` | Skill, recursos e LICENSE |
| Proposition Audit | Catálogo Awesome Legal Skills abaixo | `4b0a895640d44add67ab4db1a0250e5a48888ee1` | Apache-2.0 | `THIRD_PARTY_PINNED`; execução pericial por `WRAPPER_LOCAL` | Skill seletiva, LICENSE e NOTICE |
| Awesome Legal Skills | [repositório upstream](https://github.com/lawve-ai/awesome-legal-skills) | `4b0a895640d44add67ab4db1a0250e5a48888ee1` | Raiz CC-BY-NC-ND-4.0; licença individual por Skill | Catálogo privado `REFERENCE_ONLY`; seleção por licença | Nenhum catálogo incorporado |
| Design Motion Principles | [repositório upstream](https://github.com/kylezantos/design-motion-principles) | `4a9ca879f24a361f4dca4174fe2da0f67b5ddee3` | MIT | `THIRD_PARTY_SKILL_PINNED_BYTE_EXACT`; wrapper pericial separado | Subtree completo da Skill e `/LICENSE`; 16 blobs verificados |
| Frontend Design | [repositório upstream](https://github.com/anthropics/claude-plugins-official) | `67a666efc8524ff7abaa266f84e514aa77aee48f` | Apache-2.0 | `THIRD_PARTY_SKILL_PINNED_BYTE_EXACT`; precedência first-party em AGENTS.md | Somente `SKILL.md` e `LICENSE.txt`; 2 blobs verificados |
| Superpowers | [repositório upstream](https://github.com/obra/superpowers) | `v6.2.0` / `3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9` | MIT | `THIRD_PARTY_SKILLS_PINNED_BYTE_EXACT`; seleção mínima; telemetria desabilitada; egress deny-by-default | 8 Skills de engenharia, 25 blobs e LICENSE |

## Política

- `TRUSTED_LOCAL`: execução local permitida, sem saída de dados.
- `TRUSTED_WITH_RESTRICTIONS`: somente função delimitada e sem dados privados.
- `REFERENCE_ONLY`: consulta conceitual; nenhuma execução ou cópia automática.
- `BLOCKED`: licença, segurança ou saída de dados incompatível.

O catálogo separa decisão humana de governança (`review_status`, evidência da
revisão, commit pinado, licença e restrições) de sinais técnicos calculados.
Ausência de revisão resulta em `UNREVIEWED` e bloqueio conservador. O requisito
de egress usa os estados `YES`, `NO_VERIFIED` e `UNKNOWN`; ausência de sinal
estático nunca equivale a `NO_VERIFIED`. Integrações com estado `UNKNOWN` não
podem receber dados privados.

Nenhuma integração supera os contratos canônicos, fornece fatos do caso ou decide matéria jurídica. Atualizações exigem nova auditoria; `scripts/terceiros/verificar_atualizacoes.py` somente informa divergência e nunca atualiza.

Design Motion Principles está em
`.agents/skills/design-motion-principles/`; a adaptação first-party está em
`.agents/skills/ui-pericial/`. O manifesto do guard registra o commit e os Git
blob IDs esperados. Atualizações exigem Issue e nova comparação byte-exata.

Frontend Design está em `.agents/skills/frontend-design/`, copiada sem
modificações do subtree exato registrado em
`docs/terceiros/frontend-design-blobs.json`. A Skill fornece direção estética
para trabalho frontend futuro, mas AGENTS.md, `ui-pericial` e os princípios
first-party do produto sempre prevalecem. O guard offline
`scripts/terceiros/verificar_frontend_design.py` rejeita arquivo ausente,
extra ou com blob divergente.

Superpowers foi incorporado seletivamente em `.agents/skills/`; a adaptação de
domínio está em `.agents/skills/engenharia-seguranca-pericial/`. O servidor de
brainstorming e demais capacidades com rede não foram copiados. A política
`.agents/superpowers-policy.json` desabilita telemetria e nega egress por
padrão. O guard `scripts/terceiros/verificar_superpowers.py` impede divergência
dos blobs pinados e da licença.

## Atualização controlada

Uma atualização exige novo commit pinado, verificação de licença e atribuição,
comparação do subtree, fechamento dos imports, análise de egresso, suíte completa
e nova simulação de clone. O verificador apenas consulta referências Git e não
faz checkout, instalação, execução ou alteração automática.

Ferramentas capazes de transmitir conteúdo pela rede, inclusive `.agents/skills/impeccable/scripts/generate-image.mjs`, têm classificação `EXTERNAL_DATA_EGRESS_REQUIRED`. Elas não integram o pipeline pericial e não podem receber nem transmitir dados de processos ou de `referencias/privadas/` automaticamente. A execução exige seleção humana explícita e conteúdo exclusivamente público ou sintético.

## Hooks

A documentação oficial da OpenAI consultada nesta etapa não confirmou uma interface pública de hooks de projeto compatível. O estado é `AUDITORIA_MANUAL_DISPONIVEL`; nenhum `.codex/hooks.json` foi criado.
