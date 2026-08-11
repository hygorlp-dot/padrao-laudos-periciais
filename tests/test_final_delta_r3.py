import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from scripts.conhecimento_privado.pesquisa_online import (
    AgentSearchProvider,
    EgressPolicy,
    MockSearchProvider,
    buscar,
)
from scripts.extracao_pje import gerar_manifesto
from scripts.extracao_pje.segmentar_documentos import segmentar_documentos
from scripts.extracao_pje.validar_integridade import validar_integridade
from scripts.extracao_pje.gerar_documentos import gerar_documentos
from scripts.triagem_pericial.gerar_delimitacao import gerar as gerar_delimitacao
from scripts.planejamento_pericial.gerar_processo import gerar as gerar_processo
from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.redacao_pericial.autocorrigir_redacao import autocorrigir


ROOT = Path(__file__).resolve().parents[1]


def _item(numero, destino, titulo="Documento"):
    return {
        "documento_id_interno": f"DOC-PJE-{numero:03d}",
        "id_pje": str(numero),
        "ordem_indice": numero,
        "pagina_destino_link": destino,
        "titulo_original": titulo,
        "tipo_original": titulo,
    }


def _pagina(numero):
    return {
        "pagina_pdf": numero,
        "possui_rodape_pje": False,
        "pagina_documento_detectada": None,
        "id_pje_detectado": None,
    }


