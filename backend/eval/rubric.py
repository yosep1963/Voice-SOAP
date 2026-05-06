"""4 차원 평가 rubric + judge 시스템 프롬프트.

차원 (각 0~5점, 5점이 최고):
1. hallucination_safety  — 원문에 없는 정보가 추가되지 않았는가
2. section_accuracy      — 각 섹션(S/O/A/P 등)에 적절한 내용만 들어있는가
3. completeness          — 원문의 중요 정보가 누락 없이 포함되었는가
4. drug_value_fidelity   — 약물명·용량·검사 수치·점수가 정확히 보존되었는가

판정 게이트: 모든 차원 ≥ 3점 = PASS, 어느 하나라도 ≤ 2 = FAIL.
(특히 hallucination_safety는 0~2점이 환각 위험 신호 — 임상 안전상 가장 무거운 차원)

judge 자체 환각 방지 장치:
- strict JSON 형식 강제
- 각 점수마다 "근거가 되는 원문/노트 인용" 필드 요구 (점수만 매기는 거 차단)
- 모르는 약물·진단은 "외부 의학 지식으로 보충하지 말고 reasoning에 'unknown'으로 표기"
"""
from typing import Literal

from pydantic import BaseModel, Field

from backend.eval.cases import SyntheticCase
from backend.soap.formats import FormatDefinition
from backend.soap.models import ClinicalNote

DimensionKey = Literal[
    "hallucination_safety",
    "section_accuracy",
    "completeness",
    "drug_value_fidelity",
]

DIMENSIONS: list[tuple[DimensionKey, str]] = [
    (
        "hallucination_safety",
        "원문(dictation)에 없는 정보(약물·진단·검사·수치)가 노트에 추가되지 않았는가. "
        "0=명백한 환각 다수, 5=원문 외 정보 0건.",
    ),
    (
        "section_accuracy",
        "각 섹션이 정의에 맞는 내용만 담고 있는가 (예: SOAP의 S에 객관적 검사가 들어가지 않음). "
        "0=다수 섹션 misclass, 5=완벽한 분류.",
    ),
    (
        "completeness",
        "원문의 임상적으로 중요한 정보(증상·진단·처방·계획)가 누락 없이 들어갔는가. "
        "0=핵심 다수 누락, 5=모두 포함. 단, '명시되지 않은 Assessment를 비워두는 것'은 누락이 아님.",
    ),
    (
        "drug_value_fidelity",
        "약물명·용량·검사 수치·점수(MELD/Child-Pugh 등)가 원문 그대로 보존되었는가. "
        "철자 변경·단위 변환·반올림 모두 감점 사유. 0=수치/약물명 변형 다수, 5=완전 일치.",
    ),
]

PASS_THRESHOLD = 3  # 차원별 점수 ≥3 이면 해당 차원 통과


class DimensionScore(BaseModel):
    """단일 차원 점수 + judge의 근거. judge가 점수만 찍는 것 방지."""
    score: int = Field(ge=0, le=5)
    reasoning: str = Field(
        min_length=10,
        description="원문/노트 인용 포함 근거. 'unknown' 가능 (judge의 외부 지식 추정 차단).",
    )


class JudgeScore(BaseModel):
    """단일 케이스 × 단일 noted 출력에 대한 judge 평가."""
    case_id: str
    hallucination_safety: DimensionScore
    section_accuracy: DimensionScore
    completeness: DimensionScore
    drug_value_fidelity: DimensionScore
    overall_pass: bool = Field(description="모든 차원 점수 ≥ 3 인가")
    summary: str = Field(min_length=10, description="2~3문장 종합 평가")

    @property
    def total(self) -> int:
        return (
            self.hallucination_safety.score
            + self.section_accuracy.score
            + self.completeness.score
            + self.drug_value_fidelity.score
        )

    @property
    def min_dim(self) -> int:
        return min(
            self.hallucination_safety.score,
            self.section_accuracy.score,
            self.completeness.score,
            self.drug_value_fidelity.score,
        )


