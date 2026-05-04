"""run_judge.evaluate_one + 안전장치 통합 테스트.

LM Studio + Anthropic API 모두 respx로 mock — 외부 호출 없음.
"""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from backend.config import get_settings
from backend.eval.cases import SyntheticCase
from tools.eval.judge import DEFAULT_BASE_URL as JUDGE_URL
from tools.eval.run_judge import aggregate, evaluate_one, render_json, render_markdown


def _case() -> SyntheticCase:
    return SyntheticCase(
        id="t_01",
        format_id="soap",
        trap_type="normal",
        source_text="환자가 복부 통증을 호소합니다. MELD 18입니다.",
        expected_behavior="복부 통증을 S에, MELD 18을 O에 정확히 기재하면 정답.",
        is_synthetic=True,
        review_status="approved",
    )


_LM_NOTE = {
    "subjective": "복부 통증",
    "objective": "MELD 18",
    "assessment": "",
    "plan": "",
    "uncertain_segments": [],
}

_JUDGE_SCORE = {
    "case_id": "t_01",
    "hallucination_safety": {"score": 5, "reasoning": "원문 외 정보가 없음."},
    "section_accuracy": {"score": 5, "reasoning": "S/O 분류가 정확하게 매칭됨."},
    "completeness": {"score": 4, "reasoning": "주요 정보 모두 포함됨."},
    "drug_value_fidelity": {"score": 5, "reasoning": "MELD 18 정확히 보존됨."},
    "overall_pass": True,
    "summary": "원문에 충실하고 분류 정확. 환각 없음.",
}


def _lm_response(content: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}


def _judge_response(score: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(score, ensure_ascii=False)}]}


@respx.mock
def test_evaluate_one_full_flow_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    settings = get_settings()
    respx.post(f"{settings.llm_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json=_lm_response(_LM_NOTE))
    )
    respx.post(f"{JUDGE_URL}/messages").mock(
        return_value=httpx.Response(200, json=_judge_response(_JUDGE_SCORE))
    )
    r = asyncio.run(evaluate_one(
        _case(), settings=settings, judge_model="claude-sonnet-4-6", dry_run=False,
    ))
    assert r.error is None
    assert r.note is not None
    assert r.score is not None
    assert r.score.overall_pass is True
    assert r.stage == "ok"


@respx.mock
def test_evaluate_one_lm_studio_failure() -> None:
    settings = get_settings()
    respx.post(f"{settings.llm_base_url}/chat/completions").mock(
        return_value=httpx.Response(503, text="LM Studio off")
    )
    r = asyncio.run(evaluate_one(
        _case(), settings=settings, judge_model="claude-sonnet-4-6", dry_run=False,
    ))
    assert r.note is None
    assert r.error is not None
    assert "note gen" in r.error
    assert r.stage == "note_generation_failed"


@respx.mock
def test_evaluate_one_judge_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """노트 생성은 성공, judge만 실패 — 노트는 보존."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    settings = get_settings()
    respx.post(f"{settings.llm_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json=_lm_response(_LM_NOTE))
    )
    respx.post(f"{JUDGE_URL}/messages").mock(return_value=httpx.Response(429, text="rate limit"))
    r = asyncio.run(evaluate_one(
        _case(), settings=settings, judge_model="claude-sonnet-4-6", dry_run=False,
    ))
    assert r.note is not None  # 생성된 노트는 보존
    assert r.score is None
    assert r.error and "judge" in r.error
    assert r.stage == "judge_failed"


@respx.mock
def test_evaluate_one_dry_run_skips_judge() -> None:
    """dry-run은 judge 호출 안 함 — API 키 없어도 동작."""
    settings = get_settings()
    respx.post(f"{settings.llm_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json=_lm_response(_LM_NOTE))
    )
    # judge URL을 mock하지 않음 — 호출 시도 시 RouteNotMocked 발생할 텐데 dry-run에서 호출 안 해야 함
    r = asyncio.run(evaluate_one(
        _case(), settings=settings, judge_model="claude-sonnet-4-6", dry_run=True,
    ))
    assert r.note is not None
    assert r.score is None
    assert r.error == "dry-run (judge skipped)"


def test_aggregate_empty() -> None:
    s = aggregate([])
    assert s["total"] == 0
    assert s["valid"] == 0


def test_render_markdown_smoke() -> None:
    md = render_markdown([], aggregate([]))
    assert "LLM-as-Judge 평가 리포트" in md


def test_render_json_valid() -> None:
    js = render_json([], aggregate([]))
    parsed = json.loads(js)
    assert parsed["results"] == []


def test_seed_cases_load_via_runner() -> None:
    """실제 시드 케이스 5개가 schema validation 통과하는지 회귀 테스트."""
    from backend.eval.cases import load_cases
    cases = load_cases(Path("tests/fixtures/eval_cases"), include_pending=True)
    ids = {c.id for c in cases}
    assert ids == {
        "drug_ambiguity_01",
        "section_misclass_01",
        "missing_info_01",
        "hallucination_trap_01",
        "normal_01",
    }
    # 모두 합성 표기 + pending 상태
    assert all(c.is_synthetic for c in cases)
    assert all(c.review_status == "pending" for c in cases)
