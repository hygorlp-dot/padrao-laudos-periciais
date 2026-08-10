# Padrão de laudos periciais

Repositório privado para padronização, redação, revisão e controle de qualidade
de laudos periciais judiciais.

## Escopo inicial

Perícias judiciais de engenharia civil, inicialmente voltadas à análise de
vícios e manifestações patológicas em edificações, sem impedir expansão futura.

## Arquitetura

- `docs/`: manual operacional e padrões canônicos.
- `checklists/`: controles de preparação, redação e revisão.
- `.agents/skills/`: procedimentos de redação e revisão pericial.
- `referencias/`: orientação e referências locais.
- `schemas/`: contratos de dados iniciais.
- `scripts/` e `tests/fixtures/schemas/`: validação local dos contratos.
- `templates/` e `fixtures/`: áreas reservadas para etapas futuras.

## Fluxo futuro

O fluxo planejado parte da extração dos autos, passa por `processo.json`,
vistoria, `vistoria.json`, análises `PAT-NNN` e `laudo.json`, e termina na
revisão e no preenchimento do modelo DOCM. Esse fluxo ainda não está
automatizado.

## Skills

- `redacao-laudo-pericial`: redação conforme os padrões aprovados.
- `revisao-laudo-pericial`: auditoria crítica com status `APROVADO` ou
  `BLOQUEADO`.

## Privacidade e estado atual

`referencias/privadas/` contém material exclusivamente local e nunca deve ser
versionada. Atualmente, o projeto possui arquitetura, padrões canônicos,
checklists, skills, contratos JSON Schema e seu validador inicial. A geração
dos dados e a automação Word ainda não foram implementadas.

Consulte o [manual operacional](docs/manual-operacional.md) e as
[regras periciais](docs/padroes/regras-periciais.md).
