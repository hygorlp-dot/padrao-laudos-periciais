"""Catálogo geométrico de imagens incorporadas, sem OCR ou interpretação pericial."""
import re
from .extrair_blocos_texto import bbox,proveniencia,referencia_pagina
ROTULO_FOTO=re.compile(r"\b(Foto(?:grafia)?|Figura|FIG\.)\s*([0-9]+)?",re.I)
def _rotulos(pagina):
    palavras=sorted(pagina.extract_words() or [],key=lambda w:(float(w["top"]),float(w["x0"])))
    saida=[]
    for i,p in enumerate(palavras):
        texto=str(p.get("text",""));seguinte=palavras[i+1] if i+1<len(palavras) else None
        combinado=texto+(" "+str(seguinte.get("text","")) if seguinte and str(seguinte.get("text","" )).isdigit() and abs(float(seguinte["top"])-float(p["top"]))<5 else "")
        m=ROTULO_FOTO.search(combinado)
        if m:saida.append({"texto":m.group(0),"numero":m.group(2),"x0":float(p["x0"]),"x1":float((seguinte or p)["x1"]),"top":float(p["top"]),"bottom":float(p["bottom"])})
    return saida
def _associar(imagem,rotulos):
    candidatos=[]
    for r in rotulos:
        distancia=float(r["top"])-float(imagem["bottom"]);sobreposicao=min(float(imagem["x1"]),r["x1"])-max(float(imagem["x0"]),r["x0"])
        if -10<=distancia<=60 and sobreposicao>=0:candidatos.append((abs(distancia),abs(float(imagem["x0"])-r["x0"]),r))
    if not candidatos:return None
    candidatos=sorted(candidatos,key=lambda x:(x[0],x[1],x[2]["texto"]))
    if len(candidatos)>1 and candidatos[1][:2]==candidatos[0][:2]:return None
    return candidatos[0][2]
def catalogar_imagens(leitor,pagina_pdf,pagina_documento,contexto,inicio_imagem,inicio_foto):
    pagina=leitor.pagina_geometrica(pagina_pdf);rotulos=_rotulos(pagina);imagens=[];fotos=[];area=max(float(pagina.width*pagina.height),1.0)
    registros=[]
    for img in pagina.images:
        largura,altura=float(img["x1"]-img["x0"]),float(img["bottom"]-img["top"]);registros.append((img,largura,altura,largura*altura/area>=.05))
    escolhas={id(img):_associar(img,rotulos) if relevante else None for img,_,_,relevante in registros};usos={id(r):sum(escolhas[id(img)] is r for img,_,_,_ in registros) for r in rotulos}
    for deslocamento,(img,largura,altura,relevante) in enumerate(registros):
        rotulo=escolhas[id(img)];seguro=bool(rotulo and relevante and usos[id(rotulo)]==1);tipo="FOTOGRAFIA" if seguro else "OUTRO";nivel,score=(("ALTA",.9) if seguro else ("BAIXA",.4));caixa=bbox(img["x0"],img["top"],img["x1"],img["bottom"]);prov=proveniencia(contexto,pagina_pdf,pagina_documento,rotulo["texto"] if seguro else None,"CAMPO_ESTRUTURADO",nivel,caixa)
        imagens.append({"imagem_id":f"IMG-{inicio_imagem+deslocamento:03d}","pagina":referencia_pagina(pagina_pdf,pagina_documento),"bbox":caixa,"tipo":tipo,"largura":largura,"altura":altura,"tipo_provavel":tipo,"descricao":None,"proveniencia":prov,"confianca":{"nivel":nivel,"score":score}})
        if seguro:fotos.append({"fotografia_id":f"FOT-{inicio_foto+len(fotos):03d}","numero_original":rotulo["numero"],"rotulo_original":rotulo["texto"],"legenda":None,"pagina_pdf":pagina_pdf,"pagina_documento":pagina_documento,"pagina_original":None,"bbox":caixa,"ambiente":None,"sistema":None,"descricao":None,"data_hora":None,"coordenadas":None,"documento_pai":contexto["documento_id"],"proveniencia":prov,"confianca":{"nivel":"ALTA","score":.9}})
    return imagens,fotos
