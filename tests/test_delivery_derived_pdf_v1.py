"""PR #203: the Phase C Word to PDF renderer made productively reachable.

These tests live outside tests/test_delivery_foundation_v1.py, which the
capability trust plane scopes to the Word COM containment transition.
"""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from scripts.backend_contract import delivery_renderer
from scripts.backend_contract.application.delivery_foundation import RenderDeliveryPackage
from scripts.backend_contract.application.ports import RepositoryConflict, RepositoryIntegrityError
from scripts.backend_contract.delivery_foundation import (
    DeliveryArtifact,
    DeliveryFormat,
    DeliveryPackage,
    DeliveryRole,
    DeliverySnapshot,
    DeliveryState,
    DerivedPdfRenderer,
    delivery_snapshot_from_mapping,
    delivery_snapshot_to_mapping,
)
from scripts.backend_contract.delivery_renderer import DELIVERY_RENDERING_VERSION
from scripts.backend_contract.report_foundation import report_snapshot_to_mapping
from scripts.backend_contract.report_template import template_binding_manifest_from_mapping
from tests.opc_word_fixtures import DOCM_MAIN_TYPE, VBA_PROJECT_TYPE, bound_template_document, word_package
from tests.test_delivery_foundation_v1 import (
    SHA_A,
    _approved_report,
    _delivery_attachment_service,
    _parseable_text_pdf,
    binding,
    snapshot,
)


# --- PR #203: the Phase C renderer made productively reachable -------------------

_PDF_MEDIA = "application/pdf"
_DERIVED_RENDERER = DerivedPdfRenderer(
    renderer_type="MICROSOFT_WORD_DESKTOP_COM", renderer_version="16.0.19029", platform="win32",
)


def _word_artifact(output_format: DeliveryFormat = DeliveryFormat.DOCX, *, index: int = 1) -> DeliveryArtifact:
    return DeliveryArtifact(
        artifact_id=f"ARTIFACT-WORD-{index}", role=DeliveryRole.MAIN_REPORT, format=output_format,
        filename=f"laudo-{index}.{output_format.value.lower()}",
        content_id=f"7777777{index}-7777-4777-8777-777777777777",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", byte_size=10,
        checksum_sha256=SHA_A,
    )


def _pdf_artifact(*, index: int = 1) -> DeliveryArtifact:
    return DeliveryArtifact(
        artifact_id=f"ARTIFACT-PDF-{index}", role=DeliveryRole.DERIVED_PDF, format=DeliveryFormat.PDF,
        filename=f"laudo-{index}.pdf", content_id=f"8888888{index}-8888-4888-8888-888888888888",
        media_type=_PDF_MEDIA, byte_size=10, checksum_sha256=SHA_A,
    )


def _with(artifacts: tuple[DeliveryArtifact, ...], renderer: DerivedPdfRenderer | None) -> DeliverySnapshot:
    return replace(
        snapshot(), artifacts=artifacts, derived_pdf_renderer=renderer,
        package=DeliveryPackage("1.0.0", tuple(item.artifact_id for item in artifacts)),
    )


def test_a_derived_pdf_travels_with_closed_renderer_provenance_and_round_trips() -> None:
    value = _with((_word_artifact(), _pdf_artifact()), _DERIVED_RENDERER)
    mapping = delivery_snapshot_to_mapping(value)
    assert mapping["derived_pdf_renderer"] == {
        "renderer_type": "MICROSOFT_WORD_DESKTOP_COM", "renderer_version": "16.0.19029", "platform": "win32",
    }
    assert delivery_snapshot_from_mapping(mapping) == value
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/delivery-snapshot-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(mapping)


def test_snapshots_persisted_before_derived_pdfs_keep_their_exact_mapping() -> None:
    value = snapshot()
    mapping = delivery_snapshot_to_mapping(value)
    # No new key appears, so every stored digest over the canonical mapping holds.
    assert "derived_pdf_renderer" not in mapping
    assert delivery_snapshot_from_mapping(mapping) == value
    assert delivery_snapshot_to_mapping(delivery_snapshot_from_mapping(mapping)) == mapping


