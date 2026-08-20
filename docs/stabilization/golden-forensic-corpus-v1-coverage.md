# Golden Forensic Corpus V1 -- Coverage Map

Gerado por `python -m scripts.quality.golden_corpus --coverage-map`. Não editar manualmente.

Apenas casos com `status: APPROVED` contam para a cobertura abaixo. Casos `CHARACTERIZED_NOT_APPROVED`/`KNOWN_BUG` continuam pinados (qualquer drift ainda quebra o gate), mas ficam fora da contagem de cobertura -- ver docs/stabilization/hotspot-characterization-v1.md e o próprio corpus para o detalhe de cada um.

| Família semântica | HOTSPOT-01 | HOTSPOT-02 | HOTSPOT-03 | HOTSPOT-04 | HOTSPOT-05 |
| --- | --- | --- | --- | --- | --- |
| absent_information |  | GC-VISTORIA-004, GC-VISTORIA-006 | GC-DELIM-001 | GC-INTEGRIDADE-013 |  |
| ai_proposal_not_effective_alone |  | N/A | N/A | N/A | GC-AUTOCORRIGIR-001, GC-AUTOCORRIGIR-002, GC-AUTOCORRIGIR-003 |
| allegations |  | GC-VISTORIA-003 | GC-DELIM-001, GC-DELIM-006 |  |  |
| contradictory_evidence | GC-MOTOR-002 |  | N/A | GC-INTEGRIDADE-001, GC-INTEGRIDADE-002, GC-INTEGRIDADE-004, GC-INTEGRIDADE-005, GC-INTEGRIDADE-007, GC-INTEGRIDADE-008, GC-INTEGRIDADE-010, GC-INTEGRIDADE-011, GC-INTEGRIDADE-014 | GC-AUTOCORRIGIR-005 |
| correction_persistence |  | N/A | N/A | N/A | GC-AUTOCORRIGIR-001, GC-AUTOCORRIGIR-002, GC-AUTOCORRIGIR-003, GC-AUTOCORRIGIR-004, GC-AUTOCORRIGIR-005 |
| deterministic_replay | GC-MOTOR-006 | GC-VISTORIA-005 | GC-DELIM-001 | GC-INTEGRIDADE-000 | GC-AUTOCORRIGIR-006 |
| documentary_evidence |  |  | GC-DELIM-001, GC-DELIM-002, GC-DELIM-003 |  |  |
| duplicate_inputs |  |  | GC-DELIM-005, GC-DELIM-009 | GC-INTEGRIDADE-003 |  |
| engine_decision | GC-MOTOR-001, GC-MOTOR-004, GC-MOTOR-005 |  | GC-DELIM-001, GC-DELIM-002, GC-DELIM-003, GC-DELIM-004, GC-DELIM-005, GC-DELIM-006, GC-DELIM-007, GC-DELIM-010B | GC-INTEGRIDADE-001 | GC-AUTOCORRIGIR-003, GC-AUTOCORRIGIR-005 |
| equivalent_input_representations |  |  | GC-DELIM-009 | N/A |  |
| inconclusive_findings | GC-MOTOR-005 | GC-VISTORIA-002 | GC-DELIM-007, GC-DELIM-010 |  | GC-AUTOCORRIGIR-001 |
| measurements | GC-MOTOR-004 | GC-VISTORIA-005 | N/A | GC-INTEGRIDADE-006, GC-INTEGRIDADE-007, GC-INTEGRIDADE-008 |  |
| normative_references | GC-MOTOR-004 | N/A | GC-DELIM-002 | N/A | GC-AUTOCORRIGIR-004 |
| not_observed |  | GC-VISTORIA-004 | N/A |  |  |
| observations |  | GC-VISTORIA-003 | N/A |  |  |
| professional_override |  | N/A | N/A | N/A |  |
| provenance | GC-MOTOR-001, GC-MOTOR-007 | GC-VISTORIA-005 | GC-DELIM-001, GC-DELIM-002 | GC-INTEGRIDADE-005, GC-INTEGRIDADE-006, GC-INTEGRIDADE-009 |  |
| reordered_inputs | GC-MOTOR-007 |  |  | N/A |  |
| source_value |  |  | GC-DELIM-001 |  |  |
| technical_inference | GC-MOTOR-001, GC-MOTOR-002 | N/A | GC-DELIM-001, GC-DELIM-002, GC-DELIM-003, GC-DELIM-004, GC-DELIM-005 |  |  |
| unverifiable_information |  | GC-VISTORIA-002 | GC-DELIM-010 | GC-INTEGRIDADE-009 |  |

## Caminhos conhecidos como inalcançáveis hoje (sem caso golden)

- **HOTSPOT-02** `scripts/vistoria_estruturada/gerar_vistoria.py:128 normalizar(obs.get('elemento'))` -- `latent_defect=True`, `golden_execution_case=None`. Nenhum caminho first-party de gerar() popula uma chave 'elemento' nos dicts de medicoes/fotos (nem o literal de medicoes.append em ~linha 90 nem o de fotos.append em ~linha 79 define essa chave) -- ver Issue #74 e docs/stabilization/hotspot-characterization-v1.md. Construir manualmente um dict intermediario com 'elemento' preenchido para exercitar essa linha criaria um contrato artificial para um caminho morto, nao uma caracterizacao de comportamento real. Sem caso golden ate que exista uma entrada first-party legitima que torne o caminho alcancavel.
