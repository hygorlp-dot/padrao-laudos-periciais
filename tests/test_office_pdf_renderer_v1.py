from __future__ import annotations

from pathlib import Path

import pytest

from scripts.backend_contract.infrastructure.office_pdf import (
    LocalOfficePdfConverter,
    RendererUnavailable,
)


class _FakeDocument:
    def __init__(self, output: Path, calls: list[tuple]) -> None:
        self.output = output
        self.calls = calls

    def ExportAsFixedFormat(self, **kwargs) -> None:
        self.calls.append(("export", kwargs["OutputFileName"], kwargs["ExportFormat"], kwargs))
        Path(kwargs["OutputFileName"]).write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF")

    def Close(self, **kwargs) -> None:
        self.calls.append(("close", kwargs))


class _FakeWord:
    Version = "16.0-test"

    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls
        self.Documents = self

    def Open(self, **kwargs):
        kwargs["_source_bytes"] = Path(kwargs["FileName"]).read_bytes()
        self.calls.append(("open", kwargs))
        return _FakeDocument(Path(kwargs["FileName"]), self.calls)

    def Quit(self, **kwargs) -> None:
        self.calls.append(("quit", kwargs))


def test_word_com_converter_uses_private_copy_and_returns_local_pdf(tmp_path: Path) -> None:
    calls: list[tuple] = []
    source = b"synthetic-bound-word-bytes"
    converter = LocalOfficePdfConverter(word_factory=lambda: _FakeWord(calls), temp_root=tmp_path)

    output = converter.convert(source, "DOCX")

    assert output.startswith(b"%PDF-1.7")
    opened = next(item for item in calls if item[0] == "open")[1]
    assert tmp_path in Path(opened["FileName"]).parents
    assert opened["_source_bytes"] == source
    assert opened["ReadOnly"] is True
    assert opened["AddToRecentFiles"] is False
    assert next(item for item in calls if item[0] == "export")[2] == 17
    assert any(item[0] == "close" for item in calls)
    assert any(item[0] == "quit" for item in calls)
    assert converter.renderer_version == "16.0-test"


def test_word_com_converter_rejects_invalid_input_and_fails_closed() -> None:
    converter = LocalOfficePdfConverter(word_factory=lambda: _FakeWord([]))
    with pytest.raises(ValueError, match="DOCX or DOCM"):
        converter.convert(b"bytes", "PDF")
    with pytest.raises(ValueError, match="bytes"):
        converter.convert("not-bytes", "DOCX")  # type: ignore[arg-type]


def test_word_com_converter_missing_automation_dependency_is_unavailable() -> None:
    converter = LocalOfficePdfConverter(word_factory=lambda: (_ for _ in ()).throw(RendererUnavailable("missing")))
    with pytest.raises(RendererUnavailable, match="missing"):
        converter.convert(b"synthetic", "DOCX")
