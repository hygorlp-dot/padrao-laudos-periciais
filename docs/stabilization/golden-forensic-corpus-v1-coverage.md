# Golden Forensic Corpus V1 -- Coverage Map

Gerado por `python -m scripts.quality.golden_corpus --coverage-map`. Não editar manualmente.

Apenas casos com `status: APPROVED` contam para a cobertura abaixo. Casos `CHARACTERIZED_NOT_APPROVED`/`KNOWN_BUG` continuam pinados (qualquer drift ainda quebra o gate), mas ficam fora da contagem de cobertura -- ver docs/stabilization/hotspot-characterization-v1.md e o próprio corpus para o detalhe de cada um.

| Família semântica | HOTSPOT-01 | HOTSPOT-02 | HOTSPOT-03 | HOTSPOT-04 | HOTSPOT-05 |
| --- | --- | --- | --- | --- | --- |
| absent_information | GC-MOTOR-010 | GC-VISTORIA-004, GC-VISTORIA-006, GC-VISTORIA-008, GC-VISTORIA-009 | GC-DELIM-001 | GC-INTEGRIDADE-013 |  |
| ai_proposal_not_effective_alone |  | N/A | N/A | N/A | GC-AUTOCORRIGIR-001, GC-AUTOCORRIGIR-002, GC-AUTOCORRIGIR-003 |
| allegations |  | GC-VISTORIA-003 | GC-DELIM-001, GC-DELIM-006 |  |  |
| contradictory_evidence | GC-MOTOR-002 |  | N/A | GC-INTEGRIDADE-001, GC-INTEGRIDADE-002, GC-INTEGRIDADE-004, GC-INTEGRIDADE-005, GC-INTEGRIDADE-007, GC-INTEGRIDADE-008, GC-INTEGRIDADE-010, GC-INTEGRIDADE-011, GC-INTEGRIDADE-014 | GC-AUTOCORRIGIR-005 |
| correction_persistence |  | N/A | N/A | N/A | GC-AUTOCORRIGIR-001, GC-AUTOCORRIGIR-002, GC-AUTOCORRIGIR-003, GC-AUTOCORRIGIR-004, GC-AUTOCORRIGIR-005 |
| deterministic_replay | GC-MOTOR-006 | GC-VISTORIA-005 | GC-DELIM-001 | GC-INTEGRIDADE-000 | GC-AUTOCORRIGIR-006 |
| documentary_evidence |  | GC-VISTORIA-007 | GC-DELIM-001, GC-DELIM-002, GC-DELIM-003 |  |  |
| duplicate_inputs |  |  | GC-DELIM-005, GC-DELIM-009 | GC-INTEGRIDADE-003 |  |
| engine_decision | GC-MOTOR-001, GC-MOTOR-004, GC-MOTOR-005, GC-MOTOR-008, GC-MOTOR-010 |  | GC-DELIM-001, GC-DELIM-002, GC-DELIM-003, GC-DELIM-004, GC-DELIM-005, GC-DELIM-006, GC-DELIM-007, GC-DELIM-010B | GC-INTEGRIDADE-001 | GC-AUTOCORRIGIR-003, GC-AUTOCORRIGIR-005 |
| equivalent_input_representations |  |  | GC-DELIM-009 | N/A |  |
| inconclusive_findings | GC-MOTOR-005, GC-MOTOR-009 | GC-VISTORIA-002 | GC-DELIM-007, GC-DELIM-010 |  | GC-AUTOCORRIGIR-001 |
| measurements | GC-MOTOR-004 | GC-VISTORIA-005 | N/A | GC-INTEGRIDADE-006, GC-INTEGRIDADE-007, GC-INTEGRIDADE-008 |  |
| normative_references | GC-MOTOR-004 | N/A | GC-DELIM-002 | N/A | GC-AUTOCORRIGIR-004 |
| not_observed |  | GC-VISTORIA-004 | N/A |  |  |
| observations |  | GC-VISTORIA-003 | N/A |  |  |
| professional_override |  | N/A | N/A | N/A |  |
| provenance | GC-MOTOR-001, GC-MOTOR-007 | GC-VISTORIA-005 | GC-DELIM-001, GC-DELIM-002 | GC-INTEGRIDADE-005, GC-INTEGRIDADE-006, GC-INTEGRIDADE-009 |  |
| reordered_inputs | GC-MOTOR-007 |  |  | N/A |  |
| source_value |  |  | GC-DELIM-001 |  |  |
| technical_inference | GC-MOTOR-001, GC-MOTOR-002, GC-MOTOR-008, GC-MOTOR-009 | N/A | GC-DELIM-001, GC-DELIM-002, GC-DELIM-003, GC-DELIM-004, GC-DELIM-005 |  |  |
| unverifiable_information |  | GC-VISTORIA-002, GC-VISTORIA-009 | GC-DELIM-010 | GC-INTEGRIDADE-009 |  |

## Caminhos conhecidos como inalcançáveis hoje (sem caso golden)

- **HOTSPOT-02** `scripts/vistoria_estruturada/gerar_vistoria.py:128 normalizar(obs.get('elemento'))` -- `latent_defect=True`, `golden_execution_case=None`. Nenhum caminho first-party de gerar() popula uma chave 'elemento' nos dicts de medicoes/fotos (nem o literal de medicoes.append em ~linha 90 nem o de fotos.append em ~linha 79 define essa chave) -- ver Issue #74 e docs/stabilization/hotspot-characterization-v1.md. Construir manualmente um dict intermediario com 'elemento' preenchido para exercitar essa linha criaria um contrato artificial para um caminho morto, nao uma caracterizacao de comportamento real. Sem caso golden ate que exista uma entrada first-party legitima que torne o caminho alcancavel.
- **HOTSPOT-02** `scripts/vistoria_estruturada/gerar_vistoria.py _comp() -- motivo/origem 'ATIVIDADE_ELEMENTO_MANIFESTACAO_CONVERGENTES' branch (linha ~137 no arquivo pre-HOTSPOT-02, dentro de _registrar_relacoes pos-refactor)` -- `latent_defect=True`, `golden_execution_case=None`. Consequencia direta da Issue #74: _comp()'s 4o disjuntor (atividade and elemento and manifestacao) so pode ser True se 'elemento' for True, e 'elemento' exige item.get('elemento') verdadeiro -- mas nenhum produtor de medicoes/fotos jamais popula a chave 'elemento' (confirmado por leitura: nem o literal de medicoes.append nem o de fotos.append definem essa chave). Logo _comp() so pode retornar True via explicito/registro/atividade_univoca, e o ramo 'else' de motivo/origem em _registrar_relacoes (ATIVIDADE_ELEMENTO_MANIFESTACAO_CONVERGENTES) e inalcancavel pela mesma causa raiz que torna normalizar() morto. Nao construir um caso golden artificial forcando 'elemento' -- isso criaria um contrato para um caminho morto duplo. Sem caso golden ate a Issue #74 ser resolvida de verdade. Modo de falha distinto do de normalizar()/#74: normalizar() indefinida gera NameError auto-anunciado (crash obvio se algum dia alcancado); ja este ramo, se um dia alcancavel (ex: alguem popular "elemento" resolvendo apenas a definicao de normalizar(), sem tratar #74 de verdade), NAO quebraria em teste algum -- mudaria silenciosamente motivo/origem de uma relacao de evidencia para ATIVIDADE_ELEMENTO_MANIFESTACAO_CONVERGENTES em vez de SEM_ASSOCIACAO, sem crash. Ao resolver #74, adicionar um caso golden dedicado para este ramo especificamente, nao apenas uma implementacao de normalizar().
