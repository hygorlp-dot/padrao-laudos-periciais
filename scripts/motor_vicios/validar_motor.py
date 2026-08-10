"""Valida schema e relações essenciais do resultado do motor."""
import argparse,json
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
from referencing import Registry,Resource

RAIZ=Path(__file__).resolve().parents[2]
def validar(obj, processo=None, delimitacao=None, plano=None, vistoria=None, normas=None, ressalvas=None):
    nomes=("pje-comum.schema.json","patologia.schema.json","analise-motor-vicios.schema.json");ss=[json.loads((RAIZ/"schemas"/n).read_text(encoding="utf-8")) for n in nomes];reg=Registry().with_resources((s["$id"],Resource.from_contents(s)) for s in ss);erros=[e.message for e in Draft202012Validator(ss[-1],registry=reg,format_checker=FormatChecker()).iter_errors(obj)]
    ids={p["id"] for p in obj.get("patologias",[])}
    conjuntos={
        "ALG":{x["id"] for x in (processo or {}).get("alegacoes",[])},
        "QT":{x["id"] for x in (delimitacao or {}).get("questoes_tecnicas",[])},
        "QUE":{x["id"] for x in (delimitacao or {}).get("quesitos",[])},
        "OBS":{x["id"] for x in (vistoria or {}).get("observacoes",[])},
        "FOT":{x["id"] for x in (vistoria or {}).get("fotografias",[])},
        "MED":{x["id"] for x in (vistoria or {}).get("medicoes",[])},
        "HIP":{x["id"] for x in obj.get("hipoteses",[])},
        "NOR":{x["id"] for x in (normas or [])},
        "RES":{x["id"] for x in (ressalvas or [])}}
    fornecidos={"ALG":processo is not None,"QT":delimitacao is not None,"QUE":delimitacao is not None,"OBS":vistoria is not None,"FOT":vistoria is not None,"MED":vistoria is not None,"HIP":True,"NOR":normas is not None,"RES":ressalvas is not None}
    def conferir(valores,prefixo,dono):
        if fornecidos[prefixo] and set(valores)-conjuntos[prefixo]:erros.append(f"{dono}: referência {prefixo} órfã")
    for pat in obj.get("patologias",[]):
        conferir(pat.get("alegacoes_relacionadas",[]),"ALG",pat["id"]);conferir(pat.get("constatacoes",[]),"OBS",pat["id"]);conferir(pat.get("medicoes",[]),"MED",pat["id"]);conferir(pat.get("constatacao",{}).get("fotografias",[]),"FOT",pat["id"]);conferir(pat.get("hipoteses",[]),"HIP",pat["id"]);conferir([n.get("id") for n in pat.get("normas_relacionadas",[])],"NOR",pat["id"])
    for q in obj.get("questoes_saneadas",[]):
        if set(q["patologias"])-ids:erros.append(f"{q['id']}: PAT inexistente")
        conferir([q.get("id")],"QT",q.get("id","QT"));conferir(q.get("quesitos",[]),"QUE",q.get("id","QT"));conferir(q.get("hipoteses",[]),"HIP",q.get("id","QT"));conferir(q.get("normas",[]),"NOR",q.get("id","QT"))
    for q in obj.get("cobertura_quesitos",[]):conferir([q.get("quesito")],"QUE",q.get("quesito","QUE"));conferir(q.get("questoes",[]),"QT",q.get("quesito","QUE"))
    if obj.get("gate_redacao")!="BLOQUEADO_PARA_REDACAO" and any(a["bloqueante"] for a in obj.get("autoauditoria",[])):erros.append("gate apto com achado bloqueante")
    return erros
def main():
    p=argparse.ArgumentParser();p.add_argument("arquivos",nargs="+",type=Path);falhas=0
    for f in p.parse_args().arquivos:
        e=validar(json.loads(f.read_text(encoding="utf-8")));print(("APROVADO" if not e else "FALHA")+f": {f}");
        if e:falhas+=1;print("\n".join("- "+x for x in e))
    return bool(falhas)
if __name__=="__main__":raise SystemExit(main())
