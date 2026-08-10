# Manual operacional

## Finalidade

Este manual registra o fluxo macro aprovado para o sistema. Ele não declara
como implementada nenhuma automação, estrutura de dados ou integração ainda
inexistente.

## Fluxo macro

1. **Recebimento dos autos** — receber e organizar os elementos autorizados do
   processo de trabalho.
2. **Extração estruturada** — identificar dados, documentos, alegações,
   quesitos e lacunas, sem inventar conteúdo.
3. **`processo.json`** — futura consolidação estruturada dos dados processuais.
4. **Ficha pré-vistoria** — preparar informações, pendências e objetivos da
   diligência.
5. **Preparação da vistoria** — planejar escopo, participantes, instrumentos e
   registros necessários.
6. **Vistoria** — realizar constatações, medições e registros sob condução do
   perito.
7. **`vistoria.json`** — futura consolidação estruturada dos dados de campo.
8. **Análise por `PAT-NNN`** — analisar cada manifestação como unidade
   rastreável conforme os padrões canônicos.
9. **Redação técnica** — redigir análise, consequências, classificação e
   conclusão específica.
10. **`laudo.json`** — futura fonte estruturada única do laudo.
11. **Conclusão** — consolidar somente resultados já fundamentados e aprovados
    pelo perito.
12. **Quesitos** — responder integralmente os conjuntos identificados.
13. **Orçamento** — incluir somente itens que atendam aos requisitos técnicos
    canônicos.
14. **Revisão** — auditar integridade, coerência, rastreabilidade e completude.
15. **Preenchimento do modelo Word** — preencher futuramente o DOCM preservando
    o padrão visual aprovado.
16. **Revisão final do DOCM/PDF** — conferir conteúdo, campos, paginação e
    resultado visual.
17. **Validação e liberação pelo perito** — etapa final e indelegável.

## Estado de implementação

### Disponível atualmente

- padrões documentais canônicos;
- checklists iniciais;
- skills de redação e revisão;
- contratos JSON Schema iniciais para processo, vistoria, patologia e laudo;
- fixtures fictícias e validador local dos contratos;
- referências privadas locais para comparação;
- arquitetura preparada para evolução futura.

### Ainda não implementado

- extração estruturada automatizada;
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
