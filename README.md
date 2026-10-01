# Padrão de laudos periciais

Repositório para padronização, redação, revisão e controle de qualidade de
laudos periciais judiciais. A visibilidade no GitHub é uma decisão humana
pendente; dados reais nunca são versionados, qualquer que seja ela.

## Escopo

Perícias judiciais de engenharia civil, inicialmente voltadas à análise de
vícios e manifestações patológicas em edificações.

## Arquitetura

- `docs/`: manual operacional e padrões canônicos.
- `checklists/`: controles de preparação, redação e revisão.
- `.agents/skills/`: procedimentos de triagem, redação e revisão pericial.
- `referencias/`: orientação e referências locais.
- `schemas/`: contratos de dados.
- `scripts/` e `tests/`: contratos e validação local.
- `scripts/backend_contract/`: contratos transversais do monólito modular.

## Estado atual verificável

O oracle longitudinal sintético percorre `PDF PJe → Workspace → Case Analysis →
Planning → Inspection → Evidence → Technical Findings → Report → Delivery
Word → Budget → Backup → Recovery/Reopen` pela superfície HTTP `/app-api`, sem
chamadas diretas aos serviços. Isso não prova a UI/Data Layer nem a aceitação
Human RC. O post-main oracle do Issue #187 passou em `11 testes` no main
`27175535933a`.

O Word/DOCM é o artefato profissional autoritativo. O PDF é derivado localmente
pelo Microsoft Word 16, aceito somente após verificação de fidelidade estrutural
e visual e vinculado por SHA-256 ao Word exato; qualquer recusa mantém o Word e
nenhum PDF. PDF diagnóstico não é PDF profissional final.

Stage 10 possui gateway e propostas de IA com provider e contexto explícitos,
saída estruturada, revalidação da aplicação, auditoria append-only e limites
de tokens/custo. `AI_PROPOSAL` nunca se torna autoridade efetiva sozinho.

O Roadmap V7 (#256) fechou as etapas automáticas pré-RC: sucessão explícita de
planejamento, vistoria (reaproveitamento só por escolha do perito), análise
técnica e análise de vícios; anexo de apoio à entrega fora das fontes do caso;
política temporal híbrida; e o oráculo final sobre o processo real do produto
(`tests/test_v7_final_rc_oracle_v1.py`). `HUMAN_RC_READY = TRUE`.

A aceitação humana no Windows (`HUMAN_RC_WINDOWS_V2`, #238), a execução de caso
real e o instalador continuam pendentes.

## Histórico de escopo inicial

O fluxo inicial documentado neste repositório cobria
`manifesto-pje.json → documento-pje.json → processo.json → vistoria.json →
PAT-NNN`. Essa descrição permanece como histórico; o estado efetivo atual é o
fluxo longitudinal acima.

## Skills

As Skills first-party de triagem, planejamento, vistoria, motor de vícios,
redação, revisão, auditoria, grounding e trilha profissional orientam o
trabalho. Nenhuma Skill externa recebe dados privados por padrão.

## Privacidade

`referencias/privadas/` contém material exclusivamente local e nunca deve ser
versionada. Fixtures e oracles públicos usam dados sintéticos. `PRIVATE_EGRESS
= FALSE`.

Consulte o [manual operacional](docs/manual-operacional.md), o [relatório de
maturidade](docs/PRODUCT_MATURITY_REPORT_V1.md) e as
[regras periciais](docs/padroes/regras-periciais.md).
