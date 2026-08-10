# Padrão visual canônico para Word

## Status

**REGRA APROVADA.** Preservar o sistema visual existente, tomando o laudo
Eliane Ferreira de Souza como referência principal. O modelo não será recriado
do zero.

## Formato

- Manter o formato `.docm` nesta fase.
- Usar página A4, orientação retrato.
- Preservar a geometria geral da referência visual.
- Adotar como medidas observadas: margem superior, direita e inferior de
  2,54 cm; margem esquerda de aproximadamente 3 cm; cabeçalho de
  aproximadamente 1,25 cm; rodapé de aproximadamente 0,87 cm.

## Identidade visual

- Preservar logotipo e identidade HF.
- Preservar cabeçalho com marca no canto superior esquerdo e identificação
  profissional no canto superior direito.
- Preservar linha ou barra discreta de separação no cabeçalho.
- Preservar marca d'água HF central em baixa opacidade.
- Preservar rodapé institucional e paginação `Página X de Y`.
- Preservar barras de abertura dos capítulos.

## Tipografia e cores

- Usar Arial como fonte predominante.
- Usar 11 pt como corpo predominante.
- Reservar tamanhos menores para legendas, tabelas e elementos auxiliares.
- Manter títulos e subtítulos pela hierarquia de estilos, sem formatação manual
  concorrente.
- Manter texto principal preto ou cinza muito escuro.
- Manter azul-claro ou cinza-azulado nos elementos de identidade e hierarquia.
- Usar amarelo no orçamento somente para função tabular já definida e de modo
  consistente.

## Parágrafos, títulos e espaçamento

- Manter o corpo predominantemente justificado.
- Aplicar estilos reais de título aos capítulos e subseções.
- Evitar títulos simulados apenas por caixa alta ou formatação direta.
- Manter espaçamento coerente entre título, texto, tabela, fotografia e
  legenda.
- Evitar que título, legenda ou linha de identificação fique isolado da unidade
  a que pertence.

## Tabelas e quadros

- Preservar a linguagem visual da síntese, dos quadros fotográficos, do
  quadro-resumo e do orçamento.
- Usar cabeçalhos de tabela visualmente distintos e consistentes.
- Não permitir células truncadas, sobrepostas ou com texto contra as bordas.
- Não usar o rótulo `NÃO CONFORMIDADE` para guardar situação `CONFORME` ou
  `INCONCLUSIVA`; usar `CONSTATAÇÃO` conforme
  `docs/padroes/terminologia.md`.

## Sumário e paginação

- Manter sumário automático por campo `TOC`.
- Manter referências de página por `PAGEREF`.
- Manter numeração de figuras e tabelas por `SEQ` quando aplicável.
- Atualizar todos os campos antes da emissão.
- Conferir se a quantidade declarada no encerramento coincide com o PDF final.

## Formato DOCM

Os arquivos analisados possuem bookmarks, campos e estilos úteis, mas não
contêm `vbaProject.bin`. Não desenvolver VBA nesta etapa. A automação será
definida posteriormente.

## Pendências de validação do perito

- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** confirmar as medidas definitivas por
  inspeção do futuro modelo mestre no Microsoft Word.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** selecionar a versão oficial dos
  arquivos de logotipo, selo e assinatura.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** fixar códigos de cor exatos.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** fixar tamanhos e espaçamentos de cada
  estilo após a consolidação do DOCM.
