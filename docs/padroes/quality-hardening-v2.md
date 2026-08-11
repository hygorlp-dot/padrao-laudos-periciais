# Quality Hardening V2 do Core

## Regra aprovada

O Core V1 permanece congelado. O hardening mede e protege comportamentos já
aprovados; não cria regra pericial nem altera semântica funcional.

## Camadas

1. `config/historical-bugs.json`: corpus rastreável de falhas históricas.
2. `config/historical-mutants.json`: dez mutações críticas determinísticas.
3. `tests/test_core_properties_v2.py`: propriedades de domínio válido e
   entradas inválidas separadas.
4. `tests/test_fault_injection.py`: falhas internas sempre fail-closed.
5. `config/schema-versions.json`: versões, migradores, consumidores e campos
   materiais protegidos.
6. `config/quality-baseline.json`: cobertura e hotspots para non-regression.

## Mutation testing

- A suíte histórica é pequena, first-party, sem rede e executada no FULL.
- Cada mutante registra teste, invariante e boundary.
- Um mutante sobrevivente ou inválido bloqueia o gate.
- A campanha profunda usa mutmut 3.7.0 fora do check obrigatório e não acessa
  dados privados.

## Cobertura e complexidade

A cobertura mede módulos críticos com branch coverage. O baseline inicial é
84,545% de linhas e 72,788% de branches. A complexidade é medida por AST e
mantida como non-regression nos cinco maiores hotspots. Nenhum hotspot foi
refatorado nesta fase: o risco de alterar o Core congelado excedeu o benefício
de uma refatoração misturada ao hardening.

## Gates

FAST preserva custo baixo. FULL acrescenta histórico de mutações, properties
V2, fault injection, versões/migrações e métricas estáticas. A campanha mutmut
ampla pertence ao workflow opcional `quality-depth`.
