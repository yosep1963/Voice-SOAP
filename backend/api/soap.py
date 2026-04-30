"""POST /soap — 한국어 dictation 텍스트 → SOAP JSON."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.config import Settings, get_settings
from backend.soap.llm_client import LLMError, structure_to_soap
from backend.soap.models import SoapResponse
from backend.soap.validator import validate_soap

logger = logging.getLogger(__name__)
router = APIRouter()


class SoapRequest(BaseModel):
    text: str = Field(min_length=1, description="STT로 전사된 한국어 dictation")


@router.post("/soap", response_model=SoapResponse)
async def to_soap(
    req: SoapRequest,
    settings: Settings = Depends(get_settings),
) -> SoapResponse:
    try:
        note, elapsed = await structure_to_soap(
            req.text,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )
    except LLMError as e:
        logger.warning("LLM error: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e

    validation = validate_soap(req.text, note)
    if validation.warnings:
        logger.warning("soap validation warnings: %s", validation.warnings)

    return SoapResponse(
        note=note,
        validation=validation,
        model=settings.llm_model,
        elapsed_seconds=elapsed,
        source_text=req.text,
    )
