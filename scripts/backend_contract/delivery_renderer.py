"""Protected delivery rendering and final-byte integrity checks."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import re
from zipfile import BadZipFile, ZipFile

from .report_foundation import ReportSnapshot
from .report_template import (
    DocumentBindingResult,
    TemplateBindingManifest,
    bind_report_template,
)


_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_DOCM_MEDIA = "application/vnd.ms-word.document.macroEnabled.12"
_PDF_MEDIA = "application/pdf"


def render_word_candidate(
    *, template_bytes: bytes, report: ReportSnapshot, manifest: TemplateBindingManifest,
) -> DocumentBindingResult:
    result = bind_report_template(template_bytes, report, manifest)
    validate_final_artifact(result.output_bytes, manifest.output_kind)
    return result


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


def verify_reopened_artifact(
    *, content: bytes, output_format: str, expected_size: int, expected_sha256: str,
) -> None:
    digest, size, _ = validate_final_artifact(content, output_format)
    if size != expected_size or digest != expected_sha256:
        raise ValueError("reopened artifact bytes diverge from finalized manifest")
