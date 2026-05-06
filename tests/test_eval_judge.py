"""judge 클라이언트 테스트.

backend abstraction(`JudgeBackend`)으로 SDK 호출을 격리 — 테스트는 fake async
함수를 backend로 주입하여 SDK/네트워크 없이 동작.
"""
import asyncio
import json
from pathlib import Path

import pytest

from backend.eval.cases import SyntheticCase
from tools.eval.judge import (
    JudgeError,
    PhiGuardError,
    judge_case,
)
from backend.soap.formats import get_cached_format
from backend.soap.models import ClinicalNote


def _case() -> SyntheticCase:
    return SyntheticCase(
        id="x_01",
        format_id="soap",
        trap_type="normal",
        source_text="환자가 복부 통증을 호소합니다. MELD 18점입니다.",
        expected_behavior="복부 통증을 S에, MELD 18을 O에 정확히 기재하면 정답.",
        is_synthetic=True,
        review_status="approved",
    )


def _fmt():
    return get_cached_format(Path("hints/formats"), "soap")


def _note():
    return ClinicalNote(
        sections={"subjective": "복부 통증", "objective": "MELD 18점", "assessment": "", "plan": ""}
    )


_SCORE_OK = {
    "case_id": "x_01",
    "hallucination_safety": {"score": 5, "reasoning": "원문 외 정보 추가되지 않음."},
    "section_accuracy": {"score": 5, "reasoning": "S에 호소, O에 검사 — 분류 정확."},
    "completeness": {"score": 4, "reasoning": "주요 정보 모두 포함됨."},
    "drug_value_fidelity": {"score": 5, "reasoning": "MELD 18 정확히 보존됨."},
    "overall_pass": True,
    "summary": "원문에 충실하고 분류 정확. 환각 없음.",
}


def _make_backend(content: str):
    """주어진 문자열을 응답으로 반환하는 fake backend."""
    async def backend(system: str, user: str, model: str) -> str:
        return content
    return backend


def _make_failing_backend(exc: Exception):
    async def backend(system: str, user: str, model: str) -> str:
        raise exc
    return backend


def test_judge_phi_guard_via_schema() -> None:
    """schema 단계에서 is_synthetic=False는 거부 — 호출 자체 불가능."""
    with pytest.raises(ValueError):
        SyntheticCase(
            id="bad", format_id="soap", trap_type="normal",
            source_text="x" * 11, expected_behavior="y" * 11,
            is_synthetic=False, review_status="approved",
        )


def test_judge_phi_guard_runtime_check() -> None:
    """schema를 우회해도(후속 mutation) 호출 직전 phi_guard가 차단."""
    case = _case()
    case.is_synthetic = False  # mutate — pydantic은 후속 변경 재검증 안 함
    backend = _make_backend(json.dumps(_SCORE_OK))
    with pytest.raises(PhiGuardError):
        asyncio.run(judge_case(case=case, fmt=_fmt(), note=_note(), backend=backend))


def test_judge_success_path() -> None:
    backend = _make_backend(json.dumps(_SCORE_OK, ensure_ascii=False))
    score, elapsed = asyncio.run(
        judge_case(case=_case(), fmt=_fmt(), note=_note(), backend=backend)
    )
    assert score.case_id == "x_01"
    assert score.overall_pass is True
    assert score.total == 19
    assert score.min_dim == 4
    assert elapsed >= 0


def test_judge_strips_markdown_fence() -> None:
    """judge가 ```json ... ``` 으로 감싸도 파싱."""
    fenced = "```json\n" + json.dumps(_SCORE_OK, ensure_ascii=False) + "\n```"
    backend = _make_backend(fenced)
    score, _ = asyncio.run(
        judge_case(case=_case(), fmt=_fmt(), note=_note(), backend=backend)
    )
    assert score.case_id == "x_01"


def test_judge_fixes_wrong_case_id_echo() -> None:
    """judge가 case_id를 잘못 채워도 우리 ID로 보정."""
    bad = {**_SCORE_OK, "case_id": "wrong_id"}
    backend = _make_backend(json.dumps(bad, ensure_ascii=False))
    score, _ = asyncio.run(
        judge_case(case=_case(), fmt=_fmt(), note=_note(), backend=backend)
    )
    assert score.case_id == "x_01"  # 우리가 보낸 ID로 정정


def test_judge_backend_exception_wrapped() -> None:
    """SDK 호출 예외는 JudgeError로 래핑."""
    backend = _make_failing_backend(RuntimeError("CLI not authenticated"))
    with pytest.raises(JudgeError, match="backend 호출 실패"):
        asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note(), backend=backend))


def test_judge_empty_response_raises() -> None:
    """SDK가 빈 응답을 반환하면 인증/응답 문제로 명시적 에러."""
    backend = _make_backend("   ")
    with pytest.raises(JudgeError, match="비어있음"):
        asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note(), backend=backend))


def test_judge_invalid_json_raises() -> None:
    backend = _make_backend("this is not json at all")
    with pytest.raises(JudgeError, match="JSON"):
        asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note(), backend=backend))


def test_judge_missing_dimension_raises() -> None:
    """judge가 4 차원 중 하나를 빠뜨리면 schema validation 실패."""
    incomplete = {k: v for k, v in _SCORE_OK.items() if k != "drug_value_fidelity"}
    backend = _make_backend(json.dumps(incomplete, ensure_ascii=False))
    with pytest.raises(JudgeError, match="JudgeScore 스키마"):
        asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note(), backend=backend))
