"""Immutable presentation of the report's captured authorities, never a new decision.

No repository, latest-revision lookup, asset extraction or Word engine lives here.
The four narrow captures retain the canonical payloads the Report is bound to.
Legacy reports omit this optional capture and keep their original mapping/digest.
"""
from dataclasses import asdict, dataclass, fields
from collections.abc import Mapping
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext
import hashlib
import json
from typing import Protocol

from .case_analysis import case_analysis_from_mapping, case_analysis_to_mapping
from .vistoria import inspection_session_from_mapping, inspection_session_to_mapping
from .technical_findings import technical_snapshot_from_mapping, technical_snapshot_to_mapping
from .construction_defect_analysis import construction_defect_analysis_from_mapping, construction_defect_analysis_to_mapping


LAYOUT_ID = "PROFESSIONAL_REPORT_LAYOUT_V1"
_SOURCES = {
    "case": (case_analysis_from_mapping, case_analysis_to_mapping, "case_analysis", "snapshot_id"),
    "inspection": (inspection_session_from_mapping, inspection_session_to_mapping, "inspection_session", "session_id"),
    "technical": (technical_snapshot_from_mapping, technical_snapshot_to_mapping, "technical_snapshot", "snapshot_id"),
    "pathology": (construction_defect_analysis_from_mapping, construction_defect_analysis_to_mapping, "construction_defect_analysis", "snapshot_id"),
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not str or not value.strip() or len(value) > 20000 or any(ord(c) < 32 and c not in "\n\t\r" for c in value):
        raise ValueError("professional presentation text is invalid")


@dataclass(frozen=True, slots=True)
class CapturedReportAuthority:
    kind: str
    revision: int
    payload_json: str

    def __post_init__(self):
        if self.kind not in _SOURCES or type(self.revision) is not int or self.revision < 1 or type(self.payload_json) is not str or len(self.payload_json.encode("utf-8")) > 2_000_000:
            raise ValueError("captured professional authority is invalid")
        data = json.loads(self.payload_json)
        if _canonical(data) != self.payload_json:
            raise ValueError("captured professional authority is not canonical")
        _SOURCES[self.kind][0](data)

    def read(self):
        return _SOURCES[self.kind][0](json.loads(self.payload_json))


@dataclass(frozen=True, slots=True)
class ProfessionalReportDetails:
    action_type: str | None = None
    protocol_opening: str | None = None
    qualification: str | None = None
    preamble: str | None = None
    objective: str | None = None
    definitions: str | None = None
    classification_framework: str | None = None
    conditions: str | None = None
    city: str | None = None
    report_date: str | None = None
    closing: str | None = None

    def __post_init__(self):
        for field in fields(self):
            _text(getattr(self, field.name), optional=True)
        if self.report_date is not None:
            from datetime import date
            date.fromisoformat(self.report_date)


def _decimal(value, name):
    try:
        if type(value) is not str:
            raise ValueError(name)
        number = Decimal(value)
        if not number.is_finite() or number < 0:
            raise ValueError(name)
        return number
    except (DecimalException, ValueError) as exc:
        raise ValueError("repair budget decimal is invalid: " + name) from exc


@dataclass(frozen=True, slots=True)
class ReportRepairLine:
    group: str
    item: str
    pat_id: str
    source: str
    code: str
    description: str
    unit: str
    quantity: str
    memory: str
    unit_cost: str
    bdi_percent: str
    unit_price: str
    total: str

    def __post_init__(self):
        for field in fields(self):
            _text(getattr(self, field.name))
        quantity, cost, bdi, price, total = (_decimal(getattr(self, n), n) for n in ("quantity", "unit_cost", "bdi_percent", "unit_price", "total"))
        cents = Decimal("0.01")
        try:
            computed_price = (cost * (1 + bdi / 100)).quantize(cents, rounding=ROUND_HALF_UP)
            computed_total = (quantity * price).quantize(cents, rounding=ROUND_HALF_UP)
        except DecimalException as exc:
            raise ValueError("repair budget arithmetic cannot be represented") from exc
        if quantity <= 0 or price != computed_price or total != computed_total:
            raise ValueError("repair budget captured arithmetic diverges")


@dataclass(frozen=True, slots=True)
class ReportRepairBudget:
    competence: str
    regime: str
    observations: str
    bdi_memory: str
    lines: tuple[ReportRepairLine, ...]

    def __post_init__(self):
        for name in ("competence", "regime", "observations", "bdi_memory"):
            _text(getattr(self, name))
        if type(self.lines) is not tuple or not self.lines or len(self.lines) > 500 or any(type(v) is not ReportRepairLine for v in self.lines) or len({v.item for v in self.lines}) != len(self.lines):
            raise ValueError("repair budget capture is invalid")

    @property
    def total(self):
        amounts = tuple(_decimal(v.total, "total") for v in self.lines)
        with localcontext() as context:
            # At most 500 validated cent amounts need three additional digits.
            context.prec = max(context.prec, max(len(v.as_tuple().digits) for v in amounts) + 3)
            return format(sum(amounts, Decimal("0.00")).quantize(Decimal("0.01")), "f")


@dataclass(frozen=True, slots=True)
class ReportSheetFigures:
    pat_id: str
    photo_figure_id: str | None = None
    plan_figure_id: str | None = None

    def __post_init__(self):
        _text(self.pat_id)
        _text(self.photo_figure_id, optional=True)
        _text(self.plan_figure_id, optional=True)
        if self.photo_figure_id is not None and self.photo_figure_id == self.plan_figure_id:
            raise ValueError("photo and plan have different explicit roles")


@dataclass(frozen=True, slots=True)
class ProfessionalReportCapture:
    sources: tuple[CapturedReportAuthority, ...]
    details: ProfessionalReportDetails = ProfessionalReportDetails()
    repair_budget: ReportRepairBudget | None = None
    sheet_figures: tuple[ReportSheetFigures, ...] = ()

    def __post_init__(self):
        if type(self.sources) is not tuple or any(type(v) is not CapturedReportAuthority for v in self.sources) or {v.kind for v in self.sources} not in ({"case", "inspection", "technical"}, {"case", "inspection", "technical", "pathology"}) or len({v.kind for v in self.sources}) != len(self.sources):
            raise ValueError("captured professional sources are incomplete")
        if type(self.details) is not ProfessionalReportDetails or (self.repair_budget is not None and type(self.repair_budget) is not ReportRepairBudget) or type(self.sheet_figures) is not tuple or any(type(v) is not ReportSheetFigures for v in self.sheet_figures) or len({v.pat_id for v in self.sheet_figures}) != len(self.sheet_figures):
            raise ValueError("professional presentation capture is invalid")


def capture_from_mapping(value):
    if type(value) is not dict or set(value) != {f.name for f in fields(ProfessionalReportCapture)}:
        raise ValueError("professional presentation fields are invalid")
    try:
        budget = value["repair_budget"]
        if budget is not None:
            budget = ReportRepairBudget(**{**budget, "lines": tuple(ReportRepairLine(**v) for v in budget["lines"])})
        return ProfessionalReportCapture(tuple(CapturedReportAuthority(**v) for v in value["sources"]), ProfessionalReportDetails(**value["details"]), budget, tuple(ReportSheetFigures(**v) for v in value["sheet_figures"]))
    except (TypeError, KeyError) as exc:
        raise ValueError("professional presentation mapping is invalid") from exc


def capture_to_mapping(value):
    return json.loads(_canonical(asdict(value)))


def validate_capture_binding(report):
    capture = report.presentation
    if capture is None:
        return
    if type(capture) is not ProfessionalReportCapture:
        raise ValueError("captured professional presentation type is invalid")
    binding = report.source_snapshot
    for source in capture.sources:
        data = json.loads(source.payload_json)
        _parser, _mapping, name, identity = _SOURCES[source.kind]
        # Case/technical names already include the snapshot suffix in the Report.
        id_field = {"case": "case_analysis_snapshot_id", "inspection": "inspection_session_id", "technical": "technical_snapshot_id", "pathology": "construction_defect_analysis_snapshot_id"}[source.kind]
        if data["workspace_id"] != report.workspace_id or data[identity] != getattr(binding, id_field) or source.revision != getattr(binding, name + "_revision") or _digest(data) != getattr(binding, name + "_digest"):
            raise ValueError("captured professional authority differs from Report binding")
    if (binding.construction_defect_analysis_snapshot_id is not None) != any(v.kind == "pathology" for v in capture.sources):
        raise ValueError("captured pathology authority is incomplete")
    figures = {v.figure_id for v in report.figures or ()}
    if any(v not in figures for row in capture.sheet_figures for v in (row.photo_figure_id, row.plan_figure_id) if v is not None):
        raise ValueError("professional sheet requires explicitly captured figures")


def capture_report_authorities(report, *, case, inspection, technical, pathology):
    values = {"case": case, "inspection": inspection, "technical": technical}
    if pathology is not None:
        values["pathology"] = pathology
    sources = tuple(CapturedReportAuthority(kind, getattr(report.source_snapshot, _SOURCES[kind][2] + "_revision"), _canonical(_SOURCES[kind][1](value))) for kind, value in values.items())
    captured = ProfessionalReportCapture(sources)
    from dataclasses import replace
    validate_capture_binding(replace(report, presentation=captured))
    return captured


def origin_presentation(value):
    return {"ENDOGENA_CONSTRUTIVA": "Construtiva", "EXOGENA": "Exógena", "FUNCIONAL": "Funcional", "USO_OPERACAO_MANUTENCAO": "Uso / Operação / Manutenção (agrupado)", "MISTA": "Mista", "INCONCLUSIVA": "Inconclusiva", "NAO_APLICAVEL": "Não aplicável"}.get(value, "Não informada")


def classification_presentation(value):
    return {"ANOMALIA": "Anomalia", "FALHA": "Falha", "INCONCLUSIVA": "Inconclusivo", "CONFORME": "Conforme", "NAO_CONSTATADA": "Não constatada"}.get(value, "Não informada")


def criticality_presentation(value):
    return {"CRITICA": "Crítico", "MEDIA": "Médio", "MINIMA": "Mínimo", "INCONCLUSIVA": "Inconclusiva", "NAO_APLICAVEL": "Não aplicável"}.get(value, "Não informada")


def recommendation_presentation(value):
    if value is None or type(value) is str:
        return value
    if not isinstance(value, Mapping):
        raise ValueError("professional recommendation requires captured text")
    labels = {"objetivo": "Objetivo", "sistema": "Sistema", "escopo": "Escopo", "etapas_gerais": "Etapas gerais", "mecanismo_ou_causa_tratada": "Mecanismo ou causa tratada", "limitacoes": "Limitações", "investigacao_adicional": "Investigação adicional"}
    if set(value) - set(labels):
        raise ValueError("professional structured recommendation fields are invalid")
    parts = []
    for key, label in labels.items():
        captured = value.get(key)
        if captured is None:
            continue
        if key == "investigacao_adicional":
            if type(captured) is not bool:
                raise ValueError("professional recommendation investigation is invalid")
            captured = "Indicada" if captured else "Não indicada"
        elif key in {"etapas_gerais", "limitacoes"}:
            if type(captured) not in (list, tuple) or any(type(v) is not str for v in captured):
                raise ValueError("professional recommendation list is invalid")
            captured = "; ".join(captured)
            if not captured:
                continue
        _text(captured)
        parts.append(label + ": " + captured)
    return "; ".join(parts) or None


@dataclass(frozen=True, slots=True)
class ProfessionalQuestion:
    question_id: str
    origin: str
    number: str | None
    text: str
    answer_id: str | None
    finding_id: str | None
    decision_id: str | None


@dataclass(frozen=True, slots=True)
class ProfessionalItem:
    pat_id: str
    decision_id: str
    system: str | None
    manifestation: str
    local: str | None
    allegation: tuple[str, ...]
    observation: tuple[str, ...]
    measurements: tuple[str, ...]
    analysis: str | None
    consequences: str | None
    classification: str | None
    origin: str | None
    criticality: str | None
    conclusion: str
    recommendation: str | None
    repair_eligible: bool
    photo_figure_id: str | None
    plan_figure_id: str | None


@dataclass(frozen=True, slots=True)
class ProfessionalCover:
    process_number: str | None
    court: str | None
    expert_name: str
    claimant: str | None
    defendant: str | None
    action_type: str | None
    protocol_opening: str | None


@dataclass(frozen=True, slots=True)
class ProfessionalSystem:
    name: str
    items: tuple[ProfessionalItem, ...]


@dataclass(frozen=True, slots=True)
class ProfessionalQuestionGroup:
    origin: str
    questions: tuple[ProfessionalQuestion, ...]


@dataclass(frozen=True, slots=True)
class ProfessionalClosing:
    text: str | None
    city: str | None
    report_date: str | None
    expert_name: str
    professional_title: str
    registration: str


class ProfessionalReference(Protocol):
    """Read-only shape of the reference already captured on Report."""
    @property
    def reference_id(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def author(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def year(self) -> int | None: ...
    @property
    def identifier(self) -> str | None: ...
    @property
    def details(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ProfessionalReportProjection:
    report_id: str
    questions: tuple[ProfessionalQuestion, ...]
    items: tuple[ProfessionalItem, ...]
    visit: tuple[tuple[str, str], ...]
    details: ProfessionalReportDetails
    repair_budget: ReportRepairBudget | None
    cover: ProfessionalCover
    synopsis: tuple[tuple[str, str], ...]
    systems: tuple[ProfessionalSystem, ...]
    references: tuple[ProfessionalReference, ...]
    question_groups: tuple[ProfessionalQuestionGroup, ...]
    closing: ProfessionalClosing


def professional_report_projection(report):
    validate_capture_binding(report)
    if report.presentation is None:
        raise ValueError("professional presentation is not captured")
    capture = report.presentation
    sources = {s.kind: s.read() for s in capture.sources}
    case, inspection = sources["case"], sources["inspection"]
    answers = {a.question_id: a for a in report.answers}
    questions = []
    for q in case.questions:
        if q.item_id not in answers:
            continue  # this projection is of Report answers, not a coverage claim
        source = q.source_question
        a = answers[q.item_id]
        if a.question_text is not None and a.question_text != q.text:
            raise ValueError("captured question literal differs from Report answer")
        questions.append(ProfessionalQuestion(q.item_id, source.origin if source else "Origem não informada", source.original_number if source else None, a.question_text or q.text, a.answer_id, a.finding_id, a.decision_id))
    pathology = sources.get("pathology")
    items = []
    if pathology is not None:
        links = {(v.legacy_kind, v.legacy_id): v.canonical_id for v in pathology.identity_links}
        claims = {c.item_id: c.text for c in case.claims}
        obs = {o.observation_id: o.raw_observation for o in inspection.observations}
        measurements = {m.measurement_id: m for m in inspection.measurements}
        photos = {p.photo_id: p for p in inspection.photos}
        placements = {p.pat_id: p for p in capture.sheet_figures}
        for p in pathology.analysis_final.get("patologias", ()):
            if p["id"] not in pathology.effective_pat_ids:
                continue
            review = next(r for r in reversed(pathology.reviews) if r.pat_id == p["id"])
            constatacao, writing = p.get("constatacao", {}), p.get("redacao", {})
            recommendation = recommendation_presentation(p.get("recomendacao", {}).get("descricao"))
            photo_ids = tuple(links.get(("PHOTO", v)) for v in constatacao.get("fotografias", ()))
            photo_records = tuple(photos[v] for v in photo_ids if v in photos)
            figure = placements.get(p["id"])
            photo_figure_id = figure.photo_figure_id if figure else None
            if photo_figure_id is not None:
                chosen = next(f for f in report.figures if f.figure_id == photo_figure_id)
                if not any((chosen.content_id, chosen.original_sha256) == (photo.private_content_id, photo.original_sha256) for photo in photo_records):
                    raise ValueError("professional photo is not linked to this pathology")
            ms = tuple(measurements[v] for v in (links.get(("MEASUREMENT", m)) for m in p.get("medicoes", ())) if v in measurements)
            eligible = p.get("elegibilidade_orcamento") == "ELEGIVEL_ORCAMENTO_VICIO" and p.get("orcamento", {}).get("incluir") is True and p.get("orcamento", {}).get("revisao_profissional", {}).get("status") in {"APROVADO", "AJUSTADO"}
            items.append(ProfessionalItem(p["id"], review.review_id, p.get("sistema"), p.get("manifestacao", "Manifestação não informada"), p.get("localizacao_detalhada") or p.get("ambiente"), tuple(claims[v] for v in (links.get(("ALLEGATION", a)) for a in p.get("alegacoes_relacionadas", ())) if v in claims), tuple(obs[v] for v in (links.get(("OBSERVATION", o)) for o in p.get("constatacoes", ())) if v in obs), tuple(f"{m.raw_value} {m.raw_unit}" for m in ms), writing.get("analise_alegacoes_causas"), writing.get("consequencias"), constatacao.get("situacao"), p.get("origem"), p.get("criticidade"), writing.get("conclusao") or p["conclusao_tecnica"], recommendation, eligible, photo_figure_id, figure.plan_figure_id if figure else None))
        if set(placements) - {i.pat_id for i in items}:
            raise ValueError("professional sheet is not an effective pathology")
    budget = capture.repair_budget
    if budget is not None:
        eligible = {i.pat_id for i in items if i.repair_eligible}
        if any(line.pat_id not in eligible for line in budget.lines):
            raise ValueError("repair budget includes a pathology without approved eligibility")
    visit = inspection.visit_context
    facts = tuple((label, value) for label, value in (("Data da vistoria", visit.date if visit else None), ("Hora da vistoria", visit.start_time if visit else None), ("Clima", visit.weather if visit else None)) if value is not None)
    # These records are already immutable captures on Report. No repository is
    # consulted and no proposed participant or absent property is promoted.
    process = report.process_record
    number = process.numero_processo.strip() or None if process else None
    court = process.vara.strip() or process.tribunal.strip() or None if process else None
    claimant = defendant = None
    if process is not None:
        if process.participants is None:
            claimant = process.parte_requerente.strip() or None
            defendant = process.parte_requerida.strip() or None
        else:
            from .process_participants import ParticipantPole, participants_summary
            claimant = participants_summary(process.participants, ParticipantPole.ACTIVE, limit=len(process.participants)) or None
            defendant = participants_summary(process.participants, ParticipantPole.PASSIVE, limit=len(process.participants)) or None
    expert = report.expert_profile
    cover = ProfessionalCover(number, court, expert.full_name, claimant, defendant, capture.details.action_type, capture.details.protocol_opening)
    synopsis = [(label, value) for label, value in (("Autos", number), ("Juízo", court), ("Perito", expert.full_name), ("Parte autora", claimant), ("Parte ré", defendant)) if value]
    synopsis.extend(facts)
    if report.property_record is not None:
        from .property_record import PROPERTY_FIELDS
        labels = {field: label for field, label, *_ in PROPERTY_FIELDS}
        synopsis.extend((labels[v.field], v.value) for v in report.property_record.record.values)
    if report.site_location is not None:
        synopsis.append(("Coordenadas", report.site_location.coordinates_text))
    systems = tuple(ProfessionalSystem(name, tuple(i for i in items if (i.system or "Sistema não informado") == name)) for name in dict.fromkeys(i.system or "Sistema não informado" for i in items))
    groups = tuple(ProfessionalQuestionGroup(origin, tuple(q for q in questions if q.origin == origin)) for origin in dict.fromkeys(q.origin for q in questions))
    closing = ProfessionalClosing(capture.details.closing, capture.details.city, capture.details.report_date, expert.full_name, expert.professional_title, expert.registration)
    return ProfessionalReportProjection(report.report_id, tuple(questions), tuple(items), facts, capture.details, budget, cover, tuple(synopsis), systems, report.references, groups, closing)
