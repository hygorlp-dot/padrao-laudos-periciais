"""Fail-closed local Office-to-PDF conversion without network egress."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile


class LocalOfficePdfConverter:
    """Convert a sanitized DOCX using an installed local Office engine."""

    def convert(self, content: bytes, source_format: str) -> bytes:
        if type(content) is not bytes or not content or source_format != "DOCX":
            raise ValueError("local PDF conversion requires nonempty sanitized DOCX bytes")
        with tempfile.TemporaryDirectory(prefix="pericial-pdf-") as directory:
            root = Path(directory)
            source = root / "bound-report.docx"
            target = root / "bound-report.pdf"
            source.write_bytes(content)
            soffice = shutil.which("soffice") or shutil.which("libreoffice")
            if soffice:
                self._convert_with_libreoffice(soffice, source, root)
            elif self._word_executable().is_file():
                self._convert_with_word(source, target)
            else:
                raise RuntimeError("no local Office PDF converter is installed")
            if not target.is_file():
                raise RuntimeError("local Office converter did not produce a PDF")
            return target.read_bytes()

    @staticmethod
    def _word_executable() -> Path:
        candidates = (
            Path(r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE"),
            Path(r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE"),
        )
        return next((item for item in candidates if item.is_file()), Path())

    @staticmethod
    def _convert_with_libreoffice(executable: str, source: Path, output_dir: Path) -> None:
        result = subprocess.run(
            [executable, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(source)],
            capture_output=True, check=False, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError("LibreOffice PDF conversion failed")

    @staticmethod
    def _convert_with_word(source: Path, target: Path) -> None:
        script = (
            "$ErrorActionPreference='Stop';"
            "$word=New-Object -ComObject Word.Application;"
            "$word.Visible=$false;$word.DisplayAlerts=0;"
            "try{$doc=$word.Documents.Open($env:PERICIAL_PDF_SOURCE);"
            "$doc.ExportAsFixedFormat($env:PERICIAL_PDF_TARGET,17);$doc.Close($false)}"
            "finally{$word.Quit()}"
        )
        environment = os.environ.copy()
        environment["PERICIAL_PDF_SOURCE"] = str(source)
        environment["PERICIAL_PDF_TARGET"] = str(target)
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, check=False, timeout=120, env=environment,
        )
        if result.returncode != 0:
            raise RuntimeError("Microsoft Word PDF conversion failed")