@pytest.mark.parametrize(
    ("artifacts", "renderer"),
    [
        ((_word_artifact(), _pdf_artifact()), None),
        ((_word_artifact(),), _DERIVED_RENDERER),
        ((_pdf_artifact(),), _DERIVED_RENDERER),
        ((_word_artifact(), _pdf_artifact(), _pdf_artifact(index=2)), _DERIVED_RENDERER),
    ],
    ids=["pdf-without-provenance", "provenance-without-pdf", "pdf-without-word", "two-derived-pdfs"],
)
def test_derived_pdf_invariants_fail_closed(artifacts, renderer) -> None:
    with pytest.raises(ValueError, match="derived PDF"):
        _with(artifacts, renderer)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("renderer_type", "WORD.APPLICATION"),
        ("renderer_version", "UNKNOWN"),
        ("renderer_version", "17.0"),
        ("platform", "linux"),
    ],
)
def test_renderer_provenance_is_a_closed_vocabulary(field, value) -> None:
    values = {"renderer_type": "MICROSOFT_WORD_DESKTOP_COM", "renderer_version": "16.0.1", "platform": "win32"}
    values[field] = value
    with pytest.raises(ValueError, match="renderer"):
        DerivedPdfRenderer(**values)


def _render_fixture(output_kind="DOCX", *, artifacts=(), renderer=None, state=DeliveryState.DRAFT):
    report = _approved_report()
    document = bound_template_document()
    parts = {
        "word/styles.xml": "<styles/>",
        "word/numbering.xml": "<numbering/>",
        "docProps/custom.xml": (
            '<Properties><property name="TEMPLATE_ID"><value>TEMPLATE-1</value></property></Properties>'
        ),
    }
    if output_kind == "DOCM":
        template = word_package(
            document, main_type=DOCM_MAIN_TYPE,
            parts={**parts, "word/vbaProject.bin": b"synthetic macro"},
            overrides={"/word/vbaProject.bin": VBA_PROJECT_TYPE},
        )
    else:
        template = word_package(document, parts=parts)
    manifest = template_binding_manifest_from_mapping({
        "schema_version": "1.0.0", "template_id": "TEMPLATE-1", "output_kind": output_kind,
        "bindings": [
            {"field": "EXPERT_FULL_NAME", "placeholder": "[[EXPERT_FULL_NAME]]"},
            {"field": "EXPERT_REGISTRATION", "placeholder": "[[EXPERT_REGISTRATION]]"},
            {"field": "REPORT_ID", "placeholder": "[[REPORT_ID]]"},
        ],
    })
    report_digest = sha256(json.dumps(
        report_snapshot_to_mapping(report), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    current = replace(
        snapshot(), binding=replace(binding(), report_digest=report_digest),
        template_format=DeliveryFormat(output_kind), template_digest=sha256(template).hexdigest(),
        rendering_version=DELIVERY_RENDERING_VERSION, artifacts=artifacts, derived_pdf_renderer=renderer,
        package=DeliveryPackage("1.0.0", tuple(item.artifact_id for item in artifacts)),
    )
    if state is DeliveryState.STALE:
        current = replace(
            current, state=DeliveryState.STALE, stale_reasons=("REPORT_DIGEST_CHANGED",),
            stale_origin_state=DeliveryState.DRAFT,
        )
    return report, template, manifest, current


class _Store:
    def __init__(self, *, corrupt_suffix: str | None = None) -> None:
        self.stored: list[tuple[str, bytes]] = []
        self._corrupt_suffix = corrupt_suffix

    def execute(self, *, workspace_id, original_filename, content, media_type, origin):
        self.stored.append((original_filename, content))
        digest = sha256(content).hexdigest()
        if self._corrupt_suffix and original_filename.endswith(self._corrupt_suffix):
            digest = "0" * 64
        return SimpleNamespace(
            content_id=UUID(f"{len(self.stored):08d}-9999-4999-8999-999999999999"),
            byte_size=len(content), checksum_sha256=digest,
        )


class _Saver:
    def __init__(self) -> None:
        self.saved: list[DeliverySnapshot] = []

    def execute(self, _workspace_id, value, _expected_revision, *, allow_artifacts):
        assert allow_artifacts is True
        self.saved.append(value)
        return SimpleNamespace(revision=value.revision)


def _render_service(output_kind="DOCX", *, converter=None, store=None, artifacts=(), renderer=None,
                    state=DeliveryState.DRAFT):
    report, template, manifest, current = _render_fixture(
        output_kind, artifacts=artifacts, renderer=renderer, state=state,
    )
    counter = iter(range(1, 100))
    saver = _Saver()
    store = store or _Store()
    service = RenderDeliveryPackage(
        get_snapshot=SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=1), current)),
        get_report=SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=1), report)),
        get_private_content=SimpleNamespace(execute=lambda _w, _c: SimpleNamespace(
            content=template, metadata=SimpleNamespace(checksum_sha256=sha256(template).hexdigest()),
        )),
        store_private_content=store, save_snapshot=saver,
        ids=SimpleNamespace(new_uuid=lambda: UUID(f"{next(counter):08d}-aaaa-4aaa-8aaa-aaaaaaaaaaaa")),
        pdf_converter=converter,
    )
    return service, manifest, store, saver


