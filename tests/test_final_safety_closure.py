import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.auditoria_pericial.proposition import classificar_autoridade
from scripts.auditoria_pericial.grounding import auditar_claim
from scripts.conhecimento_privado.pesquisa_online import dados_sensiveis_processo
from scripts.extracao_pje.classificar_documentos import classificar_documento
from scripts.triagem_pericial.classificar_tipo import classificar
from scripts.motor_vicios.hipoteses import _independentes
from scripts.motor_vicios.evidencias import associar_documentos_ensaios
from scripts.motor_vicios.normas import (
    avaliar_conformidade_normativa,
    normalizar_fonte_normativa,
)
from scripts.motor_vicios.pipeline import _decisoes_trilha,_fontes_trilha
from scripts.planejamento_pericial.validar_plano import recalcular_execucao
from scripts.redacao_pericial.auditar_fidelidade import auditar_grounding_redacao
from scripts.redacao_pericial.pipeline import recalcular_gate_redacao
from scripts.terceiros.catalogar_repositorios import politica_trust
from scripts.triagem_pericial.semantica import melhores
from scripts.triagem_pericial.validar_delimitacao import status_derivado
from scripts.vistoria_estruturada.gerar_vistoria import gerar


class FinalSafetyClosure(unittest.TestCase):
    def test_e2e_adicional_cumulativo_pdf_laudo_e_invariantes_safety(self):
        from tests.test_auditoria_final2 import AuditoriaFinal2
        caso_pdf=AuditoriaFinal2();getattr(caso_pdf,next(n for n in dir(caso_pdf) if n.startswith("test_e2e_can")))()
        processo=json.loads(Path("tests/fixtures/schemas/processo-valido.json").read_text(encoding="utf8"))
        self.assertIn("100",dados_sensiveis_processo(processo))
        plano={"documentos_a_solicitar":[{"id":"DOC-PLANO-001","descricao":"memorial","criterio_satisfacao":"identidade","questoes_tecnicas":["QT-001"]}],"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"DOCUMENTO","obrigatoriedade":"OBRIGATORIA","item_planejado":"DOC-PLANO-001"}],"requisitos_semanticos":[{"requirement_id":"REQ-001-DOC","quesito":"QUE-001","requisito":"Solicitar o memorial de cálculo estrutural.","itens_planejados":["DOC-PLANO-001"]}]}
        vistoria={"documentos_obtidos":[{"id":"DOC-VIS-001","documento_planejado":"DOC-PLANO-001","descricao":"memorial","questoes":["QT-001"]}],"cobertura":[{"tipo":"DOCUMENTO","planejado":"DOC-PLANO-001","status":"EXECUTADO","executado":["DOC-VIS-001"],"evidencia_equivalente":[]}]}
        self.assertTrue(recalcular_execucao(plano,vistoria)["apto"])
        doc={"id":"DOC-001","tipo":"DOCUMENTO","questoes":["QT-001"],"sistema":"VEDACOES","manifestacao":None,"atividade":None,"alegacoes":[],"ambiente":None,"elemento":None}
        contextos=[{"relacao_id":"MAN-001","questoes":["QT-001"],"sistema":"VEDACOES","manifestacao":"fissura","ambiente":"Sala","elemento":"parede","alegacoes":[]},{"relacao_id":"MAN-002","questoes":["QT-001"],"sistema":"VEDACOES","manifestacao":"umidade","ambiente":"Sala","elemento":"parede","alegacoes":[]}]
        self.assertEqual(associar_documentos_ensaios([doc],contextos)[0]["status"],"AMBIGUA")
        norma={"id":"NOR-001","entidade":"ABNT","numero":"1","classificacao_fonte":"FONTE_TECNICA_LOCAL_VERIFICADA","status_verificacao":"VERIFICADO","verificada":True,"requisito":"x","metodo_verificacao":"medir","criterio":{"operador":"<=","valor":4,"unidade":"mm"},"proveniencia":["x"],"vigencia_inicio":"2024-01-01","data_relevante":"2020-01-01"}
        self.assertEqual(avaliar_conformidade_normativa(norma,[{"id":"MED-001","tipo":"MEDICAO","valor":3,"unidade":"mm"}])["resultado"],"INCONCLUSIVO")

    def test_documento_required_presente_e_ausente(self):
        plano={"documentos_a_solicitar":[{"id":"DOC-PLANO-001","descricao":"memorial estrutural","criterio_satisfacao":"identidade","questoes_tecnicas":["QT-001"]}],"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"DOCUMENTO","obrigatoriedade":"OBRIGATORIA","item_planejado":"DOC-PLANO-001"}],"requisitos_semanticos":[{"requirement_id":"REQ-001-DOC","quesito":"QUE-001","requisito":"Solicitar o memorial estrutural.","itens_planejados":["DOC-PLANO-001"]}]}
        presente={"documentos_obtidos":[{"id":"DOC-VIS-001","documento_planejado":"DOC-PLANO-001","descricao":"memorial estrutural","questoes":["QT-001"]}],"cobertura":[{"tipo":"DOCUMENTO","planejado":"DOC-PLANO-001","status":"EXECUTADO","executado":["DOC-VIS-001"],"evidencia_equivalente":[]}]}
        self.assertTrue(recalcular_execucao(plano,presente)["apto"])
        self.assertFalse(recalcular_execucao(plano,{"documentos_obtidos":[],"cobertura":[]})["apto"])

    def test_requisito_sem_identidade_e_ensaio_diferente_bloqueiam(self):
        sem_id={"ensaios":[{"id":"ENS-PLANO-001","nome":"ensaio A","questoes_tecnicas":["QT-001"]}],"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"ENSAIO","obrigatoriedade":"OBRIGATORIA"}]}
        self.assertFalse(recalcular_execucao(sem_id,{})["apto"])
        plano=copy.deepcopy(sem_id);plano["requisitos_cobertura"][0]["item_planejado"]="ENS-PLANO-001"
        vistoria={"ensaios":[{"id":"ENS-999","ensaio_planejado":None,"nome":"ensaio B","metodo":"B","questoes":["QT-001"]}],"cobertura":[{"tipo":"ENSAIO","planejado":"ENS-PLANO-001","status":"SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE","executado":[],"evidencia_equivalente":["ENS-999"],"equivalencia":{"requisito_original":"ENS-PLANO-001","tipo_evidencia":"ENSAIO","capability":"ensaio B","metodo_substituto":"B"},"justificativa_equivalencia":"substituição"}]}
        self.assertFalse(recalcular_execucao(plano,vistoria)["apto"])

    def test_obs_med_fot_nao_associam_por_qt_sistema_ambiente(self):
        plano={"atividades":[] ,"fotografias":[],"medicoes":[]}
        registros=[{"tipo":"OBS","descricao":"fissura vertical","manifestacao":"fissura","sistema":"VEDACOES","ambiente":"Sala","questoes":["QT-001"]},{"tipo":"OBS","descricao":"umidade localizada","manifestacao":"umidade","sistema":"VEDACOES","ambiente":"Sala","questoes":["QT-001"]},{"tipo":"MED","grandeza":"abertura","valor":"1","unidade":"mm","sistema":"VEDACOES","ambiente":"Sala","questoes":["QT-001"]}]
        inventario={"arquivos":[{"id":"ARQ-VIS-001","nome":"campo.json","caminho_relativo":"campo.json","categoria":"DOCUMENTO","metodo_ingestao":"JSON","metadados":{"texto_original":json.dumps(registros)}}]}
        vistoria=gerar(inventario,plano)
        self.assertTrue(all(not o["medicoes"] and not o["fotografias"] for o in vistoria["observacoes"]))
        self.assertEqual(vistoria["relacoes_evidencia"],[])

    def test_norma_boundary_temporal_autoridade_e_revogacao(self):
        bruto={"id":"NOR-001","entidade":"ABNT","numero":"1","titulo":"Norma","requisito":"x","verificada":True,"url":"https://oficial.example/x","dominio_oficial":True,"proveniencia":["NOR-LOCAL"],"status_verificacao":"VERIFICADO","metodo_verificacao":"medir","criterio":{"operador":"<=","valor":4,"unidade":"mm","grandeza":"abertura"},"status_vigencia":"REVOGADA","vigencia_inicio":"2010-01-01"}
        norma=normalizar_fonte_normativa(bruto,"2020-01-01")
        self.assertFalse(norma["autoridade_fonte_verificada"])
        self.assertEqual(norma["aplicabilidade_temporal"],"APLICABILIDADE_INCONCLUSIVA")
        self.assertEqual(avaliar_conformidade_normativa(norma,[{"id":"MED-001","tipo":"MEDICAO","valor":3,"unidade":"mm","grandeza":"abertura"}])["resultado"],"INCONCLUSIVO")
        self.assertNotEqual(classificar_autoridade(bruto),"FONTE_PRIMARIA_OFICIAL")
        spoof={**bruto,"status_vigencia":"VIGENTE","aplicabilidade_temporal":"APLICAVEL_PRINCIPAL","data_relevante":"2020-01-01"}
        self.assertEqual(avaliar_conformidade_normativa(spoof,[{"id":"MED-001","tipo":"MEDICAO","valor":3,"unidade":"mm","grandeza":"abertura"}])["resultado"],"INCONCLUSIVO")

    def test_pii_percorre_endereco_canonico(self):
        processo=json.loads(Path("tests/fixtures/schemas/processo-valido.json").read_text(encoding="utf8"))
        dados=dados_sensiveis_processo(processo)
        for valor in ("Rua Fictícia","100","Bairro Teste","Cidade Fictícia","PE"):
            self.assertIn(valor,dados)

    def test_proveniencia_estruturada_mesmo_documento_nao_independente(self):
        cat=[{"id":"E-1","proveniencia":[{"documento_id":"DOC-PJE-001","pagina_pdf":1}]},{"id":"E-2","proveniencia":[{"documento_id":"DOC-PJE-001","pagina_pdf":2}]}]
        self.assertEqual(_independentes(["E-1","E-2"],cat),1)
        evidencia={"id":"OBS-001","tipo":"OBSERVACAO","classe_probatoria":"EVIDENCIA_PRIMARIA","proveniencia":[{"documento_id":"DOC-PJE-001","pagina_pdf":1}],"aspectos_suportados":["CAUSA"],"aspectos_contraditos":[],"acessivel":True}
        relacao={"id":"OBS-001","tipo":"OBSERVACAO","proveniencia":[{"documento_id":"DOC-PJE-001","pagina_pdf":2}]}
        claim={"id":"CLM-001","tipo":"CAUSA","natureza":"INTERPRETIVE","saliencia":"LOAD_BEARING","texto":"Causa documentada.","aspectos_requeridos":["CAUSA"]}
        self.assertEqual(auditar_claim(claim,[relacao],[evidencia])["veredito"],"GROUNDED")
        self.assertEqual(_fontes_trilha([evidencia]),["DOC-PJE-001"])

    def test_doc_ensaio_ambiguo_nao_contamina_pat_e_relacao_fica_rastreavel(self):
        doc={"id":"DOC-001","tipo":"DOCUMENTO","questoes":["QT-001"],"sistema":"VEDACOES","manifestacao":None,"atividade":None,"alegacoes":[],"ambiente":None,"elemento":None}
        contextos=[
            {"relacao_id":"MAN-001","questoes":["QT-001"],"sistema":"VEDACOES","manifestacao":"fissura","ambiente":"Sala","elemento":"parede","alegacoes":[]},
            {"relacao_id":"MAN-002","questoes":["QT-001"],"sistema":"VEDACOES","manifestacao":"umidade","ambiente":"Sala","elemento":"parede","alegacoes":[]},
        ]
        relacao=associar_documentos_ensaios([doc],contextos)[0]
        self.assertEqual(relacao["status"],"AMBIGUA")
        self.assertEqual(relacao["manifestacoes"],["MAN-001","MAN-002"])
        doc["manifestacao"]="fissura"
        relacao=associar_documentos_ensaios([doc],contextos)[0]
        self.assertEqual(relacao["status"],"ASSOCIADA")
        self.assertEqual(relacao["manifestacoes"],["MAN-001"])
        self.assertEqual(relacao["patologias"],["PAT-001"])
        decisoes=_decisoes_trilha({"relacoes_associacao":[relacao]},[])
        self.assertTrue(any(x["evidencia"]=="DOC-001" and "MAN-001" in x["justificativa"] for x in decisoes))

    def test_trust_requer_pin_licenca_e_review_existente(self):
        with tempfile.TemporaryDirectory() as td:
            evid=Path(td)/"review.md";evid.write_text("aprovado",encoding="utf8")
            review={"review_status":"APPROVED_LOCAL","review_evidence":str(evid),"commit_pin":"A","license":"MIT","restrictions":["local only"]}
            self.assertEqual(politica_trust("repo",review,commit_real="A",licenca_real="MIT")["review_status"],"APPROVED_LOCAL")
            self.assertEqual(politica_trust("repo",review,commit_real="B",licenca_real="MIT")["review_status"],"STALE_REVIEW")

    def test_baixa_confianca_e_ambiguidade_bloqueiam_planejamento(self):
        base={"tipo_pericia":{"tipo":"VICIOS_CONSTRUTIVOS","confianca":{"nivel":"BAIXA","score":.5},"alternativas_consideradas":["ESTRUTURAS"],"documentos_fonte":["D1","D2"]},"conflitos":[],"autoauditoria":[],"questoes_tecnicas":[],"conhecimento_normativo":{}}
        self.assertEqual(status_derivado(base),"BLOQUEADO")
        empate=classificar([{"documento_id":"DOC-PJE-001","classe_normalizada":"PETICAO_INICIAL","paginas":[{"texto_bruto":"vÃ­cio construtivo fissura infiltraÃ§Ã£o avaliaÃ§Ã£o do imÃ³vel valor de mercado mÃ©todo comparativo"}]}])
        self.assertEqual(empate.nivel,"BAIXA")

    def test_manifestacao_da_parte_autora_e_classe_positiva(self):
        r=classificar_documento("Manifestação da parte autora","PETICAO","")
        self.assertEqual(r["classe_normalizada"],"MANIFESTACAO")
        self.assertNotEqual(r["confianca_classificacao"]["nivel"],"BAIXA")

    def test_matcher_baixa_afinidade_nao_faz_fallback(self):
        self.assertEqual(melhores("fissura",[{"id":"QT-001","descricao":"umidade"}],minimo=.5),[])

    def test_redacao_nao_herda_grounding_de_texto_contraditorio(self):
        red={"claims":[{"id":"CLAIM-RED-001","tipo":"CONCLUSAO_DE_QT","texto_semantico":"Não existe fissura.","pat_ids":["PAT-001"],"qt_ids":[],"obs_ids":[],"med_ids":[],"fot_ids":[],"doc_ids":[],"nor_ids":[],"res_ids":[],"con_ids":[],"natureza":"INTERPRETIVE","materialidade":"LOAD_BEARING"}]}
        motor={"claims_finais":[{"id":"CLM-001","tipo":"CONCLUSAO_DE_QT","texto":"Há fissura.","patologia":"PAT-001"}],"grounding_final":[{"claim_id":"CLM-001","veredito":"GROUNDED","evidencias":["OBS-001"]}],"analise_final":{"catalogo_evidencias":[]}}
        auditoria=auditar_grounding_redacao(red,motor)
        self.assertNotEqual(auditoria[0]["veredito"],"GROUNDED")
        self.assertEqual(recalcular_gate_redacao(fidelidade=[],semanticos=[],ausentes=[],materiais=auditoria),"BLOQUEADO_PARA_LAUDO")
        red["claims"][0]["texto_semantico"]="A fissura nÃ£o decorre de falha construtiva."
        motor["claims_finais"][0]["texto"]="A fissura decorre de falha construtiva."
        auditoria=auditar_grounding_redacao(red,motor)
        self.assertEqual(auditoria[0]["veredito"],"UNSUBSTANTIATED")
        for texto_red,texto_motor in (("O vicio construtivo esta caracterizado.","O vicio construtivo nao esta caracterizado."),("A origem e endogena.","A origem nao e endogena."),("A fissura exige demolicao integral.","A fissura foi observada."),("A fissura foi causada por sobrecarga.","A fissura foi observada."),("A fissura afeta toda a edificacao.","A fissura e localizada."),("A fissura constitui anomalia.","A fissura esta conforme."),("A fissura tem origem exogena.","A fissura tem origem endogena."),("A criticidade e critica.","A criticidade e minima."),("A fissura causou colapso.","A fissura foi observada.")):
            red["claims"][0]["texto_semantico"]=texto_red;motor["claims_finais"][0]["texto"]=texto_motor
            self.assertEqual(auditar_grounding_redacao(red,motor)[0]["veredito"],"UNSUBSTANTIATED")


if __name__ == "__main__":unittest.main()
