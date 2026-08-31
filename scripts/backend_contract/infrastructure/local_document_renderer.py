"""Local-only, timeout-bounded Word-to-PDF conversion adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile


@dataclass(frozen=True, slots=True)
class LocalLibreOfficeRenderer:
    executable: str | None = None
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        if type(self.timeout_seconds) is not int or self.timeout_seconds < 1 or self.timeout_seconds > 300:
            raise ValueError("document renderer timeout is invalid")

    def convert_to_pdf(self, content: bytes, source_format: str) -> bytes:
        if type(content) is not bytes or not content or source_format not in {"DOCX", "DOCM"}:
            raise ValueError("document conversion input is invalid")
        candidates = (Path(self.executable),) if self.executable else (
            Path("C:/Program Files/LibreOffice/program/soffice.exe"),
            Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
            Path("/usr/bin/libreoffice"), Path("/usr/bin/soffice"),
        )
        executable_path = next((item.resolve() for item in candidates if item.is_absolute() and item.is_file()), None)
        if executable_path is None:
            raise RuntimeError("local LibreOffice renderer is unavailable")
        with tempfile.TemporaryDirectory(prefix="delivery-render-") as raw_root:
            root = Path(raw_root).resolve()
            source = root / f"source.{source_format.lower()}"
            output = root / "output"
            profile = root / "profile"
            output.mkdir()
            profile.mkdir()
            source.write_bytes(content)
            command = (
                str(executable_path), "--headless", "--nologo", "--nodefault", "--nolockcheck", "--safe-mode",
                f"-env:UserInstallation={profile.as_uri()}", "--convert-to", "pdf",
                "--outdir", str(output), str(source),
            )
            try:
                completed = subprocess.run(command, check=False, capture_output=True, timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("local PDF conversion timed out") from exc
            pdf = output / "source.pdf"
            if completed.returncode != 0 or not pdf.is_file():
                raise RuntimeError("local PDF conversion failed")
            return pdf.read_bytes()
