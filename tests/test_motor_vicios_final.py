import copy,json,re,tempfile,unittest
from pathlib import Path

from scripts.auditoria_pericial.grounding import extrair_claims
from scripts.conhecimento_privado.inventariar import agregar_regras_candidatas
from scripts.motor_vicios.auditar import auditar
from scripts.motor_vicios.hipoteses import gerar as gerar_hipoteses
from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.motor_vicios.validar_motor import validar
from scripts.planejamento_pericial.aprofundar_delimitacao import aprofundar
from scripts.planejamento_pericial.gerar_plano import gerar as gerar_plano
from scripts.planejamento_pericial.gerar_processo import gerar as gerar_processo
from scripts.triagem_pericial.gerar_delimitacao import gerar as gerar_delimitacao
from scripts.vistoria_estruturada.gerar_vistoria import gerar
from scripts.vistoria_estruturada.inventariar_vistoria import inventariar
from scripts.redacao_pericial.pipeline import executar_pipeline_redacao

RAIZ=Path(__file__).resolve().parents[1]
def load(p):return json.loads((RAIZ/p).read_text(encoding="utf-8"))

class MotorViciosFinalTest(unittest.TestCase):
    def setUp(self):
        self.processo=load("tests/fixtures/schemas/processo-valido.json")
        self.delimitacao=load("tests/fixtures/triagem/delimitacao-minima-valida.json")
        self.plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json")

    def obs(self,descricao="Interface com umidade visível",resultado="OBSERVADO",aspectos=None):
        return {"id":"OBS-001","local":"Local fictício","ambiente":"Ambiente fictício","sistema":"IMPERMEABILIZACAO","elemento":"Parede","descricao_objetiva":descricao,"manifestacao":"umidade","resultado":resultado,"campo_examinado":"Superfície acessível","metodo":["INSPECAO_VISUAL"],"fotografias":[],"medicoes":[],"alegacoes":["ALG-001"],"questoes":["QT-001"],"quesitos":["QUE-001"],"confianca":{"nivel":"ALTA"},"proveniencia":["ARQ-VIS-001"],"limitacoes":[],"aspectos_suportados":aspectos or []}

    def vistoria(self,obs=None):
        v=load("tests/fixtures/schemas/vistoria-valida.json");v["observacoes"]=[obs or self.obs()]
        v["cobertura"]=[{"tipo":r["tipo"],"planejado":r.get("item_planejado"),"status":"EXECUTADO","executado":[f"EXEC-{i:03d}"],"evidencia_equivalente":[],"justificativa_equivalencia":None,"impacto":None} for i,r in enumerate(self.plano["requisitos_cobertura"],1)]
        v["atividades_executadas"]=[{"id":f"EXEC-{i:03d}","atividade_planejada":r["item_planejado"],"questoes":[r["questao_tecnica"]]} for i,r in enumerate(self.plano["requisitos_cobertura"],1) if r["tipo"]=="ATIVIDADE"]
        return v

    def test_causalidade_emerge_sem_contexto_externo(self):
        r=executar_pipeline_motor(self.processo,self.delimitacao,self.plano,self.vistoria())
        self.assertTrue(r["analise_inicial"]["hipoteses"]);self.assertNotIn("contexto",r)

    def test_evidencia_favoravel_e_contraria_mudam_hipotese(self):
        cat=[{"id":"OBS-001","descricao":"interface sob chuva","proveniencia":["A"]},{"id":"OBS-002","descricao":"interface e vedação deteriorada","proveniencia":["B"]}]
        self.assertEqual(gerar_hipoteses("umidade","MAN-001",sistema="IMPERMEABILIZACAO",catalogo=cat)[0]["status"],"NAO_TESTAVEL")
        cat=[{"id":"OBS-001","descricao":"vedação íntegra","proveniencia":["A"],"aspectos_suportados":["VEDACAO_INTEGRA"]}]
        self.assertEqual(gerar_hipoteses("umidade","MAN-001",sistema="IMPERMEABILIZACAO",catalogo=cat)[0]["status"],"AFASTADA")

    def test_norma_alimenta_hipotese_sem_substituir_evidencia(self):
        h=gerar_hipoteses("umidade","MAN-001",sistema="IMPERMEABILIZACAO",normas=[{"id":"NOR-001","aplicabilidade_temporal":"APLICAVEL"}])[0]
        self.assertEqual(h["normas"],["NOR-001"]);self.assertEqual(h["status"],"NAO_TESTAVEL")

    def test_norma_posterior_nao_vira_requisito_historico(self):
        h=gerar_hipoteses("umidade","MAN-001",sistema="IMPERMEABILIZACAO",normas=[{"id":"NOR-001","aplicabilidade_temporal":"NAO_APLICAVEL"}])[0]
        self.assertEqual(h["normas"],[])

    def test_anotacao_e_declaracao_naturais(self):
        inv={"arquivos":[{"id":"ARQ-VIS-001","nome":"campo.txt","caminho_relativo":"campo.txt","categoria":"ANOTACAO","metodo_ingestao":"TEXTO_SIMPLES","metadados":{"texto_original":"Sala: fissura visível com abertura 0,2 mm\nMorador informou que a mancha surgiu após chuva"}}]}
        v=gerar(inv,self.plano,self.processo["numero_processo"])
        self.assertEqual((len(v["observacoes"]),len(v["medicoes"]),len(v["declaracoes"])),(1,1,1));self.assertEqual(v["declaracoes"][0]["natureza"],"DECLARADO_POR_TERCEIRO")

    def test_hash_duplicado_na_mesma_rodada_reutiliza_id(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"a.txt").write_text("registro fictício",encoding="utf-8");(p/"b.txt").write_text("registro fictício",encoding="utf-8")
            inv=inventariar(p);self.assertEqual(len({x["id"] for x in inv["arquivos"]}),1)

    def test_fotografia_ambigua_nao_e_associada(self):
        plano=copy.deepcopy(self.plano);plano["fotografias"]=[{"id":"FOT-PLANO-001","finalidade":"parede sala","enquadramento":"geral"},{"id":"FOT-PLANO-002","finalidade":"parede sala","enquadramento":"geral"}]
        inv={"arquivos":[{"id":"ARQ-VIS-001","nome":"parede sala.jpg","caminho_relativo":"parede sala.jpg","categoria":"FOTOGRAFIA","metadados":{}}]}
        f=gerar(inv,plano)["fotografias"][0];self.assertIsNone(f["fotografia_planejada"]);self.assertEqual(f["metodo_associacao"],"ASSOCIACAO_AMBIGUA")

    def test_cobertura_atividade_ensaio_documento_e_equivalente(self):
        plano=copy.deepcopy(self.plano);plano["ensaios"]=[{"id":"ENS-PLANO-001","nome":"estanqueidade","questoes_tecnicas":["QT-001"]}];plano["documentos_a_solicitar"]=[{"id":"DOC-PLANO-001","descricao":"memorial","questoes_tecnicas":["QT-001"]}]
        texto="\n".join(["tipo=ATV;descricao=inspeção;atividade_planejada=ATV-001","tipo=ENS;descricao=estanqueidade;resultado=negativo;ensaio_planejado=ENS-PLANO-001","tipo=OBS;descricao=evidência genérica não equivalente"])
        plano["medicoes"]=[{"id":"MED-PLANO-001","questoes_tecnicas":["QT-001"]}]
        inv={"arquivos":[{"id":"ARQ-VIS-001","nome":"campo.txt","caminho_relativo":"campo.txt","categoria":"ANOTACAO","metodo_ingestao":"TEXTO_SIMPLES","metadados":{"texto_original":texto}},{"id":"ARQ-VIS-002","nome":"memorial.pdf","caminho_relativo":"memorial.pdf","categoria":"DOCUMENTO","metadados":{"documento_planejado":"DOC-PLANO-001"}}]}
        estados={(x["tipo"],x["planejado"]):x["status"] for x in gerar(inv,plano)["cobertura"]}
        self.assertEqual(estados[("ATIVIDADE","ATV-001")],"EXECUTADO");self.assertEqual(estados[("ENSAIO","ENS-PLANO-001")],"EXECUTADO");self.assertEqual(estados[("DOCUMENTO","DOC-PLANO-001")],"EXECUTADO");self.assertEqual(estados[("MEDICAO","MED-PLANO-001")],"NAO_EXECUTADO")

    def test_vicio_verdadeiro_nunca_tipo_nao_aplicavel(self):
        v=self.vistoria(self.obs(aspectos=["CAUSA:FALHA_DE_VEDAÇÃO","ORIGEM_ENDOGENA_CONSTRUTIVA"]));r=executar_pipeline_motor(self.processo,self.delimitacao,self.plano,v)
        for p in r["analise_final"]["patologias"]:
            if p["vicio_construtivo"]["caracterizado"]:self.assertNotEqual(p["vicio_construtivo"]["tipo"],"NAO_APLICAVEL")

    def test_pat_incompleto_e_hip_orfa_rejeitados(self):
        schema=load("schemas/patologia.schema.json");self.assertIn("manifestacao",schema["required"]);self.assertIn("evidencias",schema["required"])
        r=executar_pipeline_motor(self.processo,self.delimitacao,self.plano,self.vistoria())["analise_final"];r["patologias"][0]["hipoteses"]=["HIP-999"]
        self.assertTrue(any("HIP órfã" in x for x in validar(r,self.processo,self.delimitacao,self.plano,self.vistoria(),[],[])))

    def test_contradicoes_medicao_observacao_e_ressalva(self):
        v=self.vistoria();v["medicoes"]=[{"id":"MED-001","valor":.2,"unidade":"mm"}];r=executar_pipeline_motor(self.processo,self.delimitacao,self.plano,v)["analise_final"];p=r["patologias"][0];p["medicoes"]=["MED-001"];p["conclusao_tecnica"]="A abertura é 2,0 mm."
        self.assertTrue(any(x["tipo"]=="CONTRADICAO_MEDICAO" for x in auditar(r,v)))
        v["observacoes"][0]["descricao_objetiva"]="A esquadria abriu e fechou normalmente";p["constatacoes"]=["OBS-001"];p["conclusao_tecnica"]="Há falha funcional";self.assertTrue(any(x["tipo"]=="PAT_OBS_CONTRADICAO" for x in auditar(r,v)))
        p["ressalvas"]=["Causalidade inconclusiva"];p["conclusao_tecnica"]="A causa é definitivamente construtiva";self.assertTrue(any(x["tipo"]=="CONCLUSAO_RESSALVA_CONTRADICAO" for x in auditar(r,v)))

    def test_pipeline_integra_grounding_deep_autocorrecao_e_trilha(self):
        r=executar_pipeline_motor(self.processo,self.delimitacao,self.plano,self.vistoria())
        self.assertTrue(r["grounding_inicial"]);self.assertIsInstance(r["deep_audit_inicial"],list);self.assertEqual(r["analise_final"]["estado_analise"],"PAT_FINAL");self.assertEqual(r["trilha"]["skill"],"motor-vicios-construtivos")

    def test_rotulo_causal_de_input_nao_produz_origem_nem_vicio(self):
        v=self.vistoria(self.obs(aspectos=["CAUSA:FALHA_DE_VEDAÇÃO","ORIGEM_ENDOGENA_CONSTRUTIVA"]));r=executar_pipeline_motor(self.processo,self.delimitacao,self.plano,v);p=r["analise_final"]["patologias"][0]
        self.assertEqual(p["origem"],"INCONCLUSIVA");self.assertFalse(p["vicio_construtivo"]["caracterizado"]);self.assertEqual(p["vicio_construtivo"]["revisao_profissional"]["status"],"NAO_REVISADO")

    def test_gates_apto_com_ressalvas_e_bloqueado(self):
        conforme=self.obs("Condição examinada","CONFORME");conforme["manifestacao"]=None
        self.assertEqual(executar_pipeline_motor(self.processo,self.delimitacao,self.plano,self.vistoria(conforme))["gate"],"APTO_PARA_REDACAO")
        self.assertEqual(executar_pipeline_motor(self.processo,self.delimitacao,self.plano,self.vistoria())["gate"],"APTO_PARA_REDACAO_COM_RESSALVAS")
        v=self.vistoria();v["observacoes"][0]["alegacoes"]=["ALG-999"]
        self.assertEqual(executar_pipeline_motor(self.processo,self.delimitacao,self.plano,v)["gate"],"BLOQUEADO_PARA_REDACAO")

    def test_modelos_so_promovem_pratica_recorrente_nao_resultado(self):
        m=[{"id":"MOD-001","praticas_recorrentes":["estrutura por capítulos","causa endógena"]},{"id":"MOD-002","praticas_recorrentes":["estrutura por capítulos","causa endógena"]}]
        regras=agregar_regras_candidatas(m);self.assertEqual([x["pratica"] for x in regras],["estrutura por capítulos"])

    def test_claims_sao_extraidas_do_pat_final(self):
        r=executar_pipeline_motor(self.processo,self.delimitacao,self.plano,self.vistoria());self.assertEqual(r["claims_finais"],extrair_claims(r["analise_final"]))

    def test_e2e_integral_documentos_campo_auditoria_e_autocorrecao(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/"documentos").mkdir();manifesto=load("tests/fixtures/pje/manifesto-minimo-valido.json");doc=load("tests/fixtures/pje/documento-simples-valido.json")
            texto=("A autora alega infiltracao, fissura, trinca e descolamento no imovel adquirido, decorrentes de vicio construtivo. "
                   "O objeto da pericia e o imovel. O objetivo da pericia e determinar a causa.\nQUESITOS:\n1. Existe umidade na parede?\n2. Quem deve indenizar pelos danos?")
            doc["paginas"][0]["texto_bruto"]=texto;prov=doc["fontes"][0];doc["blocos_texto"]=[{"bloco_id":"BLT-001","texto":texto,"pagina":doc["paginas"][0]["referencia"],"proveniencia":prov}]
            (d/"manifesto-pje.json").write_text(json.dumps(manifesto),encoding="utf-8");(d/"documentos/DOC-PJE-001.json").write_text(json.dumps(doc),encoding="utf-8")
            doc2=copy.deepcopy(doc);doc2["documento_id"]="DOC-PJE-002";doc2["id_pje"]="900002";doc2["classe_normalizada"]="DECISAO";doc2["fontes"][0].update(documento_id="DOC-PJE-002",id_pje="900002");doc2["blocos_texto"][0]["proveniencia"].update(documento_id="DOC-PJE-002",id_pje="900002");(d/"documentos/DOC-PJE-002.json").write_text(json.dumps(doc2),encoding="utf-8")
            delimitacao=gerar_delimitacao(d);(d/"delimitacao-pericial.json").write_text(json.dumps(delimitacao),encoding="utf-8")
            processo=gerar_processo(d);(d/"processo.json").write_text(json.dumps(processo),encoding="utf-8")
            delimitacao=aprofundar(d);(d/"delimitacao-pericial.json").write_text(json.dumps(delimitacao),encoding="utf-8");plano=gerar_plano(d)
            linhas=[]
            for i,a in enumerate(plano["atividades"],1):
                resultado="NAO_CONSTATADO_NA_VISTORIA" if i==len(plano["atividades"]) else "OBSERVADO"
                linhas.append(f"tipo=OBS;descricao={'interface com umidade' if i==1 else 'condição examinada'};manifestacao={'umidade' if i<3 else 'fissura'};resultado={resultado};sistema=IMPERMEABILIZACAO;atividade_planejada={a['id']}")
            med_planejada=plano["medicoes"][0]["id"] if plano["medicoes"] else ""
            linhas.extend([f"tipo=MED;grandeza=abertura;valor=0,2;unidade=mm;medicao_planejada={med_planejada}","tipo=DECLARACAO;descricao=Morador relatou evento fictício"])
            campo=d/"campo";campo.mkdir();(campo/"notas.txt").write_text("\n".join(linhas),encoding="utf-8")
            for i,f in enumerate(plano["fotografias"],1):(campo/f"{f['id']}.jpg").write_bytes(f"imagem sintetica {i}".encode())
            inventario=inventariar(campo);vistoria=gerar(inventario,plano,processo["numero_processo"])
            norma={"id":"NOR-001","titulo":"Norma pública fictícia","requisito":"Critério fictício verificado","verificada":True,"edicao":"2020","aplicabilidade_temporal":"APLICAVEL","proveniencia":["https://www.gov.br/norma"],"sistema":"IMPERMEABILIZACAO","classificacao_fonte":"FONTE_PRIMARIA_OFICIAL","entidade":"Entidade sintética","documento":"Norma sintética","dominio":"gov.br","url":"https://www.gov.br/norma","dominio_oficial":True,"status_verificacao":"VERIFICADO","escopo_fonte":"CONTEUDO_NORMATIVO","conteudo_normativo_verificado":True,"conteudo_consultado":"Critério fictício verificado"}
            saida=executar_pipeline_motor(processo,delimitacao,plano,vistoria,{"normas":[norma],"data_relevante":"2026-01-01"})
            redacao=executar_pipeline_redacao(processo,delimitacao,saida)
            self.assertEqual(delimitacao["tipo_pericia"]["tipo"],"VICIOS_CONSTRUTIVOS");self.assertIn("determinar a causa",delimitacao["tema_controvertido"]["texto"].lower())
            self.assertTrue(vistoria["medicoes"]);self.assertTrue(vistoria["declaracoes"]);self.assertTrue(saida["analise_inicial"]["patologias"]);self.assertTrue(saida["claims"]);self.assertTrue(saida["grounding_inicial"])
            self.assertEqual(saida["analise_final"]["estado_analise"],"PAT_FINAL");self.assertTrue(saida["trilha"]);self.assertEqual(saida["gate"],"APTO_PARA_REDACAO_COM_RESSALVAS",{k:saida.get(k) for k in ("coverage_execucao","erros_finais","detector_final","deep_audit_final","grounding_final")})
            self.assertEqual(redacao["plano_redacao"]["modelo_documental"],"LAUDO_VICIOS_CONSTRUTIVOS_V1");self.assertEqual(redacao["plano_redacao"]["tema_controvertido"],delimitacao["tema_controvertido"]["texto"]);self.assertEqual(redacao["plano_redacao"]["objeto"],delimitacao["objeto_material"]["texto"]);self.assertEqual(redacao["plano_redacao"]["objetivo"],delimitacao["objetivo_pericial"]["texto"])
            self.assertTrue(any(q["origem"].startswith("Decisão/documentos") and q["documentos_relacionados"] for q in delimitacao["questoes_tecnicas"]))
            que=next(q for q in delimitacao["quesitos"] if q["pertinencia"]=="PERTINENTE_TECNICO");qt_ids=que["questoes_tecnicas_relacionadas"]
            qts=[q for q in saida["analise_final"]["questoes_saneadas"] if q["id"] in qt_ids]
            self.assertTrue(qt_ids and any(q.get("patologias") for q in qts))
            respostas=[q["resposta"] for g in redacao["laudo"].get("quesitos",[]) for q in g.get("itens",[]) if q.get("id")==que["id"]]
            self.assertTrue(respostas and all(r.startswith("R: ") and "INFORMAÇÃO NECESSÁRIA" not in r for r in respostas))
            self.assertTrue(any(q.get("materia_juridica_associada") for q in delimitacao["quesitos"]));self.assertTrue(all("validado_perito" not in p.get("vicio_construtivo",{}) for p in saida["analise_final"]["patologias"]))

if __name__=="__main__":unittest.main()
