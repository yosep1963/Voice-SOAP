"""POST /transcribe — wav 업로드 → 한국어 텍스트."""
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.config import Settings, get_settings
from backend.stt.hints_loader import load_hints
from backend.stt.postprocess import apply_postprocess, get_cached_rules
from backend.stt.whisper_engine import TranscriptionResult, transcribe_audio

logger = logging.getLogger(__name__)
router = APIRouter()

# content type → 임시 파일 확장자. mlx_whisper(ffmpeg)는 webm/ogg/mp4 모두 디코딩 가능.
# 브라우저 MediaRecorder가 webm/opus를 기본 출력하므로 Phase 2 웹 UI 대비 추가.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/mpeg": ".mp3",
}


@router.post("/transcribe", response_model=TranscriptionResult)
async def transcribe(
    audio: UploadFile = File(..., description="오디오 파일 (wav/webm/ogg/m4a/mp3)"),
    use_hints: bool = True,
    use_postprocess: bool = True,
    settings: Settings = Depends(get_settings),
) -> TranscriptionResult:
    suffix = ALLOWED_CONTENT_TYPES.get(audio.content_type or "")
    if suffix is None:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported content type: {audio.content_type}. Expected one of {sorted(ALLOWED_CONTENT_TYPES)}",
        )

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
        result = transcribe_audio(tmp_path, settings.whisper_model_repo, prompt)
    finally:
        tmp_path.unlink(missing_ok=True)

    if use_postprocess:
        rules = get_cached_rules(settings.postprocess_file)
        new_text, applied = apply_postprocess(result.raw_text, rules)
        result = result.model_copy(update={"text": new_text, "applied_replacements": applied})

    logger.info(
        "transcribed audio_bytes=%d duration=%.2fs elapsed=%.2fs rtf=%.3f low_conf=%d replacements=%d",
        len(payload),
        result.audio_duration_seconds,
        result.elapsed_seconds,
        result.rtf,
        len(result.low_confidence_segments),
        len(result.applied_replacements),
    )
    return result
