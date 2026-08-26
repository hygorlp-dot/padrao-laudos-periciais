"""Cache derivado e workspace-scoped para evidência OCR por página."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .models import WorkspaceId, thaw_payload
from .ports import (
    ArtifactRevisionRepository,
    Clock,
    IdGenerator,
    RepositoryConflict,
    RepositoryIntegrityError,
)
from .process_metadata import (
    PageExtractionMode,
    PageProcessingStatus,
    PageTextBlock,
    PdfTextPage,
)


_OCR_PAGE_CACHE_KIND = "OCR_PAGE_CACHE_V1"


def _cache_key(value: object) -> tuple[str, int, str, str, str, str]:
    if type(value) is not tuple or len(value) != 6:
        raise ValueError("chave de cache OCR inválida")
    document_sha256, page_number, engine, engine_version, model_version, config_version = value
    if (
        type(document_sha256) is not str
        or len(document_sha256) != 64
        or any(character not in "0123456789abcdef" for character in document_sha256)
        or type(page_number) is not int
        or page_number < 1
        or any(
            type(item) is not str or not item
            for item in (engine, engine_version, model_version, config_version)
        )
    ):
        raise ValueError("chave de cache OCR inválida")
    return value


def _artifact_id(key: tuple[str, int, str, str, str, str]) -> str:
    encoded = json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _page_payload(
    key: tuple[str, int, str, str, str, str], page: PdfTextPage
) -> dict[str, object]:
    if page.number != key[1] or page.extraction_mode is not PageExtractionMode.OCR:
        raise ValueError("página diverge da chave de cache OCR")
    if (
        page.engine != key[2]
        or page.engine_version != key[3]
        or page.model_version != key[4]
        or page.config_version != key[5]
        or page.processing_status not in {
            PageProcessingStatus.AVAILABLE,
            PageProcessingStatus.TRUNCATED,
        }
    ):
        raise ValueError("identidade da página diverge do cache OCR")
    return {
        "schema_version": 2,
        "document_sha256": key[0],
        "page_number": key[1],
        "engine": key[2],
        "engine_version": key[3],
        "model_version": key[4],
        "config_version": key[5],
        "normalized_text": page.text,
        "confidence": page.confidence,
        "processing_status": page.processing_status.value,
        "blocks": [
            {
                "text": block.text,
                "confidence": block.confidence,
                "bounding_box": list(block.bounding_box) if block.bounding_box else None,
            }
            for block in page.blocks
        ],
    }


def _page_from_payload(
    raw_value: object,
    expected_key: tuple[str, int, str, str, str, str],
) -> PdfTextPage:
    value = thaw_payload(raw_value)
    legacy_fields = {
        "schema_version",
        "document_sha256",
        "page_number",
        "engine",
        "engine_version",
        "model_version",
        "config_version",
        "normalized_text",
        "confidence",
        "blocks",
    }
    v2_fields = legacy_fields | {"processing_status"}
    if (
        type(value) is not dict
        or value.get("schema_version") not in {1, 2}
        or set(value) != (legacy_fields if value["schema_version"] == 1 else v2_fields)
    ):
        raise RepositoryIntegrityError("cache OCR persistido inválido")
    actual_key = (
        value["document_sha256"],
        value["page_number"],
        value["engine"],
        value["engine_version"],
        value["model_version"],
        value["config_version"],
    )
    if actual_key != expected_key or type(value["blocks"]) is not list:
        raise RepositoryIntegrityError("identidade do cache OCR diverge")
    try:
        blocks = []
        for raw in value["blocks"]:
            if type(raw) is not dict or set(raw) != {"text", "confidence", "bounding_box"}:
                raise ValueError
            box = raw["bounding_box"]
            blocks.append(
                PageTextBlock(
                    raw["text"],
                    raw["confidence"],
                    tuple(box) if box is not None else None,
                )
            )
        return PdfTextPage(
            expected_key[1],
            value["normalized_text"],
            PageExtractionMode.OCR,
            expected_key[2],
            expected_key[3],
            expected_key[4],
            expected_key[5],
            value["confidence"],
            tuple(blocks),
            PageProcessingStatus(
                value.get("processing_status", PageProcessingStatus.TRUNCATED)
            ),
        )
    except (TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("conteúdo do cache OCR persistido inválido") from exc


@dataclass(frozen=True, slots=True)
class RevisionOcrPageCache:
    revisions: ArtifactRevisionRepository
    workspace_id: WorkspaceId
    clock: Clock
    ids: IdGenerator

    def get(self, raw_key: object) -> PdfTextPage | None:
        key = _cache_key(raw_key)
        revision = self.revisions.latest(
            self.workspace_id,
            _OCR_PAGE_CACHE_KIND,
            _artifact_id(key),
        )
        return None if revision is None else _page_from_payload(revision.payload, key)

    def put(self, raw_key: object, page: PdfTextPage) -> None:
        key = _cache_key(raw_key)
        artifact_id = _artifact_id(key)
        existing = self.revisions.latest(self.workspace_id, _OCR_PAGE_CACHE_KIND, artifact_id)
        if existing is not None:
            if _page_from_payload(existing.payload, key) != page:
                raise RepositoryIntegrityError("cache OCR imutável diverge da nova evidência")
            return
        created_at = self.clock.now()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("clock do cache OCR exige timezone")
        try:
            self.revisions.append_if_latest(
                workspace_id=self.workspace_id,
                artifact_kind=_OCR_PAGE_CACHE_KIND,
                artifact_id=artifact_id,
                revision_id=str(self.ids.new_uuid()),
                created_at=created_at.isoformat(),
                payload=_page_payload(key, page),
                expected_revision=None,
            )
        except RepositoryConflict as exc:
            winner = self.revisions.latest(
                self.workspace_id, _OCR_PAGE_CACHE_KIND, artifact_id
            )
            if winner is None or _page_from_payload(winner.payload, key) != page:
                raise RepositoryIntegrityError(
                    "cache OCR imutável diverge da nova evidência"
                ) from exc
