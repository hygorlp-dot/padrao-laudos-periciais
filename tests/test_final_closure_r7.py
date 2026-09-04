import copy
import json
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,StreamObject

from scripts.planejamento_pericial.validar_plano import recalcular_execucao
from scripts.vistoria_estruturada.gerar_vistoria import gerar
from scripts.motor_vicios.validar_motor import lacunas_suporte_analitico
from scripts.extracao_pje.gerar_manifesto import construir_manifesto,salvar_manifesto
from scripts.extracao_pje.gerar_documentos import gerar_documentos
from scripts.triagem_pericial.gerar_delimitacao import gerar as gerar_delimitacao
from scripts.planejamento_pericial.gerar_processo import gerar as gerar_processo
from scripts.planejamento_pericial.aprofundar_delimitacao import aprofundar
from scripts.planejamento_pericial.gerar_plano import gerar as gerar_plano
from scripts.vistoria_estruturada.inventariar_vistoria import inventariar
from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.redacao_pericial.pipeline import executar_pipeline_redacao
from tests.test_auditoria_final2 import validar,load


def inventario_texto(texto):
    return {"arquivos":[{"id":"ARQ-VIS-001","nome":"campo.txt","caminho_relativo":"campo.txt","categoria":"ANOTACAO","metodo_ingestao":"TEXTO_SIMPLES","metadados":{"texto_original":texto}}]}


def plano_associacao():
    return {
        "atividades":[{"id":"ATV-001","verificar":"fissura visivel","metodo":"inspecao e medicao","evidencia_esperada":"fissura medida","questoes_tecnicas":["QT-001"],"quesitos":[],"alegacoes":[]}],
        "fotografias":[{"id":"FOT-PLANO-001","finalidade":"registrar fissura visivel","enquadramento":"detalhe","atividade":"ATV-001","questoes_tecnicas":["QT-001"],"quesitos":[],"alegacoes":[]}],
        "medicoes":[],"ensaios":[],"documentos_a_solicitar":[],"requisitos_cobertura":[],
    }

def pdf_sintetico(caminho):
    w=PdfWriter()
    def pagina(comandos):
        p=w.add_blank_page(width=612,height=792);fonte=DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")});p[NameObject("/Resources")]=DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):w._add_object(fonte)})});s=StreamObject();s.set_data(comandos.encode("ascii"));p[NameObject("/Contents")]=w._add_object(s)
    linhas=" ".join(f"{x} 650 m {x} 740 l S" for x in (40,140,260,480,570))+" 40 650 m 570 650 l S 40 680 m 570 680 l S 40 710 m 570 710 l S 40 740 m 570 740 l S"
    textos="BT /F1 10 Tf 45 720 Td (ID) Tj 100 0 Td (Data) Tj 120 0 Td (Titulo) Tj 220 0 Td (Tipo) Tj ET BT /F1 10 Tf 45 690 Td (900001) Tj 100 0 Td (01/01/2026) Tj 120 0 Td (Manifestacao da parte autora) Tj 220 0 Td (PETICAO) Tj ET BT /F1 10 Tf 45 660 Td (900002) Tj 100 0 Td (02/01/2026) Tj 120 0 Td (Decisao sintetica) Tj 220 0 Td (DECISAO) Tj ET"
    pagina(linhas+textos+" BT /F1 10 Tf 40 760 Td (Processo 0000001-00.2026.4.00.0001) Tj ET");pagina("BT /F1 10 Tf 40 730 Td (A autora alega infiltracao e fissura no imovel por vicio construtivo.) Tj 0 -20 Td (O objeto da pericia e o imovel e o objetivo da pericia e determinar a causa.) Tj 0 -20 Td (QUESITOS:) Tj 0 -20 Td (1. Existe umidade na parede?) Tj 0 -630 Td (Num. 900001 - Pag. 1) Tj ET");pagina("BT /F1 10 Tf 40 730 Td (Pagina complementar sem rodape e sem link) Tj ET");pagina("BT /F1 10 Tf 40 730 Td (DECISAO: defiro pericia para verificar infiltracao, fissura e determinar a causa.) Tj 0 -20 Td (O objeto da pericia e o imovel e o objetivo da pericia e sanear a controversia.) Tj 0 -650 Td (Num. 900002 - Pag. 1) Tj ET")
    with open(caminho,"wb") as arquivo:w.write(arquivo)


