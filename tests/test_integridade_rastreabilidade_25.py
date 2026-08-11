import copy,json,tempfile,unittest
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,StreamObject
from scripts.extracao_pje.segmentar_documentos import segmentar_documentos
from scripts.extracao_pje.extrair_capa import extrair_capa
from scripts.extracao_pje.leitor_pdf import LeitorPdf
from scripts.extracao_pje.gerar_manifesto import _conflito_colisao
from scripts.extracao_pje.gerar_manifesto import _fonte_indice,_fonte_rodape
from scripts.extracao_pje.gerar_manifesto import _status_manifesto
from scripts.extracao_pje.gerar_documentos import gerar_documentos
from scripts.triagem_pericial.gerar_delimitacao import gerar as gerar_delimitacao
from scripts.planejamento_pericial.gerar_processo import gerar as gerar_processo
from jsonschema import Draft202012Validator
from scripts.extracao_pje.extrair_indice import extrair_indice
from scripts.extracao_pje.validar_integridade import validar_integridade
from scripts.motor_vicios.autocorrigir import autocorrigir
from scripts.auditoria_pericial.detector import executar_detector
from scripts.redacao_pericial.datas import extrair_datas,auditar_datas
from scripts.redacao_pericial.auditar_fidelidade import auditar_fidelidade,auditar_laudo_semantico
from scripts.triagem_pericial.validar_delimitacao import validar_relacoes
from scripts.planejamento_pericial.aprofundar_delimitacao import aprofundar

class Leitor:
    caminho=type("P",(),{"name":"sintetico.pdf"})();sha256="0"*64
    def __init__(self,paginas):self.paginas=paginas
    def texto(self,p):return self.paginas[p]

class PaginaTabela:
    def __init__(self,tabelas):self.tabelas=tabelas
    def extract_tables(self):return self.tabelas
class LeitorIndice:
    def __init__(self,tabelas):self.p=PaginaTabela(tabelas)
    def pagina_geometrica(self,p):return self.p

