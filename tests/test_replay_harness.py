"""Edit-replay harness 단위/통합 테스트.

LM Studio 호출이 필요한 시나리오는 respx로 mock — pytest 기본 실행에서 항상 동작.
async 함수는 의존성 추가 없이 asyncio.run()으로 직접 실행 (기존 코드베이스가
pytest-asyncio를 쓰지 않는 컨벤션 유지).
"""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from backend.feedback.models import EditFeedback, SectionDiff
from backend.soap.models import ClinicalNote
from tools.eval.replay_edits import (
    aggregate,
    load_jsonl,
    render_json,
    render_markdown,
    replay_one,
)


def _entry(
    *,
    format_id: str = "soap",
    source: str = "환자가 호소합니다.",
    original: dict[str, str] | None = None,
    edited: dict[str, str] | None = None,
) -> EditFeedback:
    original = original or {"subjective": "S baseline", "objective": "", "assessment": "", "plan": ""}
    edited = edited or original
    diffs = [
        SectionDiff(
            section=k,
            original=original.get(k, ""),
            edited=edited.get(k, ""),
            changed=original.get(k, "") != edited.get(k, ""),
        )
        for k in set(original) | set(edited)
    ]
    return EditFeedback(
        timestamp="2026-05-04T00:00:00Z",
        audio_duration_seconds=10.0,
        raw_text=source,
        corrected_text=source,
        format_id=format_id,
        original_note=ClinicalNote(sections=original),
        edited_note=ClinicalNote(sections=edited),
        diffs=diffs,
        applied_replacements=[],
        uncertain_segments=[],
    )


def test_load_jsonl_skips_blank_and_invalid(tmp_path: Path) -> None:
    p = tmp_path / "edits.jsonl"
    valid = _entry().model_dump_json()
    p.write_text(f"{valid}\n\nnot-json\n{valid}\n", encoding="utf-8")
    out = load_jsonl(p)
    assert len(out) == 2


def test_load_jsonl_limit(tmp_path: Path) -> None:
    p = tmp_path / "edits.jsonl"
    body = "\n".join(_entry().model_dump_json() for _ in range(5))
    p.write_text(body, encoding="utf-8")
    assert len(load_jsonl(p, limit=2)) == 2


def test_load_jsonl_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_jsonl(tmp_path / "nope.jsonl")


def test_aggregate_empty() -> None:
    s = aggregate([])
    assert s["overall"]["n"] == 0
    assert s["total"] == 0


def test_replay_one_unknown_format(tmp_path: Path) -> None:
    """존재하지 않는 format_id면 LLM 호출 없이 error 반환."""
    from backend.config import Settings
    settings = Settings(formats_dir=tmp_path)  # 빈 디렉터리
    fb = _entry(format_id="ghost")
    r = asyncio.run(replay_one(fb, settings=settings, index=0))
    assert r.error is not None
    assert "ghost" in r.error
    assert r.replay is None
    # baseline 거리는 정상 계산
    assert r.baseline_to_gold.total_distance == 0


@respx.mock
def test_replay_one_success_path() -> None:
    """LM Studio 호출을 mock — 새 LLM이 사용자 gold와 동일한 출력을 내면 improvement>0."""
    from backend.config import get_settings
    settings = get_settings()

    fb = _entry(
        original={"subjective": "예전 LLM 출력", "objective": "", "assessment": "", "plan": ""},
        edited={"subjective": "사용자가 고친 정답", "objective": "", "assessment": "", "plan": ""},
    )
    # 새 LLM이 사용자 gold와 정확히 일치하는 응답을 반환했다고 mock
    new_response = {
        "subjective": "사용자가 고친 정답",
        "objective": "",
        "assessment": "",
        "plan": "",
        "uncertain_segments": [],
    }
    respx.post(f"{settings.llm_base_url}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(new_response, ensure_ascii=False)}}
                ]
            },
        )
    )

    r = asyncio.run(replay_one(fb, settings=settings, index=0))
    assert r.error is None
    assert r.replay_to_gold is not None
    assert r.replay_to_gold.total_distance == 0  # 새 출력 == gold
    assert r.improvement is not None
    assert r.improvement > 0  # baseline은 차이 있었으니 개선


@respx.mock
def test_replay_one_llm_error_returns_failure() -> None:
    from backend.config import get_settings
    settings = get_settings()
    respx.post(f"{settings.llm_base_url}/chat/completions").mock(
        return_value=httpx.Response(500, text="server error")
    )
    fb = _entry()
    r = asyncio.run(replay_one(fb, settings=settings, index=0))
    assert r.error is not None
    assert r.replay is None
    # baseline 거리는 그래도 계산됨
    assert r.baseline_to_gold is not None


def test_render_markdown_smoke() -> None:
    # 빈 결과여도 깨지지 않음
    md = render_markdown([], aggregate([]))
    assert "Edit-Replay Harness Report" in md


def test_render_json_is_valid_json() -> None:
    js = render_json([], aggregate([]))
    parsed = json.loads(js)
    assert "summary" in parsed
    assert parsed["results"] == []
