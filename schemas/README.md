# Contratos de dados

Esta pasta contém os contratos de dados iniciais do projeto em JSON Schema Draft 2020-12.

## Arquivos

- `processo.schema.json`: dados extraídos dos autos, separados em documentos, alegações, quesitos, decisões, conflitos e pendências.
- `vistoria.schema.json`: planejamento e registro da vistoria, incluindo participantes, métodos, equipamentos, limitações, fotografias e constatações de campo.
- `patologia.schema.json`: unidade técnica `PAT-NNN`, suas evidências, análise causal, classificações, conclusão e elegibilidade orçamentária.
- `laudo.schema.json`: agregação rastreável do laudo, com referências às patologias, quesitos, orçamento, normas e validação final.
- `pje-comum.schema.json`: definições reutilizáveis de proveniência, confiança, paginação, reconciliação, conflitos e elementos extraídos do PJe.
- `manifesto-pje.schema.json`: inventário e segmentação do PDF consolidado, sem duplicar o conteúdo integral dos documentos.
- `documento-pje.schema.json`: conteúdo estruturado de um documento PJe e de suas seções e anexos internos.

Os schemas rejeitam propriedades não declaradas. Alegações, documentos, constatações, inferências e resultados inconclusivos devem permanecer semanticamente separados.

## Dependência externa

A validação usa o pacote Python `jsonschema`, declarado em `requirements.txt`. O pacote instala também `referencing`, usado para resolver referências entre os schemas.

```powershell
python -m pip install -r requirements.txt
python scripts/validar_schemas.py
```

O validador confere os próprios schemas e os exemplos em
`tests/fixtures/schemas/` e `tests/fixtures/pje/`. Arquivos com sufixo
`-valido.json` ou `-valida.json` devem ser aceitos; os demais exemplos dessas
pastas são casos negativos e devem ser rejeitados.

## Fluxo de dados previsto

```text
PDF PJe
→ manifesto-pje.json
→ documento-pje.json
→ processo.json
→ vistoria.json
→ laudo.json
```

Os contratos do manifesto e do documento PJe estão implementados. O parser
estrutural determinístico gera `manifesto-pje.json`; a geração de
`documento-pje.json` e a transformação para `processo.json` ainda não estão
implementadas.

## Limitações atuais

- Os schemas são contratos iniciais e não substituem a validação técnica do perito.
- Unicidade e integridade referencial entre arquivos distintos exigirão validação complementar futura.
- A extração atual termina no manifesto estrutural: não há OCR, interpretação
  semântica, geração de `documento-pje.json` ou automação Word.
- Não há automação de cálculos, normas, quesitos ou orçamento.
- Alterações nos enums e nas condicionais dependem de decisão canônica documentada.
