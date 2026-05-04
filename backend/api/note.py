"""POST /note — 한국어 dictation 텍스트 → 임의 포맷 의무기록 JSON.

기존 /soap (4섹션 고정) 의 일반화 버전. 응답은 ClinicalNoteResponse(sections dict 기반).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.config import Settings, get_settings
from backend.soap.formats import get_cached_format
from backend.soap.llm_client import LLMError, structure_to_note
from backend.soap.models import ClinicalNoteResponse
from backend.soap.validator import validate_clinical

logger = logging.getLogger(__name__)
router = APIRouter()


class NoteRequest(BaseModel):
    text: str = Field(min_length=1, description="STT로 전사된 한국어 dictation")
    format_id: str | None = Field(
        default=None,
        description="포맷 id (예: 'soap', 'initial_visit'). 미지정 시 settings.default_format_id 사용.",
    )


@router.post("/note", response_model=ClinicalNoteResponse)
async def to_note(
    req: NoteRequest,
    settings: Settings = Depends(get_settings),
) -> ClinicalNoteResponse:
    format_id = req.format_id or settings.default_format_id
    try:
        fmt = get_cached_format(settings.formats_dir, format_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Unknown format_id: {format_id!r}") from e

    try:
        note, elapsed = await structure_to_note(
            req.text,
            fmt=fmt,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )
    except LLMError as e:
        logger.warning("LLM error in /note (format=%s): %s", format_id, e)
        raise HTTPException(status_code=502, detail=str(e)) from e

    validation = validate_clinical(req.text, note)
    if validation.warnings:
        logger.warning("note validation warnings (format=%s): %s", format_id, validation.warnings)

    return ClinicalNoteResponse(
        note=note,
        validation=validation,
        model=settings.llm_model,
        elapsed_seconds=elapsed,
        source_text=req.text,
        format_id=format_id,
    )
