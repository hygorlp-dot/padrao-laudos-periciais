"""Agrupamento das propostas do imóvel por valor normalizado (#288).

Cada evidência continua sendo uma proposta com a sua fonte; aqui as propostas
do MESMO valor de um campo viram um único `PropertyValueCluster`, com todas as
evidências. "01" e "01" em duas peças são um valor com duas evidências;
"55000-000" e "55000000" são o mesmo CEP. A normalização é explícita por campo
e nunca aproxima valores diferentes: "Rua 1" e "Rua Um" continuam separados.

O ranking documental só ordena, destaca e gradua a confiança. Nenhum
agrupamento torna um valor efetivo: o perito usa a proposta e confirma.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from .property_record import PROPERTY_FIELDS, PropertyProposal, property_date

_KINDS = {field: kind for field, _label, kind, _aliases in PROPERTY_FIELDS}
_UF_BY_NAME = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA", "mato grosso": "MT",
    "mato grosso do sul": "MS", "minas gerais": "MG", "para": "PA", "paraiba": "PB", "parana": "PR",
    "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}
_UF_CODES = frozenset(_UF_BY_NAME.values())
# Identificadores em que "01" e "1" são, por regra explícita, o mesmo valor:
# só quando o valor inteiro é numérico ("01A" não é tocado).
_NUMERIC_IDENTIFIERS = frozenset({"number", "unit", "block", "quadra", "floor"})
_RANK_ORDER = "ABCDEFGH"


def _spaced(value: str) -> str:
    return " ".join(value.split())


def _unaccented(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))


def normalized_property_value(field: str, value: str) -> tuple[str, str]:
    """(chave de agrupamento, valor canônico para exibir) por regra do campo."""
    text = _spaced(value)
    if field == "postal_code":
        digits = re.sub(r"[\s.\-]", "", text)
        if re.fullmatch(r"\d{8}", digits):
            return digits, f"{digits[:5]}-{digits[5:]}"
    if field == "state":
        code = text.upper()
        if code in _UF_CODES:
            return code, code
        named = _UF_BY_NAME.get(_unaccented(text).casefold())
        if named is not None:
            return named, named
    if _KINDS.get(field) == "decimal":
        grouped = re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d+", text)
        number = Decimal(text.replace(".", "").replace(",", ".") if grouped else text.replace(",", "."))
        canonical = format(number.normalize(), "f")
        return canonical, canonical.replace(".", ",")
    if _KINDS.get(field) == "date":
        day = property_date(text)
        return day.isoformat(), day.strftime("%d/%m/%Y")
    if field in _NUMERIC_IDENTIFIERS and re.fullmatch(r"\d+", text):
        return str(int(text)), str(int(text))
    return text.casefold(), text


@dataclass(frozen=True, slots=True)
class PropertyValueCluster:
    cluster_id: str
    field: str
    canonical_value: str
    # Valor da melhor evidência, como está na fonte: é o que "Usar" grava.
    display_value: str
    normalized_value: str
    # HIGH: peça A–D com vínculo forte e sem divergência forte no campo.
    # MEDIUM: vínculo forte em outra peça, ou divergência forte no campo.
    # LOW: só contexto possível.
    confidence: str
    strength: str
    best_rank: str
    source_count: int
    document_count: int
    evidences: tuple[PropertyProposal, ...]
    conflicting_cluster_ids: tuple[str, ...]


def cluster_property_proposals(proposals: tuple[PropertyProposal, ...]) -> tuple[PropertyValueCluster, ...]:
    order = {field: index for index, (field, *_rest) in enumerate(PROPERTY_FIELDS)}
    grouped: dict[tuple[str, str], list[tuple[int, PropertyProposal, str]]] = {}
    for position, proposal in enumerate(proposals):
        try:
            key, canonical = normalized_property_value(proposal.field, proposal.value)
        except (ValueError, ArithmeticError):
            key, canonical = proposal.value, proposal.value
        grouped.setdefault((proposal.field, key), []).append((position, proposal, canonical))

    drafts = []
    for (field, key), items in grouped.items():
        items.sort(key=lambda item: (_RANK_ORDER.index(item[1].source_rank), item[1].strength != "STRONG", item[0]))
        best = items[0][1]
        strong = any(item[1].strength == "STRONG" for item in items)
        pieces = {(item[1].evidence.document_id, item[1].piece_id) for item in items}
        drafts.append({
            "cluster_id": "PVC-" + sha256(f"{field}\x00{key}".encode()).hexdigest()[:24],
            "field": field, "canonical_value": items[0][2], "display_value": best.value, "normalized_value": key,
            "strength": "STRONG" if strong else "POSSIBLE", "best_rank": best.source_rank,
            "source_count": len(items), "document_count": len(pieces),
            "evidences": tuple(item[1] for item in items), "first": items[0][0],
        })

    clusters = []
    for draft in drafts:
        siblings = [other for other in drafts if other["field"] == draft["field"] and other is not draft]
        strong_conflict = draft["strength"] == "STRONG" and any(other["strength"] == "STRONG" for other in siblings)
        if draft["strength"] != "STRONG":
            confidence = "LOW"
        elif draft["best_rank"] in "ABCD" and not strong_conflict:
            confidence = "HIGH"
        else:
            confidence = "MEDIUM"
        clusters.append((draft, PropertyValueCluster(
            draft["cluster_id"], draft["field"], draft["canonical_value"], draft["display_value"],
            draft["normalized_value"], confidence, draft["strength"], draft["best_rank"],
            draft["source_count"], draft["document_count"], draft["evidences"],
            tuple(other["cluster_id"] for other in siblings),
        )))
    # Ordem por campo e, no campo: peça mais autoritativa, vínculo forte, mais
    # peças, mais ocorrências; empate pela ordem de leitura.
    clusters.sort(key=lambda pair: (
        order.get(pair[1].field, len(order)), _RANK_ORDER.index(pair[1].best_rank), pair[1].strength != "STRONG",
        -pair[1].document_count, -pair[1].source_count, pair[0]["first"],
    ))
    return tuple(cluster for _draft, cluster in clusters)
