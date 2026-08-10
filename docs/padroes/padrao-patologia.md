# Padrão canônico de manifestação patológica

## Status

**REGRA APROVADA.** Toda manifestação analisada deve formar uma unidade
rastreável e permanecer sujeita à validação técnica do perito.

## Identificador

- Atribuir identificador único no formato `PAT-NNN`.
- Não reutilizar identificador no mesmo laudo.
- Manter o identificador em alegações, fotografias, análise, quadro-resumo,
  quesitos relacionados e eventual orçamento.

## Dados internos obrigatórios

Cada `PAT-NNN` deve relacionar:

- alegação e sua fonte;
- ambiente ou local;
- sistema;
- fotografias;
- constatação;
- método utilizado;
- extensão;
- causa provável;
- causas alternativas;
- limitações;
- normas utilizadas;
- situação;
- origem;
- criticidade;
- grau de certeza;
- consequências;
- recomendação;
- conclusão;
- presença no quadro-resumo;
- quesitos relacionados;
- eventual item de orçamento.

## Estrutura textual obrigatória

### 1. Análise das Alegações e Prováveis Causas

- Identificar a alegação e sua origem.
- Descrever a constatação de modo independente.
- Informar ambiente, sistema, fotografias, método e extensão.
- Distinguir causa provável de causas alternativas.
- Registrar limitações e grau de certeza.
- Citar apenas referência efetivamente necessária.

### 2. Consequências

- Registrar efeitos observados ou tecnicamente sustentados.
- Não ampliar consequências por plausibilidade.
- Separar desempenho, segurança, funcionalidade, durabilidade, estética e
  manutenção quando pertinentes.

### 3. Classificação

- Aplicar separadamente situação, origem e criticidade conforme
  `docs/padroes/padrao-classificacao.md`.
- Não usar `vício construtivo` como sinônimo de manifestação patológica.

### 4. Conclusão

- Responder se a alegação foi confirmada, não confirmada ou permaneceu
  inconclusiva.
- Sintetizar causa, origem, criticidade, limitações e recomendação já
  fundamentadas.
- Submeter a conclusão à aprovação do perito.

## Caracterização de vício construtivo

Somente caracterizar tecnicamente como vício construtivo quando, em conjunto:

- houver manifestação ou perda de desempenho constatada;
- houver suporte técnico suficiente;
- a origem estiver classificada e validada como `ENDÓGENA/CONSTRUTIVA`;
- a conclusão estiver aprovada pelo perito.

Não extrair dessa caracterização conclusão jurídica ou direito à indenização.

## Sistema construtivo

Não presumir paredes de concreto, concreto armado porticado, pórticos,
alvenaria estrutural ou qualquer outro sistema. Na ausência de suporte, usar:

`[VALIDAÇÃO DO PERITO: sistema construtivo não documentalmente confirmado]`

## Rastreabilidade

Preservar a cadeia:

`alegação → PAT → fotografia → ambiente → sistema → constatação → classificação → criticidade → conclusão → quadro-resumo → quesitos → orçamento`

Toda informação repetida deverá ter uma única fonte de dados quando a futura
automação for implementada.

## Pendências de validação do perito

- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir escala canônica de grau de
  certeza.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir métodos e campos obrigatórios
  por especialidade ou sistema.
