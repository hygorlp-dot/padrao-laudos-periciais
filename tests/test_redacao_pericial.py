import copy
import json
import unittest
from pathlib import Path

from jsonschema.validators import validator_for

from scripts.redacao_pericial import (
    auditar_estilo,
    auditar_fidelidade,
    autocorrigir,
    executar_pipeline_redacao,
    planejar,
    redigir,
)
from scripts.redacao_pericial.auditar_estilo import auditar_redundancia_estrutural
from scripts.redacao_pericial.auditar_fidelidade import auditar_laudo_semantico


TITULOS = ["Análise das Alegações e Prováveis Causas", "Consequências", "Classificação", "Conclusão"]


def evidencia(identificador, tipo, aspectos):
    return {"id": identificador, "tipo": tipo, "classe_probatoria": "EVIDENCIA_PRIMARIA", "proveniencia": ["FONTE-SINTETICA"], "aspectos_suportados": aspectos, "aspectos_contraditos": [], "acessivel": True}


def pat(identificador, situacao, origem, criticidade, conclusao, evidencia_id, *, causa=None, grau="CONFIRMADO", ressalvas=None):
    consequencias = {nome: {"status": "NAO_APLICAVEL", "evidencias": [], "fundamentacao": None, "confianca": "ALTA"} for nome in ("seguranca", "salubridade", "funcionalidade", "desempenho", "estanqueidade", "durabilidade", "estetica", "usabilidade", "evolucao", "extensao")}
    consequencias["estetica"] = {"status": "PRESENTE", "evidencias": [evidencia_id], "fundamentacao": "repercussão visual localizada", "confianca": "ALTA"}
    return {
        "id": identificador, "manifestacao": "fissura" if situacao != "NAO_CONSTATADA" else "infiltração",
        "alegacoes_relacionadas": [f"ALG-{identificador[-3:]}"] , "constatacao": {"situacao": situacao, "descricao": "Sinais de fissura no revestimento" if situacao != "NAO_CONSTATADA" else "Infiltração alegada", "extensao": None, "metodo": ["INSPECAO_VISUAL"], "evidencias": [evidencia_id], "fotografias": []},
        "constatacoes": [evidencia_id], "evidencias": [evidencia_id], "medicoes": [], "analise_causal": {"causa_provavel": causa, "causas_alternativas": [], "fundamentos": [evidencia_id], "limitacoes": [], "grau_certeza": grau},
        "causa": causa, "origem": origem, "criticidade": criticidade, "consequencias": consequencias,
        "normas_relacionadas": [], "ressalvas": ressalvas or [], "conclusao_tecnica": conclusao,
        "confianca": {"nivel": "ALTA" if grau == "CONFIRMADO" else "MEDIA"},
    }


