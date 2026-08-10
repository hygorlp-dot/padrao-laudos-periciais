# Manual operacional

## Finalidade

Este manual registra o fluxo macro aprovado e distingue o que já está
implementado do que permanece previsto.

## Fluxo macro

1. **Recebimento dos autos** — receber e organizar os elementos autorizados do
   processo de trabalho.
2. **Extração estruturada** — identificar dados, documentos, alegações,
   quesitos e lacunas, sem inventar conteúdo.
3. **Contratos PJe** — representar o PDF consolidado em `manifesto-pje.json`
   e cada peça reconciliada em `documento-pje.json`.
4. **Triagem e delimitação pericial** — leitura semântica pelo Codex, com tipo
   de perícia, tema controvertido, objeto, objetivo, questões técnicas,
   quesitos, ressalvas, conflitos e plano preliminar em
   `delimitacao-pericial.json`.
5. **`processo.json`** — consolidação semântica rastreável do que consta nos
   autos.
6. **Conhecimento pertinente** — inventariar e recuperar normas e modelos
   privados sem convertê-los em fatos do caso.
7. **Plano e ficha pré-vistoria** — definir atividades, medições, fotografias,
   equipamentos, documentos e cobertura dos quesitos.
8. **Vistoria** — realizar constatações, medições e registros sob condução do
   perito.
9. **`vistoria.json`** — futura consolidação estruturada dos dados de campo.
10. **Análise por `PAT-NNN`** — analisar cada manifestação como unidade
   rastreável conforme os padrões canônicos.
11. **Redação técnica** — redigir análise, consequências, classificação e
   conclusão específica.
12. **`laudo.json`** — futura fonte estruturada única do laudo.
13. **Conclusão** — consolidar somente resultados já fundamentados e aprovados
    pelo perito.
14. **Quesitos** — responder integralmente os conjuntos identificados.
15. **Orçamento** — incluir somente itens que atendam aos requisitos técnicos
    canônicos.
16. **Revisão** — auditar integridade, coerência, rastreabilidade e completude.
17. **Preenchimento do modelo Word** — preencher futuramente o DOCM preservando
    o padrão visual aprovado.
18. **Revisão final do DOCM/PDF** — conferir conteúdo, campos, paginação e
    resultado visual.
19. **Validação e liberação pelo perito** — etapa final e indelegável.

## Estado de implementação

### Disponível atualmente

- padrões documentais canônicos;
- checklists iniciais;
- skills de redação e revisão;
- contratos JSON Schema iniciais para PJe, processo, vistoria, patologia e
  laudo;
- fixtures fictícias e validador local dos contratos;
- parser estrutural determinístico de PDF PJe para `manifesto-pje.json`, sem
  OCR nem extração semântica;
- geração determinística de `documento-pje.json` a partir dos intervalos
  reconciliados do manifesto, com texto digital e catálogo estrutural;
- contrato, padrão, Skill e validador relacional da triagem e delimitação;
- geração de `processo.json`, inventário incremental de conhecimento privado,
  recuperação pertinente, plano-vistoria e ficha pré-vistoria;
- referências privadas locais para comparação;
- arquitetura preparada para evolução futura.

### Ainda não implementado

- serviço autônomo de extração semântica sem intervenção do Codex;
- `vistoria.json` e `laudo.json`;
- automação de rastreabilidade entre `PAT-NNN`, fotografias, quesitos e
  orçamento;
- preenchimento automático do DOCM;
- atualização automática de campos Word;
- automação de revisão do DOCM/PDF;
- demais scripts e integrações operacionais.

## Documentos de apoio

- [Regras periciais](./padroes/regras-periciais.md).
- [Estrutura do laudo](./padroes/padrao-estrutura-laudo.md).
- [Padrão de patologia](./padroes/padrao-patologia.md).
- [Padrão de quesitos](./padroes/padrao-quesitos.md).
- [Padrão de orçamento](./padroes/padrao-orcamento.md).
- [Padrão de delimitação pericial](./padroes/padrao-delimitacao-pericial.md).
- [Padrão de planejamento e pré-vistoria](./padroes/padrao-planejamento-vistoria.md).
