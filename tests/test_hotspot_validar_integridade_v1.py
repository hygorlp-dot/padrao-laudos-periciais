"""Characterization tests for HOTSPOT-04 (scripts/extracao_pje/validar_integridade.py).

Part of HOTSPOT_CHARACTERIZATION_V1 (Issue #76). Captures current externally
observable behavior of validar_integridade's branches that were provably
untested before this PR (see docs/stabilization/hotspot-characterization-v1.md).
These are behavioral characterization tests, not implementation-detail tests:
each asserts on the (erros, alertas) contract the function already exposes.
No behavior is changed by this file.
"""
import copy
import json
import unittest
from pathlib import Path

from scripts.extracao_pje.validar_integridade import validar_integridade


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "pje" / "manifesto-minimo-valido.json").read_text(encoding="utf-8")
)


def _manifesto(**overrides):
    manifesto = copy.deepcopy(FIXTURE)
    manifesto.update(overrides)
    return manifesto


class ValidarIntegridadeCaracterizacaoTest(unittest.TestCase):
    def test_baseline_fixture_is_clean(self):
        """Sanity anchor: the shared fixture itself produces no erros/alertas."""
        erros, alertas = validar_integridade(_manifesto())
        self.assertEqual(erros, [])
        self.assertEqual(alertas, [])

    def test_associacao_ambigua_com_destino_escolhido_e_erro(self):
        manifesto = _manifesto()
        item = manifesto["indice"]["itens"][0]
        item["candidatos_destino_link"] = [3, 4]
        item["destino_escolhido_link"] = 3
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("associação ambígua não pode escolher destino" in e for e in erros))

    def test_destino_escolhido_divergente_do_destino_segmentacao_e_erro(self):
        manifesto = _manifesto()
        item = manifesto["indice"]["itens"][0]
        item["pagina_destino_link"] = 3
        item["destino_escolhido_link"] = 2
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("destino escolhido diverge do destino de segmentação" in e for e in erros))

    def test_documento_id_duplicado_e_erro(self):
        manifesto = _manifesto()
        original = manifesto["documentos"][0]
        duplicado = copy.deepcopy(original)
        duplicado["pagina_pdf_inicio"] = 4
        duplicado["pagina_pdf_fim"] = 4
        duplicado["total_paginas"] = 1
        manifesto["documentos"].append(duplicado)
        manifesto["arquivo"]["total_paginas"] = 4
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("documento_id duplicado" in e for e in erros))

    def test_inicio_posterior_ao_fim_e_erro(self):
        manifesto = _manifesto()
        manifesto["documentos"][0]["pagina_pdf_inicio"] = 3
        manifesto["documentos"][0]["pagina_pdf_fim"] = 2
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("início posterior ao fim" in e for e in erros))

    def test_confirmado_com_ids_conflitantes_e_erro(self):
        manifesto = _manifesto()
        manifesto["documentos"][0]["status_reconciliacao"]["id_indice"] = "900001"
        manifesto["documentos"][0]["status_reconciliacao"]["id_rodape"] = "900002"
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("CONFIRMADO com IDs conflitantes" in e for e in erros))

    def test_paginacao_interna_nao_comeca_em_1_e_apenas_alerta_nao_erro(self):
        manifesto = _manifesto()
        manifesto["paginas"][2]["pagina_documento_detectada"] = 2
        erros, alertas = validar_integridade(manifesto)
        self.assertTrue(any("paginação interna começa em" in a for a in alertas))
        self.assertFalse(any("paginação interna começa em" in e for e in erros))

    def test_salto_na_paginacao_interna_e_erro(self):
        manifesto = _manifesto()
        # Two-page document with internal pages [1, 3] -- a gap.
        manifesto["documentos"][0]["pagina_pdf_inicio"] = 2
        manifesto["documentos"][0]["pagina_pdf_fim"] = 3
        manifesto["documentos"][0]["total_paginas"] = 2
        manifesto["paginas"][1]["pagina_documento_detectada"] = 1
        manifesto["paginas"][2]["pagina_documento_detectada"] = 3
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("salto na paginação interna" in e for e in erros))

    def test_metrica_declarada_inconsistente_e_erro(self):
        manifesto = _manifesto()
        manifesto["metricas_extracao"]["documentos_confirmados"] = 0
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("Métrica documentos_confirmados inconsistente" in e for e in erros))

    def test_cnj_principal_sem_origem_em_pagina_do_indice_e_apenas_alerta(self):
        manifesto = _manifesto()
        manifesto["processo"]["numero_cnj"]["proveniencia"]["pagina_pdf"] = 99
        erros, alertas = validar_integridade(manifesto)
        self.assertTrue(any("CNJ principal sem origem" in a for a in alertas))
        self.assertFalse(any("CNJ principal" in e for e in erros))

    def test_status_validado_incompativel_com_conflito_bloqueante_aberto_e_erro(self):
        manifesto = _manifesto()
        manifesto["conflitos"] = [{
            "conflito_id": "CONF-001", "status": "ABERTO", "bloqueante": True,
            "itens_indice_relacionados": [],
        }]
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("Status VALIDADO incompatível" in e for e in erros))

    def test_conflito_aberto_na_mesma_pagina_de_um_documento_e_erro(self):
        """Control case establishing the page really does collide: an ABERTO
        (not RESOLVIDO_POR_FONTE_PRIMARIA) conflict placed on the same page
        already owned by DOC-PJE-001 (page 3) must be caught by the
        page-overlap loop, proving the fixture used by the next test is a
        genuine collision, not an inert page nothing else touches."""
        manifesto = _manifesto()
        manifesto["metricas_extracao"]["conflitos_abertos"] = 1
        manifesto["conflitos"] = [{
            "conflito_id": "CONF-001", "status": "ABERTO", "bloqueante": False,
            "pagina_pdf_inicio": 3, "pagina_pdf_fim": 3, "total_paginas": 1,
            "itens_indice_relacionados": ["DOC-PJE-001"],
        }]
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("owners incompatíveis" in e for e in erros))

    def test_conflito_resolvido_por_fonte_primaria_nao_bloqueia_status_validado(self):
        """KNOWN characterized behavior, not necessarily approved as ideal: a
        RESOLVIDO_POR_FONTE_PRIMARIA conflict is fully skipped by both the
        page-overlap loop (line 38) and the accounting loop (line 60), so it
        contributes neither an error nor an accounting entry for its
        itens_indice_relacionados, even though it references a real índice
        item. This is CHARACTERIZED_NOT_APPROVED: preserved as-is here, not
        endorsed as correct behavior for this maintainability program.

        Placed on the SAME page (3) already owned by DOC-PJE-001 -- the
        preceding test proves that exact placement collides and produces an
        error when status is ABERTO. Using the identical colliding page here
        (rather than an unoccupied one) makes the skip's page-overlap-loop
        branch genuinely load-bearing for this assertion, not just the
        accounting-loop branch.

        Also characterizes a naming/behavior mismatch found while writing
        this test: metricas_extracao.conflitos_abertos is verified against
        len(manifesto["conflitos"]) (line 72 of validar_integridade.py) --
        i.e. total conflict count, not a count filtered by status=="ABERTO"
        despite the field's name. Set to 1 here (matching the one conflict
        entry added, regardless of its RESOLVIDO status) to isolate the
        skip behavior under test from this separate, unrelated metric-
        mismatch branch."""
        manifesto = _manifesto()
        manifesto["metricas_extracao"]["conflitos_abertos"] = 1
        manifesto["conflitos"] = [{
            "conflito_id": "CONF-001", "status": "RESOLVIDO_POR_FONTE_PRIMARIA",
            "pagina_pdf_inicio": 3, "pagina_pdf_fim": 3, "total_paginas": 1,
            "itens_indice_relacionados": ["DOC-PJE-001"],
        }]
        erros, _ = validar_integridade(manifesto)
        self.assertEqual(erros, [])

    def test_pendencia_nao_aberta_e_ignorada_pelo_loop_de_intervalo(self):
        manifesto = _manifesto()
        manifesto["pendencias"] = [{
            "pendencia_id": "PEND-001", "status": "RESOLVIDA",
            "pagina_pdf_inicio": 3, "pagina_pdf_fim": 3,
        }]
        erros, _ = validar_integridade(manifesto)
        self.assertEqual(erros, [])

    def test_manifesto_malformado_falha_com_keyerror_nao_degradado(self):
        """Characterizes the documented lack of defensive error handling
        (no try/except in validar_integridade): a manifesto missing a
        required key crashes with a raw KeyError rather than a handled
        validation error. This is the current, intentional-by-omission
        contract -- callers must validate against JSON Schema first."""
        manifesto = _manifesto()
        del manifesto["metricas_extracao"]
        with self.assertRaises(KeyError):
            validar_integridade(manifesto)

    def test_manifesto_is_not_mutated(self):
        manifesto = _manifesto()
        before = copy.deepcopy(manifesto)
        validar_integridade(manifesto)
        self.assertEqual(manifesto, before)


if __name__ == "__main__":
    unittest.main()
