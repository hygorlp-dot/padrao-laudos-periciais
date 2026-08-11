import copy
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from scripts.conhecimento_privado.pesquisa_online import AgentSearchProvider, EgressPolicy, buscar_seguro
from scripts.motor_vicios.auditar import comparar_medicao
from scripts.motor_vicios.normas import aplicabilidade_temporal
from scripts.motor_vicios.pipeline import recalcular_gate
from scripts.motor_vicios.motor import executar as executar_motor
from scripts.planejamento_pericial.validar_plano import recalcular_cobertura
from scripts.planejamento_pericial.validar_plano import recalcular_execucao
from scripts.planejamento_pericial.migracoes import migrar_plano
from scripts.backend_contract.errors import DomainError
from scripts.redacao_pericial.pipeline import _projetar_patologia, executar_pipeline_redacao
from scripts.redacao_pericial.auditar_fidelidade import auditar_fidelidade
from scripts.redacao_pericial.planejar_redacao import planejar
from scripts.vistoria_estruturada.gerar_vistoria import _linhas, _vinculos
from scripts.extracao_pje.gerar_manifesto import construir_manifesto
from scripts.triagem_pericial.validar_delimitacao import recalcular_autoauditoria
from scripts.triagem_pericial.gerar_delimitacao import _elemento_dos_autos


