# PR-C0 — Capability control-plane rotation V1

Issue: #58
Branch: `feat/58-capability-bootstrap-prerequisite-v1`
Base inicial: `066dbcf400654a223d32d91d359cba6d8cbe3280`

## Objetivo

Preparar o plano de controle capability para que dois PRs posteriores possam
instalar e ativar um juiz pertencente ao base. O PR-C0 não contém o novo juiz
e não altera semântica de capability.

## Hipótese e boundary

O gate capability atual lê somente o registro do base. Os seus próprios
artefatos de plano de controle são protegidos pelo `architecture-protected`,
que executa o analyzer do base contra o tree candidato. Portanto, a rotação
exata de workflow, registro e trust anchor pode ser autorizada pelo juiz pai
sem executar bytes candidatos.

## TDD

1. RED: o registro candidato com path arbitrário, path removido, ordem
   divergente ou identidade inventada deve falhar.
2. RED: uma criação `ABSENT -> PRESENT` com registro candidato mecanicamente
   derivado deve passar; modo, tipo ou OID divergente deve falhar.
3. RED: `PRESENT -> ABSENT` continua bloqueado.
4. RED: o workflow seleciona o estado exclusivamente pelo tree do base e não
   executa Python candidato.
5. RED: somente os quatro paths contratuais ficam predeclarados e ausentes;
   os quatro P1 transferidos permanecem abertos.

## Implementação mínima

- Evoluir `capability_trust_anchor.py` para comparar o registro candidato ao
  registro esperado, derivado de `BASE_REGISTRY + EXACT_CANDIDATE_IDENTITIES`.
- Permitir o blob candidato do próprio registro apenas quando essa igualdade
  for exata.
- Predeclarar `config/capability-exceptions-v1.json` como `ABSENT`, junto aos
  três paths de código já predeclarados.
- Evoluir o workflow protegido para dois estados escolhidos somente pelo
  checkout trusted: custody quando bootstrap está ausente; enforcement do
  bootstrap do base quando presente.
- Autorizar a rotação pelo manifesto arquitetural V2 com paths, modos, tipos e
  OIDs exatos.

## Fora de escopo

Analyzer/bootstrap/adapter capability, registro de exceções efetivo, mudanças
de produto/perícia, expansão semântica, PR #44, PR #53 e fechamento dos quatro
P1 transferidos.

## Gates

Focused tests, regressão integral, `verify_core --full`, repository safety,
privacidade, checks exatos `core-safety`, `architecture-protected` e
`capability-protected`, Reviewer, Systemic Auditor e Claude em HEAD terminal.
