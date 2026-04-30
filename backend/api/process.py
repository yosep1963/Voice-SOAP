"""POST /process — wav 업로드 → STT → SOAP 통합 (외래 1-클릭 워크플로우)."""
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.api.transcribe import ALLOWED_CONTENT_TYPES
from backend.config import Settings, get_settings
from backend.soap.llm_client import LLMError, structure_to_soap
from backend.soap.models import SoapResponse
from backend.soap.validator import validate_soap
from backend.stt.hints_loader import load_hints
from backend.stt.postprocess import apply_postprocess, get_cached_rules
from backend.stt.whisper_engine import TranscriptionResult, transcribe_audio

logger = logging.getLogger(__name__)
router = APIRouter()


class ProcessResponse(BaseModel):
    transcription: TranscriptionResult
    soap: SoapResponse


@router.post("/process", response_model=ProcessResponse)
async def process(
    audio: UploadFile = File(..., description="오디오 파일 (wav/webm/ogg/m4a/mp3)"),
    use_hints: bool = True,
    use_postprocess: bool = True,
    settings: Settings = Depends(get_settings),
) -> ProcessResponse:
    suffix = ALLOWED_CONTENT_TYPES.get(audio.content_type or "")
    if suffix is None:
        raise HTTPException(status_code=415, detail=f"Unsupported content type: {audio.content_type}")

    payload = await audio.read()
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload too large")
    if not payload:
        raise HTTPException(status_code=400, detail="Empty upload")

    prompt = load_hints(settings.hints_file) if use_hints else None

    tmp = tempfile.NamedTemporaryFile(prefix="voice_soap_", suffix=suffix, delete=False)
    tmp_path = Path(tmp.name)
    try:
        tmp.write(payload)
        tmp.close()
        transcription = transcribe_audio(tmp_path, settings.whisper_model_repo, prompt)
    finally:
        tmp_path.unlink(missing_ok=True)

    if use_postprocess:
        rules = get_cached_rules(settings.postprocess_file)
        new_text, applied = apply_postprocess(transcription.raw_text, rules)
        transcription = transcription.model_copy(
            update={"text": new_text, "applied_replacements": applied}
        )

    try:
        note, llm_elapsed = await structure_to_soap(
            transcription.text,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )
    except LLMError as e:
        logger.warning("LLM error in /process: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e

    validation = validate_soap(transcription.text, note)
    soap = SoapResponse(
        note=note,
        validation=validation,
        model=settings.llm_model,
        elapsed_seconds=llm_elapsed,
        source_text=transcription.text,
    )

    logger.info(
        "process complete: stt=%.2fs llm=%.2fs validation_passed=%s",
        transcription.elapsed_seconds,
        llm_elapsed,
        validation.passed,
    )
    return ProcessResponse(transcription=transcription, soap=soap)
