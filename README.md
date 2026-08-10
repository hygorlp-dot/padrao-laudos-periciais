# Padrão de laudos periciais

Repositório privado para padronização, redação, revisão e controle de qualidade
de laudos periciais judiciais.

## Escopo inicial

Perícias judiciais de engenharia civil, inicialmente voltadas à análise de
vícios e manifestações patológicas em edificações, sem impedir expansão futura.

## Arquitetura

- `docs/`: manual operacional e padrões canônicos.
- `checklists/`: controles de preparação, redação e revisão.
- `.agents/skills/`: procedimentos de triagem, redação e revisão pericial.
- `referencias/`: orientação e referências locais.
- `schemas/`: contratos de dados iniciais.
- `scripts/` e `tests/`: extração estrutural PJe e validação local dos contratos.
- `templates/` e `fixtures/`: áreas reservadas para etapas futuras.

## Fluxo de dados

O fluxo atual implementa `PDF PJe → manifesto-pje.json → documento-pje.json → delimitacao-pericial.json`.
A delimitação antecede `processo.json`, vistoria,
análises `PAT-NNN`, `laudo.json`, revisão e preenchimento do modelo DOCM.

## Skills

- `redacao-laudo-pericial`: redação conforme os padrões aprovados.
- `revisao-laudo-pericial`: auditoria crítica com status `APROVADO` ou
  `BLOQUEADO`.
- `triagem-delimitacao-pericial`: leitura semântica, delimitação do encargo,
  cobertura de quesitos, ressalvas, conflitos e plano pericial preliminar.

## Privacidade e estado atual

`referencias/privadas/` contém material exclusivamente local e nunca deve ser
versionada. Atualmente, o projeto possui arquitetura, padrões canônicos,
checklists, skills, contratos JSON Schema, parser estrutural PJe e contrato de
triagem semântica. A execução semântica é conduzida pelo Codex conforme a Skill;
`processo.json` automático e automação Word ainda não foram implementados.

Consulte o [manual operacional](docs/manual-operacional.md) e as
[regras periciais](docs/padroes/regras-periciais.md).
