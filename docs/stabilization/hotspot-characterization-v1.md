# Hotspot Characterization V1

`HOTSPOT_ID` prefix `HOTSPOT-`. Ranking uses fresh re-measurement via
`scripts/quality/metrics.py::analyze_complexity` against the current protected
base, not the historical `config/quality-baseline.json` hotspot list taken on
faith. That list's 5 tracked functions match the fresh measurement exactly
(unchanged); a full sweep of `scripts/motor_vicios`, `scripts/triagem_pericial`,
`scripts/planejamento_pericial`, `scripts/redacao_pericial`,
`scripts/vistoria_estruturada`, `scripts/conhecimento_privado`,
`scripts/extracao_pje`, `scripts/backend_contract` (340 functions) surfaces 4
higher-complexity functions never previously tracked.

Fills the gap named in `scripts/quality/core_baseline.py`'s `gapMatrix`:
`{"area": "Hotspot Characterization", "gap": "No complete entrypoint
characterization matrix", "nextProgramStage": "HOTSPOT_CHARACTERIZATION_V1"}`.

## Inventário canônico

| HOTSPOT_ID | MODULE::FUNCTION | COMPLEXITY | LENGTH | SEMANTIC_RISK | REFACTOR_PRIORITY |
|---|---|---:|---:|---|---|
| HOTSPOT-01 | `scripts/motor_vicios/motor.py::executar` | 130 | 65 | HIGH — feeds `conclusao_tecnica`/`elegibilidade_orcamento` directly into the laudo | 1 |
| HOTSPOT-02 | `scripts/vistoria_estruturada/gerar_vistoria.py::gerar` | 117 | 85 | HIGH — canonical `vistoria.json`, drives ALEGAÇÃO→...→CONCLUSÃO chain | 2 |
| HOTSPOT-03 | `scripts/triagem_pericial/gerar_delimitacao.py::gerar` | 96 | 195 | HIGH — determines what gets investigated/measured; no try/except (fail-loud) | 3 |
| HOTSPOT-04 | `scripts/extracao_pje/validar_integridade.py::validar_integridade` | 76 | 75 | HIGH — hard gate for 3 downstream consumers; false PASS lets corrupted extraction flow silently | 2 |
| HOTSPOT-05 | `scripts/motor_vicios/autocorrigir.py::autocorrigir` | 72 | 84 | MEDIUM-HIGH — corrections reach report text without an in-code professional-decision gate (allowed by `AUTOCORRECTION` boundary/`ENGINE_DECISION` tier, but primary reduction loop is untested) | 3 |
| HOTSPOT-06 | `scripts/motor_vicios/auditar.py::auditar` | 58 | 37 | Not yet deep-characterized this round | — |
| HOTSPOT-07 | `scripts/planejamento_pericial/gerar_plano.py::gerar` | 57 | 73 | Already tracked historically; not re-characterized this round (unchanged since prior baseline) | — |
| HOTSPOT-08 | `scripts/redacao_pericial/auditar_fidelidade.py::auditar_fidelidade` | 53 | 57 | Not yet deep-characterized this round | — |

`REFACTOR_PRIORITY` uses `RISK × COMPLEXITY × CHANGE_FREQUENCY × DOMAIN_CRITICALITY / CHARACTERIZATION_CONFIDENCE`,
qualitative not numeric at this stage: HOTSPOT-01 ranks first because it combines
the highest complexity, the most direct path to report content, and the
shallowest coverage of its highest-value branches. HOTSPOT-04 ranks second
despite lower complexity because it is a pure, dependency-free function where
characterization is cheap and several concrete branches were provably
untested (see below) — best fix-cost-to-risk-reduction ratio.

## HOTSPOT-01 — `scripts/motor_vicios/motor.py::executar`

