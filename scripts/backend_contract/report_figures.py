"""Figures in the report: the presentation derivative and the numbering.

PHOTO_ORIGINAL != REPORT_PRESENTATION_DERIVATIVE.  The original stays intact
in private storage; the document carries a derivative made from it here --
upright, at most FIGURE_EDGE pixels on its long side, re-encoded as JPEG
without any metadata (no camera data, no embedded location).  The derivative
is a pure function of the original bytes, so the same report always renders
the same image.

Figures are numbered in document order: by the report's section order, then
by the expert's order within a section.  Text cites them by marker --
``[[FIGURA:PHOTO-…]]`` and ``[[TABELA:ACHADOS]]`` -- and the presentation
resolves each marker to "Figura N" / "Tabela 1", so reordering the figures
never leaves a stale number in the prose.  No Word field is involved.
"""

from __future__ import annotations

from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .report_foundation import FIGURE_TOKEN, FINDINGS_TABLE_KEY, TABLE_TOKEN, ReportSnapshot

FIGURE_EDGE = 1600
FIGURE_QUALITY = 85


def figure_presentation_image(original: bytes) -> bytes:
    """The derivative the document shows: upright, bounded, metadata-free JPEG."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(original)) as source:
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("figure original is truncated or corrupt") from exc
    image.thumbnail((FIGURE_EDGE, FIGURE_EDGE), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="JPEG", quality=FIGURE_QUALITY, optimize=False, progressive=False)
    return output.getvalue()


def image_size(content: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(content)) as image:
        return image.size


def figure_numbers(report: ReportSnapshot) -> dict[str, int]:
    """Figure identity -> its number in the document."""
    order = {section.kind: section.order for section in report.sections}
    figures = sorted(
        enumerate(report.figures or ()),
        key=lambda item: (order.get(item[1].section_kind, 0), item[0]),
    )
    return {figure.figure_id: number for number, (_index, figure) in enumerate(figures, 1)}


def resolve_references(text: str, numbers: dict[str, int]) -> str:
    """Prose with its figure and table markers turned into their labels."""
    text = FIGURE_TOKEN.sub(lambda match: f"Figura {numbers[match.group(1)]}", text)
    return TABLE_TOKEN.sub(lambda match: "Tabela 1" if match.group(1) == FINDINGS_TABLE_KEY else match.group(0), text)
