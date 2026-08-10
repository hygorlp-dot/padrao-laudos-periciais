# Contratos de dados

Esta pasta contém os contratos de dados iniciais do projeto em JSON Schema Draft 2020-12.

## Arquivos

- `processo.schema.json`: dados extraídos dos autos, separados em documentos, alegações, quesitos, decisões, conflitos e pendências.
- `vistoria.schema.json`: planejamento e registro da vistoria, incluindo participantes, métodos, equipamentos, limitações, fotografias e constatações de campo.
- `patologia.schema.json`: unidade técnica `PAT-NNN`, suas evidências, análise causal, classificações, conclusão e elegibilidade orçamentária.
- `laudo.schema.json`: agregação rastreável do laudo, com referências às patologias, quesitos, orçamento, normas e validação final.

Os schemas rejeitam propriedades não declaradas. Alegações, documentos, constatações, inferências e resultados inconclusivos devem permanecer semanticamente separados.

## Dependência externa

A validação usa o pacote Python `jsonschema`, declarado em `requirements.txt`. O pacote instala também `referencing`, usado para resolver referências entre os schemas.

```powershell
python -m pip install -r requirements.txt
python scripts/validar_schemas.py
```

O validador confere os próprios schemas e os exemplos em `tests/fixtures/schemas/`. Arquivos com sufixo `-valido.json` ou `-valida.json` devem ser aceitos; os demais exemplos dessa pasta são casos negativos e devem ser rejeitados.

## Limitações atuais

- Os schemas são contratos iniciais e não substituem a validação técnica do perito.
- Unicidade e integridade referencial entre arquivos distintos exigirão validação complementar futura.
- Não há geração automática de `processo.json`, `vistoria.json`, `laudo.json` ou documento Word.
- Não há automação de cálculos, normas, quesitos ou orçamento.
- Alterações nos enums e nas condicionais dependem de decisão canônica documentada.