class RedacaoPericialTest(unittest.TestCase):
    def setUp(self):
        self.processo = {"numero_processo": "PROCESSO-SINTETICO-001", "documentos_relevantes": []}
        self.delimitacao = {"tipo_pericia": "VICIOS_CONSTRUTIVOS", "sintese_processual": {"texto": "As partes divergem sobre manifestações fictícias.", "proveniencia": ["DOC-001"]}, "tema_controvertido": {"texto": "Analisar manifestações sintéticas.", "proveniencia": ["DOC-001"]}, "objeto": {"texto": "Edificação sintética", "proveniencia": ["DOC-001"]}, "objetivo": {"texto": "Verificar as manifestações delimitadas.", "proveniencia": ["DOC-001"]}, "escopo": None, "ressalvas": [], "quesitos": [{"id": "QUE-001", "origem": "JUIZO", "numero_original": "1", "texto_integral": "Quais manifestações foram verificadas?", "questoes_tecnicas": ["QT-001"], "patologias_relacionadas": ["PAT-001", "PAT-002", "PAT-003"], "referencias_secoes": ["4.2"]}]}
        pats = [
            pat("PAT-001", "ANOMALIA", "ENDOGENA_CONSTRUTIVA", "MINIMA", "A manifestação foi confirmada no revestimento.", "OBS-001", causa="retração do revestimento", grau="PROVAVEL"),
            pat("PAT-002", "NAO_CONSTATADA", "NAO_APLICAVEL", "NAO_APLICAVEL", "A infiltração não foi constatada na data da vistoria.", "OBS-002", causa=None, grau="INCONCLUSIVO"),
            pat("PAT-003", "INCONCLUSIVA", "INCONCLUSIVA", "NAO_APLICAVEL", "A causa e a origem permaneceram inconclusivas.", "OBS-003", causa=None, grau="INCONCLUSIVO", ressalvas=["A inspeção foi limitada às superfícies acessíveis"]),
        ]
        aspectos = ["CONSTATACAO_DE_VISTORIA", "MANIFESTACAO_TECNICA", "INFERENCIA_TECNICA", "ORIGEM", "CONCLUSAO_DE_QT"]
        catalogo = [evidencia(f"OBS-{i:03d}", "OBSERVACAO", aspectos) for i in range(1, 4)] + [evidencia("DOC-001", "DOCUMENTO", aspectos)]
        self.final = {"estado_analise": "PAT_FINAL", "patologias": pats, "questoes_saneadas": [{"id": "QT-001", "status": "SANEADA", "patologias": ["PAT-001", "PAT-002", "PAT-003"], "conclusao": "Resultados consolidados."}], "catalogo_evidencias": catalogo}
        self.motor = {"gate": "APTO_PARA_REDACAO_COM_RESSALVAS", "analise_final": self.final}

    def test_planejamento_vincula_pat_qt_que_e_evidencias(self):
        plano = planejar(self.processo, self.delimitacao, self.motor)
        secao = next(s for s in plano["unidades_patologia"] if s["pat_id"] == "PAT-001")
        self.assertIn("QT-001", secao["qt_ids"]); self.assertIn("QUE-001", secao["que_ids"]); self.assertIn("OBS-001", secao["evidencias_permitidas"])

    def test_quatro_blocos_canonicos_e_claims_rastreaveis(self):
        r = redigir(planejar(self.processo, self.delimitacao, self.motor), self.final)
        self.assertTrue(all(b["titulos"] == TITULOS and len(b["textos"]) == 4 for b in r["blocos"]))
        self.assertTrue(all(c["pat_ids"] and c["obs_ids"] for c in r["claims"]))

    def test_nao_constatada_e_inconclusiva_preservadas(self):
        r = redigir(planejar(self.processo, self.delimitacao, self.motor), self.final)
        b2 = next(b for b in r["blocos"] if b["pat_id"] == "PAT-002"); b3 = next(b for b in r["blocos"] if b["pat_id"] == "PAT-003")
        self.assertIn("não foi constatada", b2["textos"][0]); self.assertNotIn("não existe", b2["textos"][0]); self.assertIn("não permitem individualizar", b3["textos"][0])

    def test_estilo_ruim_01_02_05_07_08_09(self):
        ruim = ("É importante destacar que a análise robusta, minuciosa e abrangente foi realizada. " * 2) + ("Ademais, nesse contexto, em síntese, foi constatado. " * 3) + "A análise a seguir tem por objetivo explicar."
        tipos = {a["tipo"] for a in auditar_estilo(ruim)}
        self.assertTrue({"ABERTURA_GENERICA", "CONECTIVO_REPETITIVO", "ADJETIVACAO_VAZIA", "METADISCURSO"} <= tipos)

    def test_textos_bons_nao_geram_falso_positivo_grave(self):
        bons = [
            "Na vistoria foi constatada fissura superficial no revestimento, sem degrau entre as bordas. A abertura medida foi de 0,4 mm. Os elementos disponíveis não permitem individualizar a causa específica.",
            "Não foram constatados sinais de infiltração na data da vistoria. Essa constatação não permite afirmar que o fenômeno jamais tenha ocorrido.",
            "A parte autora atribui a manifestação a recalque. Na vistoria, a fissura apresentou padrão superficial, sem degrau. Não foram obtidos elementos suficientes para vincular a manifestação a recalque diferencial.",
        ]
        self.assertTrue(all(not any(a["severidade"] == "CRITICO" for a in auditar_estilo(t)) for t in bons))

    def test_adv_red_01_02_04_07_08(self):
        r = redigir(planejar(self.processo, self.delimitacao, self.motor), self.final)
        alterada = copy.deepcopy(r); b = alterada["blocos"][2]
        b["textos"][0] += " A manifestação decorre inequivocamente de falha construtiva."
        b["textos"][2] = "Origem: ENDÓGENA/CONSTRUTIVA. Criticidade: CRÍTICA."
        b["textos"][0] = b["textos"][0].replace("A inspeção foi limitada às superfícies acessíveis.", "")
        tipos = {a["tipo"] for a in auditar_fidelidade(alterada, self.final)}
        self.assertTrue({"CAUSA_INCONCLUSIVA_FECHADA", "ORIGEM_ALTERADA", "RESSALVA_ENFRAQUECIDA"} <= tipos)
        alterada["blocos"][0]["textos"][0] += " Foi constatado que o morador informou o evento."
        self.assertIn("DECLARACAO_CONVERTIDA_EM_CONSTATACAO", {a["tipo"] for a in auditar_fidelidade(alterada, self.final)})

    def test_adv_red_03_norma_inventada_e_claim_nova(self):
        r = redigir(planejar(self.processo, self.delimitacao, self.motor), self.final)
        r["claims"][0]["nor_ids"] = ["NOR-999"]
        r["blocos"][0]["claim_ids"].append("CLAIM-RED-999")
        tipos = {a["tipo"] for a in auditar_fidelidade(r, self.final)}
        self.assertTrue({"NORMA_INVENTADA", "UNSUPPORTED_REDRAFT_CLAIM"} <= tipos)

    def test_fidelidade_numerica_valida_par_decimal_valor_unidade_sem_conversao(self):
        final = {"patologias": [], "catalogo_evidencias": [{"id": "MED-001", "tipo": "MEDICAO", "valor": "4", "unidade": "mm"}]}
        def tipos(texto):
            redacao = {"blocos": [], "claims": [{"id": "CLAIM-RED-001", "pat_ids": [], "med_ids": ["MED-001"], "nor_ids": [], "texto_semantico": texto}]}
            return {a["tipo"] for a in auditar_fidelidade(redacao, final)}
        self.assertIn("MEDICAO_ALTERADA", tipos("A abertura medida foi de 40 mm."))
        self.assertIn("MEDICAO_ALTERADA", tipos("A abertura medida foi de 4 cm."))
        self.assertNotIn("MEDICAO_ALTERADA", tipos("A abertura medida foi de 4,0 mm."))
        self.assertNotIn("MEDICAO_ALTERADA", tipos("A abertura medida foi de 4.0 mm."))
        self.assertIn("MEDICAO_ALTERADA", tipos("A abertura medida foi de 4."))
        self.assertIn("MEDICAO_ALTERADA", tipos("A abertura medida foi de 0,4 cm."))

    def test_norma_verificada_citada_vincula_claim_e_referencias(self):
        motor = copy.deepcopy(self.motor)
        pat1 = motor["analise_final"]["patologias"][0]
        pat1["normas_relacionadas"] = [{"id": "NOR-001", "verificada": True, "aplicabilidade_temporal": "APLICAVEL_PRINCIPAL"}]
        pat1["conclusao_tecnica"] = "A manifestação contraria o requisito verificado da NOR-001."
        motor["analise_final"]["catalogo_evidencias"].append(evidencia("NOR-001", "NORMA", ["REQUISITO_NORMATIVO_VERIFICADO"]))
        saida = executar_pipeline_redacao(self.processo, self.delimitacao, motor)
        claim = next(c for c in saida["laudo"]["claims_redacao"] if "NOR-001" in c["texto_semantico"])
        self.assertEqual(claim["nor_ids"], ["NOR-001"])
        self.assertEqual(saida["laudo"]["referencias"], ["NOR-001"])
        normativo = next(a for a in saida["grounding"] if a.get("claim_red_id") == claim["id"] and a.get("componente") == "NORMATIVO")
        self.assertEqual(normativo["veredito"], "GROUNDED")
        self.assertEqual(normativo["evidencias"], ["NOR-001"])

    def test_autocorrecao_editorial_nao_muda_classificacao(self):
        r = redigir(planejar(self.processo, self.delimitacao, self.motor), self.final)
        r["blocos"][0]["textos"][0] = "É importante destacar que " + r["blocos"][0]["textos"][0]
        antes = r["blocos"][0]["textos"][2]
        corrigida, correcoes = autocorrigir(r, [{"tipo": "ABERTURA_GENERICA", "severidade": "EDITORIAL"}])
        self.assertTrue(correcoes); self.assertEqual(corrigida["blocos"][0]["textos"][2], antes)

    def test_adv_red_04_repeticao_e_06_terminologia(self):
        texto = "Conclusão repetida.\n\nConclusão repetida.\n\nFissura, manifestação fissurativa, abertura patológica e descontinuidade superficial."
        achados = auditar_estilo(texto); tipos = {a["tipo"] for a in achados}
        self.assertTrue({"CONCLUSAO_REPETIDA", "TERMINOLOGIA_INSTAVEL"} <= tipos)
        r = {"blocos": [{"pat_id": "PAT-001", "titulos": ["A"], "textos": [texto], "claim_ids": []}], "claims": []}
        corrigida, _ = autocorrigir(r, achados)
        self.assertNotIn("manifestação fissurativa", corrigida["blocos"][0]["textos"][0].lower())

    def test_adv_red_09_professoral_e_10_natural(self):
        professoral = "Para que o leitor compreenda, cumpre explicar inicialmente o que é uma parede antes de analisar a fissura."
        self.assertIn("TOM_PROFESSORAL", {a["tipo"] for a in auditar_estilo(professoral)})
        natural = "Na vistoria, constatou-se fissura superficial no revestimento."
        self.assertEqual(auditar_estilo(natural), [])

    def test_grounding_das_claims_e_claim_texto_divergente(self):
        saida = executar_pipeline_redacao(self.processo, self.delimitacao, self.motor)
        self.assertTrue(saida["grounding"]); self.assertTrue(all(a["veredito"] == "GROUNDED" for a in saida["grounding"]))
        alterada = copy.deepcopy(saida["redacao_final"]); alterada["claims"][0]["texto_semantico"] = "Causa nova inventada."
        self.assertIn("CLAIM_TEXTO_DIVERGENTE", {a["tipo"] for a in auditar_fidelidade(alterada, self.final)})

    def test_gate_tecnico_bloqueia_sem_redigir(self):
        motor = copy.deepcopy(self.motor); motor["gate"] = "BLOQUEADO_PARA_REDACAO"
        saida = executar_pipeline_redacao(self.processo, self.delimitacao, motor)
        self.assertEqual(saida["gate"], "BLOQUEADO_PARA_LAUDO"); self.assertEqual(saida["redacao_final"]["blocos"], [])

    def test_e2e_tres_pat_gate_ressalvas(self):
        saida = executar_pipeline_redacao(self.processo, self.delimitacao, self.motor)
        self.assertEqual(saida["gate"], "APTO_PARA_LAUDO_COM_RESSALVAS", (saida["grounding"], saida["achados"], saida["qt_ausentes"]))
        self.assertEqual(len(saida["redacao_final"]["blocos"]), 3); self.assertEqual(saida["metricas"]["claims_redigidas"], 18)
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/laudo-redacao.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(validator_for(schema)(schema).iter_errors(saida["laudo"])), [])

    def test_estrutura_judicial_1_a_8_tema_quadro_quesitos_orcamento_referencias(self):
        saida = executar_pipeline_redacao(self.processo, self.delimitacao, self.motor)
        self.assertEqual([s["numero"] for s in saida["plano_redacao"]["secoes"]], list("12345678"))
        self.assertIn("1.4 Síntese Processual e Delimitação do Tema Controvertido", saida["plano_redacao"]["secoes"][0]["subsecoes"])
        self.assertEqual(len(saida["laudo"]["quadro_resumo"]), 3)
        self.assertTrue(saida["laudo"]["sintese_conclusiva_tema"])
        self.assertEqual(saida["laudo"]["quesitos"][0]["itens"][0]["resposta"], "R: Resultados consolidados.")
        self.assertFalse(saida["laudo"]["orcamento"]["aplicavel"])
        self.assertEqual(saida["laudo"]["referencias"], [])

    def test_adv_red_11_12_13_14(self):
        self.assertIn("REDUNDANCIA_ESTRUTURAL", {a["tipo"] for a in auditar_redundancia_estrutural("Examinar fissuras no imóvel", "Examinar fissuras no imóvel", "Examinar fissuras no imóvel")})
        saida = executar_pipeline_redacao(self.processo, self.delimitacao, self.motor)
        laudo = copy.deepcopy(saida["laudo"]); laudo["sintese_conclusiva_tema"] = ""
        self.assertIn("TEMA_NAO_RESPONDIDO", {a["tipo"] for a in auditar_laudo_semantico(laudo, self.final)})
        laudo = copy.deepcopy(saida["laudo"]); laudo["quesitos"][0]["itens"][0]["resposta"] = "R: Conclusão nova."
        self.assertIn("QUESITO_CRIA_CONCLUSAO_NOVA", {a["tipo"] for a in auditar_laudo_semantico(laudo, self.final)})
        laudo["quesitos"][0]["itens"][0]["resposta"] = "R: Vide laudo."
        self.assertIn("QUESITO_SEM_RESPOSTA_TECNICA", {a["tipo"] for a in auditar_laudo_semantico(laudo, self.final)})

    def test_adv_red_15_16_18_19_20(self):
        saida = executar_pipeline_redacao(self.processo, self.delimitacao, self.motor)
        laudo = copy.deepcopy(saida["laudo"])
        laudo["orcamento"]["itens"] = [{"pat_id": "PAT-002", "descricao": "manutenção"}]
        laudo["referencias"] = ["NOR-999"]
        laudo["quadro_resumo"][0]["criticidade"] = "CRITICA"
        tipos = {a["tipo"] for a in auditar_laudo_semantico(laudo, self.final)}
        self.assertTrue({"ORCAMENTO_INELEGIVEL", "REFERENCIA_NAO_UTILIZADA", "QUADRO_RESUMO_DIVERGENTE"} <= tipos)
        laudo["orcamento"]["itens"] = [{"pat_id": "PAT-003", "descricao": "reparo arbitrário", "valor": 100}]
        self.assertIn("ORCAMENTO_INELEGIVEL", {a["tipo"] for a in auditar_laudo_semantico(laudo, self.final)})
        d = copy.deepcopy(self.delimitacao); d["tipo_pericia"] = "AVALIACAO"
        outro = executar_pipeline_redacao(self.processo, d, self.motor)
        self.assertEqual(outro["gate"], "BLOQUEADO_PARA_LAUDO")
        self.assertEqual(outro["achados"][0]["tipo"], "MODELO_DOCUMENTAL_INCOMPATIVEL")

    def test_adv_red_17_nao_constatada_nao_vira_inexistente(self):
        r = redigir(planejar(self.processo, self.delimitacao, self.motor), self.final)
        bloco = next(b for b in r["blocos"] if b["pat_id"] == "PAT-002")
        bloco["textos"][0] = "A infiltração não existe."
        self.assertIn("NAO_CONSTATADA_CONVERTIDA_EM_INEXISTENTE", {a["tipo"] for a in auditar_fidelidade(r, self.final)})


if __name__ == "__main__":
    unittest.main()
