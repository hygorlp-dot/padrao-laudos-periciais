# Catálogo externo Python

## Fonte aprovada para discovery

- Repositório: `vinta/awesome-python`
- Commit de referência: `6ff59a63c6db5f23ec808381994050bbf324801d`
- Licença do catálogo: CC BY 4.0
- Papel: `DISCOVERY_ONLY`

O catálogo não é vendorizado, não é submódulo, não é dependência e não
constitui evidência arquitetural. Nenhum pacote é instalado ou aprovado por
aparecer na lista.

`AWESOME_PYTHON_ENTRY != ADOPT`

`CATALOG_DISCOVERY != DEPENDENCY_APPROVAL`

`POPULAR != NECESSARY`

## Gate de avaliação independente

Antes de propor qualquer dependência Python runtime, registrar evidência
identificável para:

1. requisito real do produto;
2. alternativa na biblioteca padrão;
3. manutenção e atividade;
4. histórico de releases;
5. licença;
6. histórico de segurança;
7. peso das dependências transitivas;
8. compatibilidade Python;
9. compatibilidade Windows;
10. adequação offline/local-first;
11. testes determinísticos;
12. implicações de privacidade;
13. implicações de egress;
14. aderência arquitetural;
15. custo de rollback/remoção;
16. custo de manutenção de longo prazo.

Aplicam-se integralmente o
`docs/padroes/protocolo-pesquisa-ranking.md` e seus gates de licença,
segurança, Windows e packaging. Documentação oficial, upstream, PyPI e releases
são fontes primárias para fatos técnicos; a entrada no catálogo é apenas uma
pista de discovery.

Nenhum pacote pode ser adotado somente porque aparece no Awesome Python.