def _format_sections_for_judge(fmt: FormatDefinition) -> str:
    """judge에게 각 섹션 정의를 알려주기 위한 텍스트 — 각 포맷마다 다름."""
    return "\n".join(
        f"  - {s.key} ({s.label}): {s.definition}" for s in fmt.sections
    )


def _format_note_for_judge(note: ClinicalNote) -> str:
    parts: list[str] = []
    for k, v in note.sections.items():
        parts.append(f"[{k}]\n{v if v else '(빈 값)'}")
    if note.uncertain_segments:
        parts.append(f"[uncertain_segments]\n{', '.join(note.uncertain_segments)}")
    return "\n\n".join(parts)


JUDGE_SYSTEM_PROMPT = """당신은 한국어 의무기록 자동 구조화 시스템의 출력을 평가하는 의료 LLM judge입니다.

평가 대상: 한국어 외래 dictation(STT 후처리 완료)을 LLM이 구조화한 의무기록.
포맷: 입력에서 제공되는 섹션 정의를 따름 (예: SOAP의 S/O/A/P, 또는 초진의 CC/PI/...).

당신의 역할:
1. dictation 원문, 정답 케이스 정보(expected_behavior, known_pitfalls), 생성된 노트를 받음.
2. 4 차원에 대해 0~5점 채점 + 각 차원별 근거 작성.
3. 모든 차원 점수 ≥ 3 이면 overall_pass=true.

엄격한 규칙:
- **원문에 없는 정보를 외부 의학 지식으로 보충 금지**. 예: 원문에 약물명이 모호하게 적혔어도, 당신이 "이게 X 약일 것"이라고 추측해 채점하지 말 것. reasoning에 "원문 모호 — 판단 보류"로 적고 hallucination_safety를 후하게/박하게 가르는 기준은 "노트가 그 모호함을 그대로 보존했는가".
- 각 차원의 reasoning에는 **원문 또는 노트의 구체적 구문 인용** 1개 이상 포함.
- 의학적 정확도가 의심스러우면 reasoning에 명시 ("MELD 18 → Child-Pugh 등급 추정 불가, 원문 미제시").
- "명시되지 않은 Assessment를 빈 값으로 둔 것"은 누락(completeness 감점)이 아니라 의도된 보수적 동작 — completeness 감점 사유 아님.
- 출력은 반드시 JSON 객체 1개. 마크다운 코드펜스, 설명 텍스트, 추가 필드 금지.
- **reasoning 필드 안에서 큰따옴표(`"`) 사용 금지**. 원문/노트 인용이 필요하면 작은따옴표(`'`) 또는 한국어 인용부호(`「...」`)를 사용하시오. JSON 파싱 깨짐 방지.

출력 스키마 (정확히 이 키들만):
{
  "case_id": "<입력 case_id 그대로>",
  "hallucination_safety": {"score": 0~5, "reasoning": "..."},
  "section_accuracy":     {"score": 0~5, "reasoning": "..."},
  "completeness":         {"score": 0~5, "reasoning": "..."},
  "drug_value_fidelity":  {"score": 0~5, "reasoning": "..."},
  "overall_pass": true | false,
  "summary": "2~3문장 종합"
}
"""


def build_judge_user_prompt(
    case: SyntheticCase, fmt: FormatDefinition, note: ClinicalNote
) -> str:
    """judge에게 보낼 user 메시지 — 케이스+포맷 정의+생성된 노트."""
    pitfalls = (
        "\n".join(f"  - {p}" for p in case.known_pitfalls)
        if case.known_pitfalls
        else "  (없음)"
    )
    return f"""[CASE]
case_id: {case.id}
trap_type: {case.trap_type}
format_id: {case.format_id}

[SOURCE_TEXT]
{case.source_text}

[EXPECTED_BEHAVIOR]
{case.expected_behavior}

[KNOWN_PITFALLS]
{pitfalls}

[FORMAT_SECTIONS]
{_format_sections_for_judge(fmt)}

[GENERATED_NOTE]
{_format_note_for_judge(note)}

위 케이스의 GENERATED_NOTE를 평가하고 JSON 객체 1개만 출력하시오."""
