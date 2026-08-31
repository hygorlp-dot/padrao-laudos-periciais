"""Protected delivery rendering and final-byte integrity checks."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import re
import json
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from .report_foundation import ReportSnapshot
from .report_foundation import report_snapshot_to_mapping
from .report_template import (
    DocumentBindingResult,
    TemplateBindingManifest,
    bind_report_template,
)


_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_DOCM_MEDIA = "application/vnd.ms-word.document.macroEnabled.12"
_PDF_MEDIA = "application/pdf"
DELIVERY_RENDERING_VERSION = "delivery-renderer/1.0.0"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
ElementTree.register_namespace("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main")


def render_word_candidate(
    *, template_bytes: bytes, report: ReportSnapshot, manifest: TemplateBindingManifest,
) -> DocumentBindingResult:
    result = bind_report_template(template_bytes, report, manifest)
    output = _inject_canonical_report(result.output_bytes, report)
    validate_final_artifact(output, manifest.output_kind)
    return DocumentBindingResult(output, result.integrity)


def _paragraph(text: str):
    paragraph = ElementTree.Element(f"{_W}p")
    run = ElementTree.SubElement(paragraph, f"{_W}r")
    node = ElementTree.SubElement(run, f"{_W}t")
    node.text = text
    return paragraph


def _canonical_report_lines(report: ReportSnapshot) -> tuple[str, ...]:
    mapping = report_snapshot_to_mapping(report)
    digest = sha256(json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    lines = [f"LAUDO CANÔNICO | {report.report_id}", f"REPORT_SNAPSHOT_SHA256 | {digest}"]
    for item in report.context_matrix:
        lines.append(f"CONTEXTO | {item.field} | {item.status.value} | {item.source_id or 'SEM_FONTE'} | {item.note}")
    claims_by_section = {section.section_id: [] for section in report.sections}
    for claim in report.claims:
        claims_by_section[claim.section_id].append(claim)
    answers_by_section = {section.section_id: [] for section in report.sections}
    for answer in report.answers:
        answers_by_section[answer.section_id].append(answer)
    for section in sorted(report.sections, key=lambda item: item.order):
        lines.append(f"SEÇÃO {section.order} | {section.title}")
        for claim in claims_by_section[section.section_id]:
            lines.append(f"AFIRMAÇÃO | {claim.claim_id} | {claim.authority.value} | {claim.text}")
            lines.extend(f"PROVENIÊNCIA | {item.source_kind} | {item.source_id} | revisão {item.source_revision}" for item in claim.provenance)
        for answer in answers_by_section[section.section_id]:
            lines.extend((
                f"QUESITO | {answer.question_id}", f"RESPOSTA | {answer.text}",
                f"ACHADO | {answer.finding_id}", f"EVIDÊNCIAS | {', '.join(answer.evidence_ids)}",
                f"MÉTODOS | {', '.join(answer.method_ids)}", f"DECISÃO | {answer.decision_id}",
            ))
    for decision in report.review_decisions:
        lines.append(f"REVISÃO PROFISSIONAL | {decision.action.value} | {decision.professional_id} | {decision.reason} | {decision.timestamp}")
    return tuple(lines)


def _inject_canonical_report(content: bytes, report: ReportSnapshot) -> bytes:
    try:
        with ZipFile(BytesIO(content)) as source:
            parts = {item.filename: source.read(item.filename) for item in source.infolist()}
        root = ElementTree.fromstring(parts["word/document.xml"])
    except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValueError("bound Word artifact is invalid") from exc
    controls = []
    for control in root.iter(f"{_W}sdt"):
        tags = control.findall(f"./{_W}sdtPr/{_W}tag")
        if any(item.attrib.get(f"{_W}val") == "CANONICAL_REPORT" for item in tags):
            controls.append(control)
    if len(controls) != 1:
        raise ValueError("template requires exactly one CANONICAL_REPORT content control")
    target = controls[0].find(f"{_W}sdtContent")
    if target is None:
        raise ValueError("CANONICAL_REPORT content control is incomplete")
    target.clear()
    for line in _canonical_report_lines(report):
        target.append(_paragraph(line))
    parts["word/document.xml"] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        for name, value in parts.items():
            package.writestr(name, value)
    return output.getvalue()


def validate_final_artifact(content: bytes, output_format: str) -> tuple[str, int, str]:
    if type(content) is not bytes or not content:
        raise ValueError("final artifact bytes are empty")
    if output_format in {"DOCX", "DOCM"}:
        try:
            with ZipFile(BytesIO(content)) as package:
                names = set(package.namelist())
                if not {"[Content_Types].xml", "word/document.xml"} <= names:
                    raise ValueError("final Word artifact is incomplete")
                has_macro = "word/vbaProject.bin" in names
                for name in names:
                    if name.endswith(".rels"):
                        root = ElementTree.fromstring(package.read(name))
                        if any(item.attrib.get("TargetMode", "").lower() == "external" for item in root.iter(f"{_REL}Relationship")):
                            raise ValueError("external relationships are forbidden in delivery artifacts")
        except (BadZipFile, OSError) as exc:
            raise ValueError("final Word artifact is invalid") from exc
        if has_macro != (output_format == "DOCM"):
            raise ValueError("final Word artifact macro identity changed")
        media_type = _DOCM_MEDIA if has_macro else _DOCX_MEDIA
    elif output_format == "PDF":
        stripped = content.rstrip()
        if not content.startswith(b"%PDF-") or not stripped.endswith(b"%%EOF") or re.search(rb"/Type\s*/Page\b", content) is None:
            raise ValueError("final PDF artifact is invalid")
        media_type = _PDF_MEDIA
    else:
        raise ValueError("unsupported final artifact format")
    return sha256(content).hexdigest(), len(content), media_type


def validate_supporting_artifact(content: bytes, media_type: str) -> tuple[str, int, str]:
    """Verify non-Office supporting bytes without trusting filename metadata."""
    if type(content) is not bytes or not content:
        raise ValueError("supporting artifact bytes are empty")
    if media_type == "image/jpeg":
        if not (content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")):
            raise ValueError("supporting JPEG artifact is invalid")
    elif media_type == "image/png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("supporting PNG artifact is invalid")
    else:
        raise ValueError("unsupported supporting artifact media type")
    return sha256(content).hexdigest(), len(content), media_type


def safe_pdf_conversion_copy(content: bytes, output_format: str) -> tuple[bytes, str]:
    """Build a macro-free, external-link-free copy used only by the local PDF renderer."""
    validate_final_artifact(content, output_format)
    if output_format == "DOCX":
        return content, output_format
    with ZipFile(BytesIO(content)) as source:
        parts = {item.filename: source.read(item.filename) for item in source.infolist() if item.filename not in {"word/vbaProject.bin", "word/vbaData.xml"}}
    content_types = ElementTree.fromstring(parts["[Content_Types].xml"])
    for item in tuple(content_types):
        if item.attrib.get("PartName") in {"/word/vbaProject.bin", "/word/vbaData.xml"}:
            content_types.remove(item)
        elif "macroEnabled.main+xml" in item.attrib.get("ContentType", ""):
            item.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")
    parts["[Content_Types].xml"] = ElementTree.tostring(content_types, encoding="utf-8", xml_declaration=True)
    for name in tuple(parts):
        if not name.endswith(".rels"):
            continue
        root = ElementTree.fromstring(parts[name])
        for item in tuple(root):
            if "vbaProject" in item.attrib.get("Type", "") or item.attrib.get("Target", "").endswith(("vbaProject.bin", "vbaData.xml")):
                root.remove(item)
        parts[name] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        for name, value in parts.items():
            package.writestr(name, value)
    validate_final_artifact(output.getvalue(), "DOCX")
    return output.getvalue(), "DOCX"


def verify_reopened_artifact(
    *, content: bytes, output_format: str, expected_size: int, expected_sha256: str,
) -> None:
    digest, size, _ = validate_final_artifact(content, output_format)
    if size != expected_size or digest != expected_sha256:
        raise ValueError("reopened artifact bytes diverge from finalized manifest")
