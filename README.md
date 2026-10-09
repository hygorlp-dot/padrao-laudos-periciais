# Padrão de laudos periciais

Aplicação profissional local para perícia judicial de engenharia e padrão de
trabalho do perito: padronização, redação, revisão e controle de qualidade de
laudos periciais judiciais. A visibilidade do repositório no GitHub é uma
decisão humana pendente; dados reais nunca são versionados, qualquer que seja
ela.

## 1. O que é o produto

Uma aplicação local (navegador + backend em `127.0.0.1`) que conduz uma perícia
do export PJe até o laudo Word autoritativo, o orçamento de honorários e um
backup verificável. O Core Pericial é a autoridade do domínio, a IA só propõe e
a decisão profissional é sempre do perito. A descrição completa e atual está em
[`PRODUCT.md`](PRODUCT.md).

## 2. Escopo

Perícias judiciais de engenharia civil, inicialmente voltadas à análise de
vícios e manifestações patológicas em edificações. O repositório é o padrão de
trabalho do perito, nunca um arquivo de autos de processos reais.

## 3. Arquitetura

- `frontend/`: interface React + TypeScript + Vite (sem lógica pericial).
- `scripts/backend_contract/`: monólito modular — Domain, Application,
  Infrastructure, Local API (`/app-api`) e Product Bridge.
- `scripts/extracao_pje/`, `scripts/triagem_pericial/`,
  `scripts/planejamento_pericial/`, `scripts/vistoria_estruturada/`,
  `scripts/motor_vicios/`, `scripts/redacao_pericial/`: Core Pericial protegido
  por contratos, fixtures, golden corpus e gates.
- `scripts/quality/` e `tests/`: gates first-party e suíte de testes.
- `schemas/`: contratos de dados (ver [`schemas/README.md`](schemas/README.md)).
- `config/`: manifestos versionados de qualidade, schemas e maturidade.
- `.agents/skills/`: Skills de agente (first-party e terceiros pinados),
  roteadas por `.agents/skill-router.json`.
- `docs/`: padrões, decisões de arquitetura, manual e registros históricos.
- `referencias/`: orientação local; `referencias/privadas/` nunca é versionada.

## 4. Como executar

Requisitos: Python 3 com as dependências de `requirements-dev.txt` e Node.js
para o build do frontend.

```powershell
python -m pip install --require-hashes -r requirements-dev.txt
cd frontend; npm ci; npm run build; cd ..
python -m scripts.planejamento_pericial.app_composition --database <dados>\produto.sqlite3 --frontend frontend\dist --private-root <dados>\privado --port 8765
```

O produto escuta somente em `127.0.0.1`. O PDF derivado exige Microsoft Word 16
no Windows; sem ele, o Word continua sendo entregue e nenhum PDF é produzido.
Ainda não há instalador (`PACKAGING_GAP`).

## 5. Autoridades

| Documento | Responde |
|---|---|
| [`AGENTS.md`](AGENTS.md) | como trabalhar neste repositório (canônico para agentes; `CLAUDE.md`, `CODEX.md`, `CURSOR.md`, `GEMINI.md` e `WINDSURF.md` apenas apontam para ele) |
| [`PRODUCT.md`](PRODUCT.md) | o que o produto é agora |
| [`DESIGN.md`](DESIGN.md) | como o produto se parece e se comporta |
| [`docs/padroes/`](docs/padroes/) | regras de domínio, profissionais e de governança |
| [`docs/arquitetura/decisoes/`](docs/arquitetura/decisoes/) | por que a arquitetura é assim |
| [`docs/manual-operacional.md`](docs/manual-operacional.md) | fluxo operacional e fronteiras de autoridade |
| [`docs/superpowers/plans/`](docs/superpowers/plans/README.md), `docs/reviews/`, `docs/arquitetura/planos/` | como chegamos aqui (registro histórico, não autoridade) |
| `docs/stabilization/` | baselines e convenções de estabilização do Core, consumidas por gates (assurance) |
| [`artifacts/`](artifacts/README.md) | evidência e saída histórica de assurance |

O mapa completo e verificável fica em `config/repository-authority-v1.json` e é
auditado por `python -m scripts.quality.repository_hygiene`.

## 6. Privacidade

`PRIVATE_EGRESS = FALSE`: sem OCR em nuvem, mapas externos, analytics,
telemetria ou IA externa por padrão. `referencias/privadas/` contém material
exclusivamente local e nunca deve ser versionada. Fixtures e oráculos públicos
usam somente dados sintéticos (`provenance: SYNTHETIC`).

## 7. Como validar

```powershell
python -m scripts.quality.verify_core --full
cd frontend; npm run lint; npm run typecheck; npm test; npm run build; cd ..
python -m scripts.quality.repository_hygiene
```

`verify_core --full` é o gate local equivalente ao `core-safety` da CI (ver
[`docs/padroes/repository-safety-gate.md`](docs/padroes/repository-safety-gate.md)).

## 8. Onde está o estado atual

O estado temporal — candidato congelado, rodadas do Human RC, resultado de CI —
não fica neste README, porque fica falso a cada merge:

- roadmap canônico e checkpoints: issue de roadmap vigente no GitHub
  (os registros de #256 preservam o roadmap V7);
- aceitação humana no Windows: #238 e
  [`docs/HUMAN_RC_WINDOWS_V2.md`](docs/HUMAN_RC_WINDOWS_V2.md);
- declaração de maturidade: [`config/product-maturity-v1.json`](config/product-maturity-v1.json)
  e [`docs/PRODUCT_MATURITY_REPORT_V1.md`](docs/PRODUCT_MATURITY_REPORT_V1.md);
  o commit validado ali é evidência histórica, e o HEAD vivo é calculado por
  `python -m scripts.quality.product_maturity`.

## Histórico de escopo inicial

O fluxo inicial documentado neste repositório cobria
`manifesto-pje.json → documento-pje.json → processo.json → vistoria.json →
PAT-NNN`. Essa descrição permanece como histórico; o fluxo atual está em
[`PRODUCT.md`](PRODUCT.md).
