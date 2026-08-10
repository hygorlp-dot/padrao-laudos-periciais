# Terminologia canônica

## Status

**REGRA APROVADA.** Usar os termos e valores controlados deste documento.
Termos técnicos ainda sem definição aprovada permanecem pendentes.

## Campo neutro para o quadro fotográfico

Usar `CONSTATAÇÃO` como rótulo do campo que registra a situação observada. Não
usar `NÃO CONFORMIDADE` como rótulo genérico.

## Valores controlados

### Situação da constatação

- `CONFORME`
- `ANOMALIA`
- `FALHA`
- `INCONCLUSIVA`
- `NÃO CONSTATADA`

### Origem

- `ENDÓGENA/CONSTRUTIVA`
- `EXÓGENA`
- `FUNCIONAL`
- `USO/OPERAÇÃO/MANUTENÇÃO`
- `MISTA`
- `INCONCLUSIVA`
- `NÃO APLICÁVEL`

### Criticidade

- `CRÍTICA`
- `MÉDIA`
- `MÍNIMA`
- `NÃO APLICÁVEL`

## Termos com uso condicionado

| Termo | Condição de uso |
|---|---|
| Manifestação patológica | Usar para o fenômeno analisado, sem presumir origem ou responsabilidade. |
| Anomalia | Usar como situação somente após constatação e enquadramento técnico. |
| Falha | Usar conforme critério técnico aprovado, sem confundir automaticamente com anomalia. |
| Vício construtivo | Usar somente quando atendidos os requisitos de `docs/padroes/padrao-patologia.md` e houver aprovação do perito. |
| Causa provável | Usar quando houver suporte, mas não certeza suficiente para causa constatada. |
| Inconclusiva | Usar quando os elementos não permitirem conclusão segura. |

## Expressões proibidas ou a evitar

Não usar como conclusão pericial automática:

- `vício indenizável`;
- `reparação indenizável`;
- `a parte tem direito`;
- `está prescrito`;
- `não está prescrito`.

Não concluir responsabilidade civil, culpa, legitimidade, prescrição,
decadência, direito à indenização ou vício redibitório como qualificação
jurídica.

## Marcadores canônicos

- Dado ausente: `[INFORMAÇÃO NECESSÁRIA: descrever o dado]`.
- Decisão técnica pendente: `[VALIDAÇÃO DO PERITO: descrever a decisão]`.
- Sistema sem suporte suficiente:
  `[VALIDAÇÃO DO PERITO: sistema construtivo não documentalmente confirmado]`.
- Edição normativa divergente ou não confirmada:
  `[VALIDAÇÃO DO PERITO: confirmar edição normativa aplicável]`.

## Convenções

- Usar `R:` no início das respostas aos quesitos.
- Usar `PAT-NNN` para manifestação.
- Reservar `QUE-NNN` para identificador interno de quesito.
- Reservar `ORC-NNN` para identificador interno de item orçamentário.
- Usar a forma feminina `CRÍTICA`, `MÉDIA` e `MÍNIMA` para criticidade.

## Abreviações e siglas pendentes

| Forma | Significado | Regra para a primeira ocorrência | Contexto autorizado |
|---|---|---|---|
| `[A PREENCHER]` | `[A PREENCHER]` | `[VALIDAÇÃO DO PERITO]` | `[A PREENCHER]` |

Nenhuma abreviação ainda não aprovada deve ser inferida dos laudos de
referência.

## Unidades e notação pendentes

| Grandeza | Unidade autorizada | Símbolo | Casas decimais | Regra de apresentação |
|---|---|---|---|---|
| `[A PREENCHER]` | `[A PREENCHER]` | `[A PREENCHER]` | `[VALIDAÇÃO DO PERITO]` | `[VALIDAÇÃO DO PERITO]` |

## Expressões técnicas pendentes

| Expressão | Definição adotada | Escopo | Fonte técnica | Restrições de uso |
|---|---|---|---|---|
| `[A PREENCHER]` | `[VALIDAÇÃO DO PERITO]` | `[A PREENCHER]` | `[A PREENCHER]` | `[VALIDAÇÃO DO PERITO]` |

## Pendências de validação do perito

- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir tecnicamente a distinção entre
  `ANOMALIA` e `FALHA` para os tipos de perícia abrangidos.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** aprovar abreviações, siglas, unidades,
  símbolos e casas decimais.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** aprovar glossário técnico por sistema.