class _Converter:
    renderer_type = "MICROSOFT_WORD_DESKTOP_COM"
    platform = "win32"

    def __init__(self, behaviour, *, renderer_version: str = "16.0.19029") -> None:
        self._behaviour = behaviour
        self.renderer_version = renderer_version
        self.received: list[tuple[bytes, str]] = []

    def convert(self, content: bytes, source_format: str) -> bytes:
        self.received.append((content, source_format))
        return self._behaviour(content)


def _faithful_pdf(monkeypatch) -> bytes:
    """A structurally valid PDF whose fidelity to the Word is taken as proven.

    The fidelity oracle is Phase C authority with its own tests; what is under
    test here is the application's persistence and binding of a proven PDF.
    """
    monkeypatch.setattr(delivery_renderer, "_validate_pdf_fidelity", lambda _word, _pdf: None)
    return _parseable_text_pdf("Laudo derivado sintetico")


@pytest.mark.parametrize("output_kind", ["DOCX", "DOCM"])
def test_render_persists_the_authoritative_word_and_a_bound_derived_pdf(monkeypatch, output_kind) -> None:
    pdf = _faithful_pdf(monkeypatch)
    converter = _Converter(lambda _content: pdf)
    service, manifest, store, saver = _render_service(output_kind, converter=converter)

    _saved, rendered = service.execute("workspace-1", manifest=manifest, expected_revision=1)

    word, derived = rendered.artifacts
    assert (word.role, word.format) == (DeliveryRole.MAIN_REPORT, DeliveryFormat(output_kind))
    assert (derived.role, derived.format, derived.media_type) == (
        DeliveryRole.DERIVED_PDF, DeliveryFormat.PDF, _PDF_MEDIA,
    )
    # The converter received exactly the bytes the MAIN_REPORT artifact binds.
    stored = dict(store.stored)
    assert converter.received == [(stored[word.filename], output_kind)]
    assert sha256(stored[word.filename]).hexdigest() == word.checksum_sha256
    assert stored[derived.filename] == pdf
    assert derived.checksum_sha256 == sha256(pdf).hexdigest()
    assert rendered.derived_pdf_renderer == _DERIVED_RENDERER
    assert rendered.rendering_version == DELIVERY_RENDERING_VERSION
    assert saver.saved == [rendered]


def _raise(error: BaseException):
    def behaviour(_content: bytes) -> bytes:
        raise error
    return behaviour


def _unavailable():
    from scripts.backend_contract.infrastructure.office_pdf import RendererUnavailable

    return _raise(RendererUnavailable("owned Word job did not close cleanly"))


