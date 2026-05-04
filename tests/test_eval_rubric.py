from pathlib import Path

from backend.eval.cases import SyntheticCase
from backend.eval.rubric import (
    DIMENSIONS,
    JUDGE_SYSTEM_PROMPT,
    DimensionScore,
    JudgeScore,
    build_judge_user_prompt,
)
from backend.soap.formats import get_cached_format
from backend.soap.models import ClinicalNote


def _case() -> SyntheticCase:
    return SyntheticCase(
        id="x_01",
        format_id="soap",
        trap_type="normal",
        source_text="환자가 복부 통증을 호소합니다. MELD 18점입니다.",
        expected_behavior="복부 통증을 S, MELD 18을 O에 기재.",
        known_pitfalls=["MELD 점수를 다른 수치로 변형"],
        is_synthetic=True,
        review_status="approved",
    )


def test_rubric_has_four_dimensions() -> None:
    assert len(DIMENSIONS) == 4
    keys = {k for k, _ in DIMENSIONS}
    assert keys == {
        "hallucination_safety",
        "section_accuracy",
        "completeness",
        "drug_value_fidelity",
    }


def test_judge_score_total_and_min() -> None:
    s = JudgeScore(
        case_id="x",
        hallucination_safety=DimensionScore(score=5, reasoning="원문 외 정보가 추가되지 않았음."),
        section_accuracy=DimensionScore(score=4, reasoning="S/O 분류가 정확하게 되어있음."),
        completeness=DimensionScore(score=3, reasoning="MELD 점수가 objective에 포함됨."),
        drug_value_fidelity=DimensionScore(score=2, reasoning="용량 정보가 누락된 부분 있음."),
        overall_pass=False,
        summary="용량 보존 미흡으로 fidelity 차원 통과 못 함.",
    )
    assert s.total == 14
    assert s.min_dim == 2


def test_judge_user_prompt_includes_required_blocks(tmp_path: Path) -> None:
    fmt = get_cached_format(Path("hints/formats"), "soap")
    note = ClinicalNote(
        sections={
            "subjective": "복부 통증",
            "objective": "MELD 18점",
            "assessment": "",
            "plan": "",
        }
    )
    prompt = build_judge_user_prompt(_case(), fmt, note)
    assert "[SOURCE_TEXT]" in prompt
    assert "[EXPECTED_BEHAVIOR]" in prompt
    assert "[FORMAT_SECTIONS]" in prompt
    assert "[GENERATED_NOTE]" in prompt
    assert "MELD 18" in prompt
    # 각 섹션 정의가 judge에게 전달되는지 확인
    assert "subjective" in prompt
    assert "objective" in prompt


def test_judge_user_prompt_handles_empty_section() -> None:
    fmt = get_cached_format(Path("hints/formats"), "soap")
    note = ClinicalNote(sections={"subjective": "x", "objective": "", "assessment": "", "plan": ""})
    prompt = build_judge_user_prompt(_case(), fmt, note)
    assert "(빈 값)" in prompt


def test_dimension_score_requires_reasoning_min_length() -> None:
    import pytest
    with pytest.raises(ValueError):
        DimensionScore(score=4, reasoning="짧음")  # 10자 미만


def test_dimension_score_score_range() -> None:
    import pytest
    with pytest.raises(ValueError):
        DimensionScore(score=6, reasoning="범위 초과 케이스 테스트입니다.")
    with pytest.raises(ValueError):
        DimensionScore(score=-1, reasoning="음수 케이스 테스트입니다.")


def test_judge_system_prompt_mentions_no_external_knowledge() -> None:
    """judge가 자기 의학 지식으로 보충하지 않도록 명시 — 가장 중요한 제약."""
    assert "외부 의학 지식" in JUDGE_SYSTEM_PROMPT
    assert "JSON" in JUDGE_SYSTEM_PROMPT
