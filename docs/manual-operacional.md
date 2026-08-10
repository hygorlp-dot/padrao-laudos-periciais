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
   e, futuramente, cada peça em `documento-pje.json`.
4. **`processo.json`** — futura consolidação estruturada dos dados processuais.
5. **Ficha pré-vistoria** — preparar informações, pendências e objetivos da
   diligência.
6. **Preparação da vistoria** — planejar escopo, participantes, instrumentos e
   registros necessários.
7. **Vistoria** — realizar constatações, medições e registros sob condução do
   perito.
8. **`vistoria.json`** — futura consolidação estruturada dos dados de campo.
9. **Análise por `PAT-NNN`** — analisar cada manifestação como unidade
   rastreável conforme os padrões canônicos.
10. **Redação técnica** — redigir análise, consequências, classificação e
   conclusão específica.
11. **`laudo.json`** — futura fonte estruturada única do laudo.
12. **Conclusão** — consolidar somente resultados já fundamentados e aprovados
    pelo perito.
13. **Quesitos** — responder integralmente os conjuntos identificados.
14. **Orçamento** — incluir somente itens que atendam aos requisitos técnicos
    canônicos.
15. **Revisão** — auditar integridade, coerência, rastreabilidade e completude.
16. **Preenchimento do modelo Word** — preencher futuramente o DOCM preservando
    o padrão visual aprovado.
17. **Revisão final do DOCM/PDF** — conferir conteúdo, campos, paginação e
    resultado visual.
18. **Validação e liberação pelo perito** — etapa final e indelegável.

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
- referências privadas locais para comparação;
- arquitetura preparada para evolução futura.

### Ainda não implementado

- extração semântica automatizada;
- geração de `documento-pje.json`;
- `processo.json`, `vistoria.json` e `laudo.json`;
- geração automática de fichas;
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
