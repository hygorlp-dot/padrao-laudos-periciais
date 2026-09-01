"""Geração determinística de um DOCUMENTO_PJE para cada item do manifesto."""

import json
from collections import Counter
from pathlib import Path

from .catalogar_imagens import catalogar_imagens
from .classificar_documentos import classificar_documento,prioridade_documental
from .detectar_secoes_internas import criar_subdocumentos, detectar_secoes
from .extrair_blocos_texto import extrair_pagina_e_blocos, proveniencia, referencia_pagina
from .extrair_tabelas_documento import extrair_tabelas
from .leitor_pdf import LeitorPdf
from .validar_documento import criar_validador, validar_documento


def gerar_documentos(manifesto, caminho_pdf, diretorio_saida, sobrescrever=False, raiz_repositorio=None):
    from .validar_integridade import validar_integridade
    erros_manifesto,_=validar_integridade(manifesto)
    if manifesto.get("status_validacao")!="VALIDADO" or erros_manifesto:
        raise ValueError("Manifesto PJe não validado; geração de documentos bloqueada")
    saida = Path(diretorio_saida)
    documentos_dir = saida / "documentos"
    if documentos_dir.exists() and any(documentos_dir.glob("*.json")) and not sobrescrever:
        raise FileExistsError(f"Documentos já existem em {documentos_dir}. Use --sobrescrever conscientemente.")
    documentos_dir.mkdir(parents=True, exist_ok=True)
    if sobrescrever:
        # Remove somente derivados com o padrão controlado, dentro do diretório
        # de saída explicitamente selecionado. O PDF original nunca é tocado.
        for obsoleto in documentos_dir.glob("DOC-PJE-*.json"):
            obsoleto.unlink()
    validador = criar_validador(raiz_repositorio)
    resultados, erros_globais, alertas_globais = [], [], []
    with LeitorPdf(caminho_pdf) as leitor:
        if leitor.sha256 != manifesto["arquivo"]["sha256"]:
            raise ValueError("SHA-256 do PDF diverge do manifesto; geração bloqueada")
        contexto_base = {"arquivo": leitor.caminho.name, "sha256": leitor.sha256}
        for base in manifesto["documentos"]:
            if base["status_reconciliacao"]["status"] in {"CONFLITANTE", "NAO_LOCALIZADO"}:
                erros_globais.append(f"{base['documento_id']}: reconciliação bloqueia geração")
                continue
            contexto = {**contexto_base, "documento_id": base["documento_id"], "id_pje": base["id_pje"]}
            paginas, blocos, tabelas, imagens, fotos, textos = [], [], [], [], [], []
            for pdf in range(base["pagina_pdf_inicio"], base["pagina_pdf_fim"] + 1):
                diag = manifesto["paginas"][pdf - 1]
                interna = diag["pagina_documento_detectada"]
                texto, novos_blocos = extrair_pagina_e_blocos(leitor, pdf, interna, contexto, len(blocos) + 1)
                novas_tabelas = extrair_tabelas(leitor, pdf, interna, contexto, len(tabelas) + 1)
                novas_imagens, novas_fotos = catalogar_imagens(leitor, pdf, interna, contexto, len(imagens) + 1, len(fotos) + 1)
                textos.append((pdf, interna, texto)); blocos.extend(novos_blocos); tabelas.extend(novas_tabelas)
                imagens.extend(novas_imagens); fotos.extend(novas_fotos)
                paginas.append({"referencia": referencia_pagina(pdf, interna), "classificacao": diag["classificacao"],
                                "texto_bruto": texto, "metodo_extracao": "TEXTO_DIGITAL",
                                "quantidade_caracteres": len(texto), "possui_texto_util": bool(texto.strip()),
                                "possui_imagens": bool(novas_imagens), "possui_tabelas": bool(novas_tabelas),
                                "requer_ocr": diag["requer_ocr"], "confianca": diag["confianca"]})
            secoes = detectar_secoes(textos, contexto)
            subdocumentos = criar_subdocumentos(secoes, base["documento_id"], paginas)
            classificacao = classificar_documento(base["titulo_original"], base["tipo_original"], textos[0][2], secoes)
            fonte = proveniencia(contexto, base["pagina_pdf_inicio"], paginas[0]["referencia"]["pagina_documento"],
                                 base["titulo_original"], "INDICE_PJE", "ALTA")
            alertas = []
            if classificacao["status_revisao"] == "PENDENTE_REVISAO":
                alertas.append({"alerta_id": "ALT-001", "tipo": "CLASSIFICACAO_PENDENTE_REVISAO",
                                "descricao": "; ".join(classificacao["criterios_classificacao"]), "bloqueante": False,
                                "proveniencia": fonte})
            doc = {"schema_version": "1.0.0", "documento_id": base["documento_id"], "id_pje": base["id_pje"],
                   "processo_cnj": manifesto["processo"]["numero_cnj"]["valor"], "titulo_original": base["titulo_original"],
                   "tipo_original": base["tipo_original"], **classificacao, "prioridade": prioridade_documental(classificacao["classe_normalizada"],classificacao["status_revisao"]),
                   "ordem_indice": base["ordem_indice"], "data_hora": base["data_hora"], "paginas": paginas,
                   "secoes": secoes, "subdocumentos": subdocumentos, "blocos_texto": blocos, "tabelas": tabelas,
                   "imagens": imagens, "fotografias": fotos, "eventos": [], "quesitos": [], "alegacoes": [],
                   "entidades": [], "referencias_normativas": [], "fontes": [fonte], "conflitos": [], "alertas": alertas,
                   "status_reconciliacao": base["status_reconciliacao"], "status_validacao": "RASCUNHO"}
            base_validacao = {**base, "_paginas_manifesto": manifesto["paginas"],
                              "_processo_cnj": manifesto["processo"]["numero_cnj"]["valor"],
                              "_arquivo": manifesto["arquivo"]}
            erros, avisos = validar_documento(doc, base_validacao, validador)
            doc["status_validacao"] = "BLOQUEADO" if erros else "VALIDADO"
            # O status não participa das regras relacionais; valida-se novamente
            # o objeto final para impedir divergência após sua definição.
            erros_finais, _ = validar_documento(doc, base_validacao, validador)
            erros = list(dict.fromkeys(erros + erros_finais))
            destino = documentos_dir / f'{base["documento_id"]}.json'
            destino.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            resultados.append({"documento": doc, "destino": destino, "erros": erros, "alertas": avisos})
            erros_globais.extend(f"{base['documento_id']}: {e}" for e in erros)
            alertas_globais.extend(f"{base['documento_id']}: {a}" for a in avisos)
    relatorio = _relatorio(resultados, manifesto, erros_globais, alertas_globais)
    (saida / "relatorio-revisao-documentos.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return relatorio


def _relatorio(resultados, manifesto, erros, alertas):
    documentos = [r["documento"] for r in resultados]
    classes = Counter(d["classe_normalizada"] for d in documentos)
    confiancas = Counter(d["confianca_classificacao"]["nivel"] for d in documentos)
    revisao = [{"documento_id": d["documento_id"], "id_pje": d["id_pje"], "titulo_original": d["titulo_original"],
               "classe": d["classe_normalizada"], "confianca": d["confianca_classificacao"]["nivel"],
               "criterios": d["criterios_classificacao"]} for d in documentos
              if d["classe_normalizada"] == "OUTRO" or d["confianca_classificacao"]["nivel"] == "BAIXA"
              or d["status_revisao"] == "PENDENTE_REVISAO"]
    return {"documentos_esperados": len(manifesto["documentos"]), "documentos_gerados": len(documentos),
            "documentos_validos": sum(d["status_validacao"] == "VALIDADO" for d in documentos),
            "paginas_processadas": sum(len(d["paginas"]) for d in documentos),
            "tabelas_detectadas": sum(len(d["tabelas"]) for d in documentos),
            "imagens_catalogadas": sum(len(d["imagens"]) for d in documentos),
            "fotografias_detectadas": sum(len(d["fotografias"]) for d in documentos),
            "secoes_detectadas": sum(len(d["secoes"]) for d in documentos),
            "subdocumentos_detectados": sum(len(d["subdocumentos"]) for d in documentos),
            "distribuicao_classes": dict(sorted(classes.items())), "distribuicao_confianca": dict(sorted(confiancas.items())),
            "casos_revisao": revisao, "erros": erros, "alertas": alertas}
