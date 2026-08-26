"""OCR local latino, pinado e sem aquisição de modelo em runtime."""

from __future__ import annotations

import hashlib
from pathlib import Path

import rapidocr
from PIL import Image
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR


RAPIDOCR_VERSION = "3.9.2"
RAPIDOCR_LATIN_MODEL_FILENAME = "latin_PP-OCRv5_rec_mobile.onnx"
RAPIDOCR_LATIN_MODEL_SHA256 = (
    "b20bd37c168a570f583afbc8cd7925603890efbcdc000a59e22c269d160b5f5a"
)
_DETECTION_MODEL_FILENAME = "PP-OCRv6_det_small.onnx"
_DETECTION_MODEL_SHA256 = (
    "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"
)
_CLASSIFICATION_MODEL_FILENAME = "ch_ppocr_mobile_v2.0_cls_mobile.onnx"
_CLASSIFICATION_MODEL_SHA256 = (
    "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"
)


class LocalOcrModelError(RuntimeError):
    """O modelo local exigido não possui a identidade pinada."""


def bundled_ocr_model_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / RAPIDOCR_LATIN_MODEL_FILENAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(64 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _require_model(path: Path, expected_sha256: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise LocalOcrModelError("modelo OCR local não foi provisionado") from exc
    if not resolved.is_file() or _sha256(resolved) != expected_sha256:
        raise LocalOcrModelError("identidade do modelo OCR local diverge")
    return resolved


class RapidOcrLatinEngine:
    """Adapter CPU-only para os modelos ONNX locais explicitamente pinados."""

    engine = "RapidOCR/ONNXRuntime"
    engine_version = RAPIDOCR_VERSION
    model_version = "PP-OCRv6-det+PP-OCRv4-cls+PP-OCRv5-latin-rec"
    config_version = "LOCAL_OCR_CONFIG_V2_RENDER_1_5"

    def __init__(self, *, recognition_model_path: str | Path | None = None):
        self._recognition_model_path = (
            bundled_ocr_model_path()
            if recognition_model_path is None
            else Path(recognition_model_path)
        )
        self._runtime = None

    def _build_runtime(self):
        package_models = Path(rapidocr.__file__).parent / "models"
        detection = _require_model(
            package_models / _DETECTION_MODEL_FILENAME,
            _DETECTION_MODEL_SHA256,
        )
        classification = _require_model(
            package_models / _CLASSIFICATION_MODEL_FILENAME,
            _CLASSIFICATION_MODEL_SHA256,
        )
        recognition = _require_model(
            self._recognition_model_path,
            RAPIDOCR_LATIN_MODEL_SHA256,
        )
        return RapidOCR(
            params={
                "Det.model_path": str(detection),
                "Cls.model_path": str(classification),
                "Rec.model_path": str(recognition),
                "Rec.lang_type": LangRec.LATIN,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
            }
        )

    def recognize(self, image: Image.Image) -> tuple[dict[str, object], ...]:
        if not isinstance(image, Image.Image):
            raise TypeError("OCR local exige imagem PIL")
        if self._runtime is None:
            self._runtime = self._build_runtime()
        result = self._runtime(image)
        texts = tuple(result.txts or ())
        scores = tuple(result.scores or ())
        boxes = tuple(result.boxes) if result.boxes is not None else ()
        if not (len(texts) == len(scores) == len(boxes)):
            raise RuntimeError("resultado do OCR local é inconsistente")
        blocks = []
        for text, score, box in zip(texts, scores, boxes):
            points = tuple((float(point[0]), float(point[1])) for point in box)
            blocks.append(
                {
                    "text": str(text),
                    "confidence": float(score),
                    "bounding_box": (
                        min(point[0] for point in points),
                        min(point[1] for point in points),
                        max(point[0] for point in points),
                        max(point[1] for point in points),
                    ),
                }
            )
        return tuple(blocks)
