# Padrão canônico de estrutura do laudo

## Status

**REGRA APROVADA.** O modelo documental é selecionado pelo tipo de perícia. A
estrutura abaixo é exclusiva de `VICIOS_CONSTRUTIVOS` e não deve ser aplicada
automaticamente a avaliação, acidente viário ou outra especialidade.

## Estrutura judicial para vícios construtivos

1. **CONSIDERAÇÕES GERAIS**
   - 1.1 Identificação do Processo.
   - 1.2 Qualificação do Perito Nomeado.
   - 1.3 Preâmbulo.
   - 1.4 Síntese Processual e Delimitação do Tema Controvertido.
   - 1.5 Objeto da Perícia.
   - 1.6 Objetivo da Perícia.
2. **METODOLOGIA E NORMAS TÉCNICAS**
   - 2.1 Metodologia Adotada.
   - 2.2 Normas Técnicas Aplicáveis.
   - 2.3 Definições Técnicas Necessárias.
   - 2.4 Classificação das Origens.
   - 2.5 Classificação da Criticidade.
   - 2.6 Limitações da Inspeção.
3. **VISTORIA**
   - 3.1 Dados da Diligência Pericial.
   - 3.2 Condições Gerais da Edificação.
   - 3.3 Análise dos Sistemas Construtivos, somente para sistemas pertinentes.
4. **CONCLUSÃO**
   - 4.1 Avaliação das Classificações.
   - 4.2 Quadro-Resumo das Manifestações Analisadas.
   - 4.3 Síntese Conclusiva do Tema Controvertido.
5. **QUESITOS**, agrupados por Juízo, parte autora, parte ré e demais origens
   efetivamente existentes.
6. **ORÇAMENTO**, somente quando tecnicamente aplicável.
7. **REFERÊNCIAS BIBLIOGRÁFICAS**, restritas às fontes utilizadas.
8. **ENCERRAMENTO**.

## Tema, objeto e objetivo

- O item 1.4 responde por que a perícia existe e qual dúvida técnica deve ser
  saneada. Deve derivar dos autos, com precedência da decisão judicial, ser
  neutro e normalmente ocupar de meia a uma página.
- O objeto identifica o bem, sistema, local ou elemento examinado.
- O objetivo identifica as operações técnicas necessárias para responder ao
  tema.
- Repetição semântica entre os três campos deve gerar
  `REDUNDANCIA_ESTRUTURAL`, sem mudança de conteúdo técnico.
- O item 4.3 fecha explicitamente o ciclo iniciado no item 1.4 e não é mera
  cópia do quadro 4.2.

## Conteúdo semântico e apresentação

`laudo.json` representa conteúdo e rastreabilidade. Fontes, margens,
cabeçalhos, rodapés, campos Word e quebras de página pertencem à futura camada
Word 365 e não integram esse contrato semântico.

## Regras de composição

- Cada `PAT-NNN` mantém exatamente os quatro blocos definidos em
  [padrão de patologia](padrao-patologia.md).
- O quadro 4.2, as respostas aos quesitos e o orçamento não podem criar ou
  alterar conclusão.
- Subseção de quesitos sem itens deve ser omitida.
- A numeração não pode ser duplicada.
- A extensão decorre da complexidade; não há número mínimo de páginas.

## Pendências de validação do perito

- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir os modelos documentais dos
  demais tipos de perícia.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir anexos e apêndices canônicos.