class FinalClosureR7(unittest.TestCase):
    def test_frase_unica_vincula_medicao_somente_a_observacao_correta(self):
        vistoria=gerar(inventario_texto("Sala: fissura visivel com abertura 0,2 mm"),plano_associacao())
        obs=vistoria["observacoes"][0];med=vistoria["medicoes"][0]
        self.assertEqual((med["valor"],med["unidade"]),(0.2,"mm"))
        self.assertEqual(obs["medicoes"],[med["id"]])
        self.assertEqual(med["observacoes"],[obs["id"]])
        self.assertTrue(any(r["observacao"]==obs["id"] and r["evidencia"]==med["id"] and r["origem"]=="REGISTRO_CAMPO_COMUM" for r in vistoria["relacoes_evidencia"]))

    def test_medicoes_distintas_nao_contaminam_observacoes(self):
        texto="\n".join((
            "tipo=OBS;registro_id=A;descricao=fissura A;manifestacao=fissura;atividade_planejada=ATV-001",
            "tipo=MED;vinculo_registro=A;grandeza=abertura;valor=0,2;unidade=mm",
            "tipo=OBS;registro_id=B;descricao=fissura B;manifestacao=fissura;atividade_planejada=ATV-001",
            "tipo=MED;vinculo_registro=B;grandeza=abertura;valor=0,4;unidade=mm",
        ))
        vistoria=gerar(inventario_texto(texto),plano_associacao());a,b=vistoria["observacoes"]
        self.assertEqual(a["medicoes"],["MED-001"]);self.assertEqual(b["medicoes"],["MED-002"])

    def test_foto_planejada_univoca_vincula_e_ambigua_nao_vincula(self):
        plano=plano_associacao()
        inventario={"arquivos":[
            {"id":"ARQ-VIS-001","nome":"campo.txt","caminho_relativo":"campo.txt","categoria":"ANOTACAO","metodo_ingestao":"TEXTO_SIMPLES","metadados":{"texto_original":"tipo=OBS;descricao=fissura visivel;manifestacao=fissura;atividade_planejada=ATV-001"}},
            {"id":"ARQ-VIS-002","nome":"FOT-PLANO-001.jpg","caminho_relativo":"FOT-PLANO-001.jpg","categoria":"FOTOGRAFIA","metodo_ingestao":"METADADOS","metadados":{}},
        ]}
        vistoria=gerar(inventario,plano);self.assertEqual(vistoria["observacoes"][0]["fotografias"],["FOT-001"])
        self.assertTrue(any(r["motivo"]=="ATIVIDADE_PLANEJADA_UNIVOCA" for r in vistoria["relacoes_evidencia"]))
        inventario["arquivos"][0]["metadados"]["texto_original"]+="\ntipo=OBS;descricao=outra fissura;manifestacao=fissura;atividade_planejada=ATV-001"
        ambigua=gerar(inventario,plano);self.assertTrue(all(not o["fotografias"] for o in ambigua["observacoes"]))

    def test_equivalencia_somente_medicao_e_fotografia(self):
        casos={
            "MEDICAO":({"id":"MED-PLANO-001","grandeza":"abertura","local":"Sala","criterio":"resultado em mm","questoes_tecnicas":["QT-001"]},{"id":"MED-001","medicao_planejada":None,"grandeza":"abertura","valor":0.2,"unidade":"mm","local":"Sala","questoes":["QT-001"],"observacoes":["OBS-001"],"metodo":"fissurômetro"},"medicoes"),
            "FOTOGRAFIA":({"id":"FOT-PLANO-001","finalidade":"fissura detalhe","questoes_tecnicas":["QT-001"]},{"id":"FOT-001","fotografia_planejada":None,"finalidade_planejada":"fissura detalhe","questoes":["QT-001"]},"fotografias"),
        }
        for tipo,(planejado,executado,colecao) in casos.items():
            with self.subTest(tipo=tipo):
                chave={"MEDICAO":"medicoes","FOTOGRAFIA":"fotografias"}[tipo]
                plano={chave:[planejado],"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":tipo,"obrigatoriedade":"OBRIGATORIA","item_planejado":planejado["id"]}],
                       "requisitos_semanticos":[{"requirement_id":"REQ-001-EQ","quesito":"QUE-001",
                                                 "requisito":"Medir a abertura das fissuras na Sala." if tipo=="MEDICAO" else "Fotografar a fissura em detalhe.",
                                                 "itens_planejados":[planejado["id"]]}]}
                cap="abertura" if tipo=="MEDICAO" else "fissura detalhe"
                linha={"tipo":tipo,"planejado":planejado["id"],"status":"SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE","executado":[],"evidencia_equivalente":[executado["id"]],"equivalencia":{"requisito_original":planejado["id"],"tipo_evidencia":tipo,"capability":cap,"metodo_substituto":"metodo equivalente"},"justificativa_equivalencia":"equivalencia documentada"}
                vistoria={colecao:[executado],"cobertura":[linha]};self.assertTrue(recalcular_execucao(plano,vistoria)["apto"])
                errado=copy.deepcopy(vistoria);errado[colecao][0]["questoes"]=["QT-999"];self.assertFalse(recalcular_execucao(plano,errado)["apto"])
                errado=copy.deepcopy(vistoria);errado["cobertura"][0]["equivalencia"]["capability"]="outra";self.assertFalse(recalcular_execucao(plano,errado)["apto"])
        for tipo,chave,pid,item in (("ATIVIDADE","atividades","ATV-001",{"id":"ATV-001","verificar":"x","questoes_tecnicas":["QT-001"]}),("ENSAIO","ensaios","ENS-PLANO-001",{"id":"ENS-PLANO-001","nome":"x","questoes_tecnicas":["QT-001"]}),("DOCUMENTO","documentos_a_solicitar","DOC-PLANO-001",{"id":"DOC-PLANO-001","descricao":"x","questoes_tecnicas":["QT-001"]})):
            plano={chave:[item],"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":tipo,"obrigatoriedade":"OBRIGATORIA","item_planejado":pid}]}
            vistoria={"cobertura":[{"tipo":tipo,"planejado":pid,"status":"SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE","executado":[],"evidencia_equivalente":["X-001"],"equivalencia":{"requisito_original":pid,"tipo_evidencia":tipo,"capability":"x","metodo_substituto":"x"},"justificativa_equivalencia":"x"}]}
            self.assertFalse(recalcular_execucao(plano,vistoria)["apto"])
        contrato=load("tests/fixtures/schemas/vistoria-valida.json");linha=contrato["cobertura"][0]
        linha.update(tipo="ATIVIDADE",status="SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE",executado=[],evidencia_equivalente=["ATV-EXEC-999"],equivalencia={"requisito_original":"ATV-001","tipo_evidencia":"ATIVIDADE","capability":"x","metodo_substituto":"x"},justificativa_equivalencia="x")
        self.assertTrue(validar("vistoria.schema.json",contrato))

    def test_execucao_sem_relacao_analitica_nao_satisfaz_motor(self):
        plano={"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"MEDICAO","obrigatoriedade":"OBRIGATORIA","item_planejado":"MED-PLANO-001"}]}
        motor={"patologias":[{"id":"PAT-001","constatacoes":["OBS-001"]}],"questoes_saneadas":[{"id":"QT-001","patologias":["PAT-001"]}]}
        vistoria={"cobertura":[{"planejado":"MED-PLANO-001","executado":["MED-001"],"evidencia_equivalente":[]}],"relacoes_evidencia":[]}
        self.assertEqual(lacunas_suporte_analitico(motor,plano,vistoria)[0]["tipo"],"MEDICAO")
        vistoria["relacoes_evidencia"]=[{"observacao":"OBS-001","evidencia":"MED-001","motivo":"VINCULO_REGISTRO_EXPLICITO","origem":"REGISTRO_CAMPO_COMUM"}]
        self.assertEqual(lacunas_suporte_analitico(motor,plano,vistoria),[])

    def test_e2e_positivo_apenas_com_produtores_reais(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);pdf=d/"autos-sinteticos.pdf";pdf_sintetico(pdf)
            manifesto,erros,_=construir_manifesto(pdf);self.assertEqual(erros,[]);salvar_manifesto(manifesto,d)
            self.assertEqual(validar("manifesto-pje.schema.json",manifesto),[]);self.assertEqual(gerar_documentos(manifesto,pdf,d)["erros"],[])
            for caminho in (d/"documentos").glob("*.json"):self.assertEqual(validar("documento-pje.schema.json",json.loads(caminho.read_text(encoding="utf8"))),[])
            delimitacao=gerar_delimitacao(d);self.assertEqual(validar("delimitacao-pericial.schema.json",delimitacao),[]);(d/"delimitacao-pericial.json").write_text(json.dumps(delimitacao),encoding="utf8")
            processo=gerar_processo(d,data_laudo="2026-08-11");self.assertEqual(validar("processo.schema.json",processo),[]);(d/"processo.json").write_text(json.dumps(processo),encoding="utf8")
            delimitacao=aprofundar(d);(d/"delimitacao-pericial.json").write_text(json.dumps(delimitacao),encoding="utf8");self.assertEqual(validar("delimitacao-pericial.schema.json",delimitacao),[])
            plano=gerar_plano(d);self.assertEqual(validar("plano-vistoria.schema.json",plano),[]);from scripts.planejamento_pericial.validar_plano import recalcular_cobertura;self.assertTrue(recalcular_cobertura(plano)["apto"])
            campo=d/"campo";campo.mkdir();atividade_por_qt={qt:a["id"] for a in plano["atividades"] for qt in a["questoes_tecnicas"]}
            for i,item in enumerate(plano["atividades"],1):
                (campo/f"atividade-{i}.txt").write_text(f"tipo=OBS;registro_id={item['id']};descricao=condição verificada em campo;manifestacao=condição verificada;resultado=CONFORME;sistema=VEDACOES;ambiente=Sala;elemento=Parede;atividade_planejada={item['id']};aspectos_suportados=MANIFESTACAO_TECNICA,CONSTATACAO",encoding="utf8")
            for i,item in enumerate(plano["medicoes"],1):
                atividade=atividade_por_qt[item["questoes_tecnicas"][0]]
                (campo/f"medicao-{i}.txt").write_text(f"tipo=MED;vinculo_registro={atividade};grandeza={item['grandeza']};valor=0,2;unidade=mm;medicao_planejada={item['id']}",encoding="utf8")
            for i,item in enumerate(plano["fotografias"],1):(campo/f"{item['id']}.jpg").write_bytes(f"imagem-{i}".encode())
            for i,item in enumerate(plano["ensaios"],1):(campo/f"ensaio-{i}.txt").write_text(f"tipo=ENS;descricao={item['nome']};ensaio_planejado={item['id']};status=EXECUTADO",encoding="utf8")
            for i,item in enumerate(plano["documentos_a_solicitar"],1):(campo/f"{item['id']}.pdf").write_bytes(b"%PDF-1.4 documento sintetico")
            inv=inventariar(campo)
            vistoria=gerar(inv,plano,processo["numero_processo"]);self.assertEqual(validar("vistoria.schema.json",vistoria),[]);self.assertTrue(recalcular_execucao(plano,vistoria)["apto"])
            motor=executar_pipeline_motor(processo,delimitacao,plano,vistoria);erros_schema=validar("analise-motor-vicios.schema.json",motor["analise_final"]);self.assertEqual(erros_schema,[],[(list(e.path),e.message) for e in erros_schema]);self.assertIn(motor["gate"],{"APTO_PARA_REDACAO","APTO_PARA_REDACAO_COM_RESSALVAS"},{"erros":motor.get("erros_finais"),"grounding":motor.get("grounding_final")})
            pat=next(p for p in motor["analise_final"]["patologias"] if p["constatacoes"]);self.assertTrue(pat["medicoes"]);self.assertTrue(pat["constatacao"]["fotografias"])
            redacao=executar_pipeline_redacao(processo,delimitacao,motor);self.assertIn(redacao["gate"],{"APTO_PARA_LAUDO","APTO_PARA_LAUDO_COM_RESSALVAS"},{"achados":redacao.get("achados"),"grounding":redacao.get("grounding")});self.assertEqual(validar("laudo-redacao.schema.json",redacao["laudo"]),[])
            que=delimitacao["quesitos"][0];qt=que["questoes_tecnicas_relacionadas"][0];saneada=next(q for q in motor["analise_final"]["questoes_saneadas"] if q["id"]==qt);pat=next(p for p in motor["analise_final"]["patologias"] if p["id"] in saneada["patologias"])
            self.assertTrue(set(pat["constatacoes"]));self.assertTrue(set(pat["medicoes"]));self.assertTrue(set(pat["constatacao"]["fotografias"]));self.assertTrue(any(item["id"]==que["id"] and qt in item["qt_ids"] and pat["id"] in item["pat_ids"] for grupo in redacao["laudo"]["quesitos"] for item in grupo["itens"]))


if __name__=="__main__":unittest.main()