@pytest.mark.parametrize(
    "behaviour",
    [
        _unavailable(),
        _raise(TimeoutError("worker timeout")),
        _raise(RuntimeError("conversion failed")),
        _raise(OSError("render root vanished")),
        lambda _content: b"not a pdf",
        lambda _content: _parseable_text_pdf("RELATORIO-SEM-RELACAO"),
    ],
    ids=[
        "renderer-unavailable", "worker-timeout", "conversion-failure", "os-failure",
        "invalid-pdf", "structural-infidelity",
    ],
)
def test_every_pdf_refusal_leaves_the_word_and_no_pdf(behaviour) -> None:
    service, manifest, store, saver = _render_service(converter=_Converter(behaviour))

    _saved, rendered = service.execute("workspace-1", manifest=manifest, expected_revision=1)

    assert [item.role for item in rendered.artifacts] == [DeliveryRole.MAIN_REPORT]
    assert rendered.derived_pdf_renderer is None
    assert not any(name.endswith(".pdf") for name, _ in store.stored)
    assert saver.saved == [rendered]


def test_a_visual_fidelity_refusal_leaves_no_pdf(monkeypatch) -> None:
    def refuse(_word: bytes, _pdf: bytes) -> None:
        raise ValueError("final PDF does not faithfully represent the Word: text is not visibly painted")

    monkeypatch.setattr(delivery_renderer, "_validate_pdf_fidelity", refuse)
    service, manifest, store, _saver = _render_service(
        converter=_Converter(lambda _c: _parseable_text_pdf("x")),
    )

    _saved, rendered = service.execute("workspace-1", manifest=manifest, expected_revision=1)

    assert [item.role for item in rendered.artifacts] == [DeliveryRole.MAIN_REPORT]
    assert not any(name.endswith(".pdf") for name, _ in store.stored)


def test_unknown_renderer_provenance_leaves_no_pdf(monkeypatch) -> None:
    pdf = _faithful_pdf(monkeypatch)
    service, manifest, store, _saver = _render_service(
        converter=_Converter(lambda _c: pdf, renderer_version="UNKNOWN"),
    )

    _saved, rendered = service.execute("workspace-1", manifest=manifest, expected_revision=1)

    assert [item.role for item in rendered.artifacts] == [DeliveryRole.MAIN_REPORT]
    assert rendered.derived_pdf_renderer is None
    assert not any(name.endswith(".pdf") for name, _ in store.stored)


@pytest.mark.parametrize("suffix", [".pdf", ".docx"])
def test_storage_that_changes_either_artifact_fails_the_whole_render_closed(monkeypatch, suffix) -> None:
    pdf = _faithful_pdf(monkeypatch)
    service, manifest, _store, saver = _render_service(
        converter=_Converter(lambda _c: pdf), store=_Store(corrupt_suffix=suffix),
    )

    with pytest.raises(RepositoryIntegrityError):
        service.execute("workspace-1", manifest=manifest, expected_revision=1)

    assert saver.saved == []


def test_a_stale_delivery_cannot_render(monkeypatch) -> None:
    pdf = _faithful_pdf(monkeypatch)
    converter = _Converter(lambda _c: pdf)
    service, manifest, store, saver = _render_service(converter=converter, state=DeliveryState.STALE)

    with pytest.raises(RepositoryConflict):
        service.execute("workspace-1", manifest=manifest, expected_revision=1)

    assert converter.received == [] and store.stored == [] and saver.saved == []


def test_re_rendering_never_carries_the_previous_derived_pdf_forward() -> None:
    previous = (_word_artifact(), _pdf_artifact())
    service, manifest, _store, _saver = _render_service(
        converter=_Converter(_raise(RuntimeError("Word unavailable now"))),
        artifacts=previous, renderer=_DERIVED_RENDERER,
    )

    _saved, rendered = service.execute("workspace-1", manifest=manifest, expected_revision=1)

    assert [item.role for item in rendered.artifacts] == [DeliveryRole.MAIN_REPORT]
    assert not {item.artifact_id for item in rendered.artifacts} & {item.artifact_id for item in previous}
    assert rendered.derived_pdf_renderer is None


