# Golden Forensic Corpus V1 — Design Proposal (Stage 2 of `POST_TOOLING_MAINTAINABILITY_SEQUENCE_V1`)

**Status of this document: DESIGN ONLY.** No code, fixtures, schemas, or config
were added or changed by this pass. It is read-only research against the
checkout at the time of writing, intended as the implementation brief for the
session that opens the real Issue/branch/PR for `GOLDEN_FORENSIC_CORPUS_V1`.

Fills the gap named in `scripts/quality/core_baseline.py`'s `gapMatrix`:
`{"area": "Golden Forensic Corpus", "currentState": "Synthetic fixtures and
E2E positive/negative", "gap": "No future Golden Forensic Corpus",
"nextProgramStage": "GOLDEN_FORENSIC_CORPUS_V1"}`, and follows directly from
`docs/stabilization/hotspot-characterization-v1.md`'s "Próxima etapa" section
(Stage 1, PR #77), which named this corpus as the vehicle for detecting
semantic drift across the 5 characterized hotspots before
`MAINTAINABILITY_REFACTORING_V1` touches any of them.

Constraints carried over from the objective, restated for traceability:
`NO_REAL_CASE_PRIVATE_DATA = TRUE` (no real PII, no `referencias/privadas/`
content, no copied real expert-report conclusions), deterministic, first-party,
synthetic. A golden output is frozen only once it is `INTENDED`,
`SUPPORTED_BY_FIRST_PARTY_CONTRACT`, and `NOT_A_KNOWN_BUG`; anything uncertain
gets isolated as `CHARACTERIZED_NOT_APPROVED` (or similar), never blessed.

---

## EXISTING_INFRASTRUCTURE_TO_REUSE

### Fixture registry and its validator

`tests/fixtures/core-fixtures.json` is the canonical fixture registry (38
entries today). Each entry requires `arquivo`, `dominio`, `schema`,
`consumer`, `finalidade`, `expected` (`VALID` | `INVALID` | `DATASET`).
`scripts/quality/fixture_registry.py::validate_fixture_registry` enforces:

- every `tests/fixtures/**/*.json` file (except registries themselves) is
  registered (`FIXTURE_ORFA` if not — P1, invariant `NO_SILENT_LOSS`,
  boundary `REPOSITORY`);
- every registered entry's file still exists (`REGISTRY_STALE`);
- the declared `consumer` (`path::Class::method` or `path::function`) exists
  syntactically in the target file (regex `def|class <symbol>`), and the
  fixture is actually referenced there (`fixture.name in source` or a
  discovery match against `scripts/validar_schemas.py`'s `PASTAS_FIXTURES`
  constant) — else `FIXTURE_NAO_EXERCITADA`;
- `schema` (if set) resolves under `schemas/` (`SCHEMA_STALE`);
- `expected` is one of the three allowed values.

**Implication for the corpus**: any `tests/fixtures/golden_corpus/*.json`
files MUST be registered here with `expected: "DATASET"` (matching the
existing pattern for `tests/fixtures/motor-vicios-cenarios.json`,
`tests/fixtures/planejamento-cenarios.json`, `tests/fixtures/triagem/cenarios.json`,
`tests/fixtures/pje_parser/casos.json`, `tests/fixtures/pje_documentos/casos-classificacao.json`
— every existing "big scenario table" fixture already uses `DATASET` +
a `consumer` pointing at the one test method that iterates it) or the new
files will be flagged `FIXTURE_ORFA` on the next gate run. This is a hard
mechanical constraint, not a style preference — reuse the existing validator
rather than inventing a parallel one.

### `core_baseline.py`'s manifest inclusion rule

`scripts/quality/core_baseline.py::_manifest_paths` only pulls
`tests/fixtures/**` files into the Core baseline manifest **if they are
listed in `tests/fixtures/core-fixtures.json`'s `fixtures[].arquivo`** — it
does not glob `tests/fixtures/` unconditionally the way it globs
`schemas/*.json` and `tests/test*.py`. So registering the corpus (previous
point) is also what makes it visible to the Core baseline at all. Landing
Stage 2 will therefore change `config/core-stable-baseline-v1.json`'s
`coreManifest`/`fixtureBaseline` and its `semanticFingerprint` — see
OPEN_QUESTIONS #9.

### Property/replay-adjacent tests that already exist

`tests/test_core_properties.py` and `tests/test_core_properties_v2.py`
(Hypothesis-based) are the only existing determinism/order-invariance tests
relevant to the 5 hotspots, and they operate at **sub-function granularity**,
not at the hotspot entrypoint itself:

- `test_motor_identity_is_invariant_to_observation_order` /
  `test_valid_domain_motor_identity_ignores_order_and_irrelevant_text` exercise
  `scripts/motor_vicios/motor.py::_identidade_manifestacao` directly — a
  private helper of HOTSPOT-01, not `executar()` end-to-end.
- `test_pje_segmentation_is_order_invariant` /
  `test_valid_domain_pje_index_permutation_preserves_semantics` exercise
  `segmentar_documentos`, upstream of HOTSPOT-04 (`validar_integridade`),
  not `validar_integridade` itself.
- `test_measurement_equivalence_*` exercise `recalcular_execucao`
  (`planejamento_pericial/validar_plano.py`), a different boundary
  (`COVERAGE`/`PLANNING`) than any of the 5 characterized hotspots.
- No existing test drives `motor.executar`, `gerar_vistoria.gerar`,
  `gerar_delimitacao.gerar`, `validar_integridade`, or `autocorrigir` twice
  with reordered/duplicated top-level input and asserts identical output.

**Implication**: the corpus's order/duplicate/replay cases are new coverage,
not a duplication of `test_core_properties*.py`. They should be designed to
*compose with* those tests (same invariant IDs — `ORDER_INVARIANCE`,
`IDEMPOTENCE` — same conceptual guarantee) rather than reinvent them, but
they close a real, previously-undocumented gap: entrypoint-level determinism.

### The `cenarios`/`casos` DATASET pattern

`tests/fixtures/motor-vicios-cenarios.json` (30 cases) is consumed by
`tests/test_motor_vicios.py::test_trinta_cenarios_de_risco_executam_comportamento`
via `scripts/motor_vicios/cenarios.py::executar_cenario`, a small dispatcher
keyed by `input.operacao` (`"situacao"`, `"origem"`, `"norma"`,
`"aspectos_foto"`, `"associacao"`, `"elegibilidade"`, `"criticidade"`,
`"tipo_vicio"`) that routes each case to one pure sub-function of
`scripts/motor_vicios/regras.py`/`evidencias.py` and asserts `output ==
expected`. `tests/fixtures/triagem/cenarios.json` and
`tests/fixtures/planejamento-cenarios.json` follow the identical shape for
their domains.

**This is the closest existing architectural precedent for a golden-case
runner** (`{id, input, expected}` rows dispatched by a small first-party
function, exact-match assertion), but it operates at **unit/sub-function
granularity** (single `regras.py`/`evidencias.py` function per case). The
Golden Forensic Corpus needs the same *shape* one level up: full-entrypoint
granularity (`executar`, `gerar`, `validar_integridade`, `autocorrigir`),
richer per-case metadata (`EXPECTED_PROVENANCE`, `EXPECTED_CLASSIFICATIONS`,
`INVARIANTS_EXERCISED`, etc., none of which `cenarios.json`'s flat
`{id, input, expected}` carries today), and — for HOTSPOT-03 specifically —
filesystem materialization instead of pure in-memory dicts (see below). The
runner design in this document treats `cenarios.py`'s dispatcher as the
minimal-viable pattern to extend, not to replace.

### Existing HOTSPOT-04 characterization tests are pre-built golden-case material

`tests/test_hotspot_validar_integridade_v1.py` (13 tests, all built on
`copy.deepcopy` + `.update()` overrides of
`tests/fixtures/pje/manifesto-minimo-valido.json`) already gives 12
GOLDEN-eligible cases and 1 explicitly `CHARACTERIZED_NOT_APPROVED` case for
HOTSPOT-04, written and passing as of PR #77. See HOTSPOT-04 section below —
this is the cheapest, lowest-risk part of Stage 2 to implement because the
behavior is already pinned; the work is porting it into the corpus's richer
schema, not discovering new behavior.

### What does NOT exist yet and Stage 2 must build fresh

No `scripts/quality/golden_corpus.py`-equivalent module exists (confirmed:
`scripts/quality/` contains `architecture_analyzer.py`, `ast_inventory.py`,
`capability_analyzer.py`, `capability_bootstrap.py`,
`capability_gate_adapter.py`, `capability_trust_anchor.py`,
`change_impact.py`, `config.py`, `core_baseline.py`, `deep_quality.py`,
`fixture_registry.py`, `historical_mutations.py`, `metrics.py`,
`repository_inventory.py`, `schema_versions.py`, `verify_core.py` — no
`golden_corpus.py`). No `config/golden-forensic-corpus-v1.json` or
`tests/fixtures/golden-corpus-v1.json` exists. No coverage-map document
exists.

---

## PER_HOTSPOT_CANDIDATE_CASES

Every case below targets a branch the characterization doc marked untested
(`CHARACTERIZATION_CONFIDENCE: LOW`) or explicitly named as a gap, and is
written against real field names confirmed from
`schemas/analise-motor-vicios.schema.json`, `schemas/patologia.schema.json`,
`schemas/delimitacao-pericial.schema.json`, and the source files themselves.
None of these are finished fixtures — they are target semantics + the exact
mechanism to reach them, for an implementer to materialize and validate by
actually running the function (see OPEN_QUESTIONS #1 for the one case whose
literal input text still needs empirical tuning against live regexes).

### HOTSPOT-01 — `scripts/motor_vicios/motor.py::executar`

1. **`GC-MOTOR-001` — vício endógeno caracterizado fim a fim.**
   `sistema="IMPERMEABILIZACAO"` (the only system in
   `scripts/motor_vicios/hipoteses.py::CATALOGO` whose first hypothesis pair
   is `("ingresso de água por interface","falha de vedação",
   {"INTERFACE_IDENTIFICADA","VEDACAO_DETERIORADA","PRECIPITACAO_REGISTRADA"},
   {"VEDACAO_INTEGRA"})`). Two-plus observations, each from a distinct
   `proveniencia` (independent sources, per
   `regras_probatorias.py::identidade_fontes`), whose `descricao_objetiva`
   text is built to trip the regex patterns in
   `scripts/motor_vicios/evidencias.py::PADROES_OBSERVAVEIS` for
   `INTERFACE_IDENTIFICADA` (`\binterface\b`), `VEDACAO_DETERIORADA`
   (`selagem ... degradada`), `PRECIPITACAO_REGISTRADA` (`\bchuva\b`), plus
   at least two independent-source observations carrying
   `DETALHE_CONSTRUTIVO_DOCUMENTADO` (`detalhe executivo`) and
   `EXECUCAO_DIVERGENTE_DOCUMENTADA` (`execucao divergente`) so that
   `regras_probatorias.py::suporte_endogeno` is satisfied and
   `regras.py::inferir_origem` returns `ENDOGENA_CONSTRUTIVA`.
   `EXPECTED_OUTPUT`: `patologias[0].vicio_construtivo.caracterizado == True`,
   `.origem == "ENDOGENA_CONSTRUTIVA"`, `.elegibilidade_orcamento ==
   "ELEGIVEL_ORCAMENTO_VICIO"` (requires `estruturar_reparo` to fire, which
   needs exactly those same two construtivo aspects — already satisfied),
   `.hipoteses[i].status == "MAIS_PROVAVEL"`.
   `INVARIANTS_EXERCISED`: `SOURCE_TRUTH`, `SEMANTIC_MONOTONICITY`,
   `PROVENANCE_FIDELITY`, `NO_CERTAINTY_INFLATION` (negative control: this
   case proves the *positive* path so a future drift toward
   over-classifying weaker evidence as `caracterizado=True` is detectable by
   diffing against sibling near-miss cases GC-MOTOR-002).
   Semantic families: technical inference, engine decision, provenance.

2. **`GC-MOTOR-002` — hipótese afastada por contradição.** Same `sistema`,
   but one observation also trips `VEDACAO_INTEGRA` (the hypothesis's own
   `contra` aspect set). `hipoteses.py::gerar` computes `ci>=1 and not
   fi -> status="AFASTADA"`. `EXPECTED_OUTPUT`: the hypothesis's
   `status=="AFASTADA"`, no `MAIS_PROVAVEL` hypothesis exists, `pat.causa is
   None`, `vicio_construtivo.caracterizado == False`. Semantic families:
   contradictory evidence, technical inference.

3. **`GC-MOTOR-003` — `contexto` override explícito.** `contexto =
   {"_modo": "OVERRIDE_EXPLICITO", "MAN-001": {"causalidade": {...}}}`
   exercises `motor.py` line 53 (`if ctx.get("causalidade"):causalidade=
   {**causalidade,**ctx["causalidade"]}`). `EXPECTED_OUTPUT`: the overridden
   fields (e.g. `causalidade["criticidade"]`) appear verbatim in
   `patologias[0]`, taking precedence over the computed value.
   **Naming caution for the corpus author**: this `contexto` parameter is a
   caller-supplied override into `executar()`'s own computation, distinct
   from the `PROFESSIONAL_OVERRIDE` tier defined by
   `scripts/backend_contract/revisions.py` / invariant
   `PROPOSAL_NOT_EFFECTIVE_WITHOUT_DECISION` (boundary `BACKEND_AUTHORITY`).
   Label this case's semantic family as "engine input override", not
   "professional override", to avoid conflating two different authority
   concepts in the coverage map (see OPEN_QUESTIONS is not needed here, this
   is just a labeling instruction for the implementer).

4. **`GC-MOTOR-004` — conformidade normativa `ATENDE` fim a fim.**
   `conhecimento.normas` includes one norm whose `criterio` is satisfied by
   a `MED-*` measurement on the manifestação, exercising the per-PAT norm
   loop (motor.py lines 76-79: `normalizar_fonte_normativa`,
   `avaliar_conformidade_normativa`, `projetar_norma_pat`, then the in-place
   `n.clear();n.update(projecao)` self-mutation the characterization doc
   flagged as an aliasing risk). `EXPECTED_OUTPUT`:
   `patologias[0].normas_relacionadas[0].avaliacao_conformidade.resultado ==
   "ATENDE"`. `INVARIANTS_EXERCISED`: `NORMATIVE_FIDELITY`. This case is the
   one most likely to catch a refactor that "fixes" the double-pass PAT
   computation but accidentally drops the `n.clear()/n.update()` aliasing
   behavior — flag it as a priority regression pin ahead of
   `MAINTAINABILITY_REFACTORING_V1` touching this exact code.

5. **`GC-MOTOR-005` — sistema sem motor causal implementado.** `sistema` not
   present in `hipoteses.py::CATALOGO` with real hypotheses (e.g.
   `"COBERTURA"`), `situacao in {"ANOMALIA","FALHA"}`.
   `EXPECTED_OUTPUT`: `patologias[0].analise_causal.status_capacidade ==
   "MOTOR_CAUSAL_NAO_IMPLEMENTADO"`, `.limitacoes[0] ==
   "MOTOR_ESPECIALIZADO_NAO_IMPLEMENTADO"`, `conclusao_tecnica` contains
   "motor causal implementado"; if the linked QT's `intencoes()` include
   `CAUSALIDADE`/`ORIGEM`/`MECANISMO`, `questoes_saneadas[i].status ==
   "INCONCLUSIVA_POR_LIMITACAO"` (distinguishing a **capability limitation**
   from an **evidentiary inconclusivity** — the objective's "inconclusive
   findings" family has two structurally different sources in this codebase
   and the corpus should pin both separately, see GC-MOTOR-002 for the
   evidentiary flavor).

6. **`GC-MOTOR-006` — replay determinístico e invariância de ordem em
   `executar()` completo.** Run `executar()` twice on independently
   deep-copied, byte-identical input → assert
   `json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)`
   (`DETERMINISTIC_REPLAY`). Then re-run with `vistoria["observacoes"]`
   permuted (same set, different list order) → assert `manifestacoes`,
   `patologias`, and `hipoteses` are identical **as sets keyed by id**
   (grouping key is `chave = (manifestacao, ambiente, sistema, elemento)`,
   independent of input list order; `_identidade_manifestacao`'s numeric
   suffix is derived from `min(OBS-NNN)`, also order-independent) —
   `ORDER_INVARIANCE` exercised at entrypoint granularity for the first
   time (see EXISTING_INFRASTRUCTURE_TO_REUSE above: only the private helper
   was order-tested before). `motor.executar` itself imports no
   `datetime`/`uuid` (confirmed by reading the file), so unlike HOTSPOT-03
   this case needs no non-semantic-field exclusion — a genuinely exact
   byte-for-byte comparison is possible here.

### HOTSPOT-02 — `scripts/vistoria_estruturada/gerar_vistoria.py::gerar`

**Landmine avoidance note**: line 128's `normalizar(obs.get("elemento"))`
call is confirmed dead code (Issue #74, `CHARACTERIZED_NOT_APPROVED`) because
neither the `medicoes.append({...})` literal (line 90) nor the
`fotos.append({...})` literal (line 79) ever sets an `"elemento"` key.
Driving cases only through the public `gerar()` entrypoint (never hand-
constructing intermediate `medicoes`/`fotos` dicts with an `"elemento"` key)
keeps every corpus case for this hotspot safely on the reachable side of that
landmine by construction — no special-casing needed in the runner, just
discipline in how cases build `inventario`.

1. **`GC-VISTORIA-001` — associação fotográfica por ID planejado explícito.**
   `inventario.arquivos[0]` with `categoria="FOTOGRAFIA"`, `nome`/
   `caminho_relativo` containing (case-insensitive) a `plano.fotografias[i].id`.
   `EXPECTED_OUTPUT`: `fotografias[0].metodo_associacao ==
   "ID_PLANEJADO_EXPLICITO"`, `.fotografia_planejada == plano.fotografias[0].id`.
   **Notable existing quirk to freeze, not silently "fix"**: the confidence
   formula (`"BAIXA" if ambiguo or not melhor else "MEDIA"`) means even an
   unambiguous *explicit* ID match never reaches `confianca.nivel=="ALTA"`
   — see OPEN_QUESTIONS #8.

2. **`GC-VISTORIA-002` — associação fotográfica ambígua por score
   próximo.** Two `plano.fotografias` entries whose `afinidade()` scores
   against the same arquivo differ by `<=0.05`, no explicit id match.
   `EXPECTED_OUTPUT`: `metodo_associacao == "ASSOCIACAO_AMBIGUA"`,
   `fotografia_planejada is None`, `confianca.nivel == "BAIXA"`. Semantic
   family: unverifiable information / inconclusive findings.

3. **`GC-VISTORIA-003` — declaração mista com constatação do perito.** A
   free-text anotação line matching the `declaracao` regex (line 44) *and*
   the `mista` sub-regex (`;\s*(?:o\s+)?perito\s+(?:constatou|observou)`,
   line 47), e.g. `"O morador informou que houve infiltração; perito
   constatou fissura na parede."`. `EXPECTED_OUTPUT`: one `declaracoes[]`
   entry with `natureza` derived from the declarant keyword
   (`DECLARADO_PELA_PARTE`/`DECLARADO_POR_TERCEIRO`/`DECLARADO_PELO_ASSISTENTE`),
   *and* a separately synthesized `observacoes[]`/`OBS` entry from the
   post-`;` clause via `proposicoes_observacionais`. `INVARIANTS_EXERCISED`:
   `DECLARATION_NOT_OBSERVATION`, `ALLEGATION_NOT_OBSERVATION`. This is the
   single most direct test of the "allegations vs. observations" semantic
   family named in the objective.

4. **`GC-VISTORIA-004` — observação negada produz `NAO_CONSTATADO_NA_VISTORIA`.**
   Free text matching a `NEGADOR` pattern, e.g. `"Não foram observados
   indícios de infiltração na parede da sala."`. `EXPECTED_OUTPUT`: the
   synthesized OBS has `resultado == "NAO_CONSTATADO_NA_VISTORIA"`,
   `polaridade == "NEGADO"`. Semantic families: not observed, absent
   information. Feeds directly into HOTSPOT-01's `NAO_CONSTATADO_NOT_INEXISTENTE`
   guarantee downstream — worth a comment in the case linking it to
   `test_nao_constatado_nao_vira_inexistente` in `tests/test_motor_vicios.py`.

5. **`GC-VISTORIA-005` — medição extraída de texto livre com vínculo de
   registro.** One anotação line combining an OBS-shaped clause and a
   measurement pattern (`abertura ... \d+(?:[.,]\d+)?\s*(mm|cm|m)`) sharing
   the same `registro_id` (`f"{arquivo_id}:{numero_linha}"`).
   `EXPECTED_OUTPUT`: `medicoes[0].grandeza=="abertura_fissura"`, and — via
   the `comp()`/`registros` univocidade path (`univocos(observacoes,
   "_registro_id")`) — `observacoes[0].medicoes` includes the MED id and
   `relacoes_evidencia[]` contains an entry with `motivo ==
   "VINCULO_REGISTRO_EXPLICITO"`, `origem == "REGISTRO_CAMPO_COMUM"`.
   Semantic families: measurements, provenance.

6. **`GC-VISTORIA-006` — cobertura planejado vs. executado.** `plano` with
   entries across all five tracked types (`atividades`, `medicoes`,
   `fotografias`, `ensaios`, `documentos_a_solicitar`), `inventario`
   covering only a subset. `EXPECTED_OUTPUT`: `cobertura[]` has
   `status=="EXECUTADO"` for matched items and `status=="NAO_EXECUTADO"`,
   `impacto=="Ausência ainda não avaliada tecnicamente."` for the rest.
   Semantic family: absent information, directly.

### HOTSPOT-03 — `scripts/triagem_pericial/gerar_delimitacao.py::gerar`

**Structural note affecting the whole hotspot**: `gerar(diretorio: Path)`
reads from the filesystem (`diretorio/manifesto-pje.json`,
`diretorio/documentos/*.json`, and — via `diretorio.parent.parent` —
`modelos-referenciais/`, `normas/`, `conhecimento/modelos/MOD-*.json`,
`conhecimento/normas/NOR-*.json`). Unlike the other four hotspots, its
`INPUT` cannot be a pure in-memory JSON dict; the corpus registry needs a
directory-layout shape and the runner needs a materialization step (see
RUNNER_DESIGN_PROPOSAL). It also calls `datetime.now(timezone.utc)` for
`identificacao.data_geracao` — the **one wall-clock read among all 5
hotspots** (confirmed absent from the other four by reading their source);
every case for this hotspot needs that one field excluded from exact-match
comparison.

1. **`GC-DELIM-001` — perfil `AVALIACAO_IMOBILIARIA` end-to-end.**
   Documentos classified (via `classificar_tipo.classificar`) to
   `tipo=="AVALIACAO_IMOBILIARIA"`. `EXPECTED_OUTPUT`:
   `tipo_pericia.tipo=="AVALIACAO_IMOBILIARIA"`, `questoes_tecnicas` seeded
   from `PERFIS["AVALIACAO_IMOBILIARIA"]["questoes"]` (3 items), `modulos_tecnicos[0].sistemas
   == ["OUTRO"]`. Covers the previously-untested non-`VICIOS_CONSTRUTIVOS`
   profile branches named in the characterization doc.

2. **`GC-DELIM-002` — perfil `OUTRO` quando capability não resolve perfil.**
   `capability(resultado.tipo)["PERFIL_DELIMITACAO"]` falsy.
   `EXPECTED_OUTPUT`: `perfil == PERFIS["OUTRO"]`,
   `autoauditoria` entry `{"criterio":"Capability de delimitação
   disponível", "resultado":"BLOQUEADO"}`. `INVARIANTS_EXERCISED`:
   `FAIL_CLOSED`.

3. **`GC-DELIM-003` — quesitos duplicados deduplicados.** Two `documentos`
   whose extracted quesito text is identical after
   `normalizar()`+`re.sub(r"\W+","",...)`. `EXPECTED_OUTPUT`: second
   quesito's `status_cobertura=="REPETITIVO"`, and — importantly —
   `_classificar_pertinencia(texto, repetitivo=True)` returns
   `"REPETITIVO"` **unconditionally**, regardless of whether the text also
   contains matéria jurídica/técnica terms; freeze this short-circuit
   explicitly since it is easy to "improve" accidentally during a refactor.
   Semantic family: duplicate inputs, directly.

4. **`GC-DELIM-004` — confiança MÉDIA gera RES-003.** `classificar()`
   resolves `resultado.nivel=="MEDIA"` (ambiguous evidence between two
   `tipoPericiaValor`s). `EXPECTED_OUTPUT`: `ressalvas` contains an entry
   `id=="RES-003"`, `categoria=="INCERTEZA_TECNICA"`; every
   `questoes_tecnicas[i].ressalvas` includes `"RES-003"`. This is the exact
   branch the characterization doc flagged as untested.

5. **`GC-DELIM-005` — isolamento jurídico/técnico.** A quesito whose text
   contains a `_materia_juridica` term (e.g. "responsabilidade civil")
   without a `_tem_materia_tecnica` term. `EXPECTED_OUTPUT`:
   `pertinencia=="MATERIA_JURIDICA"`, `status_cobertura=="JURIDICO_DELIMITADO"`,
   `materia_tecnica is None`, and `materias_excluidas[]` documents the
   exclusion. `INVARIANTS_EXERCISED`: `JURIDICAL_TECHNICAL_ISOLATION`.

6. **`GC-DELIM-006` — manifesto inválido bloqueia a triagem (fail-closed).**
   `manifesto["status_validacao"] != "VALIDADO"` (or manufactured to trip
   `validar_integridade`'s own error list). `EXPECTED_OUTPUT`: `raises
   ValueError("Manifesto PJe não validado; triagem bloqueada")` — no output
   dict. This is the golden proof that HOTSPOT-04's gate is actually wired
   into a real caller, directly addressing the semantic risk the
   characterization doc raised about HOTSPOT-04 ("a false PASS here would
   let corrupted extraction flow into the rest of the pipeline undetected").
   `INVARIANTS_EXERCISED`: `FAIL_CLOSED`, `PRODUCER_NOT_VALIDATOR`.

### HOTSPOT-04 — `scripts/extracao_pje/validar_integridade.py::validar_integridade`

This hotspot's characterization work (PR #77) already produced 13 passing
tests in `tests/test_hotspot_validar_integridade_v1.py`, all built as
`copy.deepcopy(FIXTURE).update(overrides)` against
`tests/fixtures/pje/manifesto-minimo-valido.json`. **12 are directly
promotable to GOLDEN status; 1 must stay `CHARACTERIZED_NOT_APPROVED`.**
Representative six (of the 12 promotable):

1. **`GC-INTEGRIDADE-001`** ← `test_associacao_ambigua_com_destino_escolhido_e_erro`.
   `indice.itens[0].candidatos_destino_link=[3,4]`,
   `.destino_escolhido_link=3`. `EXPECTED_OUTPUT`: `erros` contains
   `"...: associação ambígua não pode escolher destino"`. Family: engine
   decision / contradictory evidence.

2. **`GC-INTEGRIDADE-002`** ← `test_documento_id_duplicado_e_erro`.
   Duplicate `documento_id` across two `documentos[]` entries.
   `EXPECTED_OUTPUT`: `erros` contains `"...: documento_id duplicado"`.
   Family: duplicate inputs, directly.

3. **`GC-INTEGRIDADE-003`** ← `test_confirmado_com_ids_conflitantes_e_erro`.
   `status_reconciliacao.status=="CONFIRMADO"` with `id_indice != id_rodape`.
   `EXPECTED_OUTPUT`: `erros` contains `"...: CONFIRMADO com IDs
   conflitantes"`. Family: contradictory evidence, provenance.

4. **`GC-INTEGRIDADE-004`** ← `test_paginacao_interna_nao_comeca_em_1_e_apenas_alerta_nao_erro`.
   `EXPECTED_OUTPUT`: `alertas` (not `erros`) contains the message —
   pins the erro-vs-alerta severity distinction itself as golden, a
   drift-sensitive detail (a refactor could easily promote/demote this by
   accident). Family: measurements, provenance (warnings-vs-errors
   distinction).

5. **`GC-INTEGRIDADE-005`** ← `test_status_validado_incompativel_com_conflito_bloqueante_aberto_e_erro`.
   `EXPECTED_OUTPUT`: `erros` contains `"Status VALIDADO incompatível..."`.
   `INVARIANTS_EXERCISED`: `FAIL_CLOSED`.

6. **`GC-INTEGRIDADE-006`** ← `test_manifesto_is_not_mutated`. No
   `EXPECTED_OUTPUT` diff beyond `erros==[] and alertas==[]`; the assertion
   is `manifesto == before` after the call. `INVARIANTS_EXERCISED`: an
   implicit no-input-mutation guarantee (not currently a named invariant in
   `config/core-invariants.json` — worth flagging to whoever maintains that
   file, out of scope here).

**Excluded from GOLDEN status (must be tagged, not silently promoted)**:
`test_conflito_resolvido_por_fonte_primaria_nao_bloqueia_status_validado`,
which the characterization doc explicitly marks
`CHARACTERIZED_NOT_APPROVED` (a `RESOLVIDO_POR_FONTE_PRIMARIA` conflict is
skipped by both the page-overlap loop and the accounting loop, so its
`itens_indice_relacionados` gets no accounting entry at all — preserved as-is,
not endorsed). The corpus should still pin this behavior (losing regression
coverage of a known landmine is worse than not tracking it), but its
`status` field must read `CHARACTERIZED_NOT_APPROVED`, and it must be
excluded from any "golden coverage" count in the coverage map.

The remaining 6 of the 12 (`fallback posicional + confiança ALTA`, `destino
escolhido diverge do destino de segmentação`, `início posterior ao fim`,
`salto na paginação interna`, `métrica declarada inconsistente`, `CNJ sem
origem em página do índice`, `pendência não aberta ignorada`, `manifesto
malformado → KeyError`) map 1:1 to the corpus with the same mechanical
porting effort — see OPEN_QUESTIONS #4 for the one open question they raise
(how to represent an expected-exception case in a JSON-fixture-driven
corpus).

### HOTSPOT-05 — `scripts/motor_vicios/autocorrigir.py::autocorrigir`

Signature: `autocorrigir(resultado, claims, auditorias, achados=None) ->
(final, historico)`. The characterization doc found **zero** repo-wide test
matches for this function's own action labels
(`REDUZIR_CLAIM`/`REMOVER_CARACTERIZACAO`/etc.) — the entire claim-reduction
loop (lines 13-38) is untested today.

1. **`GC-AUTOCORRIGIR-001` — claim de causa reprovada reduz e gera
   ressalva.** `claims=[{"id":"CLM-001","tipo":"CAUSA","patologia":"PAT-001"}]`,
   `auditorias=[{"claim_id":"CLM-001","veredito":"UNSUBSTANTIATED",
   "evidencias":["OBS-001"]}]`, target `pat["constatacao"]["situacao"]`
   in `{"ANOMALIA","FALHA"}`. `EXPECTED_OUTPUT`: `pat.causa is None`,
   `.analise_causal.causa_provavel is None`, `.origem=="INCONCLUSIVA"`,
   `.vicio_construtivo=={"caracterizado":False,"tipo":"INCONCLUSIVO",
   "fundamentacao":None,...}`, `.reparabilidade=="NECESSITA_INVESTIGACAO"`,
   `.elegibilidade_orcamento=="PENDENTE"`,
   `.analise_causal.grau_certeza=="INCONCLUSIVO"`, ressalva string
   `"Causalidade inconclusiva após auditoria do suporte probatório."`
   appended; `historico[0].acao=="REDUZIR_CLAIM"`.
   `INVARIANTS_EXERCISED`: `CORRECTION_PERSISTENCE`,
   `CORRECTION_TRACEABILITY`. Semantic family: AI proposal that must NOT
   become effective alone (a rejected causal claim from audit not
   persisting as an engine decision).

2. **`GC-AUTOCORRIGIR-002` — claim de mecanismo reprovada só limpa
   mecanismo.** Same shape, `tipo="MECANISMO"`, `veredito="INTERPOLATED"`.
   `EXPECTED_OUTPUT`: `pat.mecanismo is None`, `pat.causa` **unchanged**
   (different mutated field than case 1 — direct drift detector for the
   `if tipo=="CAUSA" ... else: pat["mecanismo"]=None` branch split).

3. **`GC-AUTOCORRIGIR-003` — vício construtivo removido por claim
   reprovada.** `tipo="VICIO_CONSTRUTIVO"`, `veredito="CONTRADICTED"`,
   target `pat.vicio_construtivo.caracterizado` starts `True`.
   `EXPECTED_OUTPUT`: forced to `False`, `.elegibilidade_orcamento=="PENDENTE"`,
   `historico[0].acao=="REMOVER_CARACTERIZACAO"`. This is the most direct
   "certainty inflation reversed by audit" case in the whole corpus — a
   previously-`True` `caracterizado` flag from `motor.executar` not
   surviving an audit failure.

4. **`GC-AUTOCORRIGIR-004` — conformidade normativa reprovada filtra
   normas não verificadas.** `tipo="CONFORMIDADE_NORMATIVA"`, pat has
   `normas_relacionadas` with mixed `verificada`/`aplicabilidade_temporal`
   values. `EXPECTED_OUTPUT`: only entries with `verificada==True and
   aplicabilidade_temporal!="NAO_APLICAVEL"` survive. Note for the corpus
   author: `historico` here stores `len(before)`/`len(after)` as strings,
   not the full norma list — pin that shape too, since "fixing" it to store
   full objects would be a silent historico-contract change.

5. **`GC-AUTOCORRIGIR-005` — achado `NEGACAO_CONVERTIDA_EM_FATO` corrige
   polaridade no catálogo.** `achados=[{"tipo":
   "NEGACAO_CONVERTIDA_EM_FATO","claim_id":"EVD-001"}]`, target
   `catalogo_evidencias[i]` with `auditoria_aspectos` containing a
   `NEGADO`-polarity aspect currently listed in `aspectos_suportados`.
   `EXPECTED_OUTPUT`: that aspect moves from `aspectos_suportados` to
   `aspectos_contraditos`; `historico` entry `acao=="CORRIGIR_POLARIDADE"`.
   This exercises the achado-driven half of the function (lines 39-78),
   structurally distinct from the claim-driven half (lines 13-38) — the
   corpus needs cases in both halves since they are independently
   untested.

6. **`GC-AUTOCORRIGIR-006` — idempotência sob reexecução.** Run
   `autocorrigir(resultado, claims, auditorias, achados)` twice on
   independently deep-copied, identical inputs → assert structurally
   identical `final` (the `historico`'s own `AUT-NNN` numbering restarts at
   1 each call, so compare `final` only, not `historico`).
   `INVARIANTS_EXERCISED`: `IDEMPOTENCE` (boundary `AUTOCORRECTION`).
   Bonus sub-case: call `autocorrigir` a **second time treating its own
   prior `final` as `resultado`**, same `claims`/`auditorias` — assert the
   `if ress not in pat["ressalvas"]:` guard (line 25) prevents a duplicate
   ressalva string on re-application. This is the concrete mechanism the
   objective calls "correction persistence" × "duplicate inputs"
   interacting.

---

## REGISTRY_SCHEMA_PROPOSAL

### File location: `tests/fixtures/golden_corpus/<hotspot-slug>.json`, one file per hotspot

Recommended over a single `config/golden-forensic-corpus-v1.json`:

- **`config/` is reserved for governance/policy** (`core-boundaries.json`,
  `core-invariants.json`, `core-registry-lock.json`, baselines) — every
  existing file there is a rule or a manifest of rules, never bulk fixture
  *content*. The corpus is content (large `INPUT`/`EXPECTED_OUTPUT` payloads
  per case), matching the existing convention that bulk domain data lives
  under `tests/fixtures/`.
- **Splitting by hotspot** (`tests/fixtures/golden_corpus/motor_executar.json`,
  `gerar_vistoria.json`, `gerar_delimitacao.json`, `validar_integridade.json`,
  `autocorrigir.json`) matches the existing per-domain directory convention
  (`tests/fixtures/{pje,pje_parser,pje_documentos,planejamento,redacao,
  triagem,motor-vicios,auditoria,agentic}/`), keeps diffs small and
  reviewable per hotspot during `MAINTAINABILITY_REFACTORING_V1` (one
  hotspot refactored at a time per the characterization doc's stated plan),
  and lets `fixture_registry.py` validate each file independently. See
  OPEN_QUESTIONS #2 for the single-file alternative and its tradeoffs.
- Each file gets its own `tests/fixtures/core-fixtures.json` entry:
  `{"arquivo": "tests/fixtures/golden_corpus/motor_executar.json",
  "dominio": "GOLDEN_CORPUS_MOTOR", "schema": null, "consumer":
  "scripts/quality/golden_corpus.py::main", "finalidade": "Corpus dourado -
  motor.executar", "expected": "DATASET"}` (mirroring how
  `motor-vicios-cenarios.json` is registered against its consumer test).

### Per-file shape

```json
{
  "schema_version": "1.0.0",
  "hotspot_id": "HOTSPOT-01",
  "entrypoint": "scripts/motor_vicios/motor.py::executar",
  "cases": [
    {
      "case_id": "GC-MOTOR-001",
      "purpose": "Vício endógeno caracterizado fim a fim via convergência de evidências independentes.",
      "status": "GOLDEN",
      "semantic_families": ["technical_inference", "engine_decision", "provenance"],
      "invariants_exercised": ["SOURCE_TRUTH", "SEMANTIC_MONOTONICITY", "PROVENANCE_FIDELITY"],
      "input": { "processo": { "...": "..." }, "delimitacao": { "...": "..." }, "plano": { "...": "..." }, "vistoria": { "...": "..." }, "contexto": null, "conhecimento": { "...": "..." } },
      "expected_output_mode": "EXACT",
      "expected_output": { "...": "the full literal result dict" },
      "expected_provenance": ["OBS-001", "OBS-002"],
      "expected_classifications": { "patologias[0].vicio_construtivo.caracterizado": true, "patologias[0].elegibilidade_orcamento": "ELEGIVEL_ORCAMENTO_VICIO" },
      "expected_warnings": [],
      "expected_inconclusivity": null,
      "non_semantic_fields_ignored": [],
      "notes": "See docs/stabilization/golden-forensic-corpus-v1-design.md#GC-MOTOR-001."
    }
  ]
}
```

Field notes:

- **`status`**: `GOLDEN` | `CHARACTERIZED_NOT_APPROVED` | `PROPOSED` (staged
  before human review promotes it). Only `GOLDEN` cases count toward the
  coverage map's "covered" cells.
- **`expected_output_mode`**: `EXACT` (default, strongly preferred — see
  RUNNER_DESIGN_PROPOSAL for why partial matching risks missing exactly the
  kind of silent omission / certainty inflation the corpus exists to catch)
  or `RAISES` for the fail-closed cases (`GC-DELIM-006`,
  `GC-INTEGRIDADE-*` KeyError case) — shape:
  `"expected_output": {"raises": {"type": "ValueError", "message_contains":
  "não validado"}}`. This convention does not exist anywhere else in the
  repo's JSON fixtures today; flagged as OPEN_QUESTIONS #4.
- **`non_semantic_fields_ignored`**: dotted-path list, used only by
  HOTSPOT-03 cases (`["identificacao.data_geracao"]`) to exclude the one
  known wall-clock field before exact comparison. Empty for the other four
  hotspots — deliberately, so their exact-match guarantee stays maximal.
- **`input`**: full literal JSON per case, not a `$fixture` reference +
  overlay. See OPEN_QUESTIONS #3 for why a reuse/overlay mechanism was
  considered and deferred.
- For HOTSPOT-03 specifically, `input` becomes a directory-layout map
  instead of flat keys:
  ```json
  "input": {
    "diretorio_layout": { "manifesto-pje.json": {"...": "..."}, "documentos/DOC-PJE-001.json": {"...": "..."} },
    "private_root_layout": { "modelos-referenciais": [], "normas": [] }
  }
  ```
  (`private_root_layout` entries are empty by default — matching
  `NO_REAL_CASE_PRIVATE_DATA` — populated only for cases that specifically
  need to exercise the `conhecimento_modelos`/`conhecimento_normas`
  recovery branches, with synthetic `MOD-*.json`/`NOR-*.json` content, never
  anything under `referencias/privadas/`.)

### Optional top-level `not_applicable` block (feeds the coverage map)

```json
"not_applicable": [
  {"hotspot_id": "HOTSPOT-04", "family": "professional_override", "reason": "validar_integridade is a pure pre-audit structural validator with no engine-decision or override surface."}
]
```

---

## RUNNER_DESIGN_PROPOSAL

Propose `scripts/quality/golden_corpus.py`, matching the existing style in
`scripts/quality/` (pure functions, `_finding(...)`-shaped results like
`fixture_registry.py`; deterministic, argparse `--check` CLI like
`core_baseline.py`).

### Responsibilities

1. **`load_corpus(root) -> list[dict]`**: discover golden-corpus files via
   `tests/fixtures/core-fixtures.json` entries whose `dominio` starts with
   `"GOLDEN_CORPUS"` (reuses the existing registry rather than a separate
   glob, so an orphaned/unregistered golden-corpus file is caught by the
   *existing* `fixture_registry.py::FIXTURE_ORFA` check for free).
2. **Per-hotspot adapter functions** — one thin first-party wrapper per
   hotspot that knows how to call the real entrypoint and, for HOTSPOT-03,
   how to materialize `diretorio_layout`/`private_root_layout` into a
   `tempfile.TemporaryDirectory()` tree before calling `gerar(diretorio)`.
   These adapters are the only hotspot-specific code in the runner; the
   comparison/reporting logic below is shared.
3. **Comparison logic**, keyed by `expected_output_mode`:
   - `EXACT`: deep-copy actual output, pop every dotted path in
     `non_semantic_fields_ignored` from both actual and expected, then
     compare via `json.dumps(x, sort_keys=True, ensure_ascii=False) ==
     json.dumps(y, sort_keys=True, ensure_ascii=False)`. On mismatch, emit a
     small first-party recursive diff (new, but tiny — no `deepdiff`
     dependency exists in `requirements*.txt` today, confirmed against the
     external-dependency list in `docs/stabilization/core-stable-baseline-v1.md`:
     `PIL`, `jsonschema`, `pdfplumber`, `pypdf`, `referencing`).
   - `RAISES`: assert the named exception type is raised and (if given)
     `message_contains` is a substring of `str(exc)`.
4. **Replay/order/duplicate mechanics** — not separate case types, but
   declarative transforms applied to a base case's `input` before a second
   run:
   - **Deterministic replay**: run the entrypoint twice on independently
     deep-copied input; assert canonical-JSON equality between the two runs
     (independent of the `EXPECTED_OUTPUT` comparison — this catches
     *internal* nondeterminism even if nobody has pinned the exact golden
     value yet).
   - **Reordered inputs**: `"reordering": {"path": "vistoria.observacoes",
     "permutation": [2,0,1]}` — apply, run, and assert the result equals
     `EXPECTED_OUTPUT` under the same order-insensitive-set comparison used
     for the base case (list fields whose membership, not position, carries
     meaning — `manifestacoes`, `patologias`, `hipoteses` — compared as sets
     keyed by their own `id`).
   - **Duplicate inputs**: `"duplication": {"path": "documentos", "index":
     0}` — insert a duplicate at the given list path, run, and assert
     against a case-specific `EXPECTED_OUTPUT`/`RAISES` (some duplicates
     must collapse silently-safely, others — e.g. `documento_id` collision
     — must produce an explicit `erros` entry; this is case-specific, not a
     generic rule the runner can infer, so each duplicate-input case
     declares its own expectation like any other case).
   This design extends, rather than duplicates, `test_core_properties*.py`'s
   Hypothesis-based approach: those tests randomize inputs broadly at
   sub-function granularity; the corpus's reordering/duplication transforms
   are targeted, declarative, and operate at full-entrypoint granularity on
   the same concrete cases used for semantic assertions — cheaper to reason
   about for a human reviewing "did this refactor break order-invariance for
   *this specific* scenario" than a property test's abstract counterexample.
5. **Findings format**: reuse `fixture_registry.py::_finding`'s exact shape
   (`invariant`, `boundary`, `teste`, `motivo`, `severidade`, `detalhe`) so
   golden-corpus failures surface through the same P0/P1 vocabulary as the
   rest of `scripts/quality/*` and can be aggregated by whatever currently
   aggregates `fixture_registry.validate_fixture_registry`'s output (the
   implementer should confirm this wiring in `scripts/quality/verify_core.py`
   — not fully traced in this pass, see OPEN_QUESTIONS #7).
6. **`NO_REAL_CASE_PRIVATE_DATA` mechanical guard**: a companion check that
   greps every case's serialized JSON text for the literal substring
   `"referencias/privadas"` (or a path starting with it) and fails loud if
   found — the same philosophy as `core_baseline.py`'s `PRIVATE_PREFIX`
   check, applied to corpus content instead of the Core manifest.
7. **CLI**: `python -m scripts.quality.golden_corpus --check`, exit 0/1,
   mirroring `core_baseline.py`'s ergonomics. An optional `--coverage-map`
   flag (see below) renders the generated coverage document.

### What this runner deliberately does NOT do

It does not attempt general UUID/wall-clock normalization across the Core —
that is explicitly `SEMANTIC_DETERMINISM_V1`/`REPLAY_V1`'s scope per the
`gapMatrix`. It only special-cases the one field HOTSPOT-03 is confirmed to
emit (`identificacao.data_geracao`), via each case's own
`non_semantic_fields_ignored` list, keeping the runner itself simple and
hotspot-agnostic rather than embedding hotspot knowledge into shared
comparison code.

---

## COVERAGE_MAP_PROPOSAL

**Generate it from the registry; do not hand-author it.** Every case already
carries `hotspot_id` (file-level), `semantic_families`, and
`invariants_exercised`. A hand-maintained coverage doc drifts from the
registry the moment someone adds or removes a case without remembering to
update the doc — the exact "documented coverage map" exit criterion should
be satisfied by an artifact that is mechanically regenerated and
mechanically verified not-stale, the same way `core_baseline.py --check`
already treats its own baseline file.

Concretely:

- `python -m scripts.quality.golden_corpus --coverage-map` renders a matrix:
  rows = the 20 semantic families named in the objective (allegations,
  documentary evidence, observations, measurements, technical inference,
  inconclusive findings, contradictory evidence, normative references,
  provenance, professional override, source value, engine decision, AI
  proposal that must NOT become effective alone, absent information,
  unverifiable information, not observed, correction persistence,
  deterministic replay, reordered inputs, duplicate inputs, equivalent
  input representations); columns = the 5 `HOTSPOT_ID`s; cells = `GOLDEN`
  case IDs (or `N/A` from the registry's `not_applicable` block, or empty =
  genuine gap).
- Structural validation: every case MUST declare at least one
  `semantic_families` entry and at least one `invariants_exercised` entry
  (extend `golden_corpus.py`'s own checks the same way
  `fixture_registry.py` already requires `{arquivo, dominio, schema,
  consumer, finalidade, expected}` on every fixture entry) — a case with an
  empty family list can't contribute to the map and should fail validation,
  not silently render as a blank cell.
- Output target: `docs/stabilization/golden-forensic-corpus-v1-coverage.md`
  (generated, committed, and — like `core-stable-baseline-v1.md`/`.sha256`
  — checked for staleness by regenerating and diffing in `--check` mode,
  so it cannot silently drift from the registry that produced it).
- `N/A` cells require one human decision each, recorded in the registry's
  `not_applicable` block with a `reason` string (example given in
  REGISTRY_SCHEMA_PROPOSAL: `professional_override` is `N/A` for HOTSPOT-04
  because `validar_integridade` is a pure structural validator with no
  engine-decision surface). This keeps genuine gaps visually distinct from
  deliberate non-applicability in the rendered table, rather than
  conflating "nobody wrote this case yet" with "this case doesn't make
  sense here."

---

## OPEN_QUESTIONS

1. **`GC-MOTOR-001`'s exact literal input text is not yet validated.** I
   specified the required aspect-tags (`INTERFACE_IDENTIFICADA`,
   `VEDACAO_DETERIORADA`, `PRECIPITACAO_REGISTRADA`,
   `DETALHE_CONSTRUTIVO_DOCUMENTADO`, `EXECUCAO_DIVERGENTE_DOCUMENTADA`) and
   the independent-source-count requirements from reading
   `evidencias.py::PADROES_OBSERVAVEIS` and
   `regras_probatorias.py::suporte_endogeno`/`fontes_independentes`, but I
   have not executed the function to confirm a literal fixture reaches
   `MAIS_PROVAVEL` + `ENDOGENA_CONSTRUTIVA` + `reparo_completo`
   simultaneously. This is real construction/iteration work for whoever
   implements Stage 2, not a research gap closeable by further reading.

2. **Registry file layout**: one file per hotspot under
   `tests/fixtures/golden_corpus/` (recommended above) vs. a single
   `tests/fixtures/golden-corpus-v1.json`. The single-file alternative gives
   one source of truth for the coverage-map cross-reference and a smaller
   `core-fixtures.json` footprint (1 entry vs. 5), at the cost of larger
   diffs and worse git-blame granularity when a case is added during
   per-hotspot refactor work later. Needs a decision before implementation
   since it determines the registration shape.

3. **Input reuse mechanism**: this design recommends fully literal `input`
   per case (no `$fixture`/overlay indirection) for V1, since no generic
   deep-merge utility exists in the repo today (the closest precedent,
   `test_hotspot_validar_integridade_v1.py::_manifesto`, does a *shallow*
   `dict.update()`, not a deep merge) and inventing merge semantics is
   itself a design decision that would need its own scrutiny. Revisit if
   corpus size makes duplication genuinely painful.

4. **`RAISES` case shape** (`{"raises": {"type": "...", "message_contains":
   "..."}}`) is a new convention, not present in any existing repo JSON
   fixture. Needed for `GC-DELIM-006` and the HOTSPOT-04
   `manifesto_malformado` case. Needs explicit sign-off before
   implementation, or an alternative (e.g. keep exception-raising cases out
   of the JSON corpus entirely and leave them as plain unittest methods,
   losing their place in the generated coverage map).

5. **Fixture reuse across the existing `tests/fixtures/pje/`,
   `tests/fixtures/schemas/`, `tests/fixtures/planejamento/`, etc.
   directories vs. full self-containment.** I read `NO_REAL_CASE_PRIVATE_DATA`
   /"first-party, synthetic" as being about *content* (no real case data),
   not about file-sharing — so a golden case referencing
   `tests/fixtures/schemas/processo-valido.json` by copying its (already
   synthetic) content inline should be fine — but this should be confirmed
   explicitly since "first-party" could also be read as "the corpus must be
   fully self-contained, zero cross-references."

6. **Exact status vocabulary for the one excluded HOTSPOT-04 case.** I
   recommend keeping `test_conflito_resolvido_por_fonte_primaria_nao_bloqueia_status_validado`
   in the corpus tagged `CHARACTERIZED_NOT_APPROVED` (regression-pinned but
   excluded from "golden" coverage counts) rather than dropping it, since
   losing coverage of a known landmine seems worse than flagging it — but
   this is exactly the kind of call the objective says needs human
   isolation, not silent inclusion under either extreme.

7. **Gate severity**: whether `golden_corpus.py` findings should block
   `verify_core.py`/CI at P0 or stay P1/informational for V1. I did not
   fully trace `scripts/quality/verify_core.py`'s aggregation logic in this
   research pass to make a confident recommendation — the implementer
   should check how `fixture_registry.validate_fixture_registry`'s findings
   are currently wired into the gate before deciding golden_corpus's
   default severity.

8. **`GC-VISTORIA-001`'s confidence-formula quirk** (an unambiguous
   *explicit* photo-id match never reaches `confianca.nivel=="ALTA"`,
   only `"MEDIA"`) — worth a human decision on whether this deserves the
   same `CHARACTERIZED_NOT_APPROVED` treatment as the HOTSPOT-04 precedent,
   or whether it's simply intended (explicit id match still isn't visual
   confirmation, so `MEDIA` may be correct-by-design). This design freezes
   it as characterized either way but doesn't resolve which status is
   right.

9. **Baseline version bump.** Registering the corpus in
   `tests/fixtures/core-fixtures.json` changes what
   `core_baseline.py::_manifest_paths` includes, which changes
   `config/core-stable-baseline-v1.json`'s `coreManifest`/`fixtureBaseline`
   and its `semanticFingerprint`/`.sha256`. `core_baseline.py` currently
   hardcodes `SUPPORTED_BASELINES = {"V1": "1.0.0"}` and a single pinned
   `TRUSTED_EVIDENCE` SHA for `("V1", "8530584c82061fb35018afd6638032ba8798b105")`.
   Landing Stage 2 will require either a new baseline version (`V2`) with
   its own evidence receipt, or some other accepted amendment process for
   `core-stable-baseline-v1.json` — this is a real blocker for a clean merge
   that needs a plan before implementation starts, and is out of this
   design's scope to resolve.

---

## RESOLUCOES_STAGE_2 (implementação real, Issue #78)

Registradas aqui para rastreabilidade — este documento continua sendo o
design original; as decisões abaixo são o que a implementação de fato
adotou, incluindo duas correções que a pesquisa original errou.

- **OPEN_QUESTIONS #9 (baseline version bump) — RESOLVIDA, hipótese original
  estava ERRADA.** `config/core-stable-baseline-v1.json` é um snapshot
  histórico **congelado** em um SHA fixo (`8530584c...`, ver
  `.github/workflows/core-safety.yml`'s step "Verify frozen Core V1"),
  construído via `git ls-tree`/`git show` NAQUELE commit — não a partir do
  HEAD corrente. Nenhum workflow de CI invoca `core_baseline.py --check`;
  é um utilitário observacional standalone. Registrar
  `tests/fixtures/golden_corpus/*.json` no HEAD atual não altera o
  snapshot congelado. Nenhuma mudança em `core-stable-baseline-v1.json`
  faz parte de Stage 2.
- **OPEN_QUESTIONS #7 (severidade de gate) — RESOLVIDA sem tocar
  `verify_core.py`.** `scripts/quality/verify_core.py` está em
  `config/capability-protected-artifacts-v1.json` (hash-pinned) —
  alterá-lo abriria uma nova transição de trust/capability, fora de
  escopo. Solução por composição: `tests/test_golden_forensic_corpus_v1.py`
  é descoberto automaticamente pelo step "regression" já existente
  (nenhum `--ignore` bate com o novo arquivo), e cada fixture é validada
  quanto a estar "realmente exercitada" pelo `validate_fixture_registry`
  já plugado. Resultado: qualquer drift no corpus falha o step
  "regression", já classificado P0/`FAIL_CLOSED`/`CORE` — sem nenhuma
  linha nova em `verify_core.py`.
- **Vocabulário de status mudou** de `GOLDEN`/`PROPOSED` (proposta original
  deste documento) para `APPROVED`/`CHARACTERIZED_NOT_APPROVED`/`KNOWN_BUG`,
  por instrução direta do revisor humano. Apenas `APPROVED` conta para o
  mapa de cobertura; os outros dois continuam bloqueantes (qualquer drift
  ainda quebra o gate) mas ficam documentados como não endossados.
- **Campos declarativos adicionados** a cada caso:
  `expected_provenance`/`expected_classifications`/`expected_warnings`/
  `expected_inconclusivity` (todos opcionais, `null` quando não aplicável)
  — o corpus não pode virar apenas `assert actual == json_gigante`; cada
  caso declara por que existe. Combinado com `invariants_exercised`
  específico por caso, uma quebra futura aparece como
  "quebrou ORDER_INVARIANCE no caso GC-MOTOR-007", não "JSON diferente".
- **HOTSPOT-02 (`gerar_vistoria`) — `normalizar()` permanece
  deliberadamente sem caso golden.** A Issue #74 já provou que
  `normalizar(obs.get("elemento"))` (linha ~128) é código morto: nenhum
  caminho first-party de `gerar()` popula a chave `"elemento"` em
  `medicoes`/`fotos`. Construir manualmente esse shape só para exercitar a
  linha criaria um contrato artificial para um caminho morto. Registrado
  como `known_unreachable` no corpus:
  `NORMALIZAR_REACHABILITY_TODAY=false`, `LATENT_DEFECT=true`,
  `GOLDEN_EXECUTION_CASE=null` — permanece assim até existir uma entrada
  first-party legítima que torne o caminho alcançável.
- **HOTSPOT-03 (`gerar_delimitacao`) — lista de casos expandida** de 6 para
  10 casos obrigatórios (perfis VICIOS_CONSTRUTIVOS/AVALIACAO_IMOBILIARIA/
  ENGENHARIA_RODOVIARIA/OUTRO, deduplicação, pertinência, confiança MEDIA,
  entrada reordenada, entrada semanticamente equivalente, dados
  insuficientes), com atenção especial a: mesma informação semanticamente
  equivalente em ordem ou representação diferente deve produzir a mesma
  decisão técnica — divergência real vira achado (`KNOWN_BUG`/
  `CHARACTERIZED_NOT_APPROVED`), nunca é escondida.