class IntegridadeRastreabilidade25(unittest.TestCase):
    def test_colisao_indice_nao_perde_item_e_ordem_nao_importa(self):
        itens=[{"id_pje":"10","ordem_indice":1,"pagina_destino_link":2},{"id_pje":"20","ordem_indice":2,"pagina_destino_link":2}]
        paginas=[{"pagina_pdf":i,"possui_rodape_pje":False,"pagina_documento_detectada":None,"id_pje_detectado":None} for i in range(1,5)]
        a=segmentar_documentos(itens,paginas);b=segmentar_documentos(list(reversed(itens)),paginas)
        self.assertEqual(len(a),1);self.assertEqual(a[0]["estado_item_indice"],"CONFLITO_DESTINO");self.assertEqual([i["id_pje"] for i in a[0]["itens_colididos"]],[i["id_pje"] for i in b[0]["itens_colididos"]])
        completos=[{**x,"documento_id_interno":f"DOC-PJE-{i:03d}","pagina_origem_indice":1,"texto_bruto":f"item {i}","confianca":{"nivel":"MEDIA"}} for i,x in enumerate(itens,1)]
        conflito=_conflito_colisao(Leitor({}),completos,2,1);schema=json.loads((Path(__file__).resolve().parents[1]/"schemas/pje-comum.schema.json").read_text(encoding="utf8"));contrato={"$schema":schema["$schema"],"$defs":schema["$defs"],"$ref":"#/$defs/conflito"}
        self.assertEqual(list(Draft202012Validator(contrato).iter_errors(conflito)),[])
        self.assertEqual(conflito["itens_indice_relacionados"],["DOC-PJE-001","DOC-PJE-002"])
        self.assertEqual(_status_manifesto([], [conflito], []),"BLOQUEADO")
    def test_segmentacao_normal_e_descoberta_por_rodape(self):
        paginas=[{"pagina_pdf":i,"possui_rodape_pje":i in {2,4},"pagina_documento_detectada":1 if i in {2,4} else None,"id_pje_detectado":str(i) if i in {2,4} else None} for i in range(1,5)]
        itens=[{"documento_id_interno":"DOC-PJE-001","id_pje":"2","ordem_indice":1,"pagina_destino_link":2}]
        docs=segmentar_documentos(itens,paginas);self.assertEqual([(x["id_pje"],x["estado_item_indice"]) for x in docs],[("2","SEGMENTADO"),("4","DESCOBERTO_RODAPE")])
    def test_divergencia_indice_rodape_nao_causa_excecao(self):
        itens=[{"documento_id_interno":"DOC-PJE-001","id_pje":"10","ordem_indice":1,"pagina_destino_link":2}]
        paginas=[{"pagina_pdf":1,"possui_rodape_pje":False,"pagina_documento_detectada":None,"id_pje_detectado":None},{"pagina_pdf":2,"possui_rodape_pje":True,"pagina_documento_detectada":1,"id_pje_detectado":"99"}]
        docs=segmentar_documentos(itens,paginas);self.assertEqual(len(docs),1);self.assertEqual((docs[0]["item_indice"]["id_pje"],docs[0]["id_rodape"]),("10","99"))
    def test_link_inequivoco_alta_fallback_media_e_ambiguo_fechado(self):
        tabela=[["900001","01/01/2026","Peticao","TIPO"]]
        base={"pagina_origem":1,"texto_associado":""}
        fallback=extrair_indice(LeitorIndice([tabela]),[1],[{**base,"pagina_destino":2}])[0]
        self.assertEqual((fallback["metodo_associacao_link"],fallback["confianca"]["nivel"]),("FALLBACK_POSICIONAL","MEDIA"))
        inequivoco=extrair_indice(LeitorIndice([tabela]),[1],[{**base,"pagina_destino":2,"texto_associado":"900001"}])[0]
        self.assertEqual((inequivoco["metodo_associacao_link"],inequivoco["confianca"]["nivel"]),("LINK_ID_INEQUIVOCO","ALTA"))
        ambiguo=extrair_indice(LeitorIndice([tabela]),[1],[{**base,"pagina_destino":2,"texto_associado":"900001"},{**base,"pagina_destino":3,"texto_associado":"900001"}])[0]
        self.assertIsNone(ambiguo["destino_escolhido_link"]);self.assertEqual(ambiguo["metodo_associacao_link"],"LINK_AMBIGUO")
    def test_validator_recalcula_accounting_e_confianca(self):
        raiz=Path(__file__).resolve().parents[1];m=json.loads((raiz/"tests/fixtures/pje/manifesto-minimo-valido.json").read_text(encoding="utf8"))
        m["indice"]["itens"][0]["metodo_associacao_link"]="FALLBACK_POSICIONAL";m["indice"]["itens"][0]["confianca"]["nivel"]="ALTA";m["documentos"]=[];m["metricas_extracao"]["documentos_segmentados"]=0;m["metricas_extracao"]["documentos_confirmados"]=0
        erros,_=validar_integridade(m);self.assertTrue(any("fallback posicional" in e for e in erros));self.assertTrue(any("não contabilizados" in e for e in erros));self.assertTrue(any("Status VALIDADO" in e for e in erros))
        m["conflitos"]=[{"observacoes":"DOC-PJE-001"}];erros,_=validar_integridade(m);self.assertTrue(any("não contabilizados" in e for e in erros))
        m=json.loads((raiz/"tests/fixtures/pje/manifesto-minimo-valido.json").read_text(encoding="utf8"));m["conflitos"]=[{"itens_indice_relacionados":["DOC-PJE-001"],"bloqueante":True,"status":"ABERTO"}];erros,_=validar_integridade(m);self.assertTrue(any("mais de uma vez" in e for e in erros))
    def test_manifesto_bloqueado_nao_chega_a_consumidores(self):
        raiz=Path(__file__).resolve().parents[1];m=json.loads((raiz/"tests/fixtures/pje/manifesto-minimo-valido.json").read_text(encoding="utf8"));m["status_validacao"]="BLOQUEADO";m["conflitos"]=[{"itens_indice_relacionados":["DOC-PJE-001"],"bloqueante":True,"status":"ABERTO"}]
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/"manifesto-pje.json").write_text(json.dumps(m),encoding="utf8")
            with self.assertRaises(ValueError):gerar_documentos(m,d/"ausente.pdf",d/"saida")
            with self.assertRaises(ValueError):gerar_delimitacao(d)
            with self.assertRaises(ValueError):gerar_processo(d)
    def test_capa_preserva_pagina_real_e_conflito(self):
        r=extrair_capa(Leitor({1:"0000001-00.2026.4.00.0001",2:"Tribunal: TJBA\nClasse: A",3:"Classe: B"}),[1,2,3])
        self.assertEqual(r["processo"]["tribunal"]["proveniencia"]["pagina_pdf"],2);self.assertEqual(r["processo"]["classe"]["status"],"CONFLITANTE");self.assertEqual({f["pagina_pdf"] for f in r["processo"]["classe"]["fontes"]},{2,3})
        self.assertIsNone(r["processo"]["subsecao"]["proveniencia"]["pagina_pdf"])
        igual=extrair_capa(Leitor({1:"0000001-00.2026.4.00.0001",2:"Tribunal: TJBA",3:"Tribunal: TJBA\nValor da causa: R$ 1.000,00"}),[1,2,3])
        self.assertNotIn("status",igual["processo"]["tribunal"]);self.assertEqual(igual["processo"]["valor_causa"]["proveniencia"]["pagina_pdf"],3)
    def test_capa_singletons_conflitam_assuntos_sao_multivalor(self):
        r=extrair_capa(Leitor({1:"0000001-00.2026.4.00.0001\nSegredo de justiça: SIM\nValor da causa: R$ 1.000,00\nAssunto: A",2:"0000002-00.2026.4.00.0002\nSegredo de justiça: NAO\nValor da causa: R$ 2.000,00\nAssunto: B\nClasse: X",3:"Assunto: A\nClasse: Y"}),[1,2,3])
        campos={c["campo"] for c in r["conflitos"]};self.assertTrue({"processo.numero_cnj","processo.flags.segredo_justica","processo.valor_causa","processo.classe"}<=campos);self.assertEqual({a["valor"] for a in r["processo"]["assuntos"]},{"A","B"});self.assertEqual(len(next(a for a in r["processo"]["assuntos"] if a["valor"]=="A")["fontes"]),2)
    def test_proveniencia_documentada_sem_pagina_e_rejeitada(self):
        raiz=Path(__file__).resolve().parents[1];schema=json.loads((raiz/"schemas/pje-comum.schema.json").read_text(encoding="utf8"));contrato={"$schema":schema["$schema"],"$defs":schema["$defs"],"$ref":"#/$defs/proveniencia"};p=_prov=extrair_capa(Leitor({1:"Tribunal: T"}),[1])["processo"]["tribunal"]["proveniencia"];p["pagina_pdf"]=None
        self.assertTrue(list(Draft202012Validator(contrato).iter_errors(p)))
    def test_fontes_indice_rodape_usam_paginas_reais(self):
        item={"documento_id_interno":"DOC-PJE-001","id_pje":"10","pagina_origem_indice":1,"texto_bruto":"10 item","confianca":{"nivel":"ALTA"}};pagina={"pagina_pdf":4,"pagina_documento_detectada":1,"id_pje_detectado":"99","confianca":{"nivel":"ALTA"}}
        self.assertEqual((_fonte_indice(Leitor({}),item)["pagina_pdf"],_fonte_rodape(Leitor({}),pagina)["pagina_pdf"]),(1,4))
    def test_capa_pdf_real_multipagina_preserva_origem(self):
        with tempfile.TemporaryDirectory() as td:
            pdf=Path(td)/"capa-sintetica.pdf";w=PdfWriter()
            for texto in ("Processo 0000001-00.2026.4.00.0001","Tribunal: TJBA","Classe: PROCEDIMENTO SINTETICO"):
                p=w.add_blank_page(width=612,height=792);fonte=DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")});p[NameObject("/Resources")]=DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):w._add_object(fonte)})});s=StreamObject();s.set_data(f"BT /F1 10 Tf 40 730 Td ({texto}) Tj ET".encode("ascii"));p[NameObject("/Contents")]=w._add_object(s)
            with pdf.open("wb") as f:w.write(f)
            with LeitorPdf(pdf) as leitor:r=extrair_capa(leitor,[1,2,3])
        self.assertEqual(r["processo"]["tribunal"]["proveniencia"]["pagina_pdf"],2);self.assertEqual(r["processo"]["classe"]["proveniencia"]["pagina_pdf"],3)
    def test_quesito_juridico_contaminado_e_invalido(self):
        d={"questoes_tecnicas":[{"id":"QT-001","quesitos_relacionados":["QUE-001"],"ressalvas":[]}],"quesitos":[{"id":"QUE-001","pertinencia":"MATERIA_JURIDICA","questoes_tecnicas_relacionadas":["QT-001"],"secoes_laudisticas_previstas":["3"],"ressalvas_aplicaveis":[]}],"ressalvas":[],"conflitos":[],"matriz_cobertura":[{"quesito_id":"QUE-001","questoes_tecnicas":["QT-001"],"secoes_laudisticas":["3"],"status":"JURIDICO_DELIMITADO"}],"autoauditoria":[]}
        self.assertTrue(any("jurídico" in e for e in validar_relacoes(d)))
    def test_datas_equivalentes_alteradas_inventadas_e_falsos_positivos(self):
        self.assertEqual(extrair_datas("11 de agosto de 2026"),["2026-08-11"]);self.assertEqual(extrair_datas("2026 ABNT 15575 R$ 2.026,00 processo 0000001-00.2026.4.00.0001"),[])
        self.assertEqual(auditar_datas("Vistoria em 11/08/2026",["2026-08-11"]),[]);self.assertEqual(auditar_datas("Vistoria em 10/08/2026",["2026-08-11"])[0]["tipo"],"DATA_ALTERADA");self.assertEqual(auditar_datas("Vistoria em 11/08/2026",[])[0]["tipo"],"DATA_INVENTADA")
        redacao={"blocos":[],"claims":[{"id":"CLAIM-RED-001","texto_semantico":"Documento de 10/08/2026","doc_ids":["DOC-001"],"pat_ids":[]}]}
        motor={"patologias":[],"catalogo_evidencias":[{"id":"DOC-001","data":"2026-08-11"}]}
        self.assertEqual(auditar_fidelidade(redacao,motor)[0]["tipo"],"DATA_ALTERADA")
        self.assertTrue(any(a["tipo"]=="DATA_LAUDO_AUSENTE" for a in auditar_laudo_semantico({"encerramento":{"data":None}},motor)))
        catalogo=[{"id":"DOC-001","data":"2026-08-11"},{"id":"DOC-002","data":"2026-08-10"}]
        def auditar(texto,doc):return auditar_fidelidade({"blocos":[],"claims":[{"id":"CLAIM-RED-001","texto_semantico":texto,"doc_ids":[doc],"pat_ids":[]}]},{"patologias":[],"catalogo_evidencias":catalogo})
        self.assertEqual(auditar("Em 11/08/2026", "DOC-001"),[]);self.assertEqual(auditar("Em 10/08/2026","DOC-001")[0]["tipo"],"DATA_ALTERADA");self.assertEqual(auditar("Em 11/08/2026","DOC-002")[0]["tipo"],"DATA_ALTERADA")

    def test_autocorrecao_preserva_catalogo_corrigido_trilha_e_idempotencia(self):
        resultado={"patologias":[],"questoes_saneadas":[],"cobertura_quesitos":[],"catalogo_evidencias":[{"id":"OBS-001","aspectos_suportados":["CAUSA"],"aspectos_contraditos":[],"auditoria_aspectos":[{"aspecto":"CAUSA","polaridade":"NEGADO"}]}]}
        achado={"tipo":"NEGACAO_CONVERTIDA_EM_FATO","claim_id":"OBS-001","evidencias":["OBS-001"]}
        final,trilha=autocorrigir(resultado,[],[],[achado]);self.assertEqual(final["catalogo_evidencias"][0]["aspectos_suportados"],[]);self.assertTrue(all(k in trilha[0] for k in ("alvo","valor_antes","valor_depois","achado_originador","acao","motivo","evidencia")))
        final2,trilha2=autocorrigir(final,[],[],[achado]);self.assertEqual(final2["catalogo_evidencias"],final["catalogo_evidencias"]);self.assertEqual(trilha2,[])
    def test_quatro_achados_catalogo_sao_reauditados_apos_correcao(self):
        obs={"id":"OBS-001","tipo":"OBSERVACAO","resultado":"OBSERVADO","aspectos_suportados":["FISSURA_PRESENTE"],"aspectos_contraditos":[],"auditoria_aspectos":[{"aspecto":"FISSURA_PRESENTE","polaridade":"NEGADO"}]}
        nor={"id":"NOR-001","tipo":"NORMA","authority":"FONTE_OFICIAL_VERIFICADA","classificacao_fonte":"FONTE_SECUNDARIA","dominio_oficial":False,"status_verificacao":"PENDENTE_VERIFICACAO","aspectos_suportados":["REQUISITO_NORMATIVO_VERIFICADO","FISSURA_PRESENTE"],"aspectos_contraditos":[],"auditoria_aspectos":[]}
        r={"patologias":[],"catalogo_evidencias":[obs,nor],"cobertura_quesitos":[],"questoes_saneadas":[]}
        iniciais=executar_detector(r);tipos={a["tipo"] for a in iniciais};self.assertTrue({"NEGACAO_CONVERTIDA_EM_FATO","OBS_NEGADA_COM_RESULTADO_OBSERVADO","NORMA_USADA_COMO_FATO_DO_CASO","AUTORIDADE_NORMATIVA_AUTODECLARADA"}<=tipos)
        final,trilha=autocorrigir(r,[],[],iniciais);restantes={a["tipo"] for a in executar_detector(final)}
        obrigatorios={"NEGACAO_CONVERTIDA_EM_FATO","OBS_NEGADA_COM_RESULTADO_OBSERVADO","NORMA_USADA_COMO_FATO_DO_CASO","AUTORIDADE_NORMATIVA_AUTODECLARADA"}
        self.assertFalse(obrigatorios&restantes);self.assertTrue(trilha);self.assertEqual(r["catalogo_evidencias"][0]["resultado"],"OBSERVADO")

    def test_aprofundar_limpa_juridico_e_e_idempotente(self):
        raiz=Path(__file__).resolve().parents[1]
        processo=json.loads((raiz/"tests/fixtures/schemas/processo-valido.json").read_text(encoding="utf8"));d=json.loads((raiz/"tests/fixtures/triagem/delimitacao-minima-valida.json").read_text(encoding="utf8"))
        q={"id":"QUE-001","origem":"JUIZO","documento_id":"DOC-PJE-001","numero_original":"1","texto_integral":"Quem deve indenizar?","pertinencia":"MATERIA_JURIDICA","materia_tecnica":None,"questoes_tecnicas_relacionadas":["QT-001"],"secoes_laudisticas_previstas":["3"],"status_cobertura":"JURIDICO_DELIMITADO","proveniencia":d["proveniencia"]}
        d["quesitos"]=[q];d["questoes_tecnicas"][0]["quesitos_relacionados"]=["QUE-001"];d["matriz_cobertura"]=[{"quesito_id":"QUE-001","questoes_tecnicas":["QT-001"],"secoes_laudisticas":["3"],"status":"JURIDICO_DELIMITADO"}]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"processo.json").write_text(json.dumps(processo),encoding="utf8");(p/"delimitacao-pericial.json").write_text(json.dumps(d),encoding="utf8")
            a=aprofundar(p);(p/"delimitacao-pericial.json").write_text(json.dumps(a),encoding="utf8");b=aprofundar(p)
        self.assertEqual(a,b);self.assertEqual(a["quesitos"][0]["questoes_tecnicas_relacionadas"],[]);self.assertNotIn("QUE-001",a["questoes_tecnicas"][0]["quesitos_relacionados"])
