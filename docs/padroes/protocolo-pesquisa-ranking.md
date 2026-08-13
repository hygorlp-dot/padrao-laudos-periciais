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

Avaliar, quando aplicável: correção/fit; fit arquitetural; Python e Windows;
manutenção e cadência; API/documentação; licença; vulnerabilidades;
dependências transitivas; supply chain; testes; maturidade; tamanho/complexidade;
installer/packaging; operação offline/local; privacidade; egress; lock-in;
reversibilidade; custo operacional; abandono; migração; e builds determinísticos.
Popularidade/estrelas podem aparecer apenas como sinal fraco do ecossistema e
nunca dominar a pontuação. Toda nota material exige fonte identificável.

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
