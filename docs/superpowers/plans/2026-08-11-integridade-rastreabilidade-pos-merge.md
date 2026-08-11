# Integridade e rastreabilidade pós-merge — plano de implementação

> **Para agentes executores:** usar `executing-plans` para executar este plano
> tarefa por tarefa, preservando RED → GREEN → regressão.

**Objetivo:** eliminar perdas silenciosas e proveniência falsa nos boundaries
PJe, Triagem, Motor e Redação sem IA, API, UI ou dados privados.

**Arquitetura:** cada produtor passa a emitir metadados estruturados suficientes
para o consumidor recalcular integridade. Validadores independentes recusam
cardinalidade, proveniência, correção ou fidelidade que não possam ser provadas.

**Tecnologia:** Python 3, `unittest`, JSON Schema 2020-12 e PDFs sintéticos.

## Restrições globais

- Issue #25; branch `fix/25-integridade-rastreabilidade`; um PR draft.
- Nenhum acesso ou versionamento de `referencias/privadas/`.
- Nenhuma IA/API/UI ou dependência nova.
- Toda correção começa por reprodução e teste RED observável.

### Tarefa 1: cardinalidade e links do índice PJe

**Arquivos:** `scripts/extracao_pje/extrair_indice.py`,
`scripts/extracao_pje/segmentar_documentos.py`,
`scripts/extracao_pje/validar_integridade.py`, schemas PJe e testes.

- [ ] Criar adversariais para destinos únicos, colisão, rodapé incompatível,
  descoberta sem índice e invariância por ordem.
- [ ] Confirmar RED causado pelo mapa destrutivo página→item.
- [ ] Emitir associação por item com página de origem, método, candidatos,
  destino e confiança; colisão vira conflito bloqueante.
- [ ] Recalcular accounting integral no validator e versionar contrato se houver
  breaking change.
- [ ] Executar testes PJe direcionados e schemas.

### Tarefa 2: proveniência multipágina da capa

**Arquivos:** `scripts/extracao_pje/extrair_capa.py` e testes PJe.

- [ ] Criar RED para campos nas páginas 2/3, repetição idêntica, conflito real e
  ausência sem página fabricada.
- [ ] Extrair por pares `(pagina_pdf, texto)` e preservar todas as fontes reais.
- [ ] Adicionar PDF sintético multipágina e validar schema/manifesto.

### Tarefa 3: catálogo corrigido e trilha completa

**Arquivos:** `scripts/motor_vicios/autocorrigir.py`,
`scripts/motor_vicios/pipeline.py` e testes do Motor.

- [ ] Criar RED para os quatro achados de catálogo e restauração stale.
- [ ] Fazer a segunda auditoria consumir o catálogo corrigido.
- [ ] Registrar alvo, antes, depois, achado, ação, motivo e evidência para toda
  mutação, sem tocar no objeto primário original.
- [ ] Provar desaparecimento condicionado, idempotência e gates recalculados.

### Tarefa 4: isolamento do quesito jurídico

**Arquivos:** `scripts/planejamento_pericial/aprofundar_delimitacao.py`,
validator/autoauditoria da Triagem e testes integrados.

- [ ] Criar RED para jurídico puro contaminado, idempotência, parcial,
  repetitivo, planejamento e resposta da Redação.
- [ ] Limpar todos os vínculos técnicos do jurídico puro sem chamar matcher;
  preservar o componente técnico parcial.
- [ ] Recalcular o mesmo invariante no validator e na autoauditoria.

### Tarefa 5: fidelidade canônica de datas

**Arquivos:** módulo dedicado de datas em `scripts/redacao_pericial/`,
`auditar_fidelidade.py`, pipeline e testes da Redação.

- [ ] Criar RED para formatos equivalentes, alteração, invenção, ausência de
  `data_laudo`, escopos de diligência/documento/norma e falsos positivos.
- [ ] Implementar parser real baseado em `datetime`, sem substring nem conversão
  de anos/normas/processos/valores em datas.
- [ ] Vincular data normalizada à fonte autorizada e integrar achados bloqueantes
  aos dois auditores e ao gate.

### Tarefa 6: sweep, regressão e entrega

**Arquivos:** testes adversariais e review package do PR.

- [ ] Auditar os boundaries completos solicitados e corrigir P0/P1 reproduzido
  da mesma classe com novo ciclo RED/GREEN.
- [ ] Executar suíte integral, schemas/fixtures, compileall, guards/privacy,
  diff-check e E2E PDF positivo/negativo.
- [ ] Solicitar revisão independente apenas no HEAD final; corrigir achados.
- [ ] Commitar atomicamente, enviar branch, abrir/atualizar PR draft e persistir
  review package vinculado ao SHA. Não fazer merge.
