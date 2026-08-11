import copy,json,tempfile,unittest
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
from referencing import Registry,Resource

from scripts.backend_contract.errors import DomainError
from scripts.conhecimento_privado.pesquisa_online import EgressPolicy,dados_sensiveis_processo,buscar_seguro
from scripts.motor_vicios.auditar import comparar_medicao
from scripts.motor_vicios.normas import aplicabilidade_temporal,avaliar_conformidade_normativa,recuperar_normas_para_manifestacao
from scripts.planejamento_pericial.migracoes import migrar_plano
from scripts.planejamento_pericial.validar_plano import recalcular_execucao
from scripts.planejamento_pericial.validar_plano import recalcular_cobertura
from scripts.extracao_pje.gerar_manifesto import construir_manifesto,salvar_manifesto
from scripts.extracao_pje.gerar_documentos import gerar_documentos
from scripts.triagem_pericial.gerar_delimitacao import gerar as gerar_delimitacao
from scripts.triagem_pericial.validar_delimitacao import validar_relacoes,status_derivado
from scripts.planejamento_pericial.gerar_processo import gerar as gerar_processo
from scripts.planejamento_pericial.aprofundar_delimitacao import aprofundar
from scripts.planejamento_pericial.gerar_plano import gerar as gerar_plano
from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.motor_vicios.motor import executar as executar_motor
from scripts.redacao_pericial.pipeline import executar_pipeline_redacao
from tests.test_adv_safe_hardening import AdvSafeHardening
from scripts.redacao_pericial.pipeline import _grupos_quesitos
from scripts.vistoria_estruturada.gerar_vistoria import gerar
from scripts.vistoria_estruturada.inventariar_vistoria import inventariar

ROOT=Path(__file__).resolve().parents[1]
def load(p):return json.loads((ROOT/p).read_text(encoding="utf8"))
def validar(schema_nome,obj):
    schemas=[load(p.relative_to(ROOT)) for p in (ROOT/"schemas").glob("*.schema.json")];reg=Registry()
    for s in schemas:reg=reg.with_resource(s["$id"],Resource.from_contents(s))
    schema=next(s for s in schemas if s["$id"].rsplit("/",1)[-1]==schema_nome);return list(Draft202012Validator(schema,registry=reg,format_checker=FormatChecker()).iter_errors(obj))

