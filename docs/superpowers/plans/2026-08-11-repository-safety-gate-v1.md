# Repository Safety Gate V1 — plano de implementação

Base: `71dea5d95d9843d08fe1547b6b52812ddd060511`. Issue: #10.

1. Confirmar baseline congelada e criar branch canônica.
2. Criar testes RED do registro, fixture registry, change-impact e orquestrador.
3. Implementar registros first-party e `scripts.quality` sem mudar o Core.
4. Adicionar property tests, Skill, documentação e workflow `core-safety`.
5. Executar FAST, FULL, regressão, schemas, fixtures, E2Es e privacidade.
6. Fazer revisão independente no SHA final, persistir evidência e abrir PR draft.

Mutation testing permanece piloto documental/follow-up da Issue #11 nesta V1,
pois não é blocker e não justifica nova dependência antes de avaliar custo e
compatibilidade no Python 3.13/3.14.
