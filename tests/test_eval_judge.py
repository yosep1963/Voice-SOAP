"""judge 클라이언트 테스트. respx로 Anthropic API mock."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from backend.eval.cases import SyntheticCase
from tools.eval.judge import (
    DEFAULT_BASE_URL,
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


def _judge_response_body(score: dict) -> dict:
    """Anthropic Messages API 응답 형태로 감싸기."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": json.dumps(score, ensure_ascii=False)}],
        "stop_reason": "end_turn",
    }


_SCORE_OK = {
    "case_id": "x_01",
    "hallucination_safety": {"score": 5, "reasoning": "원문 외 정보 추가되지 않음."},
    "section_accuracy": {"score": 5, "reasoning": "S에 호소, O에 검사 — 분류 정확."},
    "completeness": {"score": 4, "reasoning": "주요 정보 모두 포함됨."},
    "drug_value_fidelity": {"score": 5, "reasoning": "MELD 18 정확히 보존됨."},
    "overall_pass": True,
    "summary": "원문에 충실하고 분류 정확. 환각 없음.",
}


@respx.mock
def test_judge_phi_guard_via_schema() -> None:
    """schema 단계에서 is_synthetic=False는 거부 — 호출 자체 불가능."""
    with pytest.raises(ValueError):
        SyntheticCase(
            id="bad", format_id="soap", trap_type="normal",
            source_text="x" * 11, expected_behavior="y" * 11,
            is_synthetic=False, review_status="approved",
        )


@respx.mock
def test_judge_phi_guard_runtime_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """schema를 우회해도(model_construct 등) 호출 직전 phi_guard가 차단."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    case = _case()
    case.is_synthetic = False  # 강제 변형 — pydantic은 mutate 후 재검증 안 함
    with pytest.raises(PhiGuardError):
        asyncio.run(judge_case(case=case, fmt=_fmt(), note=_note()))


@respx.mock
def test_judge_missing_api_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(JudgeError, match="ANTHROPIC_API_KEY"):
        asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note()))


@respx.mock
def test_judge_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    respx.post(f"{DEFAULT_BASE_URL}/messages").mock(
        return_value=httpx.Response(200, json=_judge_response_body(_SCORE_OK))
    )
    score, elapsed = asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note()))
    assert score.case_id == "x_01"
    assert score.overall_pass is True
    assert score.total == 19
    assert score.min_dim == 4
    assert elapsed >= 0


@respx.mock
def test_judge_strips_markdown_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    """judge가 ```json ... ``` 으로 감싸도 파싱."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fenced = "```json\n" + json.dumps(_SCORE_OK, ensure_ascii=False) + "\n```"
    body = {"content": [{"type": "text", "text": fenced}]}
    respx.post(f"{DEFAULT_BASE_URL}/messages").mock(return_value=httpx.Response(200, json=body))
    score, _ = asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note()))
    assert score.case_id == "x_01"


@respx.mock
def test_judge_fixes_wrong_case_id_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    """judge가 case_id를 잘못 채워도 우리 ID로 보정."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    bad = {**_SCORE_OK, "case_id": "wrong_id"}
    respx.post(f"{DEFAULT_BASE_URL}/messages").mock(
        return_value=httpx.Response(200, json=_judge_response_body(bad))
    )
    score, _ = asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note()))
    assert score.case_id == "x_01"  # 우리가 보낸 ID로 정정


@respx.mock
def test_judge_http_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    respx.post(f"{DEFAULT_BASE_URL}/messages").mock(
        return_value=httpx.Response(500, text="internal server error")
    )
    with pytest.raises(JudgeError, match="HTTP 500"):
        asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note()))


@respx.mock
def test_judge_invalid_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    body = {"content": [{"type": "text", "text": "this is not json at all"}]}
    respx.post(f"{DEFAULT_BASE_URL}/messages").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(JudgeError, match="JSON"):
        asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note()))


@respx.mock
def test_judge_missing_dimension_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """judge가 4 차원 중 하나를 빠뜨리면 schema validation 실패."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    incomplete = {k: v for k, v in _SCORE_OK.items() if k != "drug_value_fidelity"}
    respx.post(f"{DEFAULT_BASE_URL}/messages").mock(
        return_value=httpx.Response(200, json=_judge_response_body(incomplete))
    )
    with pytest.raises(JudgeError, match="JudgeScore 스키마"):
        asyncio.run(judge_case(case=_case(), fmt=_fmt(), note=_note()))
