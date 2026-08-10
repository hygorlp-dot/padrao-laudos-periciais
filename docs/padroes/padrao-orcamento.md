# Padrão canônico de orçamento

## Status

**REGRA APROVADA.** O orçamento é consequência da análise técnica e não pode
criar, ampliar ou reclassificar manifestação.

## Critérios cumulativos de inclusão

Uma manifestação somente poderá integrar o orçamento quando:

- estiver abrangida pelo objeto da perícia;
- estiver efetivamente constatada;
- estiver classificada como `ANOMALIA`;
- tiver origem `ENDÓGENA/CONSTRUTIVA` validada pelo perito;
- possuir serviço necessário definido;
- possuir quantitativo tecnicamente justificado;
- possuir memória de cálculo;
- possuir conclusão técnica aprovada pelo perito.

## Situações sem geração automática de item

Não gerar automaticamente item orçamentário para:

- `CONFORME`;
- `NÃO CONSTATADA`;
- `INCONCLUSIVA`;
- origem `FUNCIONAL`;
- origem `EXÓGENA`;
- origem `USO/OPERAÇÃO/MANUTENÇÃO`;
- origem ainda não validada.

Qualquer exceção depende de decisão expressa do perito e não representa, por si
só, indenização ou responsabilidade jurídica.

## Identificação e rastreabilidade

- Atribuir identificador interno ao item no formato futuro `ORC-NNN`.
- Relacionar cada item a pelo menos uma manifestação `PAT-NNN`.
- Relacionar, quando aplicável, quesitos `QUE-NNN`.
- Impedir item sem origem técnica, serviço, quantitativo e memória de cálculo.
- Manter uma única fonte para quantidade, preço, BDI e total repetidos.

## Estrutura mínima

- item;
- fonte;
- código;
- descrição do serviço;
- unidade;
- quantidade;
- memória de cálculo;
- custo unitário sem BDI;
- BDI;
- preço unitário com BDI;
- preço total;
- data-base;
- manifestação `PAT-NNN` relacionada;
- observações e limitações.

## Conferências

- Conferir unidades e casas decimais.
- Recalcular preços unitários, totais, subtotais e total geral.
- Conferir a vigência e a localidade da fonte de preços.
- Conferir se cada serviço corresponde à recomendação aprovada.
- Conferir se quadro-resumo, quesitos e orçamento usam a mesma classificação.

## Pendências de validação do perito

- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir fontes de preços autorizadas e
  sua hierarquia.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir critérios de BDI, encargos,
  arredondamento e data-base.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir o modelo da memória de cálculo.