def test_rendering_keeps_exact_renderer_version_equality() -> None:
    service, manifest, _store, _saver = _render_service()
    current = service.get_snapshot.execute("workspace-1")[1]
    drifted = replace(current, rendering_version=f"{DELIVERY_RENDERING_VERSION}|type=MICROSOFT_WORD_DESKTOP_COM")
    service = replace(
        service, get_snapshot=SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=1), drifted)),
    )

    with pytest.raises(ValueError, match="provenance mismatch"):
        service.execute("workspace-1", manifest=manifest, expected_revision=1)


def test_a_derived_pdf_cannot_enter_through_generic_attachment() -> None:
    service, content_id, saved = _delivery_attachment_service(_parseable_text_pdf("Anexo"), "application/pdf")

    with pytest.raises(ValueError, match="protected rendering"):
        service.execute(
            "workspace-1", expected_revision=1, content_id=content_id, role=DeliveryRole.DERIVED_PDF.value,
        )

    assert saved == []



# --- PR #203: SAME_RENDERED_LINE is decided by geometry, in PDF coordinates ------
#
# pdfium reports bottom-up coordinates (top > bottom).  Line grouping measured
# max(bottom) - min(top), which in that orientation is the GAP between two
# lines, so a tall glyph such as "|" or "/" shrank the gap below the tolerance
# and merged two rendered lines -- inverting the reading order of a faithful
# Word 16 render of the product's own canonical text.

_FIXTURES = Path(__file__).parent / "fixtures"


def _line(text: str, bottom: float, top: float, *, x: float = 72.0, right: float = 300.0,
          size: float = 12.0, page: int = 0) -> "delivery_renderer._PositionedText":
    return delivery_renderer._PositionedText(
        page, delivery_renderer._normalized_visible_text(text), x, bottom, size, right, bottom, top,
        strict_text=text,
    )


def test_real_word_render_with_a_pipe_on_the_second_line_is_faithful() -> None:
    """RED_THIS_REPAIR: the exact Word 16 PDF of the reproduced product gap."""
    word = (_FIXTURES / "word16-reading-order-pipe.docx").read_bytes()
    pdf = (_FIXTURES / "word16-reading-order-pipe.pdf").read_bytes()

    delivery_renderer._validate_pdf_fidelity(word, pdf)


def test_a_tall_glyph_cannot_bridge_two_rendered_lines() -> None:
    """RED_THIS_REPAIR: the geometry measured in that Word 16 PDF."""
    # Exactly as pdfium laid them out: Word starts the second line 0.8pt left.
    first = _line("Primeiro paragrafo curto", 707.66, 717.99, x=86.11, right=205.40)
    second = _line("A | B curto", 693.02, 703.54, x=85.31, right=137.64)

    ordered = delivery_renderer._positioned_reading_order([second, first])

    assert [item.strict_text for item in ordered] == ["Primeiro paragrafo curto", "A | B curto"]
    assert delivery_renderer._ordered_text_blocks_match(
        ["Primeiro paragrafo curto", "A | B curto"], ordered, [],
    )


@pytest.mark.parametrize(
    ("glyph", "bottom", "top"),
    [
        ("|", 693.02, 703.54),  # tall bar reaching into the leading
        ("/", 693.40, 703.30),
        ("hlk", 695.12, 704.10),  # ascenders
        ("gjpq", 692.60, 700.90),  # descenders
        ("ÁÇÕ", 692.80, 705.20),  # accents above and cedilla below
    ],
)
def test_line_grouping_follows_the_rendered_line_not_one_glyph(glyph, bottom, top) -> None:
    """Sibling sweep of the same invariant: the second line stays the second line."""
    first = _line("Primeira linha", 707.66, 717.99, x=86.11)
    second = _line(f"Segunda {glyph} linha", bottom, top, x=85.31)

    ordered = delivery_renderer._positioned_reading_order([second, first])

    assert [item.strict_text for item in ordered] == ["Primeira linha", f"Segunda {glyph} linha"]


