"""Orquestração do parser e geração validada do manifesto PJe."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .diagnosticar_paginas import diagnosticar_paginas
from .extrair_capa import extrair_capa
from .extrair_indice import extrair_indice
from .extrair_links_indice import extrair_links_indice
from .leitor_pdf import LeitorPdf
from .reconciliar_indice import reconciliar_documento
from .segmentar_documentos import segmentar_documentos
from .validar_integridade import validar_integridade
from .classificar_documentos import classificar_documento,prioridade_documental

def _classificacao_manifesto(titulo,tipo):
    classificada=classificar_documento(titulo,tipo,f"{titulo} {tipo}")
    classe="NAO_CLASSIFICADO" if classificada["classe_normalizada"]=="OUTRO" else classificada["classe_normalizada"]
    return {**classificada,"classe_normalizada":classe,"prioridade":prioridade_documental(classe,classificada["status_revisao"])}

def _conflito_colisao(leitor,itens,inicio,fim=None,numero=None):
    if numero is None:
        numero,fim=fim,inicio
    fontes=[{"arquivo": leitor.caminho.name, "sha256": leitor.sha256, "pagina_pdf": i["pagina_origem_indice"], "pagina_documento": None, "pagina_original": None, "documento_id": i["documento_id_interno"], "id_pje": i["id_pje"], "trecho": i["texto_bruto"], "natureza":"DOCUMENTADO", "metodo_extracao": "TEXTO_DIGITAL", "confianca":i["confianca"], "status_verificacao":"VERIFICADO"} for i in itens]
    return {"conflito_id":f"CON-PJE-{numero:03d}","campo":"indice.pagina_destino_link","tipo":"COLISAO_DESTINO","descricao":"Mais de um item do índice aponta para o mesmo intervalo","valores_conflitantes":[i["id_pje"] for i in itens],"fontes":fontes,"status":"ABERTO","bloqueante":True,"decisao":None,"observacoes":f"Intervalo PDF {inicio}-{fim}","itens_indice_relacionados":[i["documento_id_interno"] for i in itens],"pagina_pdf_inicio":inicio,"pagina_pdf_fim":fim,"total_paginas":fim-inicio+1}
def _fonte_indice(leitor,item):
    return {"arquivo":leitor.caminho.name,"sha256":leitor.sha256,"documento_id":item["documento_id_interno"],"id_pje":item["id_pje"],"pagina_pdf":item["pagina_origem_indice"],"pagina_documento":None,"pagina_original":None,"trecho":item["texto_bruto"],"natureza":"DOCUMENTADO","metodo_extracao":"INDICE_PJE","confianca":item["confianca"],"status_verificacao":"VERIFICADO"}
def _fonte_rodape(leitor,pagina):
    return {"arquivo":leitor.caminho.name,"sha256":leitor.sha256,"documento_id":None,"id_pje":pagina["id_pje_detectado"],"pagina_pdf":pagina["pagina_pdf"],"pagina_documento":pagina["pagina_documento_detectada"],"pagina_original":None,"trecho":f'Num. {pagina["id_pje_detectado"]} - Pag. {pagina["pagina_documento_detectada"]}',"natureza":"DOCUMENTADO","metodo_extracao":"CAMPO_ESTRUTURADO","confianca":pagina["confianca"],"status_verificacao":"VERIFICADO"}
def _status_manifesto(erros,conflitos,pendencias):
    bloqueio=bool(erros) or any(c.get("bloqueante") and c.get("status")=="ABERTO" for c in conflitos) or any(p.get("bloqueante") and p.get("status")=="ABERTA" for p in pendencias)
    return "BLOQUEADO" if bloqueio else "VALIDADO"


def _validar_schema(manifesto, raiz):
    arquivos = [raiz / "schemas" / n for n in ("pje-comum.schema.json", "manifesto-pje.schema.json")]
    schemas = [json.loads(p.read_text(encoding="utf-8")) for p in arquivos]
    registro = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    erros = sorted(Draft202012Validator(schemas[1], registry=registro).iter_errors(manifesto), key=lambda e: list(e.path))
    if erros:
        raise ValueError("Manifesto inválido: " + "; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in erros[:10]))


def construir_manifesto(caminho_pdf, raiz_repositorio=None):
    raiz = Path(raiz_repositorio or Path(__file__).resolve().parents[2])
    with LeitorPdf(caminho_pdf) as leitor:
        paginas = diagnosticar_paginas(leitor)
        primeira_documental = next((p["pagina_pdf"] for p in paginas if p["possui_rodape_pje"]), leitor.total_paginas + 1)
        paginas_indice = list(range(1, primeira_documental)) or [1]
        links = extrair_links_indice(leitor, paginas_indice)
        itens = extrair_indice(leitor, paginas_indice, links)
        capa = extrair_capa(leitor, paginas_indice)
        segmentos = segmentar_documentos(itens, paginas)
        documentos = []
        conflitos = []
        colisoes_registradas=set()
        for conflito_capa in capa.get("conflitos",[]):
            conflitos.append({"conflito_id":f"CON-PJE-{len(conflitos)+1:03d}","campo":conflito_capa["campo"],"tipo":"DIVERGENCIA_CAPA","descricao":"Valores materialmente divergentes na capa PJe","valores_conflitantes":conflito_capa["valores"],"fontes":conflito_capa["fontes"],"status":"ABERTO","bloqueante":True,"decisao":None,"observacoes":None,"itens_indice_relacionados":[]})
        for seg in segmentos:
            item = seg.pop("item_indice")
            rodapes = seg.pop("rodapes")
            id_rodape = seg.pop("id_rodape")
            estado_item = seg.pop("estado_item_indice", "SEGMENTADO")
            if estado_item == "CONFLITO_DESTINO":
                itens_colididos=seg.pop("itens_colididos")
                chave_colisao=tuple(sorted(i["documento_id_interno"] for i in itens_colididos))
                if chave_colisao in colisoes_registradas:continue
                colisoes_registradas.add(chave_colisao)
                conflitos.append(_conflito_colisao(leitor,itens_colididos,seg["pagina_pdf_inicio"],seg["pagina_pdf_fim"],len(conflitos)+1))
                continue
            rec = reconciliar_documento({**seg, "id_rodape": id_rodape, "item_indice": item, "rodapes": rodapes})
            fatia = paginas[seg["pagina_pdf_inicio"] - 1:seg["pagina_pdf_fim"]]
            data_hora = None
            if item and item["data"] and item["hora"]:
                data_hora = f'{item["data"]}T{item["hora"]}-03:00'
            classificacao=_classificacao_manifesto(item["titulo_original"] if item else "Documento sem item no índice",item["tipo_original"] if item else "Não informado no índice")
            documentos.append({
                **seg, "titulo_original": item["titulo_original"] if item else "Documento sem item no índice",
                "tipo_original": item["tipo_original"] if item else "Não informado no índice",
                "classe_normalizada": classificacao["classe_normalizada"], "subclasse_normalizada": classificacao["subclasse_normalizada"],
                "prioridade": classificacao["prioridade"], "ordem_indice": item["ordem_indice"] if item else None,
                "data_hora": data_hora, "possui_texto": any(p["quantidade_caracteres"] > 0 for p in fatia),
                "possui_imagens": any(p["quantidade_imagens"] > 0 for p in fatia), "possui_tabelas": False,
                "possui_anexos_internos": False, "requer_ocr": any(p["requer_ocr"] for p in fatia),
                "confianca_segmentacao": rec["confianca"], "confianca_classificacao": classificacao["confianca_classificacao"],
                "status_reconciliacao": rec, "referencia_documento_pje": f'documentos/{seg["documento_id"]}.json',
            })
        for doc in documentos:
            if doc["status_reconciliacao"]["status"] == "CONFLITANTE":
                item=next(i for i in itens if i["documento_id_interno"]==doc["documento_id"]);pagina_rodape=next(p for p in paginas if p["pagina_pdf"]==doc["pagina_pdf_inicio"] and p.get("id_pje_detectado"))
                conflitos.append({"conflito_id": f"CON-PJE-{len(conflitos)+1:03d}", "campo": "id_pje", "tipo": "DIVERGENCIA_INDICE_RODAPE",
                                  "descricao": "ID do índice diverge do rodapé", "valores_conflitantes": [doc["status_reconciliacao"]["id_indice"], doc["status_reconciliacao"]["id_rodape"]],
                                  "fontes": [_fonte_indice(leitor,item),_fonte_rodape(leitor,pagina_rodape)], "status": "ABERTO", "bloqueante": True,
                                  "decisao": None, "observacoes": doc["documento_id"], "itens_indice_relacionados":[doc["documento_id"]]})
        pendencias = []
        if not capa["cnj_localizado"]:
            pendencias.append({"pendencia_id": "PEN-PJE-001", "campo": "processo.numero_cnj", "motivo_ausencia": "NAO_LOCALIZADO",
                               "descricao": "CNJ principal não localizado na capa ou índice", "bloqueante": True, "fontes": [], "status": "ABERTA", "itens_indice_relacionados":[]})
        contabilizados={d["documento_id"] for d in documentos if d.get("ordem_indice") is not None}|{x for c in conflitos for x in c.get("itens_indice_relacionados",[])}
        for item in itens:
            if item["documento_id_interno"] in contabilizados:continue
            pendencias.append({"pendencia_id":f"PEN-PJE-{len(pendencias)+1:03d}","campo":"indice.pagina_destino_link","motivo_ausencia":"NAO_LOCALIZADO","descricao":"Item do índice sem destino segmentável inequívoco","bloqueante":True,"fontes":[],"status":"ABERTA","itens_indice_relacionados":[item["documento_id_interno"]]})
        eventos = []
        if capa["ultima_distribuicao"]["valor"]:
            eventos.append({"evento_id": "EVE-001", "tipo": "OUTRO", "data": None, "hora": None,
                            "local": None, "valor": capa["ultima_distribuicao"]["valor"], "unidade": None,
                            "descricao": "Última distribuição registrada na capa do PJe",
                            "proveniencia": capa["ultima_distribuicao"]["proveniencia"],
                            "status_verificacao": "VERIFICADO"})
        met = {"documentos_indice": len(itens), "documentos_segmentados": len(documentos),
               "documentos_confirmados": sum(d["status_reconciliacao"]["status"] == "CONFIRMADO" for d in documentos),
               "paginas_com_rodape": sum(p["possui_rodape_pje"] for p in paginas),
               "paginas_sem_texto_util": sum(p["quantidade_caracteres"] == 0 for p in paginas),
               "paginas_candidatas_ocr": sum(p["requer_ocr"] for p in paginas), "conflitos_abertos": len(conflitos)}
        manifesto = {"schema_version": "1.1.0", "arquivo": {"nome": leitor.caminho.name, "sha256": leitor.sha256,
                     "total_paginas": leitor.total_paginas, "data_exportacao": None}, "processo": capa["processo"],
                     "pessoas": [], "vinculos_processuais": [], "representacoes": [],
                     "indice": {"paginas": paginas_indice, "itens": itens, "possui_links_internos": bool(links),
                                "confianca": {"nivel": "BAIXA" if not itens or any(i["confianca"]["nivel"]=="BAIXA" for i in itens) else "MEDIA" if any(i["confianca"]["nivel"]=="MEDIA" for i in itens) else "ALTA"}},
                     "documentos": documentos, "paginas": paginas, "eventos": eventos, "conflitos": conflitos,
                     "pendencias": pendencias, "metricas_extracao": met, "status_validacao": "RASCUNHO"}
        erros, alertas = validar_integridade(manifesto)
        manifesto["status_validacao"]=_status_manifesto(erros,conflitos,pendencias)
        _validar_schema(manifesto, raiz)
        return manifesto, erros, alertas


def salvar_manifesto(manifesto, diretorio, sobrescrever=False):
    destino = Path(diretorio) / "manifesto-pje.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and not sobrescrever:
        raise FileExistsError(f"Resultado já existe: {destino}. Use --sobrescrever conscientemente.")
    destino.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return destino
