import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.planejamento_pericial.gerar_processo import gerar as gerar_processo
from scripts.planejamento_pericial.validar_plano import recalcular_execucao
from scripts.triagem_pericial import gerar_delimitacao


ROOT=Path(__file__).resolve().parents[1]
load=lambda p:json.loads((ROOT/p).read_text(encoding="utf-8"))


class ClaudeTerminalContinuation(unittest.TestCase):
    def test_delimitacao_bloqueada_nao_atravessa_para_processo(self):
        manifesto=load("tests/fixtures/pje/manifesto-minimo-valido.json")
        base=load("tests/fixtures/triagem/delimitacao-minima-valida.json")
        variantes=[]
        baixa=copy.deepcopy(base);baixa["tipo_pericia"]["confianca"]={"nivel":"BAIXA","score":0.2};baixa["status"]="BLOQUEADO";variantes.append(baixa)
        sem_fonte=copy.deepcopy(base);sem_fonte["tema_controvertido"]["documentos_fonte"]=[];sem_fonte["status"]="BLOQUEADO";variantes.append(sem_fonte)
        conflito=copy.deepcopy(base);conflito["conflitos"]=[{"id":"CNF-001","tipo":"ESCOPO","descricao":"Conflito","fontes":["DOC-PJE-001","DOC-PJE-002"],"classificacao":"BLOQUEANTE","status":"ABERTO","decisao":None}];conflito["status"]="BLOQUEADO";variantes.append(conflito)
        auditada=copy.deepcopy(base);auditada["autoauditoria"][0]["resultado"]="BLOQUEADO";auditada["status"]="BLOQUEADO";variantes.append(auditada)
        for delimitacao in variantes:
            with self.subTest(motivo=delimitacao.get("conflitos") or delimitacao["tipo_pericia"]["confianca"]):
                with tempfile.TemporaryDirectory() as td:
                    pasta=Path(td);(pasta/"manifesto-pje.json").write_text(json.dumps(manifesto),encoding="utf-8")
                    with patch("scripts.planejamento_pericial.gerar_processo.gerar_delimitacao",return_value=delimitacao):
                        with self.assertRaises(ValueError):gerar_processo(pasta)
                    self.assertFalse((pasta/"processo.json").exists())

    def test_catalogo_final_preserva_declaracoes_sem_promove_las(self):
        processo=load("tests/fixtures/schemas/processo-valido.json");delim=load("tests/fixtures/triagem/delimitacao-minima-valida.json")
        plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json");vistoria=load("tests/fixtures/schemas/vistoria-valida.json")
        vistoria["declaracoes"]=[
            {"id":"DEC-VIS-001","natureza":"DECLARADO_PELA_PARTE","declarante":None,"texto_original":"Há fissura.","questoes":["QT-001"],"alegacoes":[],"proveniencia":["ARQ-VIS-001"]},
            {"id":"DEC-VIS-002","natureza":"DECLARADO_POR_TERCEIRO","declarante":None,"texto_original":"Não há fissura.","questoes":["QT-001"],"alegacoes":[],"proveniencia":["ARQ-VIS-001"]},
        ]
        resultado=executar_pipeline_motor(processo,delim,plano,vistoria)
        catalogo={e["id"]:e for e in resultado["analise_final"]["catalogo_evidencias"]}
        self.assertTrue({"OBS-001","DEC-VIS-001","DEC-VIS-002"}<=set(catalogo))
        self.assertTrue(all(catalogo[i]["classe_probatoria"]!="EVIDENCIA_PRIMARIA" for i in ("DEC-VIS-001","DEC-VIS-002")))
        self.assertTrue(all(c.get("evidencia_id") in catalogo for c in resultado["claims_finais"] if c.get("evidencia_id")))
        rerun=executar_pipeline_motor(processo,delim,plano,vistoria)
        self.assertEqual([e["id"] for e in resultado["analise_final"]["catalogo_evidencias"]],[e["id"] for e in rerun["analise_final"]["catalogo_evidencias"]])

        sem_observacao=copy.deepcopy(vistoria);sem_observacao["observacoes"]=[]
        bloqueado=executar_pipeline_motor(processo,delim,plano,sem_observacao)
        catalogo_bloqueado={e["id"]:e for e in bloqueado["analise_final"]["catalogo_evidencias"]}
        self.assertEqual(bloqueado["gate"],"BLOQUEADO_PARA_REDACAO")
        self.assertTrue({"DEC-VIS-001","DEC-VIS-002"}<=set(catalogo_bloqueado))
        self.assertTrue(all(catalogo_bloqueado[i]["classe_probatoria"]!="EVIDENCIA_PRIMARIA" for i in ("DEC-VIS-001","DEC-VIS-002")))

    def test_causa_juridica_nao_vira_componente_tecnico(self):
        casos={
            "Qual o valor da causa e há prescrição?":"MATERIA_JURIDICA",
            "A ré deve ser responsabilizada por causa do inadimplemento contratual?":"MATERIA_JURIDICA",
            "A causa de pedir autoriza indenização?":"MATERIA_JURIDICA",
            "Qual a causa da fissura observada?":"PERTINENTE_TECNICO",
            "Está caracterizada a culpa da construtora pela manifestação de vícios?":"PERTINENTE_PARCIAL",
        }
        for texto,esperado in casos.items():
            with self.subTest(texto=texto):self.assertEqual(gerar_delimitacao._classificar_pertinencia(texto,False),esperado)

    def test_equivalencia_medicao_recalculada_sem_autodeclaracao(self):
        planejada={"id":"MED-PLANO-001","grandeza":"abertura de fissura","local":"Sala","criterio":"resultado em mm","questoes_tecnicas":["QT-001"]}
        plano={"medicoes":[planejada],"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"MEDICAO","obrigatoriedade":"OBRIGATORIA","item_planejado":"MED-PLANO-001"}]}
        def vistoria(grandeza="abertura de fissura",unidade="mm",valor=0.2,qt="QT-001",local="Sala",observacoes=None):
            med={"id":"MED-001","medicao_planejada":None,"grandeza":grandeza,"valor":valor,"unidade":unidade,"local":local,"questoes":[qt],"observacoes":["OBS-001"] if observacoes is None else observacoes,"metodo":"paquímetro"}
            return {"medicoes":[med],"cobertura":[{"tipo":"MEDICAO","planejado":"MED-PLANO-001","status":"SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE","executado":[],"evidencia_equivalente":["MED-001"],"equivalencia":{"requisito_original":"MED-PLANO-001","tipo_evidencia":"MEDICAO","capability":"abertura de fissura","metodo_substituto":"paquímetro"},"justificativa_equivalencia":"medição substituta rastreada"}]}
        self.assertTrue(recalcular_execucao(plano,vistoria())["apto"])
        for dado in (vistoria("umidade","%"),vistoria(unidade="cm"),vistoria(valor=None),vistoria(qt="QT-999"),vistoria(local="Cobertura"),vistoria(observacoes=[])):
            with self.subTest(dado=dado["medicoes"][0]):self.assertFalse(recalcular_execucao(plano,dado)["apto"])

    def test_zero_requisitos_tem_diagnostico_estruturado(self):
        resultado=recalcular_execucao({"requisitos_cobertura":[]},{"cobertura":[]})
        self.assertFalse(resultado["apto"]);self.assertTrue(resultado["faltantes"]);self.assertEqual(resultado["faltantes"][0]["motivo"],"SEM_REQUISITOS_COBERTURA")


if __name__=="__main__":unittest.main()