@pytest.mark.parametrize("leading", [12.5, 14.4, 30.0])
def test_consecutive_lines_stay_separate_at_small_and_large_leading(leading) -> None:
    lines = [
        _line(f"Linha {index}", 700.0 - index * leading - 2.9, 700.0 - index * leading + 8.6, x=90.0 - index)
        for index in range(4)
    ]

    ordered = delivery_renderer._positioned_reading_order(list(reversed(lines)))

    assert [item.strict_text for item in ordered] == [f"Linha {index}" for index in range(4)]


def test_fragments_of_one_rendered_line_are_still_one_line_in_horizontal_order() -> None:
    """Mixed glyph heights and near font sizes on one baseline remain one line."""
    fragments = [
        _line("B curto", 695.14, 702.72, x=110.0, right=160.0, size=12.0),
        _line("A", 695.12, 702.76, x=72.0, right=80.0, size=12.0),
        _line("|", 693.02, 703.54, x=90.0, right=94.0, size=11.5),
    ]

    ordered = delivery_renderer._positioned_reading_order(fragments)

    assert [item.strict_text for item in ordered] == ["A", "|", "B curto"]


def test_same_line_fragments_in_the_wrong_horizontal_order_are_rejected() -> None:
    fragments = [
        _line("mundo", 695.1, 702.7, x=72.0, right=110.0),
        _line("Ola", 695.1, 702.7, x=120.0, right=150.0),
    ]
    ordered = delivery_renderer._positioned_reading_order(fragments)

    assert not delivery_renderer._ordered_text_blocks_match(["Ola mundo"], ordered, [])


def test_genuinely_reordered_paragraphs_are_still_rejected() -> None:
    upper = _line("A | B curto", 707.66, 717.99)
    lower = _line("Primeiro paragrafo curto", 693.02, 703.54)
    ordered = delivery_renderer._positioned_reading_order([upper, lower])

    assert not delivery_renderer._ordered_text_blocks_match(
        ["Primeiro paragrafo curto", "A | B curto"], ordered, [],
    )


def test_page_order_is_preserved_before_vertical_order() -> None:
    later_page_high = _line("Pagina dois", 760.0, 770.0, x=60.0, page=1)
    first_page_low = _line("Pagina um", 60.0, 70.0, x=90.0, page=0)

    ordered = delivery_renderer._positioned_reading_order([later_page_high, first_page_low])

    assert [item.strict_text for item in ordered] == ["Pagina um", "Pagina dois"]


@pytest.mark.parametrize("separator", [";", "·"])
def test_short_glyph_separators_on_the_second_line_stay_ordered(separator) -> None:
    first = _line("Primeiro paragrafo curto", 707.66, 717.99, x=86.11)
    second = _line(f"A {separator} B curto", 695.10, 702.80, x=85.31)

    ordered = delivery_renderer._positioned_reading_order([second, first])

    assert [item.strict_text for item in ordered] == ["Primeiro paragrafo curto", f"A {separator} B curto"]



# --- PR #203: pdfium's line-end hyphen marker, restored only where proven ------------
#
# Word 16 breaking "FINDING-" / "1B38..." across two lines paints a hyphen, and
# pypdf extracts "FINDING-".  pdfium's text page reports that hyphen as U+0002,
# flagged as a hyphen and not generated.  The oracle compared "\x02" with "-" and
# refused a faithful PDF of the product's own canonical text.


def _fixture_pair(word_name: str, pdf_name: str) -> tuple[bytes, bytes]:
    # Full file names, so the fixture registry can see each file exercised here.
    return (_FIXTURES / word_name).read_bytes(), (_FIXTURES / pdf_name).read_bytes()


