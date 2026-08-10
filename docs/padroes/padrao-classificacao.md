# Padrão canônico de classificação

## Status

**REGRA APROVADA.** Situação, origem e criticidade são dimensões independentes.
Não combinar categorias em um único campo.

## Situação da constatação

Valores permitidos:

- `CONFORME`
- `ANOMALIA`
- `FALHA`
- `INCONCLUSIVA`
- `NÃO CONSTATADA`

Usar o rótulo neutro `CONSTATAÇÃO` no quadro fotográfico. Não usar
`NÃO CONFORMIDADE` para armazenar `CONFORME`, `INCONCLUSIVA` ou outra situação
semanticamente incompatível.

## Origem

Valores permitidos:

- `ENDÓGENA/CONSTRUTIVA`
- `EXÓGENA`
- `FUNCIONAL`
- `USO/OPERAÇÃO/MANUTENÇÃO`
- `MISTA`
- `INCONCLUSIVA`
- `NÃO APLICÁVEL`

A origem deve decorrer da análise causal e ser validada pelo perito. Não usar
idade, prazo de garantia ou ausência documental como substitutos isolados do
diagnóstico.

## Criticidade

Valores permitidos:

- `CRÍTICA`
- `MÉDIA`
- `MÍNIMA`
- `NÃO APLICÁVEL`

Usar sempre a forma feminina para concordar com `criticidade`. Fundamentar a
categoria aplicada e não copiar classificação de outro processo.

## Prazo de garantia

Prazo de garantia e origem técnica são dimensões diferentes. A ocorrência após
determinado prazo não permite, isoladamente:

- classificar a origem como funcional;
- afastar possível origem construtiva;
- concluir responsabilidade ou ausência de responsabilidade.

O prazo pode integrar a análise temporal, mas não substituir o diagnóstico
causal.

## Vício construtivo

Aplicar os requisitos cumulativos de
`docs/padroes/padrao-patologia.md`. A classificação técnica não autoriza
conclusões jurídicas.

## Regras de consistência

- O quadro-resumo deve reproduzir as categorias aprovadas na análise.
- Quesitos e orçamento não podem alterar silenciosamente a classificação.
- Divergência entre texto, quadro, resposta ou orçamento deve bloquear a
  finalização até revisão do perito.

## Pendências de validação do perito

- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** aprovar definições técnicas detalhadas
  e critérios de enquadramento de cada categoria.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir como registrar classificações
  múltiplas ou concorrentes na origem `MISTA`.