- **RESPONSIBILITY**: top-level orchestrator of the Motor Técnico de Vícios
  Construtivos. Given `processo`, `delimitacao`, `plano` (dead parameter — never
  read), `vistoria`, optional `contexto`/`conhecimento`: gates on perícia type
  and inspection readiness, groups observations into manifestações, generates
  causal hypotheses, derives origin/criticidade/reparo/vício classification
  (computed twice — a first pass at lines 44-57 is superseded by a second pass
  at lines 58-79, a real complexity smell), saneia questões técnicas, and
  self-audits.
- **DEPENDENCIES**: `triagem_pericial.semantica.intencoes`, `.auditar`,
  `.hipoteses`, `.regras`, `.evidencias`, `.normas` (module-level + one
  function-local import inside the per-PAT norm loop).
- **STATE_MUTATION**: builds a new result dict; does not mutate `processo`/
  `delimitacao`/`vistoria`. One in-place self-mutation (`n.clear();n.update(...)`
  on its own output's norm entries, line 79) worth an order/aliasing
  characterization test. `catalogo_evidencias` entries carry shared list
  references from source `vistoria` items (not copied) — no current code path
  mutates them, but a future one could silently corrupt caller data; worth an
  explicit "vistoria unchanged after executar()" test.
- **ERROR_PATHS**: no try/except anywhere in the function body — fails loud.
  Concrete crash sites: `delimitacao["tipo_pericia"]["tipo"]` (line 29,
  unguarded), missing observation keys, and a `StopIteration` risk (line 81)
  if the PAT-id↔MAN-id numeric-suffix invariant is ever broken.
- **CURRENT_TEST_COVERAGE**: ~9 direct unit tests in `tests/test_motor_vicios.py`
  cover the readiness gate, wrong-tipo early return, and each `situacao()`
  branch individually. This PR adds 2 more, targeting the two cheapest-to-reach
  previously-untested branches (both reachable via existing fixture
  scaffolding, no evidencia/hipótese wiring needed):
  `test_contexto_override_explicito_afeta_ressalvas_mas_nao_sobrevive_a_segunda_passada`
  and `test_norma_recuperada_e_avaliada_no_laco_de_conformidade_da_segunda_passada`.
  The first empirically discovered and now documents a genuine
  `CHARACTERIZED_NOT_APPROVED` finding: `contexto` override's
  `evidencias_ausentes` durably lands in `ressalvas`/`analise_causal.limitacoes`
  (neither field is rewritten by the second pass), but a `causalidade`
  override's effect on `origem`/`criticidade`/`vicio_construtivo`/
  `elegibilidade_orcamento` is silently discarded by the second pass, which
  rebuilds those four fields from `p.get("causa")` with no reference to `ctx`
  at all — i.e. the override mechanism is only partially effective today, in
  a way that isn't documented anywhere else in the codebase. Still NOT
  directly asserted (deferred to `GOLDEN_FORENSIC_CORPUS_V1`, which requires
  cross-module evidencia/hipótese fixture wiring beyond this stage's scope):
  causal-chain-established path (`MAIS_PROVAVEL` hypothesis →
  `causa`/`mecanismo` populated end-to-end through both passes),
  `vicio_construtivo.caracterizado=True`, `elegibilidade_orcamento ==
  "ELEGIVEL_ORCAMENTO_VICIO"`, a norm reaching an `ATENDE`/`NAO_ATENDE`
  verdict (requires matching MEDICAO evidence), and the saneamento status
  matrix.
- **CHARACTERIZATION_CONFIDENCE**: LOW on the causal-chain/vício/elegibilidade
  branches; MEDIUM-HIGH on the gate/situação dispatch and the two branches
  this PR now covers (contexto-override field survival, norm-conformity loop
  reachability).
- **RECOMMENDED_BOUNDARY**: leave orchestration shape alone until Golden Corpus
  exists; the two-pass PAT computation (compute-then-overwrite) is the most
  promising extraction boundary for `MAINTAINABILITY_REFACTORING_V1` once
  characterized.

## HOTSPOT-04 — `scripts/extracao_pje/validar_integridade.py::validar_integridade`

- **RESPONSIBILITY**: pure relational validator over a `manifesto` dict,
  complementing JSON Schema with cross-field invariants. Returns
  `(erros, alertas)`; never raises intentionally, never mutates input.
- **DEPENDENCIES**: none — zero imports, fully self-contained.
- **STATE_MUTATION**: none (pure).
- **ERROR_PATHS**: no try/except; several unguarded direct-index accesses
  (`manifesto["documentos"]`, deep chain
  `manifesto["processo"]["numero_cnj"]["proveniencia"]["pagina_pdf"]`) create
  real `KeyError` risk on malformed input, inconsistent with the `.get(...)`
  style used elsewhere in the same function (e.g. line 36 vs line 58 access
  the same `conflitos` field two different ways).
- **CURRENT_TEST_COVERAGE**: 7 direct unit-test calls across 3 files, all
  fixture-driven, no PDF/full pipeline. NOT directly tested: ambiguous-link
  divergence (line 10-11), duplicate `documento_id` (21-22), início>fim
  inversion (16-17), `CONFIRMADO`-with-conflicting-IDs (29-30),
  paginação-interna alerta (32-33), the `metricas_extracao` field-by-field
  mismatch loop (68-75), and the CNJ-provenance alert (76-77).
- **CHARACTERIZATION_CONFIDENCE**: previously LOW on the branches above; this
  PR raises it to HIGH — see `tests/test_hotspot_validar_integridade_v1.py`.
- **SEMANTIC_RISK**: hard gate — `gerar_documentos.py`, `gerar_delimitacao.py`,
  `gerar_processo.py` each independently re-check `status_validacao`/`erros`
  and `raise ValueError` if not `VALIDADO`; none re-derive integrity
  themselves, so a false PASS here (e.g. via an untested branch silently
  returning no error on real corruption) would let corrupted PJe extraction
  flow into the rest of the pipeline undetected.
- **RECOMMENDED_BOUNDARY**: candidate for future decomposition by check
  category (index-range checks / accounting checks / metrics checks), but
  behavior-preserving only — no functional change in this stage.

## HOTSPOT-02, 03, 05 — summary (full field data in agent transcripts, not duplicated here)

- **HOTSPOT-02** (`gerar_vistoria.py::gerar`, 117): pure w.r.t. inputs, heavily
  imperative internally. The known `normalizar()` undefined-name finding
  (Issue #74) traced to confirmed dead code — `medicoes`/`fotos` dict literals
  never set an `"elemento"`/`"manifestacao"` key, so the guarding `and`
  short-circuits before reaching `normalizar()` for any input. Marked inline
  (`# TODO(#74)`, PR #75) as `CHARACTERIZED_NOT_APPROVED`: known landmine,
  confirmed unreachable today, not fixed pending a product decision on which
  of two existing `normalizar`-shaped candidates (`semantica.py::_n`,
  `motor_vicios/normas.py::normalizar_fonte_normativa`) is intended, or
  whether a distinct implementation is needed.
- **HOTSPOT-03** (`gerar_delimitacao.py::gerar`, 96): no try/except anywhere
  (fail-loud by design). Coverage is shallow/incidental — only 5-6 E2E call
  sites, each once, driving a single happy-path fixture; `AVALIACAO_IMOBILIARIA`/
  `ENGENHARIA_RODOVIARIA`/`OUTRO` profile branches, quesito-dedup, and the
  `MEDIA`-confidence RES-003 branch are untested.
- **HOTSPOT-05** (`autocorrigir.py::autocorrigir`, 72): deep-copies input,
  never mutates it; every audit-driven correction is individually logged to an
  append-only `historico` trail with before/after values, which survives into
  `laudo.metadados_de_auditoria.autocorrecoes`. Confirmed against
  `config/core-boundaries.json`: this function sits under the `AUTOCORRECTION`
  boundary (`CORRECTION_PERSISTENCE`, `IDEMPOTENCE`, `NO_SILENT_OVERWRITE`),
  not the `BACKEND_AUTHORITY` boundary that enforces
  `PROPOSAL_NOT_EFFECTIVE_WITHOUT_DECISION` — so corrections reaching report
  text without an in-code professional-decision gate is consistent with this
  repo's own governance model (deterministic `ENGINE_DECISION` tier, no LLM
  involved), not a violation. The primary audit-verdict-driven reduction loop
  (lines 13-38 — the largest, highest-complexity half of the function) is
  untested by any direct unit test today: zero repo-wide matches for its
  action labels (`REDUZIR_CLAIM`, `REMOVER_CARACTERIZACAO`, etc.) in `tests/`.

## Comportamento suspeito registrado

- `scripts/vistoria_estruturada/gerar_vistoria.py` lines 128-129:
  `CHARACTERIZED_NOT_APPROVED` — `normalizar()` undefined, confirmed
  unreachable, tracked as Issue #74, not blessed as golden.
- `scripts/motor_vicios/motor.py::executar` line 28: dead parameter `plano`
  (accepted, never read) — `AMBIGUOUS_BEHAVIOR`, not a bug but worth a
  decision (remove from signature vs. document why it's reserved) before any
  refactor touches the function signature.
- `scripts/motor_vicios/motor.py::executar` lines 48-54 vs. 58-79: `contexto`
  override's `causalidade` merge only reaches the function's FIRST pass;
  the second pass rebuilds `origem`/`criticidade`/`vicio_construtivo.caracterizado`/
  `elegibilidade_orcamento` from `p.get("causa")` with no reference to `ctx`,
  silently discarding the override's effect on those four fields.
  `evidencias_ausentes` survives (it lands in fields the second pass never
  rewrites). `AMBIGUOUS_BEHAVIOR`, empirically confirmed and now regression-
  tested (`tests/test_motor_vicios.py::test_contexto_override_explicito_afeta_ressalvas_mas_nao_sobrevive_a_segunda_passada`) --
  not fixed here; whether the override SHOULD survive the second pass is a
  product decision, not a mechanical one.
- `scripts/extracao_pje/validar_integridade.py` line 72:
  `metricas_extracao.conflitos_abertos` is verified against
  `len(manifesto["conflitos"])` — total conflict count, not conflicts
  filtered by `status=="ABERTO"` despite the field's name. Found while
  writing `tests/test_hotspot_validar_integridade_v1.py`
  (`test_conflito_resolvido_por_fonte_primaria_nao_bloqueia_status_validado`).
  `AMBIGUOUS_BEHAVIOR`: may be intentional (the metric could genuinely mean
  "conflicts recorded", not "conflicts currently open"), but the name invites
  the opposite reading. Not changed here — naming/semantics decision, not a
  mechanical fix.
- `scripts/extracao_pje/validar_integridade.py` lines 36-48: a
  `RESOLVIDO_POR_FONTE_PRIMARIA` conflict is fully skipped by the page-overlap
  loop, and (line 60) also skipped by the índice-item accounting loop — so a
  resolved conflict's `itens_indice_relacionados` never gets an accounting
  entry at all, even though it references a real índice item.
  `CHARACTERIZED_NOT_APPROVED`: preserved as-is by
  `test_conflito_resolvido_por_fonte_primaria_nao_bloqueia_status_validado`,
  not endorsed as correct.

## Próxima etapa

`GOLDEN_FORENSIC_CORPUS_V1` (Issue TBD) builds a deterministic first-party
corpus exercising the branch categories enumerated above across all 5
hotspots, not just HOTSPOT-01/04. `MAINTAINABILITY_REFACTORING_V1` refactors
only once each targeted hotspot has corpus coverage, per hotspot, one at a
time.