@pytest.mark.parametrize(
    ("word_name", "pdf_name"),
    [
        ("word16-line-end-hyphen.docx", "word16-line-end-hyphen.pdf"),
        ("word16-line-end-hyphens-multiple.docx", "word16-line-end-hyphens-multiple.pdf"),
    ],
)
def test_word_16_line_end_hyphens_are_read_as_the_hyphens_word_painted(word_name, pdf_name) -> None:
    """RED_THIS_REPAIR: one and three proven line-end hyphens."""
    word, pdf = _fixture_pair(word_name, pdf_name)

    fragments = "".join(item.strict_text for item in delivery_renderer._pdfium_visible_layout(pdf)[0])
    assert "\x02" not in fragments
    delivery_renderer._validate_pdf_fidelity(word, pdf)


@pytest.mark.parametrize(
    ("word_name", "pdf_name"),
    [
        ("word16-line-end-hyphen-nowrap.docx", "word16-line-end-hyphen-nowrap.pdf"),
        ("word16-line-end-hyphen-with-tail.docx", "word16-line-end-hyphen-with-tail.pdf"),
    ],
)
def test_hyphenated_identifiers_with_and_without_a_wrap_stay_faithful(word_name, pdf_name) -> None:
    word, pdf = _fixture_pair(word_name, pdf_name)

    delivery_renderer._validate_pdf_fidelity(word, pdf)


@pytest.mark.parametrize(
    "mutated",
    [
        "word16-line-end-hyphen-missing.pdf",
        "word16-line-end-hyphen-replaced.pdf",
        "word16-line-end-hyphen-id-changed.pdf",
        "word16-line-end-hyphen-reordered.pdf",
    ],
)
def test_a_pdf_that_really_changed_the_hyphenated_text_is_still_refused(mutated) -> None:
    word, pdf = _fixture_pair("word16-line-end-hyphen-with-tail.docx", mutated)

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, pdf)


_OBJECT = (100.0, 700.0, 400.0, 712.0)
_PROVEN_INSIDE = [(380.0, 705.0, 383.0, 706.0)]


@pytest.mark.parametrize(
    ("raw", "proven", "expected"),
    [
        ("FINDING\x02", _PROVEN_INSIDE, ("FINDING-", True)),
        ("FINDING-1B38", [], ("FINDING-1B38", True)),
        ("A\x02B\x02", _PROVEN_INSIDE * 2, ("A-B-", True)),
    ],
    ids=["proven-marker", "inline-hyphen", "two-proven-markers"],
)
def test_only_proven_markers_are_restored(raw, proven, expected) -> None:
    assert delivery_renderer._restore_pdfium_line_end_hyphens(raw, _OBJECT, proven) == expected


@pytest.mark.parametrize(
    ("raw", "proven"),
    [
        ("FINDING\x02", []),
        ("FINDING\x02", [(10.0, 705.0, 13.0, 706.0)]),
        ("A\x02B\x02", _PROVEN_INSIDE),
        ("FINDING\x01", _PROVEN_INSIDE),
        ("FINDING\x03", _PROVEN_INSIDE),
        ("FINDING\x1f", []),
        ("FINDING\x7f", []),
        ("FINDING\x00", []),
    ],
    ids=[
        "unproven-u0002", "proven-glyph-outside-object", "more-markers-than-proof",
        "u0001", "u0003", "other-c0", "delete", "nul",
    ],
)
def test_every_other_control_leaves_the_layout_unsafe(raw, proven) -> None:
    _text, modeled = delivery_renderer._restore_pdfium_line_end_hyphens(raw, _OBJECT, proven)

    assert modeled is False


def test_material_text_distinctions_survive_the_extraction_repair() -> None:
    """Only the pdfium marker is modeled; strict identity is untouched."""
    for left, right in (("m²", "m2"), ("1º", "1o"), ("REJEITADO", "rejeitado"), ("-", "_")):
        assert delivery_renderer._strict_visible_text(left) != delivery_renderer._strict_visible_text(right)
    assert delivery_renderer._restore_pdfium_line_end_hyphens("m² 1º REJEITADO", _OBJECT, []) == (
        "m² 1º REJEITADO", True,
    )
