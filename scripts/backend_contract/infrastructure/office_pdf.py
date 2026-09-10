"""Local Microsoft Word COM PDF conversion with fail-closed semantics.

The converter receives only a private, sanitized copy of the authoritative
Word artifact.  It never invokes a shell or subprocess and never edits the
source bytes.  The optional ``word_factory`` exists solely for deterministic
boundary tests; production uses the local ``win32com`` COM adapter when the
dependency is installed on Windows.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from typing import Callable

from ..delivery_renderer import RendererUnavailable

try:
    import win32com.client as _win32_client
except ModuleNotFoundError:  # Optional local Windows dependency; fail closed at use time.
    _win32_client = None


def _default_word_factory() -> object:
    if sys.platform != "win32":
        raise RendererUnavailable("Microsoft Word Desktop COM requires Windows")
    if _win32_client is None:
        raise RendererUnavailable("Microsoft Word COM automation dependency is unavailable")
    try:
        return _win32_client.DispatchEx("Word.Application")
    except Exception as exc:  # COM providers expose platform-specific errors.
        raise RendererUnavailable("Microsoft Word Desktop COM is unavailable") from exc


class LocalOfficePdfConverter:
    """Convert an exact Word copy through local Microsoft Word Desktop COM."""

    renderer_type = "MICROSOFT_WORD_DESKTOP_COM"
    requires_visual_raster = True

    def __init__(
        self,
        *,
        word_factory: Callable[[], object] | None = None,
        temp_root: Path | None = None,
    ) -> None:
        self._word_factory = word_factory or _default_word_factory
        self._temp_root = temp_root
        self._renderer_version = "UNKNOWN"

    @property
    def renderer_version(self) -> str:
        return self._renderer_version

    @property
    def platform(self) -> str:
        return sys.platform

    def convert(self, word_bytes: bytes, source_format: str) -> bytes:
        if type(word_bytes) is not bytes:
            raise ValueError("Word content must be bytes")
        if source_format not in {"DOCX", "DOCM"}:
            raise ValueError("source format must be DOCX or DOCM")

        app = None
        document = None
        try:
            with tempfile.TemporaryDirectory(
                prefix="plp-word-pdf-",
                dir=str(self._temp_root) if self._temp_root is not None else None,
            ) as directory:
                root = Path(directory)
                source = root / ("source.docm" if source_format == "DOCM" else "source.docx")
                target = root / "output.pdf"
                source.write_bytes(word_bytes)

                try:
                    app = self._word_factory()
                    self._renderer_version = str(getattr(app, "Version", "UNKNOWN"))
                    app.Visible = False
                    app.DisplayAlerts = 0
                    documents = getattr(app, "Documents")
                    document = documents.Open(
                        FileName=str(source),
                        ConfirmConversions=False,
                        ReadOnly=True,
                        AddToRecentFiles=False,
                        OpenAndRepair=False,
                        NoEncodingDialog=True,
                    )
                    document.ExportAsFixedFormat(
                        OutputFileName=str(target),
                        ExportFormat=17,
                        OpenAfterExport=False,
                        OptimizeFor=0,
                        Range=0,
                        Item=0,
                        IncludeDocProps=True,
                        KeepIRMSettings=True,
                        CreateBookmarks=0,
                        DocStructureTags=True,
                        BitmapMissingFonts=True,
                        UseISO19005_1=False,
                    )
                    output = target.read_bytes()
                    if not output.startswith(b"%PDF-") or not output.rstrip().endswith(b"%%EOF"):
                        raise RendererUnavailable("Microsoft Word returned invalid PDF bytes")
                    return output
                finally:
                    if document is not None:
                        try:
                            document.Close(SaveChanges=0)
                        except Exception:
                            pass
                        document = None
                    if app is not None:
                        try:
                            app.Quit(SaveChanges=0)
                        except Exception:
                            pass
                        app = None
        except RendererUnavailable:
            raise
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            raise RendererUnavailable("local Microsoft Word PDF conversion failed") from exc
        except Exception as exc:
            raise RendererUnavailable("local Microsoft Word PDF conversion failed") from exc
        finally:
            # The inner finally performs cleanup before TemporaryDirectory exits.
            # Keep this guard for failures before the temporary context opens.
            if document is not None:
                try:
                    document.Close(SaveChanges=0)
                except Exception:
                    pass
            if app is not None:
                try:
                    app.Quit(SaveChanges=0)
                except Exception:
                    pass
