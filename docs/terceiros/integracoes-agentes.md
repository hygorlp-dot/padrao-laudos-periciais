# Integrações externas de agentes

| Projeto | URL | Commit auditado | Licença | Integração | Código incorporado |
|---|---|---|---|---|---|
| Impeccable | [repositório upstream](https://github.com/pbakaus/impeccable) | `2ab054d1f400c5ec085133352232ffc2617f0d54` | Apache-2.0 | `THIRD_PARTY_PINNED`; `FULL_PINNED_COPY` do subtree da Skill, sem hooks | Skill completa, LICENSE e NOTICE; sem instalador |
| Claim Audit | [repositório upstream](https://github.com/mhalle/claim-audit) | `f09c72ef22119692667dce2b288fc51a24534db5` | MIT | `THIRD_PARTY_PINNED`; wrapper pericial separado; `INTEGRACAO_METODOLOGICA_ADAPTADA` | Skill, recursos e LICENSE |
| Proposition Audit | Catálogo Awesome Legal Skills abaixo | `4b0a895640d44add67ab4db1a0250e5a48888ee1` | Apache-2.0 | `THIRD_PARTY_PINNED`; execução pericial por `WRAPPER_LOCAL` | Skill seletiva, LICENSE e NOTICE |
| Awesome Legal Skills | [repositório upstream](https://github.com/lawve-ai/awesome-legal-skills) | `4b0a895640d44add67ab4db1a0250e5a48888ee1` | Raiz CC-BY-NC-ND-4.0; licença individual por Skill | Catálogo privado `REFERENCE_ONLY`; seleção por licença | Nenhum catálogo incorporado |

## Política

- `TRUSTED_LOCAL`: execução local permitida, sem saída de dados.
- `TRUSTED_WITH_RESTRICTIONS`: somente função delimitada e sem dados privados.
- `REFERENCE_ONLY`: consulta conceitual; nenhuma execução ou cópia automática.
- `BLOCKED`: licença, segurança ou saída de dados incompatível.

Nenhuma integração supera os contratos canônicos, fornece fatos do caso ou decide matéria jurídica. Atualizações exigem nova auditoria; `scripts/terceiros/verificar_atualizacoes.py` somente informa divergência e nunca atualiza.

## Atualização controlada

Uma atualização exige novo commit pinado, verificação de licença e atribuição,
comparação do subtree, fechamento dos imports, análise de egresso, suíte completa
e nova simulação de clone. O verificador apenas consulta referências Git e não
faz checkout, instalação, execução ou alteração automática.

Ferramentas capazes de transmitir conteúdo pela rede, inclusive `.agents/skills/impeccable/scripts/generate-image.mjs`, têm classificação `EXTERNAL_DATA_EGRESS_REQUIRED`. Elas não integram o pipeline pericial e não podem receber nem transmitir dados de processos ou de `referencias/privadas/` automaticamente. A execução exige seleção humana explícita e conteúdo exclusivamente público ou sintético.

## Hooks

A documentação oficial da OpenAI consultada nesta etapa não confirmou uma interface pública de hooks de projeto compatível. O estado é `AUDITORIA_MANUAL_DISPONIVEL`; nenhum `.codex/hooks.json` foi criado.
