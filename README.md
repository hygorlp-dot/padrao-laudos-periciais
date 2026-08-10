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

O fluxo atual implementa `PDF PJe → manifesto-pje.json → documento-pje.json →
processo.json → delimitacao-pericial.json → plano-vistoria.json →
ficha-pre-vistoria.md → vistoria.json → motor técnico → PAT-NNN → gate de
redação`. `laudo.json`, Word e PDF permanecem em etapas futuras.

## Skills

- `redacao-laudo-pericial`: redação conforme os padrões aprovados.
- `revisao-laudo-pericial`: auditoria crítica com status `APROVADO` ou
  `BLOQUEADO`.
- `triagem-delimitacao-pericial`: leitura semântica, delimitação do encargo,
  cobertura de quesitos, ressalvas, conflitos e plano pericial preliminar.
- `planejamento-pericial-autonomo`: gera processo semântico, recupera
  conhecimento e produz plano e ficha pré-vistoria.
- `motor-vicios-construtivos`: estrutura evidências de campo, testa hipóteses,
  gera PAT, saneia questões e aplica o gate de redação.
- `auditoria-pericial-continua`, `auditoria-grounding-pericial`,
  `trilha-auditoria-pericial` e `auditoria-pericial-integrada`: detector,
  grounding, deep audit, trilha profissional e gate.

Integrações externas auditadas são documentadas em
[`docs/terceiros/integracoes-agentes.md`](docs/terceiros/integracoes-agentes.md).

## Privacidade e estado atual

`referencias/privadas/` contém material exclusivamente local e nunca deve ser
versionada. Atualmente, o projeto possui arquitetura, padrões canônicos,
checklists, skills, contratos JSON Schema, parser estrutural PJe, processo
semântico, triagem, planejamento e motor pós-vistoria inicial para vícios.
A execução semântica é conduzida
pelo Codex conforme as Skills; automação Word ainda não foi implementada.

Consulte o [manual operacional](docs/manual-operacional.md) e as
[regras periciais](docs/padroes/regras-periciais.md).
