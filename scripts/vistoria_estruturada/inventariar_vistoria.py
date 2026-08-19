"""Inventaria arquivos privados de vistoria de forma incremental, sem interpretar causalidade."""

from __future__ import annotations
import argparse
import csv
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

IMAGENS={".jpg",".jpeg",".png",".tif",".tiff",".heic"}; VIDEOS={".mp4",".mov",".avi",".mkv",".m4v"}
TEXTOS={".txt",".md"}; DADOS={".json",".csv",".xlsx"}
DOCUMENTOS={".pdf",".doc",".docx",".docm",".odt"}

def agora(): return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
def sha256(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def categoria(p):
    e=p.suffix.lower(); base="/".join(x.lower() for x in p.parts)
    if e in IMAGENS:return "FOTOGRAFIA"
    if e in VIDEOS:return "VIDEO"
    if e in DOCUMENTOS:return "DOCUMENTO"
    if "medic" in base:return "MEDICAO"
    if e in TEXTOS|DADOS:return "ANOTACAO"
    if "document" in base:return "DOCUMENTO"
    return "OUTRO"

def _xlsx(p):
    with zipfile.ZipFile(p) as z:
        shared=[]
        if "xl/sharedStrings.xml" in z.namelist():
            root=ElementTree.fromstring(z.read("xl/sharedStrings.xml")); shared=["".join(t.text or "" for t in x.iter() if t.tag.endswith("}t")) for x in root]
        vals=[]
        for n in z.namelist():
            if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"):
                root=ElementTree.fromstring(z.read(n))
                for c in (x for x in root.iter() if x.tag.endswith("}c")):
                    v=next((x.text for x in c if x.tag.endswith("}v")),None)
                    if v is not None: vals.append(shared[int(v)] if c.attrib.get("t")=="s" and int(v)<len(shared) else v)
        return "\n".join(vals)

def texto(p):
    e=p.suffix.lower()
    if e in TEXTOS:return p.read_text(encoding="utf-8",errors="replace"),"TEXTO_SIMPLES"
    if e==".json":return json.dumps(json.loads(p.read_text(encoding="utf-8")),ensure_ascii=False),"JSON"
    if e==".csv":
        with p.open(encoding="utf-8-sig",errors="replace",newline="") as f:return "\n".join(" | ".join(r) for r in csv.reader(f)),"CSV"
    if e==".xlsx":return _xlsx(p),"XLSX_OOXML"
    return None,"METADADOS_ARQUIVO"

def exif(p):
    meta={"data_hora_captura":None,"orientacao":None,"coordenadas":None,"texto_original":None,"exif_bruto":{}}
    if p.suffix.lower() not in IMAGENS:return meta,"METADADOS_ARQUIVO"
    try:
        from PIL import Image, ExifTags
        with Image.open(p) as im:
            bruto_exif=im.getexif();dados={ExifTags.TAGS.get(k,k):v for k,v in bruto_exif.items()}
            gps=bruto_exif.get_ifd(ExifTags.IFD.GPSInfo) if hasattr(ExifTags,"IFD") else {}
        meta["exif_bruto"]={str(ExifTags.TAGS.get(k,k)):str(v) for k,v in bruto_exif.items()}
        bruto=dados.get("DateTimeOriginal") or dados.get("DateTime")
        if bruto: meta["data_hora_captura"]=datetime.strptime(str(bruto),"%Y:%m:%d %H:%M:%S").astimezone().isoformat()
        if dados.get("Orientation") is not None:meta["orientacao"]=str(dados["Orientation"])
        def grau(v): return float(v[0])+float(v[1])/60+float(v[2])/3600
        if gps and 2 in gps and 4 in gps:
            lat,lon=grau(gps[2]),grau(gps[4])
            if gps.get(1)=="S":lat=-lat
            if gps.get(3)=="W":lon=-lon
            meta["coordenadas"]={"latitude":lat,"longitude":lon}
        return meta,"EXIF"
    except Exception:return meta,"METADADOS_ARQUIVO"

def inventariar(diretorio:Path, destino:Path|None=None):
    destino=destino or diretorio/"inventario-vistoria.json"
    antigo=json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {"arquivos":[]}
    por_hash={x["sha256"]:x for x in antigo["arquivos"]}; itens=[]
    proximo=max([int(x["id"].rsplit("-",1)[1]) for x in antigo["arquivos"]] or [0])+1
    fontes=[p for p in sorted(diretorio.rglob("*")) if p.is_file() and p.resolve()!=destino.resolve()]
    for p in fontes:
        h=sha256(p)
        if h in por_hash:
            x=dict(por_hash[h]);x["acao_processamento"]="REUTILIZADO";itens.append(x);continue
        txt,met=texto(p); meta,met_exif=exif(p)
        if txt is not None:meta["texto_original"]=txt
        metodo=met_exif if met_exif=="EXIF" else met
        # Documentos de campo são preservados por metadados nesta etapa, ainda
        # que sua extração semântica pertença a outro boundary.
        suportado=p.suffix.lower() in IMAGENS|VIDEOS|TEXTOS|DADOS|DOCUMENTOS
        novo={"id":f"ARQ-VIS-{proximo:03d}","nome":p.name,"caminho_relativo":p.relative_to(diretorio).as_posix(),"sha256":h,"extensao":p.suffix.lower(),"tamanho_bytes":p.stat().st_size,"data_processamento":agora(),"data_arquivo":datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).astimezone().isoformat(timespec="seconds"),"categoria":categoria(p),"metodo_ingestao":metodo,"metadados":meta,"confianca":{"nivel":"ALTA" if txt is not None or met_exif=="EXIF" else "MEDIA"},"status":"EXTRAIDO" if txt is not None else "METADADOS_PARCIAIS" if suportado else "FORMATO_NAO_SUPORTADO","acao_processamento":"PROCESSADO"}
        itens.append(novo);por_hash[h]=novo;proximo+=1
    obj={"schema_version":"1.0.0","processo":diretorio.name,"gerado_em":agora(),"arquivos":itens,"status":"INVENTARIADO" if itens else "SEM_DADOS_DE_VISTORIA"}
    destino.parent.mkdir(parents=True,exist_ok=True);destino.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");return obj

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("diretorios",nargs="+",type=Path)
    for d in p.parse_args().diretorios: print(json.dumps({"diretorio":str(d),"arquivos":len(inventariar(d)["arquivos"])},ensure_ascii=False))
    return 0
if __name__=="__main__":raise SystemExit(main())
