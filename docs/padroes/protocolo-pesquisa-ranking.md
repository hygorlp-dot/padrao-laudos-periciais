# Protocolo de pesquisa e ranking

## Regras canônicas

`PYTHON_DEPENDENCY_DISCOVERY_V1 = TRUE`

`CATALOG_ENTRY != APPROVAL`

`POPULARITY != QUALITY`

`STAR_COUNT != SECURITY`

`DISCOVERY_SOURCE != PRIMARY_TECHNICAL_AUTHORITY`

`OFFICIAL_DOCS_AND_UPSTREAM_ARE_PRIMARY_FOR_TECHNICAL_FACTS`

`NO_DEPENDENCY_ADOPTION_WITHOUT_LICENSE_CHECK`

`NO_DEPENDENCY_ADOPTION_WITHOUT_SECURITY_CHECK`

`NO_DEPENDENCY_ADOPTION_WITHOUT_WINDOWS_COMPATIBILITY_CHECK`

`NO_DEPENDENCY_ADOPTION_WITHOUT_PACKAGING_IMPACT_CHECK`

`NO_GO_JUST_TO_USE_AWESOME_GO`

`RESEARCH_EVIDENCE_MUST_BE_IDENTIFIABLE = TRUE`

`RANKING_MUST_BE_REPRODUCIBLE = TRUE`

`MATERIAL_RECOMMENDATION_MUST_BE_REPOSITORY_SPECIFIC = TRUE`

O Researcher usa execução separada para decisão material. Modelo, memória,
catálogo, popularidade e estrelas não constituem evidência técnica nem
autorização de adoção. Nenhuma descoberta instala ou copia dependência.

## Discovery

Catálogos preferenciais, somente para formar o conjunto de candidatos:

- `vinta/awesome-python` e `lukasmasuch/best-of-python` — Python geral;
- `ml-tooling/best-of-python-dev` — ferramentas de desenvolvimento;
- `avelino/awesome-go` — complementar apenas quando já houver componente Go
  arquiteturalmente justificado. O catálogo nunca justifica introduzir Go.

## Validação primária

Cada candidato material deve ser verificado, conforme aplicável, em:

- documentação oficial e repositório upstream;
- metadados, versões e releases do PyPI;
- changelog/release notes e versões Python/OS declaradas;
- licença declarada e política/advisories de segurança upstream;
- vulnerabilidades em fontes autoritativas;
- `deps.dev` e `OpenSSF Scorecard` como sinais auxiliares de supply chain.

Sinais deps.dev/OpenSSF não aprovam automaticamente um pacote e não substituem
fontes oficiais para API, compatibilidade, licença, manutenção ou segurança.

## Fluxo para dependência material

`NEED → DISCOVERY → CANDIDATE SET → PRIMARY-SOURCE VALIDATION → SECURITY / SUPPLY CHAIN / LICENSE → REPOSITORY-SPECIFIC COMPARISON → AUDITABLE RANKING → RECOMMENDATION → INDEPENDENT CHALLENGE WHEN MATERIAL → ADOPTION DECISION`

Comparar normalmente ao menos três candidatos reais quando existirem
alternativas legítimas. Um conjunto menor exige registro de que o ecossistema
tem poucas opções críveis ou uma solução praticamente canônica.

## Critérios mínimos reproduzíveis

O ranking material contém exatamente estes 24 critérios canônicos:

1. `CORRECTNESS_FIT`
2. `ARCHITECTURAL_FIT`
3. `PYTHON_COMPATIBILITY`
4. `WINDOWS_COMPATIBILITY`
5. `MAINTENANCE_ACTIVITY`
6. `RELEASE_CADENCE`
7. `API_DOCUMENTATION_QUALITY`
8. `LICENSE`
9. `KNOWN_VULNERABILITIES`
10. `TRANSITIVE_DEPENDENCY_RISK`
11. `SUPPLY_CHAIN_SIGNALS`
12. `TEST_QUALITY`
13. `ECOSYSTEM_MATURITY`
14. `PACKAGE_SIZE_COMPLEXITY`
15. `PACKAGING_IMPACT`
16. `OFFLINE_LOCAL_OPERATION`
17. `PRIVACY`
18. `EXTERNAL_EGRESS`
19. `LOCK_IN`
20. `REVERSIBILITY`
21. `OPERATIONAL_COST`
22. `ABANDONMENT_RISK`
23. `MIGRATION_COST`
24. `REPRODUCIBLE_BUILDS_IMPACT`

