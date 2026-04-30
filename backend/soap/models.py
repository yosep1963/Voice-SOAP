"""SOAP 응답 데이터 모델."""
from pydantic import BaseModel, Field


class SoapNote(BaseModel):
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
        description="원문에 없는데 SOAP에 등장한 숫자 (환각 의심)",
    )


class SoapResponse(BaseModel):
    note: SoapNote
    validation: ValidationReport
    model: str
    elapsed_seconds: float = Field(ge=0)
    source_text: str = Field(description="입력 원문 (검증/디버깅용)")
