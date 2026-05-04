"""편집 diff 학습 로그 데이터 모델. plan.md Phase 5 §"학습/개선 시스템".

Day 3: SoapNote 4섹션 고정 → ClinicalNote (sections dict) 일반화로 마이그레이션.
format_id 필드 추가 — 분석 시 포맷별 그루핑 가능.
"""
from pydantic import BaseModel, Field

from backend.soap.models import ClinicalNote
from backend.stt.postprocess import AppliedReplacement


class SectionDiff(BaseModel):
    section: str  # 포맷에 따른 섹션 키 (예: subjective/cc/pi/...)
    original: str
    edited: str
    changed: bool


class EditFeedback(BaseModel):
    """사용자가 의무기록 결과를 EMR에 복사하는 시점(=검토 완료 시점)의 스냅샷."""

    timestamp: str = Field(description="ISO 8601 (클라이언트 시각)")
    audio_duration_seconds: float = Field(ge=0)
    raw_text: str = Field(description="Whisper 원본 STT 출력")
    corrected_text: str = Field(description="후처리 사전 적용 후 텍스트")
    format_id: str = Field(default="soap", description="사용된 포맷 id")
    original_note: ClinicalNote = Field(description="LLM 출력 (사용자 편집 전)")
    edited_note: ClinicalNote = Field(description="사용자 편집 후 최종 의무기록")
    diffs: list[SectionDiff] = Field(default_factory=list)
    applied_replacements: list[AppliedReplacement] = Field(default_factory=list)
    uncertain_segments: list[str] = Field(default_factory=list)
