"""합성 dictation 평가 케이스 스키마 + 로더.

각 케이스는 yaml 파일 1개 (tests/fixtures/eval_cases/<id>.yaml). 의도적으로
1 케이스 = 1 파일 — 의학적 검토를 케이스 단위로 git-track하기 위함.

is_synthetic=True가 PHI guard의 gate. 이 플래그가 False/누락이면 judge 호출 차단.
review_status='approved'만 기본 실행 — 'pending'은 --include-pending 플래그 필요.
"""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

# 가능한 trap 종류. 새 trap 추가 시 여기에 등록.
TrapType = Literal[
    "drug_ambiguity",        # 약물명이 헷갈리는 dictation
    "section_misclass",      # LLM이 S/O/A/P 분류를 틀릴 수 있는 케이스
    "missing_info",          # dictation에 명시 안 된 정보 — LLM이 추측해 채우면 환각
    "hallucination_trap",    # 약물 유사명·검사 수치 변형으로 환각 유도
    "score_extraction",      # MELD/Child-Pugh 점수 정확 추출 검증
    "normal",                # 환각 없이 정확히 처리되어야 하는 평범한 케이스
]

ReviewStatus = Literal["pending", "approved", "rejected"]


class SyntheticCase(BaseModel):
    """단일 평가 케이스. yaml에 1:1 대응.

    Pydantic이 알 수 없는 필드를 거부하도록 설정 — 오타·이상한 yaml을 빠르게 catch.
    """
    model_config = {"extra": "forbid"}

    id: str = Field(min_length=1, description="고유 ID, 보통 '<trap_type>_<번호>'")
    format_id: str = Field(description="'soap' | 'initial_visit' 등")
    trap_type: TrapType
    source_text: str = Field(
        min_length=10,
        description="STT 후처리까지 끝났다고 가정하는 dictation 텍스트 (한국어)",
    )
    expected_behavior: str = Field(
        min_length=10,
        description="judge에게 전달될 자연어 가이드 — 무엇이 정답이고 무엇이 환각인지",
    )
    known_pitfalls: list[str] = Field(
        default_factory=list,
        description="이 케이스에서 LLM이 빠질 수 있는 알려진 실패 모드 (judge 컨텍스트)",
    )
    is_synthetic: bool = Field(
        description="합성 케이스 여부. False면 judge 호출 차단됨 — 안전 기본값을 두지 않음(명시적 선언 강제).",
    )
    review_status: ReviewStatus = "pending"
    notes: str = Field(default="", description="작성/검토 메모 (자유 형식)")

    @field_validator("is_synthetic")
    @classmethod
    def _must_be_synthetic(cls, v: bool) -> bool:
        # is_synthetic=False는 schema-level에서 거부 — 실데이터는 절대 케이스로 저장 금지
        if not v:
            raise ValueError(
                "is_synthetic must be True. 실데이터(PHI)는 평가 케이스로 사용할 수 없음. "
                "logs/edits.jsonl 같은 실데이터는 별도 replay harness 사용."
            )
        return v


def load_case(path: Path) -> SyntheticCase:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: yaml 루트는 dict여야 함 (case 1개), got {type(data).__name__}")
    return SyntheticCase.model_validate(data)


def load_cases(directory: Path, *, include_pending: bool = False) -> list[SyntheticCase]:
    """디렉터리의 모든 .yaml 케이스 로드. id 기준 sort. 중복 id 발견 시 즉시 실패."""
    if not directory.is_dir():
        raise FileNotFoundError(f"case directory not found: {directory}")
    cases: list[SyntheticCase] = []
    seen: dict[str, Path] = {}
    for p in sorted(directory.glob("*.yaml")):
        case = load_case(p)
        if case.id in seen:
            raise ValueError(
                f"duplicate case id {case.id!r} in {p} and {seen[case.id]}"
            )
        seen[case.id] = p
        if case.review_status == "rejected":
            continue
        if not include_pending and case.review_status == "pending":
            continue
        cases.append(case)
    cases.sort(key=lambda c: c.id)
    return cases
