"""의무기록 응답 데이터 모델.

- ClinicalNote: 포맷 독립 (sections dict 기반) — /note 엔드포인트 사용
- SoapNote: 4섹션 고정 — 기존 /soap 엔드포인트의 후방호환을 위한 형태
"""
from pydantic import BaseModel, Field


class ClinicalNote(BaseModel):
    """포맷 독립 의무기록. sections는 format yaml의 section key로 정렬."""
    sections: dict[str, str] = Field(default_factory=dict)
    uncertain_segments: list[str] = Field(default_factory=list)


class SoapNote(BaseModel):
    """SOAP 4섹션 고정 형태. /soap 엔드포인트 후방호환용."""
    subjective: str = Field(default="", description="환자 호소 (S)")
    objective: str = Field(default="", description="진찰소견/검사결과 (O)")
    assessment: str = Field(default="", description="진단/평가 (A)")
    plan: str = Field(default="", description="치료 계획 (P)")
    uncertain_segments: list[str] = Field(
        default_factory=list,
        description="LLM이 불확실하다고 표시한 구간 (원문에 [?] 표시)",
    )


class ValidationReport(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)
    extra_numbers: list[str] = Field(
        default_factory=list,
        description="원문에 없는데 응답에 등장한 숫자 (환각 의심)",
    )


class SoapResponse(BaseModel):
    note: SoapNote
    validation: ValidationReport
    model: str
    elapsed_seconds: float = Field(ge=0)
    source_text: str = Field(description="입력 원문 (검증/디버깅용)")


class ClinicalNoteResponse(BaseModel):
    note: ClinicalNote
    validation: ValidationReport
    model: str
    elapsed_seconds: float = Field(ge=0)
    source_text: str = Field(description="입력 원문 (검증/디버깅용)")
    format_id: str = Field(description="사용된 포맷 id (예: 'soap', 'initial_visit')")