class FinalDeltaR3Test(unittest.TestCase):
    def test_colisao_preserva_intervalo_e_contabilidade_exata_de_paginas(self):
        itens = [_item(1, 2), _item(2, 2), _item(3, 8)]
        segmentos = segmentar_documentos(itens, [_pagina(i) for i in range(1, 11)])
        conflito = next(s for s in segmentos if s["estado_item_indice"] == "CONFLITO_DESTINO")
        resolvido = next(s for s in segmentos if s["estado_item_indice"] == "SEGMENTADO")
        self.assertEqual((conflito["pagina_pdf_inicio"], conflito["pagina_pdf_fim"], conflito["total_paginas"]), (2, 7, 6))
        self.assertEqual([i["documento_id_interno"] for i in conflito["itens_colididos"]], ["DOC-PJE-001", "DOC-PJE-002"])
        self.assertEqual((resolvido["pagina_pdf_inicio"], resolvido["pagina_pdf_fim"], resolvido["total_paginas"]), (8, 10, 3))
        self.assertEqual(set(range(2, 8)) | set(range(8, 11)), set(range(2, 11)))

    def test_validator_detecta_perda_e_sobreposicao_de_pagina(self):
        manifesto = json.loads((ROOT / "tests/fixtures/pje/manifesto-minimo-valido.json").read_text(encoding="utf-8"))
        manifesto["arquivo"]["total_paginas"] = 4
        manifesto["indice"]["paginas"] = [1]
        manifesto["paginas"] = [copy.deepcopy(manifesto["paginas"][0]) for _ in range(4)]
        for numero, pagina in enumerate(manifesto["paginas"], 1):
            pagina["pagina_pdf"] = numero
        manifesto["documentos"][0].update(pagina_pdf_inicio=2, pagina_pdf_fim=3, total_paginas=2)
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("Página 4 sem owner" in erro for erro in erros), erros)
        manifesto["conflitos"].append({
            "conflito_id": "CON-PJE-001", "campo": "indice.pagina_destino_link", "tipo": "COLISAO_DESTINO",
            "descricao": "Intervalo conflitante", "valores_conflitantes": ["1", "2"], "fontes": [],
            "status": "ABERTO", "bloqueante": True, "decisao": None, "observacoes": None,
            "itens_indice_relacionados": [], "pagina_pdf_inicio": 3, "pagina_pdf_fim": 4, "total_paginas": 2,
        })
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("Página 3 com owners incompatíveis" in erro for erro in erros), erros)

    def test_conflito_resolvido_nao_duplica_owner_de_item_ou_pagina(self):
        manifesto=json.loads((ROOT/"tests/fixtures/pje/manifesto-minimo-valido.json").read_text(encoding="utf-8"))
        manifesto["conflitos"]=[{"conflito_id":"CON-PJE-001","campo":"indice.pagina_destino_link","tipo":"COLISAO_DESTINO","descricao":"Colisão resolvida por fonte primária","valores_conflitantes":["A","B"],"fontes":[],"status":"RESOLVIDO_POR_FONTE_PRIMARIA","bloqueante":True,"decisao":"Documento confirmado","observacoes":None,"itens_indice_relacionados":["DOC-PJE-001"],"pagina_pdf_inicio":2,"pagina_pdf_fim":3,"total_paginas":2}]
        manifesto["metricas_extracao"]["conflitos_abertos"]=1
        erros,_=validar_integridade(manifesto)
        self.assertFalse(any("mais de uma vez" in erro or "owners incompatíveis" in erro or "Status VALIDADO incompatível" in erro for erro in erros),erros)

    def test_colisao_bloqueia_todos_os_consumidores_sem_saida_parcial(self):
        manifesto = json.loads((ROOT / "tests/fixtures/pje/manifesto-minimo-valido.json").read_text(encoding="utf-8"))
        manifesto["status_validacao"]="BLOQUEADO"
        manifesto["conflitos"]=[{"conflito_id":"CON-PJE-001","campo":"indice.pagina_destino_link","tipo":"COLISAO_DESTINO","descricao":"Intervalo 2-7 não resolvido","valores_conflitantes":["A","B"],"fontes":[],"status":"ABERTO","bloqueante":True,"decisao":None,"observacoes":None,"itens_indice_relacionados":["DOC-PJE-001"],"pagina_pdf_inicio":2,"pagina_pdf_fim":7,"total_paginas":6}]
        with __import__("tempfile").TemporaryDirectory() as td:
            raiz=Path(td);(raiz/"manifesto-pje.json").write_text(json.dumps(manifesto),encoding="utf-8")
            saida=raiz/"saida"
            with self.assertRaises(ValueError):gerar_documentos(manifesto,raiz/"ausente.pdf",saida)
            with self.assertRaises(ValueError):gerar_delimitacao(raiz)
            with self.assertRaises(ValueError):gerar_processo(raiz)
            self.assertFalse((saida/"documentos").exists())

    def test_classificacao_e_prioridade_do_manifesto_nao_sao_placeholders(self):
        casos = {
            "Decisao": ("DECISAO", "A_ESSENCIAL"),
            "Peticao inicial": ("PETICAO_INICIAL", "A_ESSENCIAL"),
            "Parecer tecnico CREA 123": ("PARECER_TECNICO_PARTE", "A_ESSENCIAL"),
            "Peticao inicial com procuracao": ("NAO_CLASSIFICADO", "PENDENTE"),
        }
        for titulo, esperado in casos.items():
            with self.subTest(titulo=titulo):
                obtido = gerar_manifesto._classificacao_manifesto(titulo, titulo)
                self.assertEqual((obtido["classe_normalizada"], obtido["prioridade"]), esperado)

    def test_boundary_egress_exige_capability_explicita(self):
        class Local:
            EGRESS_CAPABILITY = "LOCAL_NO_EGRESS"
            def buscar(self, consulta):
                return [{"url": "https://www.gov.br/fonte", "consulta": consulta}]
        class Unknown:
            def buscar(self, consulta):
                return []
        self.assertEqual(len(buscar("fonte pública", Local())), 1)
        with self.assertRaises(PermissionError):
            buscar("fonte pública", Unknown())
        with self.assertRaises(PermissionError):
            buscar("fonte pública", AgentSearchProvider(lambda _: []))
        self.assertEqual(len(buscar("fonte pública", AgentSearchProvider(lambda _: [{"url": "https://www.gov.br/fonte"}]), EgressPolicy(permitir_egress=True))), 1)
        self.assertEqual(buscar("fonte pública", MockSearchProvider([])), [])
        recebido=[]
        class Externo:
            EGRESS_CAPABILITY="EXTERNAL_EGRESS"
            def buscar(self,consulta,politica):recebido.append(consulta);return []
        buscar("Maria Exemplo norma",Externo(),EgressPolicy(permitir_egress=True,autorizar_dados_caso=True,dados_sensiveis=("Maria Exemplo",)))
        self.assertEqual(recebido,["[DADO_REMOVIDO] norma"])

    def test_autocorrecao_editorial_preserva_blocos_e_claims_materiais(self):
        tipos = ["ABERTURA_GENERICA", "CONECTIVO_REPETITIVO", "TERMINOLOGIA_INSTAVEL", "TOM_PROFESSORAL", "CONCLUSAO_REPETIDA"]
        textos = [
            "É importante destacar que texto.",
            "Ademais, texto.",
            "Manifestação fissurativa.",
            "Para que o leitor compreenda, texto.",
            "Texto.\n\nTexto.",
        ]
        for titulo in ("Classificação", "Conclusão"):
            for tipo, texto in zip(tipos, textos):
                redacao = {"blocos": [{"pat_id": "PAT-001", "titulos": [titulo], "textos": [texto], "claim_ids": ["CLM-001"]}], "claims": [{"id": "CLM-001", "tipo": "ORIGEM" if titulo == "Classificação" else "CONCLUSAO_DE_QT", "texto_semantico": texto}]}
                corrigida, correcoes = autocorrigir(redacao, [{"tipo": tipo, "severidade": "EDITORIAL"}])
                self.assertEqual(corrigida["blocos"][0]["textos"][0], texto)
                self.assertEqual(corrigida["claims"][0]["texto_semantico"], texto)
                self.assertEqual(correcoes, [])
        redacao = {"blocos": [{"pat_id": "PAT-001", "titulos": ["Consequências"], "textos": [textos[0]], "claim_ids": ["CLM-001"]}], "claims": [{"id": "CLM-001", "tipo": "CONSEQUENCIA", "texto_semantico": textos[0]}]}
        corrigida, correcoes = autocorrigir(redacao, [{"tipo": tipos[0], "severidade": "EDITORIAL"}])
        self.assertNotEqual(corrigida["blocos"][0]["textos"][0], textos[0]); self.assertTrue(correcoes)
        for marcador in ({"tipo":"ORIGEM"},{"tipo":"OUTRO","material":True},{"tipo":"OUTRO","imutavel":True}):
            redacao={"blocos":[{"pat_id":"PAT-001","titulos":["Consequências"],"textos":[textos[0]],"claim_ids":["CLM-001"]}],"claims":[{"id":"CLM-001","texto_semantico":textos[0],**marcador}]}
            corrigida,correcoes=autocorrigir(redacao,[{"tipo":tipos[0],"severidade":"EDITORIAL"}])
            self.assertEqual(corrigida["blocos"][0]["textos"][0],textos[0]);self.assertEqual(correcoes,[])

    def test_pipeline_motor_reaudita_catalogo_autocorrigido_e_usa_estado_final(self):
        load=lambda p:json.loads((ROOT/p).read_text(encoding="utf-8"))
        processo=load("tests/fixtures/schemas/processo-valido.json");delim=load("tests/fixtures/triagem/delimitacao-minima-valida.json")
        plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json");vistoria=load("tests/fixtures/schemas/vistoria-valida.json")
        base=executar_pipeline_motor(processo,delim,plano,vistoria)["analise_inicial"]
        obs=next(e for e in base["catalogo_evidencias"] if e["id"].startswith("OBS-"))
        obs.update(resultado="OBSERVADO",aspectos_suportados=["FISSURA_PRESENTE"],aspectos_contraditos=[],auditoria_aspectos=[{"aspecto":"FISSURA_PRESENTE","polaridade":"NEGADO","aspectos_derivados_consultados":False}])
        norma={"id":"NOR-999","tipo":"NORMA","classe_probatoria":"EVIDENCIA_PRIMARIA","authority":"FONTE_OFICIAL_VERIFICADA","classificacao_fonte":"FONTE_SECUNDARIA","dominio_oficial":False,"status_verificacao":"PENDENTE_VERIFICACAO","aspectos_suportados":["REQUISITO_NORMATIVO_VERIFICADO","FISSURA_PRESENTE"],"aspectos_contraditos":[],"auditoria_aspectos":[],"proveniencia":["NOR-999"],"acessivel":True}
        base["catalogo_evidencias"].append(norma)
        if base.get("patologias"):
            base["patologias"][0].setdefault("analise_causal",{}).setdefault("fundamentos",[]).append("NOR-999")
        with patch("scripts.motor_vicios.pipeline.executar",return_value=base):
            resultado=executar_pipeline_motor(processo,delim,plano,vistoria)
        finais={e["id"]:e for e in resultado["analise_final"]["catalogo_evidencias"]}
        self.assertEqual(finais[obs["id"]]["resultado"],"NAO_CONSTATADO_NA_VISTORIA")
        self.assertNotIn("FISSURA_PRESENTE",finais["NOR-999"]["aspectos_suportados"])
        self.assertEqual(finais["NOR-999"]["authority"],"NAO_DETERMINADA")
        self.assertTrue(resultado["autocorrecoes"])
        alvo={"NEGACAO_CONVERTIDA_EM_FATO","OBS_NEGADA_COM_RESULTADO_OBSERVADO","NORMA_USADA_COMO_FATO_DO_CASO","AUTORIDADE_NORMATIVA_AUTODECLARADA"}
        self.assertFalse(alvo & {a["tipo"] for a in resultado["detector_final"]})
        self.assertTrue(resultado["trilha"]["correcoes"]);self.assertEqual(resultado["gate"],resultado["analise_final"]["gate_redacao"])

    def test_registry_exerce_todas_as_fixtures_pje(self):
        registry_path = ROOT / "tests/fixtures/pje-registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))["fixtures"]
        existentes = {p.name for p in (ROOT / "tests/fixtures/pje").glob("*.json")}
        registrados = {item["arquivo"] for item in registry}
        self.assertEqual(registrados, existentes)
        schemas = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "schemas").glob("*.schema.json")]
        recursos = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
        mapa = {"manifesto-pje.schema.json": "manifesto-pje.schema.json", "documento-pje.schema.json": "documento-pje.schema.json"}
        exercidas = set()
        for item in registry:
            self.assertTrue(item["finalidade"]); self.assertTrue(item["consumer"])
            schema = next(s for s in schemas if s["$id"].endswith(mapa[item["schema"]]))
            validador = validator_for(schema)(schema, registry=recursos, format_checker=FormatChecker())
            erros = list(validador.iter_errors(json.loads((ROOT / "tests/fixtures/pje" / item["arquivo"]).read_text(encoding="utf-8"))))
            self.assertEqual(not erros, item["expected"] == "VALID", item["arquivo"])
            exercidas.add(item["arquivo"])
        self.assertEqual(exercidas, registrados)


if __name__ == "__main__":
    unittest.main()