class AdvSafeHardening(unittest.TestCase):
    @staticmethod
    def _pdf_sintetico(caminho):
        w=PdfWriter()
        def pagina(comandos):
            p=w.add_blank_page(width=612,height=792)
            fonte=DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")})
            p[NameObject("/Resources")]=DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):w._add_object(fonte)})})
            s=StreamObject();s.set_data(comandos.encode("ascii"));p[NameObject("/Contents")]=w._add_object(s)
        linhas=" ".join(f"{x} 650 m {x} 740 l S" for x in (40,140,260,480,570))+" 40 650 m 570 650 l S 40 680 m 570 680 l S 40 710 m 570 710 l S 40 740 m 570 740 l S"
        textos="BT /F1 10 Tf 45 720 Td (ID) Tj 100 0 Td (Data) Tj 120 0 Td (Titulo) Tj 220 0 Td (Tipo) Tj ET BT /F1 10 Tf 45 690 Td (900001) Tj 100 0 Td (01/01/2026) Tj 120 0 Td (Peticao sintetica) Tj 220 0 Td (PETICAO) Tj ET BT /F1 10 Tf 45 660 Td (900002) Tj 100 0 Td (02/01/2026) Tj 120 0 Td (Decisao sintetica) Tj 220 0 Td (DECISAO) Tj ET"
        pagina(linhas+textos+" BT /F1 10 Tf 40 760 Td (Processo 0000001-00.2026.4.00.0001) Tj ET")
        pagina("BT /F1 10 Tf 40 730 Td (Documento sintetico sem PII real) Tj 0 -690 Td (Num. 900001 - Pag. 1) Tj ET")
        pagina("BT /F1 10 Tf 40 730 Td (Pagina complementar sem rodape e sem link) Tj ET")
        pagina("BT /F1 10 Tf 40 730 Td (Segundo documento sintetico) Tj 0 -690 Td (Num. 900002 - Pag. 1) Tj ET")
        with open(caminho,"wb") as f:w.write(f)

    def test_associacao_ambigua_falha_fechado(self):
        plano={"atividades":[
            {"id":"ATV-001","verificar":"fissura fachada","questoes_tecnicas":["QT-001"],"quesitos":[],"alegacoes":[]},
            {"id":"ATV-002","verificar":"fissura fachada","questoes_tecnicas":["QT-002"],"quesitos":[],"alegacoes":[]},
        ]}
        r=_vinculos("fissura fachada",plano)
        self.assertTrue(r["ambiguidade"])
        self.assertEqual(r["questoes"],[])

    def test_cobertura_exige_identidade_qt_e_tipo(self):
        base={"requisitos_cobertura":[{"id":"REQ-001","questao_tecnica":"QT-001","tipo":"DOCUMENTO","obrigatoriedade":"OBRIGATORIA","item_planejado":"DOC-PLANO-001"}],
              "cobertura":[{"quesito":"QUE-001","questoes_tecnicas":["QT-001"],"documentos":["DOC-PLANO-999"],"atividades":[],"medicoes":[],"fotografias":[],"ensaios":[]}],
              "atividades":[],"medicoes":[],"fotografias":[],"ensaios":[],"documentos_a_solicitar":[{"id":"DOC-PLANO-001","questoes_tecnicas":["QT-001"]}]}
        self.assertFalse(recalcular_cobertura(base)["apto"])
        base["cobertura"][0]["documentos"]=["DOC-PLANO-001"]
        self.assertTrue(recalcular_cobertura(base)["apto"])

    def test_required_executed_e_equivalencia_justificada(self):
        plano={"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"ENSAIO","obrigatoriedade":"OBRIGATORIA","item_planejado":"ENS-PLANO-001"}]}
        ausente={"cobertura":[{"tipo":"ENSAIO","planejado":"ENS-PLANO-001","status":"NAO_EXECUTADO","executado":[],"evidencia_equivalente":[]}]}
        self.assertFalse(recalcular_execucao(plano,ausente)["apto"])
        equivalente=copy.deepcopy(ausente);equivalente["cobertura"][0].update(status="SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE",evidencia_equivalente=["OBS-001"])
        self.assertFalse(recalcular_execucao(plano,equivalente)["apto"])
        equivalente["cobertura"][0]["justificativa_equivalencia"]="Método alternativo tecnicamente identificado";equivalente["observacoes"]=[{"id":"OBS-001","questoes":["QT-001"]}]
        self.assertTrue(recalcular_execucao(plano,equivalente)["apto"])
        forjado=copy.deepcopy(ausente);forjado["cobertura"][0].update(status="EXECUTADO",executado=["ENS-FAKE"])
        self.assertFalse(recalcular_execucao(plano,forjado)["apto"])
        irrelevante=copy.deepcopy(equivalente);irrelevante["observacoes"][0]["questoes"]=[]
        self.assertFalse(recalcular_execucao(plano,irrelevante)["apto"])

    def test_migracao_plano_explicita_e_fail_closed(self):
        legado={"schema_version":"1.0.0","requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"ATIVIDADE","obrigatoriedade":"OBRIGATORIA"}]}
        self.assertEqual(migrar_plano(legado)["schema_version"],"2.0.0")
        with self.assertRaises(DomainError):migrar_plano({"schema_version":"1.0.0"})
        with self.assertRaises(DomainError):migrar_plano({"schema_version":"3.0.0"})

    def test_unidades_unicode_e_multiplos_valores(self):
        for unidade in ("%","°C","kN/m²"):
            self.assertTrue(comparar_medicao(f"Resultado 4 {unidade}",{"valor":"4","unidade":unidade}))
        self.assertFalse(comparar_medicao("Resultado 4 mm e 40 mm",{"valor":"4","unidade":"mm"}))

    def test_provider_direto_exige_policy(self):
        chamadas=[]; provider=AgentSearchProvider(lambda q: chamadas.append(q) or [])
        with self.assertRaises(PermissionError): provider.buscar("consulta")
        self.assertEqual(chamadas,[])
        autorizada=EgressPolicy(permitir_egress=True,autorizar_dados_caso=True,dados_sensiveis=("Maria Exemplo",))
        self.assertNotIn("Maria Exemplo",autorizada.preparar("Maria Exemplo norma"))
        ok=buscar_seguro("norma técnica pública",provider,EgressPolicy(permitir_egress=True))
        self.assertEqual(ok["status"],"CONCLUIDA")

    def test_contexto_sensivel_e_url_com_pii_nao_cruzam_boundary(self):
        chamadas=[]; provider=AgentSearchProvider(lambda q: chamadas.append(q) or [])
        politica=EgressPolicy(permitir_egress=True,dados_sensiveis=("Maria Exemplo",))
        for consulta in ("Maria Exemplo fissura", "https://www.gov.br/busca?q=Maria%20Exemplo", "00000010020264000001"):
            self.assertEqual(buscar_seguro(consulta,provider,politica)["status"],"BLOQUEADO_POR_EGRESS")
        self.assertEqual(chamadas,[])

    def test_deep_critico_bloqueia_gate(self):
        estado={"erros":[],"detector":[],"materiais":[],"autoauditoria":[],"deep":[{"severidade":"CRITICO","tipo":"CONTRADICAO_ENTRE_CLAIMS"}]}
        self.assertEqual(recalcular_gate(estado),"BLOQUEADO_PARA_REDACAO")
        estado["deep"]=[{"severidade":"IMPORTANTE"}];self.assertEqual(recalcular_gate(estado),"APTO_PARA_REDACAO_COM_RESSALVAS")

    def test_redacao_recalcula_coverage_e_rejeita_status_adulterado(self):
        motor={"gate":"APTO_PARA_REDACAO","analise_final":{"patologias":[],"questoes_saneadas":[],"autoauditoria":[]},
               "erros_finais":[],"detector_final":[],"deep_audit_final":[],"grounding_final":[],"proposition_audit_results":[],
               "coverage_execucao":{"apto":True,"faltantes":[]},
               "coverage_inputs":{"plano":{"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"ENSAIO","obrigatoriedade":"OBRIGATORIA","item_planejado":"ENS-PLANO-001"}]},"vistoria":{}}}
        delimitacao={"tipo_pericia":{"tipo":"VICIOS_CONSTRUTIVOS"},"tema_controvertido":{"texto":"Tema"},"objeto_material":{"texto":"Objeto"},"objetivo_pericial":{"texto":"Objetivo"},"quesitos":[]}
        self.assertEqual(executar_pipeline_redacao({"numero_processo":"X"},delimitacao,motor)["gate"],"BLOQUEADO_PARA_LAUDO")

    def test_delimitacao_canonica_e_quesitos(self):
        d={"tipo_pericia":{"tipo":"VICIOS_CONSTRUTIVOS"},"tema_controvertido":{"texto":"Tema"},"objeto_material":{"texto":"Objeto"},"objetivo_pericial":{"texto":"Objetivo"},"quesitos":[]}
        p=planejar({"numero_processo":"X"},d,{"gate":"APTO_PARA_REDACAO","analise_final":{"patologias":[],"questoes_saneadas":[]}})
        self.assertEqual(p["modelo_documental"],"LAUDO_VICIOS_CONSTRUTIVOS_V1")
        self.assertEqual((p["tema_controvertido"],p["objeto"],p["objetivo"]),("Tema","Objeto","Objetivo"))

    def test_declaracoes_variantes_nao_viram_obs(self):
        for texto in ("segundo o morador, há infiltração", "conforme relatado pela autora, há fissura", "o proprietário afirmou que há umidade"):
            itens=_linhas({"metadados":{"texto_original":texto}})
            self.assertTrue(any(x.get("tipo")=="DECLARACAO" for x in itens))
            self.assertFalse(any(x.get("tipo")=="OBS" for x in itens))
        mistos=_linhas({"metadados":{"texto_original":"morador informou que houve infiltração; o perito constatou fissura"}})
        self.assertEqual([x["tipo"] for x in mistos],["DECLARACAO","OBS"])

    def test_temporal_mesmo_ano(self):
        base={"verificada":True,"requisito":"x"}
        self.assertEqual(aplicabilidade_temporal({**base,"vigencia_inicio":"2026-09-01"},"2026-03-01"),"NAO_APLICAVEL")
        self.assertEqual(aplicabilidade_temporal({**base,"vigencia_inicio":"2026-01-01","vigencia_fim":"2026-02-01"},"2026-03-01"),"NAO_APLICAVEL")
        self.assertEqual(aplicabilidade_temporal({**base,"vigencia_inicio":"2026-01-01","vigencia_fim":"2026-12-31"},"2026-03-01"),"APLICAVEL_PRINCIPAL")
        self.assertEqual(aplicabilidade_temporal(base,None),"APLICABILIDADE_INCONCLUSIVA")

    def test_claim_nao_quantitativa_nao_precisa_repetir_medicao(self):
        redacao={"claims":[{"id":"CLAIM-RED-001","texto_semantico":"Foi observada fissura.","pat_ids":["PAT-001"],"med_ids":["MED-001"],"nor_ids":[]}],"blocos":[]}
        final={"patologias":[{"id":"PAT-001","normas_relacionadas":[]}],"catalogo_evidencias":[{"id":"MED-001","tipo":"MEDICAO","valor":"4","unidade":"mm"}]}
        self.assertNotIn("MEDICAO_ALTERADA",{a["tipo"] for a in auditar_fidelidade(redacao,final)})
        for texto in ("Em 2026 foi observada fissura.","A fotografia 2 registra fissura.","PAT-001 apresentou fissura."):
            redacao["claims"][0]["texto_semantico"]=texto;self.assertNotIn("MEDICAO_ALTERADA",{a["tipo"] for a in auditar_fidelidade(redacao,final)})

    def test_pat_preserva_identidade_ao_adicionar_manifestacao_irrelevante(self):
        raiz=Path(__file__).resolve().parents[1]
        import json
        processo=json.loads((raiz/"tests/fixtures/schemas/processo-valido.json").read_text(encoding="utf8"));delim=json.loads((raiz/"tests/fixtures/triagem/delimitacao-minima-valida.json").read_text(encoding="utf8"))
        def obs(i,manifestacao):return {"id":f"OBS-{i:03d}","ambiente":"Sala","sistema":"IMPERMEABILIZACAO","elemento":"Parede","manifestacao":manifestacao,"descricao_objetiva":manifestacao,"resultado":"OBSERVADO","metodo":["INSPECAO_VISUAL"],"alegacoes":[],"fotografias":[],"medicoes":[],"questoes":["QT-001"],"aspectos_suportados":[],"proveniencia":["SINTETICA"]}
        vist=lambda itens:{"status":"VISTORIA_ESTRUTURADA","observacoes":itens,"medicoes":[],"fotografias":[]}
        base=executar_motor(processo,delim,{},vist([obs(2,"umidade")]))
        mutado=executar_motor(processo,delim,{},vist([obs(1,"fissura"),obs(2,"umidade")]))
        id_base=next(p["id"] for p in base["patologias"] if p["manifestacao"]=="umidade");id_mutado=next(p["id"] for p in mutado["patologias"] if p["manifestacao"]=="umidade")
        self.assertEqual(id_base,id_mutado)

    def test_pdf_pje_real_sintetico(self):
        with tempfile.TemporaryDirectory() as td:
            pdf=Path(td)/"autos-sinteticos.pdf";self._pdf_sintetico(pdf)
            manifesto,erros,alertas=construir_manifesto(pdf)
            self.assertEqual(manifesto["arquivo"]["total_paginas"],4)
            self.assertEqual(manifesto["processo"]["numero_cnj"]["valor"],"0000001-00.2026.4.00.0001")
            self.assertEqual(len(manifesto["documentos"]),2)
            self.assertEqual([d["status_reconciliacao"]["status"] for d in manifesto["documentos"]],["CONFIRMADO","CONFIRMADO"])
            self.assertFalse(erros)

    def test_autoauditoria_mutante_nao_aprova_por_vazio_ou_tautologia(self):
        base={"tipo_pericia":{"documentos_fonte":["DOC-PJE-001"]},"conhecimento_normativo":{"itens_recuperados":[]},"memoria_referencial":{},"autoauditoria":[]}
        r=recalcular_autoauditoria(base)
        self.assertEqual(r["Classificação usa múltiplas peças e não o número do processo"],"BLOQUEADO")
        self.assertEqual(r["Normas usadas possuem proveniência"],"ALERTA")
        base["conhecimento_normativo"]["itens_recuperados"]=["NOR-0001"]
        self.assertEqual(recalcular_autoauditoria(base)["Normas usadas possuem proveniência"],"BLOQUEADO")
        base["questoes_tecnicas"]=[{"fundamento":"MOD-0001"}]
        self.assertEqual(recalcular_autoauditoria(base)["Modelos não contaminam fatos do caso"],"BLOQUEADO")

    def test_objeto_e_objetivo_usam_autos_ou_fallback_explicito(self):
        doc={"documento_id":"DOC-PJE-001","classe_normalizada":"DECISAO","paginas":[{"referencia":1,"texto_bruto":"O objetivo da perícia é examinar a fachada delimitada."}]}
        extraido=_elemento_dos_autos([doc],("objetivo da pericia",),"fallback")
        self.assertEqual(extraido["documentos_fonte"],["DOC-PJE-001"])
        fallback=_elemento_dos_autos([],('objetivo da pericia',),"fallback")
        self.assertEqual((fallback["texto"],fallback["status_verificacao"]),("fallback","INCONCLUSIVO"))

    def test_adapter_pat_laudo_preserva_semantica(self):
        base={"id":"PAT-001","ambiente":"Sala","localizacao_detalhada":"Parede norte","sistema":"VEDACOES","manifestacao":"fissura","constatacao":{"situacao":"INCONCLUSIVA","fotografias":[]},"origem":"INCONCLUSIVA","criticidade":"INCONCLUSIVA","vicio_construtivo":{"caracterizado":False,"tipo":"INCONCLUSIVO"},"recomendacao":{"necessaria":True,"descricao":"Investigar","extensao":None},"elegibilidade_orcamento":"PENDENTE","conclusao_tecnica":"Inconclusiva"}
        p=_projetar_patologia(base)
        self.assertEqual((p["local"],p["criticidade"]),("Parede norte","INCONCLUSIVA"));self.assertFalse(p["elegivel_orcamento"]);self.assertEqual(p["reparo"]["descricao"],"Investigar")
        base["elegibilidade_orcamento"]="ELEGIVEL_ORCAMENTO_VICIO";self.assertTrue(_projetar_patologia(base)["elegivel_orcamento"])


if __name__ == "__main__": unittest.main()
