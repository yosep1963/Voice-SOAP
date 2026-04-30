"""mlx-whisper 래퍼. PoC의 transcribe()를 모듈화."""
import logging
import subprocess
import time
import wave
from pathlib import Path

import mlx_whisper
from pydantic import BaseModel, Field

from backend.stt.postprocess import AppliedReplacement

LOW_CONFIDENCE_THRESHOLD = -0.5

logger = logging.getLogger(__name__)


class LowConfidenceSegment(BaseModel):
    start: float
    end: float
    text: str
    avg_logprob: float


class TranscriptionResult(BaseModel):
    text: str = Field(description="후처리 사전 적용 후 최종 텍스트")
    raw_text: str = Field(description="Whisper 원본 출력 (후처리 전)")
    model: str
    elapsed_seconds: float = Field(ge=0)
    audio_duration_seconds: float = Field(ge=0)
    rtf: float = Field(ge=0, description="Real-time factor (elapsed / audio duration)")
    low_confidence_segments: list[LowConfidenceSegment]
    used_hints: bool
    applied_replacements: list[AppliedReplacement] = Field(default_factory=list)


def get_audio_duration(audio_path: Path) -> float:
    """wav는 wave 모듈로(빠름, PoC 회귀 보장), 그 외 포맷(webm/ogg/m4a)은 ffprobe로."""
    try:
        with wave.open(str(audio_path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except wave.Error:
        # webm 등은 RIFF 헤더 없음 — ffprobe로 fallback
        pass

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError) as e:
        logger.warning("ffprobe failed for %s: %s — duration=0", audio_path, e)
        return 0.0


def transcribe_audio(
    audio_path: Path,
    model_repo: str,
    prompt: str | None,
) -> TranscriptionResult:
    start = time.perf_counter()
    raw = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model_repo,
        language="ko",
        initial_prompt=prompt,
        word_timestamps=False,
        verbose=None,
        # 반복 환각 방지: 이전 segment 컨텍스트로 계속 잘못 생성되는 연쇄 차단
        condition_on_previous_text=False,
        # 반복 텍스트 감지(압축률 기반) 시 더 빨리 fallback temperature로 재시도 (기본 2.4)
        compression_ratio_threshold=2.0,
    )
    elapsed = time.perf_counter() - start
    duration = get_audio_duration(audio_path)

    segments = raw.get("segments", []) or []
    low = [
        LowConfidenceSegment(
            start=float(s["start"]),
            end=float(s["end"]),
            text=str(s["text"]).strip(),
            avg_logprob=float(s.get("avg_logprob", 0.0)),
        )
        for s in segments
        if s.get("avg_logprob", 0.0) < LOW_CONFIDENCE_THRESHOLD
    ]

    raw_text = str(raw["text"]).strip()
    return TranscriptionResult(
        text=raw_text,  # 호출 측에서 후처리 적용 후 새 객체로 교체
        raw_text=raw_text,
        model=model_repo,
        elapsed_seconds=elapsed,
        audio_duration_seconds=duration,
        rtf=elapsed / duration if duration > 0 else 0.0,
        low_confidence_segments=low,
        used_hints=prompt is not None,
    )