Por candidato e critério registrar `SCORE = 0..4 | NOT_APPLICABLE`, justificativa
curta e IDs das evidências. `NOT_APPLICABLE` exige motivo e não vira zero. Pesos,
se usados, são declarados antes da avaliação e iguais entre candidatos.
Popularidade/estrelas podem aparecer apenas como sinal fraco do ecossistema e
nunca dominar a pontuação.

Cada entrada em `SOURCES` registra `URL_OR_IDENTIFIER`, `SOURCE_ENTITY`,
`VERSION_OR_ACCESS_DATE` e `SUPPORTED_CLAIM`. Toda nota material referencia ao
menos uma dessas entradas; ausência de evidência produz incerteza, não score
positivo presumido.

### Agregação e desempate

`ELIGIBILITY_GATE_BEFORE_RANKING`: candidato só é elegível quando todos os
predicados positivos forem demonstrados por evidência:

- `LICENSE_ACCEPTABLE = TRUE`
- `SECURITY_ACCEPTABLE = TRUE`
- `WINDOWS_COMPATIBLE = TRUE`
- `PACKAGING_IMPACT_ACCEPTABLE = TRUE`

`ADVERSE_OR_UNRESOLVED_GATE = INELIGIBLE`: licença proibitiva/incompatível,
vulnerabilidade material sem mitigação aceita, Windows não suportado, impacto
de packaging incompatível ou qualquer resultado inconclusivo impede adoção e
vitória por score numérico. A exclusão e suas evidências permanecem no relatório.

Para candidato elegível, a direção da escala é universal:
`SCORE_0 = WORST_OR_UNACCEPTABLE` e `SCORE_4 = BEST_OR_LOWEST_RISK`.
Nos critérios de risco, vulnerabilidade, custo, lock-in, abandono, migração e
complexidade, menor exposição recebe score maior; nunca alternar a direção por
candidato. Usar pesos inteiros positivos predeclarados (peso 1
para todos quando não houver pesos específicos) e excluir `NOT_APPLICABLE` do
numerador e denominador:

`NORMALIZED_SCORE = 100 * SUM(SCORE_i * WEIGHT_i) / SUM(4 * WEIGHT_i)`

Calcular com decimal exato, `ROUND_HALF_EVEN` e `DECIMAL_PLACES = 2`. É inválido
rankear candidato sem ao menos um critério aplicável. Publicar scores, pesos,
itens não aplicáveis, numerador, denominador e resultado para reprodução.

Empates no score normalizado usam, nesta ordem:

1. `TIE_BREAK_1 = FEWER_OPEN_UNCERTAINTIES`
2. `TIE_BREAK_2 = GREATER_APPLICABLE_CRITERIA_COUNT`
3. `TIE_BREAK_3 = CANONICAL_PACKAGE_NAME_ASCENDING`

## Contrato de saída

Persistir síntese auditável, não chain-of-thought, com:

- `RESEARCH_QUESTION`
- `REPOSITORY_CONTEXT`
- `REQUIREMENTS`
- `CANDIDATES`
- `SOURCES`
- `VERSIONS_CHECKED`
- `LICENSES`
- `SECURITY_FINDINGS`
- `COMPATIBILITY`
- `TRANSITIVE_DEPENDENCY_NOTES`
- `PACKAGING_IMPACT`
- `PRIVACY_EGRESS_IMPACT`
- `REVERSIBILITY`
- `RISKS`
- `RANKING`
- `RECOMMENDATION`
- `CONFIDENCE`
- `MATERIALITY`
- `OPEN_UNCERTAINTIES`

Cada score ou conclusão material deve apontar para evidência identificável. A
recomendação registra incertezas e é específica para este repositório.
