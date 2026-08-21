# Catálogo externo de APIs

## Fonte aprovada para discovery

- Repositório: `public-apis/public-apis`
- Commit de referência: `c045a2eb505f0f8b7992bb4af53cc020f25003fd`
- Licença do catálogo: MIT
- Papel: `DISCOVERY_ONLY`

O catálogo não é vendorizado, não é submódulo, não é dependência, não é uma
Skill e não autoriza integração. Seus campos Auth/HTTPS/CORS não constituem
avaliação de segurança e a indicação de gratuidade não é garantia de custo.

`PUBLIC_APIS_ENTRY != APPROVED_INTEGRATION`

`PUBLIC_APIS_ENTRY != AUTHORITATIVE_SOURCE`

`LISTED_AS_FREE != FREE_FOR_OUR_USE`

`FREE_TIER != ZERO_COST_GUARANTEE`

`HTTPS != TRUSTED_PROVIDER`

`NO_AUTH != PRIVACY_SAFE`

`POPULAR_API != OFFICIAL_SOURCE`

`CATALOG_DISCOVERY != PROVIDER_VALIDATION`

## Gate de validação de provider

Antes de qualquer adoção futura, verificar independentemente:

1. requisito real do produto;
2. identidade do provider;
3. autoridade da fonte e condição de fonte primária/oficial;
4. proveniência e propriedade dos dados;
5. qualidade da documentação e versão da API;
6. licença dos dados e Terms of Service;
7. política de privacidade;
8. PII e LGPD;
9. dados enviados em cada request;
10. egress de dados privados de caso;
11. credenciais e secrets;
12. HTTPS/TLS e autenticação;
13. rate limits, SLA e disponibilidade;
14. preço e restrições do free tier;
15. estabilidade de schema, versionamento e depreciação;
16. timeout, retry e cache;
17. estratégia determinística de testes, mocks e replay;
18. fallback offline;
19. comportamento fail-closed e durante indisponibilidade;
20. rollback e remoção;
21. alternativa oficial ou local;
22. risco de vendor lock-in e manutenção de longo prazo.

Para informação pericial, normativa ou técnica pública, a precedência é:

`PRIMARY_OFFICIAL_SOURCE > OFFICIAL_API > OFFICIAL_OPEN_DATA > VERIFIED_THIRD_PARTY > PUBLIC_APIS_DISCOVERY`.

Public APIs nunca autoriza envio de dados de caso. `APPLICATION_LAYER_V1` é
inteiramente local e usa zero providers/APIs externas.
