"""Inventaria referências privadas e gera conhecimento derivado incremental."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader


EXTENSOES = {".pdf", ".docx", ".docm"}
VERSAO_EXTRATOR = "1.2.0"
SISTEMAS = {
    "REVESTIMENTOS": ("revestimento", "ceram", "argamassa", "aderencia"),
    "VEDACOES": ("vedacao", "alvenaria", "fissura", "trinca"),
    "IMPERMEABILIZACAO": ("impermeabil", "umidade", "infiltr"),
    "ESQUADRIAS": ("esquadria", "janela", "porta"),
    "ESTRUTURA": ("estrutura", "concreto", "fundacao"),
    "INSTALACOES_ELETRICAS": ("eletrica", "instalacoes eletricas"),
    "INSTALACOES_HIDROSSANITARIAS": ("hidrossanit", "esgoto", "agua fria"),
    "AVALIACAO_IMOBILIARIA": ("avaliacao", "valor de mercado", "imovel urbano"),
    "ENGENHARIA_RODOVIARIA": ("rodovia", "pavimento", "sinalizacao viaria"),
}


def agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def hash_arquivo(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def extrair_texto(caminho: Path) -> tuple[list[str], str]:
    if caminho.suffix.lower() == ".pdf":
        leitor = PdfReader(caminho)
        return [(pagina.extract_text() or "") for pagina in leitor.pages], "PYPDF_TEXTO_DIGITAL"
    with zipfile.ZipFile(caminho) as pacote:
        xml = pacote.read("word/document.xml")
    raiz = ElementTree.fromstring(xml)
    textos = [item.text for item in raiz.iter() if item.tag.endswith("}t") and item.text]
    return ["\n".join(textos)], "OOXML_DOCUMENT_XML"


def normalizar(texto: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def tipo_provavel(texto: str, categoria: str) -> tuple[str, dict]:
    base = normalizar(texto[:300000])
    placar = {nome: sum(1 for termo in termos if termo in base) for nome, termos in SISTEMAS.items()}
    tipo = max(placar, key=placar.get) if max(placar.values(), default=0) else ("NORMA_TECNICA" if categoria != "MODELO_REFERENCIAL" else "OUTRO")
    nivel = "ALTA" if placar.get(tipo, 0) >= 3 else "MEDIA" if placar.get(tipo, 0) else "BAIXA"
    return tipo, {"nivel": nivel}


def metadados_norma(nome: str, pasta: str) -> tuple[str | None, str | None, str | None]:
    entidade = "ABNT" if pasta == "abnt" else pasta.upper() if pasta != "literatura-tecnica" else None
    numero = None
    edicao = None
    m = re.search(r"(?i)NBR\s*([0-9]{4,6}(?:-[0-9]+)?)", nome)
    if m:
        numero = "NBR " + m.group(1)
    anos = re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", nome)
    if anos:
        edicao = anos[-1]
    return entidade, numero, edicao


def itens_textuais(paginas: list[str], padrao: str, limite: int = 40) -> list[dict]:
    itens = []
    regex = re.compile(padrao, re.I)
    for numero, pagina in enumerate(paginas, 1):
        for trecho in re.split(r"(?<=[.;:])\s+|\n+", pagina):
            limpo = re.sub(r"\s+", " ", trecho).strip()
            if 20 <= len(limpo) <= 700 and regex.search(limpo):
                secao = re.match(r"^([0-9]+(?:\.[0-9]+){0,5})\s+", limpo)
                itens.append({"descricao": limpo, "pagina": numero, "secao_item": secao.group(1) if secao else None,
                              "status_verificacao": "VERIFICADO" if secao else "PENDENTE_VERIFICACAO_NORMATIVA"})
                if len(itens) >= limite:
                    return itens
    return itens


def derivar_norma(item: dict, paginas: list[str], raiz_privada: Path) -> dict:
    texto = "\n".join(paginas)
    pasta = Path(item["caminho_relativo"]).parent.name.lower()
    entidade, numero, edicao = metadados_norma(item["nome"], pasta)
    titulo_base = normalizar(Path(item["nome"]).stem)
    vocabulario_titulo = {
        "REVESTIMENTOS": ("revestimento", "ceram", "argamassa", "rejunt"),
        "VEDACOES": ("vedacao", "alvenaria"), "IMPERMEABILIZACAO": ("impermeabil",),
        "ESQUADRIAS": ("esquadria", "janela", "porta"),
        "ESTRUTURA": ("estrutura", "concreto", "fundacao", "encosta"),
        "INSTALACOES_ELETRICAS": ("instalacoes eletricas", "nbr 5410"),
        "INSTALACOES_HIDROSSANITARIAS": ("hidrossanit", "esgoto", "nbr 8160"),
        "AVALIACAO_IMOBILIARIA": ("avaliacao de bens", "imoveis urbanos", "valor de mercado", "nbr 14653"),
        "ENGENHARIA_RODOVIARIA": ("rodovia", "rodoviari", "seguranca viaria", "pavimento rodoviario"),
        "VICIOS_CONSTRUTIVOS": ("desempenho", "inspecao predial", "pericias de engenharia", "manutencao de edificacoes", "patologia", "trincas em edificios"),
    }
    sistemas = [nome for nome, termos in vocabulario_titulo.items() if any(t in titulo_base for t in termos)]
    requisitos = itens_textuais(paginas, r"\b(deve|devem|dever[aá]|obrigat[oó]ri|requer)\b")
    metodos = itens_textuais(paginas, r"\b(verificar|verifica[cç][aã]o|inspe[cç][aã]o|medir|medi[cç][aã]o|ensaio)\b", 25)
    ensaios = itens_textuais(paginas, r"\bensaio\b", 20)
    escopo = itens_textuais(paginas[:8], r"\b(escopo|estabelece|especifica|aplica-se|prescreve)\b", 5)
    status = "PENDENTE_VERIFICACAO_NORMATIVA" if texto.strip() else "TEXTO_INSUFICIENTE"
    return {
        "schema_version": "1.0.0", "id": item["id"], "entidade": entidade, "numero": numero,
        "titulo": Path(item["nome"]).stem, "edicao": edicao, "data": edicao, "vigencia": None,
        "escopo": escopo, "sistemas": sistemas, "assuntos": sistemas, "terminologia": [],
        "requisitos": requisitos, "criterios_aceitacao": [], "metodos_verificacao": metodos,
        "ensaios": ensaios, "limitacoes": [], "referencias_cruzadas": [],
        "aplicabilidade_temporal": "APLICABILIDADE_INCONCLUSIVA",
        "proveniencia": {"arquivo": item["caminho_relativo"], "sha256": item["sha256"], "norma": numero,
                          "edicao": edicao, "pagina": 1 if texto.strip() else None, "secao_item": None,
                          "metodo_extracao": item["metodo_extracao"], "confianca": item["confianca"],
                          "status_verificacao": status if status != "TEXTO_INSUFICIENTE" else "PENDENTE_VERIFICACAO_NORMATIVA"},
        "status": status,
    }


def derivar_modelo(item: dict, paginas: list[str]) -> dict:
    texto = "\n".join(paginas)
    tipo, _ = tipo_provavel(texto, "MODELO_REFERENCIAL")
    base = normalizar(texto[:300000])
    sistemas = [nome for nome, termos in SISTEMAS.items() if any(t in base for t in termos)]
    extrair=lambda padrao,limite:[x["descricao"] for x in itens_textuais(paginas,padrao,limite)]
    estrutura=extrair(r"^(?:[0-9]+(?:\.[0-9]+)*\s+)?(?:considera[cç][oõ]es|metodologia|vistoria|conclus[aã]o|quesitos|or[cç]amento|encerramento)\b",30)
    metodologia=extrair(r"\b(metodologia|inspe[cç][aã]o visual|levantamento|procedimento)\b",20)
    medicoes=extrair(r"\b(medi[cç][aã]o|medidor|trena|fissur[oô]metro|umidade)\b",20)
    ressalvas=extrair(r"\b(limita[cç][aã]o|ressalva|n[aã]o foi poss[ií]vel|inacess[ií]vel)\b",20)
    questoes=extrair(r"^(?:quesito|pergunta|quest[aã]o)(?:\s+n?[.º°]?\s*\d+)?\s*[:.-]",30)
    estrategias=extrair(r"\b(confrontou-se|comparou-se|correlacionou-se|foi verificado|procedeu-se|adotou-se)\b",20)
    formas_resposta=extrair(r"^(?:r\s*:|resposta\s*:|ao quesito)\s*",30)
    return {"schema_version": "1.0.0", "id": item["id"],
            "fonte": {"arquivo": item["caminho_relativo"], "sha256": item["sha256"], "metodo_extracao": item["metodo_extracao"], "confianca": item["confianca"]},
            "nivel": "CASO_ANTERIOR", "tipo_pericia": tipo, "subtipos": [], "temas": sistemas,
            "estrutura": estrutura, "metodologia": metodologia, "tecnicas": metodologia, "sistemas": sistemas, "medicoes": medicoes,
            "ensaios": extrair(r"\bensaio\b",10), "equipamentos": medicoes, "tipos_evidencia": ["fotografias","medições","documentos"] if estrutura else [], "ressalvas": ressalvas,
            "questoes_tecnicas": questoes, "estrategias_analise": estrategias,
            "formas_resposta_quesitos": formas_resposta,
            "praticas_recorrentes": (["estrutura por capítulos"] if estrutura else []) +
                                    (["respostas identificadas individualmente"] if formas_resposta else []),
            "elementos_proibidos_como_regra": ["fatos", "nomes", "endereços", "conclusões", "causalidade", "valores", "responsabilidade"],
            "status": "EXTRAIDO" if texto.strip() else "TEXTO_INSUFICIENTE"}


def agregar_regras_candidatas(modelos: list[dict], minimo_fontes: int = 2) -> list[dict]:
    """Promove apenas práticas metodológicas recorrentes; nunca resultados de casos."""
    proibidos = re.compile(r"\b(causa|culpa|respons[aá]vel|indeniza|v[ií]cio caracterizado|origem end[oó]gena|valor)\b", re.I)
    ocorrencias: dict[str, set[str]] = {}
    originais: dict[str, str] = {}
    for modelo in modelos:
        fonte = modelo.get("id") or modelo.get("fonte", {}).get("sha256")
        for campo in ("praticas_recorrentes", "estrategias_analise", "formas_resposta_quesitos"):
            for pratica in modelo.get(campo, []):
                texto = pratica if isinstance(pratica, str) else pratica.get("descricao", "")
                chave = re.sub(r"\s+", " ", normalizar(texto)).strip()
                if fonte and chave and not proibidos.search(texto):
                    ocorrencias.setdefault(chave, set()).add(fonte)
                    originais.setdefault(chave, texto)
    return [
        {"pratica": originais[chave], "fontes_independentes": sorted(fontes),
         "status": "CANDIDATA_VALIDACAO_PERITO"}
        for chave, fontes in sorted(ocorrencias.items()) if len(fontes) >= minimo_fontes
    ]


def inventariar(raiz_privada: Path) -> dict:
    conhecimento = raiz_privada / "conhecimento"
    conhecimento.mkdir(parents=True, exist_ok=True)
    inventario_path = conhecimento / "inventario-referencias.json"
    anterior = json.loads(inventario_path.read_text(encoding="utf-8")) if inventario_path.exists() else {"arquivos": []}
    por_hash = {item["sha256"]: item for item in anterior["arquivos"]}
    arquivos = []
    contadores = {"MOD": max([int(i["id"].split("-")[1]) for i in anterior["arquivos"] if i["id"].startswith("MOD-")] or [0]),
                 "NOR": max([int(i["id"].split("-")[1]) for i in anterior["arquivos"] if i["id"].startswith("NOR-")] or [0])}
    fontes = [(raiz_privada / "modelos-referenciais", "MODELO_REFERENCIAL", "MOD"), (raiz_privada / "normas", "NORMA_TECNICA", "NOR")]
    for base, categoria_padrao, prefixo in fontes:
        for caminho in sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSOES):
            digest = hash_arquivo(caminho); anterior_item = por_hash.get(digest)
            if anterior_item and anterior_item.get("versao_extrator") == VERSAO_EXTRATOR:
                item = dict(anterior_item); item["acao_processamento"] = "REUTILIZADO"
                if item["situacao_extracao"] == "NAO_ALTERADO":
                    derivado = conhecimento / ("modelos" if prefixo == "MOD" else "normas") / f"{item['id']}.json"
                    status = json.loads(derivado.read_text(encoding="utf-8")).get("status") if derivado.exists() else None
                    item["situacao_extracao"] = "TEXTO_INSUFICIENTE" if status == "TEXTO_INSUFICIENTE" else "EXTRAIDO"
                arquivos.append(item); continue
            if anterior_item:
                identificador = anterior_item["id"]
            else:
                contadores[prefixo] += 1
                identificador = f"{prefixo}-{contadores[prefixo]:04d}"
            categoria = "LITERATURA_TECNICA" if "literatura-tecnica" in caminho.parts else categoria_padrao
            item = {"id": identificador, "categoria": categoria,
                    "caminho_relativo": caminho.relative_to(raiz_privada).as_posix(), "nome": caminho.name,
                    "extensao": caminho.suffix.lower(), "sha256": digest, "tamanho_bytes": caminho.stat().st_size,
                    "processado_em": agora(), "versao_extrator": VERSAO_EXTRATOR, "acao_processamento": "PROCESSADO", "metodo_extracao": "NAO_SUPORTADO", "situacao_extracao": "ERRO_EXTRACAO",
                    "tipo_provavel": "OUTRO", "confianca": {"nivel": "BAIXA"}}
            try:
                paginas, metodo = extrair_texto(caminho); texto = "\n".join(paginas)
                item["metodo_extracao"] = metodo; item["situacao_extracao"] = "EXTRAIDO" if len(texto.strip()) >= 100 else "TEXTO_INSUFICIENTE"
                item["tipo_provavel"], item["confianca"] = tipo_provavel(texto, categoria)
                destino_dir = conhecimento / ("modelos" if prefixo == "MOD" else "normas"); destino_dir.mkdir(parents=True, exist_ok=True)
                derivado = derivar_modelo(item, paginas) if prefixo == "MOD" else derivar_norma(item, paginas, raiz_privada)
                (destino_dir / f"{item['id']}.json").write_text(json.dumps(derivado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            except Exception as exc:  # falha isolada não bloqueia o inventário
                item["situacao_extracao"] = "ERRO_EXTRACAO"; item["tipo_provavel"] = type(exc).__name__
            arquivos.append(item)
    inventario = {"schema_version": "1.0.0", "gerado_em": agora(), "arquivos": arquivos}
    inventario_path.write_text(json.dumps(inventario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return inventario


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("raiz_privada", type=Path)
    inventario = inventariar(parser.parse_args().raiz_privada)
    print(json.dumps({"arquivos": len(inventario["arquivos"]), "processados": sum(i["acao_processamento"] == "PROCESSADO" for i in inventario["arquivos"]), "reutilizados": sum(i["acao_processamento"] == "REUTILIZADO" for i in inventario["arquivos"]), "extraidos": sum(i["situacao_extracao"] == "EXTRAIDO" for i in inventario["arquivos"]), "insuficientes": sum(i["situacao_extracao"] == "TEXTO_INSUFICIENTE" for i in inventario["arquivos"]), "erros": sum(i["situacao_extracao"] == "ERRO_EXTRACAO" for i in inventario["arquivos"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