class AuditoriaFinal2(unittest.TestCase):
    def test_produtor_vistoria_20_valida_exatamente_no_schema(self):
        plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json")
        inv={"arquivos":[{"id":"ARQ-VIS-001","nome":"campo.txt","caminho_relativo":"campo.txt","categoria":"ANOTACAO","metodo_ingestao":"TEXTO_SIMPLES","metadados":{"texto_original":"tipo=OBS;descricao=fissura observada;manifestacao=fissura;atividade_planejada=ATV-001;sistema=REVESTIMENTOS"}}]}
        vistoria=gerar(inv,plano,"0000001-00.2026.4.00.0001")
        self.assertEqual(validar("vistoria.schema.json",vistoria),[])

    def test_migracao_plano_schema_valid_idempotente_e_fail_closed(self):
        legado=load("tests/fixtures/planejamento/plano-vistoria-valido.json");legado["schema_version"]="1.0.0"
        for r in legado["requisitos_cobertura"]:r.pop("item_planejado",None)
        migrado=migrar_plano(legado);self.assertEqual(validar("plano-vistoria.schema.json",migrado),[]);self.assertEqual(migrar_plano(migrado),migrado)
        ruim=copy.deepcopy(legado);ruim["atividades"].append({**ruim["atividades"][0],"id":"ATV-002"})
        with self.assertRaises(DomainError):migrar_plano(ruim)
        with self.assertRaises(DomainError):migrar_plano({"schema_version":"3.0.0"})

    def test_equivalencia_tipagem_e_catalogo_planejado(self):
        plano={"ensaios":[{"id":"ENS-PLANO-001","nome":"ESTANQUEIDADE","questoes_tecnicas":["QT-001"]}],"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"ENSAIO","obrigatoriedade":"OBRIGATORIA","item_planejado":"ENS-PLANO-001"}]}
        base={"cobertura":[{"planejado":"ENS-PLANO-001","status":"SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE","executado":[],"evidencia_equivalente":["OBS-001"],"justificativa_equivalencia":"justificada","equivalencia":{"requisito_original":"ENS-PLANO-001","tipo_evidencia":"ENSAIO","capability":"ESTANQUEIDADE","metodo_substituto":"ensaio equivalente"}}],"observacoes":[{"id":"OBS-001","questoes":["QT-001"]}]}
        self.assertFalse(recalcular_execucao(plano,base)["apto"])
        base["ensaios"]=[{"id":"ENS-001","ensaio_planejado":None,"nome":"OUTRO ENSAIO","questoes":["QT-001"]}];base["cobertura"][0]["evidencia_equivalente"]=["ENS-001"]
        self.assertFalse(recalcular_execucao(plano,base)["apto"]);base["ensaios"][0]["nome"]="ESTANQUEIDADE";base["cobertura"][0]["equivalencia"]["capability"]="estanqueidade"
        self.assertFalse(recalcular_execucao(plano,base)["apto"])

    def test_isolamento_mesmo_arquivo_ambiente_sem_vinculo(self):
        plano={"atividades":[{"id":"ATV-001","verificar":"fissura A","metodo":"visual","evidencia_esperada":"A","questoes_tecnicas":["QT-001"],"quesitos":[],"alegacoes":[]},{"id":"ATV-002","verificar":"fissura B","metodo":"visual","evidencia_esperada":"B","questoes_tecnicas":["QT-002"],"quesitos":[],"alegacoes":[]}]}
        texto="\n".join(("tipo=OBS;descricao=fissura A;manifestacao=fissura A;atividade_planejada=ATV-001;ambiente=Sala;sistema=VEDACOES","tipo=MED;grandeza=abertura;valor=1;unidade=mm;medicao_planejada=MED-X;ambiente=Sala;sistema=VEDACOES","tipo=OBS;descricao=fissura B;manifestacao=fissura B;atividade_planejada=ATV-002;ambiente=Sala;sistema=VEDACOES"))
        v=gerar({"arquivos":[{"id":"ARQ-VIS-001","nome":"campo.txt","caminho_relativo":"campo.txt","categoria":"ANOTACAO","metodo_ingestao":"TEXTO_SIMPLES","metadados":{"texto_original":texto}}]},plano)
        self.assertTrue(all(not o["medicoes"] for o in v["observacoes"]));self.assertEqual(v["relacoes_evidencia"],[])

    def test_quesito_multi_qt_exige_todas_dimensoes(self):
        d={"quesitos":[{"id":"QUE-001","origem":"JUIZO","numero_original":"1","texto_integral":"A e B?","questoes_tecnicas_relacionadas":["QT-001","QT-002"],"secoes_laudisticas_previstas":["4.2"]}]}
        parcial={"questoes_saneadas":[{"id":"QT-001","conclusao":"A","patologias":["PAT-001"]},{"id":"QT-002","conclusao":None,"patologias":[]}]}
        resposta=_grupos_quesitos(d,parcial)[0]["itens"][0];self.assertIn("QT-002: [INFORMAÇÃO NECESSÁRIA",resposta["resposta"]);self.assertEqual(resposta["pat_ids"],["PAT-001"])
        parcial["questoes_saneadas"][1].update(conclusao="B",patologias=["PAT-002"]);resposta=_grupos_quesitos(d,parcial)[0]["itens"][0];self.assertIn("QT-001: A",resposta["resposta"]);self.assertIn("QT-002: B",resposta["resposta"])

    def test_quesito_parcial_preserva_tecnico_e_delimita_juridico(self):
        final={"questoes_saneadas":[{"id":"QT-001","conclusao":"Há manifestação constatada.","patologias":["PAT-001"]}]}
        parcial={"quesitos":[{"id":"QUE-001","origem":"JUIZO","numero_original":"1","texto_integral":"Há vício e dever de indenizar?","pertinencia":"PERTINENTE_PARCIAL","materia_juridica_associada":"dever de indenizar","questoes_tecnicas_relacionadas":["QT-001"],"secoes_laudisticas_previstas":["4.2"]}]}
        resposta=_grupos_quesitos(parcial,final)[0]["itens"][0]["resposta"]
        self.assertIn("QT-001: Há manifestação constatada.",resposta);self.assertIn("compete ao Juízo",resposta)
        juridico={"quesitos":[{"id":"QUE-002","origem":"JUIZO","numero_original":"2","texto_integral":"Quem deve indenizar?","pertinencia":"MATERIA_JURIDICA","materia_juridica_associada":"responsabilidade civil","questoes_tecnicas_relacionadas":[],"secoes_laudisticas_previstas":[]}]}
        resposta_juridica=_grupos_quesitos(juridico,{"questoes_saneadas":[]})[0]["itens"][0]["resposta"]
        self.assertIn("reservada à apreciação do Juízo",resposta_juridica);self.assertNotIn("INFORMAÇÃO NECESSÁRIA",resposta_juridica)

    def test_norma_temporal_autoridade_e_decimal(self):
        self.assertEqual(aplicabilidade_temporal({"edicao":"2024","publicacao":"2024-01-01","status_vigencia":"REVOGADA"},"2020-01-01"),"APLICABILIDADE_INCONCLUSIVA")
        norma={"id":"NOR-001","entidade":"ABNT","numero":"1","classificacao_fonte":"FONTE_TECNICA_LOCAL_VERIFICADA","status_verificacao":"VERIFICADO","verificada":True,"requisito":"x","metodo_verificacao":"medir","criterio":{"operador":"<=","valor":"4,0","unidade":"mm"},"proveniencia":["x"],"vigencia_inicio":"2010-01-01","data_relevante":"2020-01-01"}
        self.assertEqual(avaliar_conformidade_normativa(norma,[{"id":"MED-001","tipo":"MEDICAO","valor":"4.0","unidade":"mm"}])["resultado"],"ATENDE")
        norma["vigencia_inicio"]="2024-01-01";self.assertEqual(avaliar_conformidade_normativa(norma,[{"id":"MED-001","tipo":"MEDICAO","valor":4,"unidade":"mm"}])["resultado"],"INCONCLUSIVO")
        recuperada=recuperar_normas_para_manifestacao([{**norma,"url":"https://oficial.example/norma","sistema":"VEDACOES"}],sistema="VEDACOES",manifestacao="fissura",data_relevante="2020-01-01")[0];self.assertFalse(recuperada["verificada"])
        local=recuperar_normas_para_manifestacao([{**norma,"url":None,"proveniencia":[],"classificacao_fonte":"FONTE_TECNICA_LOCAL_VERIFICADA","sistema":"VEDACOES"}],sistema="VEDACOES",manifestacao="fissura",data_relevante="2020-01-01")[0];self.assertFalse(local["autoridade_fonte_verificada"]);self.assertFalse(local["verificada"])

    def test_boundary_plano_rejeita_delimitacao_fora_do_schema(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);processo=load("tests/fixtures/schemas/processo-valido.json");delimitacao=load("tests/fixtures/triagem/delimitacao-minima-valida.json");delimitacao["campo_nao_canonico"]=True
            (d/"processo.json").write_text(json.dumps(processo),encoding="utf8");(d/"delimitacao-pericial.json").write_text(json.dumps(delimitacao),encoding="utf8")
            with self.assertRaises(ValueError):gerar_plano(d)

    def test_numeros_assinados_e_unidades_unicode(self):
        self.assertTrue(comparar_medicao("Temperatura -2 °C",{"valor":"-2","unidade":"°C"}));self.assertTrue(comparar_medicao("Carga +2 kN / m²",{"valor":"+2","unidade":"kN/m²"}))

    def test_pii_helper_boundary_generico_e_pdf_documento(self):
        dados=dados_sensiveis_processo({"numero_processo":"0000001-00.2026.4.00.0001","partes":[{"nome":"Maria Exemplo","cpf_cnpj":"12345678901"}],"endereco":"Rua Alfa 10","matricula":"ABC-1"});self.assertIn("Maria Exemplo",dados)
        class Externo:
            EXTERNAL_DATA_EGRESS_REQUIRED=True
            def __init__(self):self.calls=[]
            def buscar(self,q,politica=None):self.calls.append(q);return []
        p=Externo();self.assertEqual(buscar_seguro("Maria Exemplo norma",p,EgressPolicy(permitir_egress=True,dados_sensiveis=dados))["status"],"BLOQUEADO_POR_EGRESS");self.assertEqual(p.calls,[])
        with tempfile.TemporaryDirectory() as td:
            caminho=Path(td)/"laudo-campo.pdf";caminho.write_bytes(b"%PDF-1.4 synthetic")
            arquivo=inventariar(Path(td))["arquivos"][0];self.assertEqual(arquivo["categoria"],"DOCUMENTO");self.assertEqual(arquivo["status"],"METADADOS_PARCIAIS")

    def test_input_obs_declarativo_nao_vira_constatacao(self):
        inv={"arquivos":[{"id":"ARQ-VIS-001","nome":"campo.txt","caminho_relativo":"campo.txt","categoria":"ANOTACAO","metodo_ingestao":"TEXTO_SIMPLES","metadados":{"texto_original":"tipo=OBS;descricao=Morador informou que há infiltração"}}]}
        v=gerar(inv);self.assertEqual((len(v["declaracoes"]),len(v["observacoes"])),(1,0))

    def test_inventario_incremental_preserva_obs_man_pat_hip_com_entrada_irrelevante(self):
        with tempfile.TemporaryDirectory() as td:
            campo=Path(td);plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json");processo=load("tests/fixtures/schemas/processo-valido.json");delimitacao=load("tests/fixtures/triagem/delimitacao-minima-valida.json")
            (campo/"z-campo.txt").write_text("tipo=OBS;descricao=umidade observada;manifestacao=umidade;resultado=OBSERVADO;sistema=IMPERMEABILIZACAO;atividade_planejada=ATV-001",encoding="utf8")
            primeira=gerar(inventariar(campo),plano);motor1=executar_motor(processo,delimitacao,plano,primeira)
            man1=next(m["id"] for m in motor1["manifestacoes"] if m.get("descricao")=="umidade");identidade1=(primeira["observacoes"][0]["id"],man1,motor1["patologias"][0]["id"],tuple(h["id"] for h in motor1["hipoteses"] if h.get("manifestacao")==man1))
            (campo/"a-irrelevante.txt").write_text("tipo=DECLARACAO;descricao=Terceiro relatou condição sem vínculo técnico",encoding="utf8")
            segunda=gerar(inventariar(campo),plano);motor2=executar_motor(processo,delimitacao,plano,segunda);pat=next(p for p in motor2["patologias"] if p["manifestacao"]=="umidade")
            man2=next(m["id"] for m in motor2["manifestacoes"] if m.get("descricao")=="umidade");identidade2=(next(o["id"] for o in segunda["observacoes"] if o.get("manifestacao")=="umidade"),man2,pat["id"],tuple(h["id"] for h in motor2["hipoteses"] if h.get("manifestacao")==man2))
            self.assertEqual(identidade2,identidade1)

    def test_e2e_canônico_pdf_ate_laudo_valida_contratos_relacoes_e_gates(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);pdf=d/"autos-sinteticos.pdf";AdvSafeHardening._pdf_sintetico(pdf)
            manifesto,erros,_=construir_manifesto(pdf);self.assertEqual(erros,[]);self.assertEqual(validar("manifesto-pje.schema.json",manifesto),[]);salvar_manifesto(manifesto,d)
            relatorio=gerar_documentos(manifesto,pdf,d);self.assertEqual((relatorio["documentos_gerados"],relatorio["documentos_validos"],relatorio["erros"]),(2,2,[]))
            docs_gerados=[]
            for caminho in sorted((d/"documentos").glob("*.json")):
                doc=json.loads(caminho.read_text(encoding="utf8"));docs_gerados.append(doc);self.assertEqual(validar("documento-pje.schema.json",doc),[])
            self.assertEqual(docs_gerados[0]["classe_normalizada"],"MANIFESTACAO")
            delimitacao=gerar_delimitacao(d);self.assertEqual(validar("delimitacao-pericial.schema.json",delimitacao),[]);self.assertEqual(validar_relacoes(delimitacao),[]);self.assertEqual(status_derivado(delimitacao),"APTO_PARA_PLANEJAMENTO");(d/"delimitacao-pericial.json").write_text(json.dumps(delimitacao),encoding="utf8")
            processo=gerar_processo(d);processo["imovel"]["endereco"]=load("tests/fixtures/schemas/processo-valido.json")["imovel"]["endereco"];self.assertIn("100",dados_sensiveis_processo(processo));self.assertEqual(validar("processo.schema.json",processo),[]);(d/"processo.json").write_text(json.dumps(processo),encoding="utf8")
            delimitacao=aprofundar(d);self.assertEqual(validar("delimitacao-pericial.schema.json",delimitacao),[]);self.assertEqual(validar_relacoes(delimitacao),[]);self.assertEqual(status_derivado(delimitacao),"APTO_PARA_PLANEJAMENTO");(d/"delimitacao-pericial.json").write_text(json.dumps(delimitacao),encoding="utf8")
            plano=gerar_plano(d);qt_documento=plano["requisitos_cobertura"][0]["questao_tecnica"];plano["documentos_a_solicitar"].append({"id":"DOC-PLANO-999","descricao":"memorial sintetico","questoes_tecnicas":[qt_documento],"criterio_satisfacao":"identidade documental"});plano["requisitos_cobertura"].append({"questao_tecnica":qt_documento,"tipo":"DOCUMENTO","obrigatoriedade":"OBRIGATORIA","item_planejado":"DOC-PLANO-999"});next(c for c in plano["cobertura"] if qt_documento in c["questoes_tecnicas"])["documentos"].append("DOC-PLANO-999");self.assertEqual(validar("plano-vistoria.schema.json",plano),[]);self.assertTrue(recalcular_cobertura(plano)["apto"])
            campo=d/"campo";campo.mkdir()
            for i,item in enumerate(plano["atividades"],1):(campo/f"atividade-{i}.txt").write_text(f"tipo=OBS;descricao=interface com umidade observada;manifestacao=umidade;resultado=OBSERVADO;sistema=IMPERMEABILIZACAO;ambiente=Sala;elemento=Parede;atividade_planejada={item['id']}",encoding="utf8")
            for i,item in enumerate(plano["medicoes"],1):(campo/f"medicao-{i}.txt").write_text(f"tipo=MED;grandeza=abertura;valor=0,2;unidade=mm;medicao_planejada={item['id']}",encoding="utf8")
            for i,item in enumerate(plano["fotografias"],1):(campo/f"{item['id']}.jpg").write_bytes(f"imagem-{i}".encode())
            (campo/"segunda-manifestacao.txt").write_text(f"tipo=OBS;descricao=não há fissura;manifestacao=fissura;resultado=NAO_CONSTATADO_NA_VISTORIA;sistema=IMPERMEABILIZACAO;ambiente=Sala;elemento=Parede;atividade_planejada={plano['atividades'][0]['id']}",encoding="utf8");(campo/"DOC-PLANO-999.pdf").write_bytes(b"%PDF-1.4 memorial sintetico")
            inventario_campo=inventariar(campo);next(a for a in inventario_campo["arquivos"] if a["nome"]=="DOC-PLANO-999.pdf")["metadados"]["documento_planejado"]="DOC-PLANO-999"
            vistoria=gerar(inventario_campo,plano,processo["numero_processo"]);self.assertEqual(validar("vistoria.schema.json",vistoria),[]);self.assertTrue(recalcular_execucao(plano,vistoria)["apto"]);self.assertEqual(len({o["manifestacao"] for o in vistoria["observacoes"]}),2)
            norma={"id":"NOR-999","entidade":"ABNT","numero":"999","titulo":"impermeabilizacao","sistema":"IMPERMEABILIZACAO","classificacao_fonte":"FONTE_TECNICA_LOCAL_VERIFICADA","status_verificacao":"VERIFICADO","verificada":True,"requisito":"abertura maxima","metodo_verificacao":"medir","criterio":{"operador":"<=","valor":4,"unidade":"mm","grandeza":"abertura"},"proveniencia":["NOR-LOCAL-999"],"vigencia_inicio":"2024-01-01"}
            motor=executar_pipeline_motor(processo,delimitacao,plano,vistoria,{"normas":[norma],"data_relevante":"2020-01-01"});self.assertEqual(validar("analise-motor-vicios.schema.json",motor["analise_final"]),[]);self.assertEqual(motor["gate"],"BLOQUEADO_PARA_REDACAO");self.assertTrue(any("sem vínculo analítico" in erro for erro in motor["erros_finais"]));self.assertTrue(all(n["avaliacao_conformidade"]["resultado"]=="INCONCLUSIVO" for p in motor["analise_final"]["patologias"] for n in p["normas_relacionadas"] if n["id"]=="NOR-999"))
            redacao=executar_pipeline_redacao(processo,delimitacao,motor);self.assertEqual(redacao["gate"],"BLOQUEADO_PARA_LAUDO")
            que=delimitacao["quesitos"][0];caso_novo=copy.deepcopy(delimitacao);caso_novo["quesitos"][0].update(texto_integral="Determinar o teor de cloretos no concreto.",materia_tecnica="Teor de cloretos no concreto",questoes_tecnicas_relacionadas=[])
            for qt in caso_novo["questoes_tecnicas"]:qt["quesitos_relacionados"]=[x for x in qt["quesitos_relacionados"] if x!=que["id"]]
            (d/"delimitacao-pericial.json").write_text(json.dumps(caso_novo),encoding="utf8");primeira=aprofundar(d);nova=next(q for q in primeira["questoes_tecnicas"] if q["origem"]=="Quesito pertinente sem equivalente no perfil metodológico");self.assertEqual((nova["descricao"],nova["proveniencia"]),("Teor de cloretos no concreto",caso_novo["quesitos"][0]["proveniencia"]));(d/"delimitacao-pericial.json").write_text(json.dumps(primeira),encoding="utf8");self.assertEqual(aprofundar(d),primeira)

if __name__=="__main__":unittest.main()
