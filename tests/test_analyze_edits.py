"""tools.eval.analyze_edits 단위 테스트.

합성 EditFeedback에 대해 분석 함수가 기대대로 동작하는지 검증.
실데이터(logs/edits.jsonl)는 PHI라 테스트에서 사용 불가.
"""
from collections import Counter
from pathlib import Path

import pytest

from backend.feedback.models import EditFeedback, SectionDiff
from backend.soap.models import ClinicalNote
from backend.stt.postprocess import AppliedReplacement, PostprocessRule
from tools.eval.analyze_edits import (
    CaseAnalysis,
    aggregate,
    analyze_one,
    extract_edit_pairs,
    extract_term_candidates,
    flatten_note,
    load_jsonl,
    load_known_terms,
    render_json,
    render_markdown,
)


def _make_fb(
    *,
    raw: str = "환자가 엔드카벨 복용 중입니다",
    corrected: str = "환자가 엔테카비르 복용 중입니다",
    edited_subj: str = "환자가 엔테카비르 복용 중입니다",
    edited_obj: str = "",
    edited_assess: str = "",
    edited_plan: str = "",
    applied: list[AppliedReplacement] | None = None,
) -> EditFeedback:
    return EditFeedback(
        timestamp="2026-05-06T10:00:00",
        audio_duration_seconds=12.0,
        raw_text=raw,
        corrected_text=corrected,
        format_id="soap",
        original_note=ClinicalNote(sections={
            "subjective": edited_subj,
            "objective": edited_obj,
            "assessment": edited_assess,
            "plan": edited_plan,
        }),
        edited_note=ClinicalNote(sections={
            "subjective": edited_subj,
            "objective": edited_obj,
            "assessment": edited_assess,
            "plan": edited_plan,
        }),
        diffs=[],
        applied_replacements=applied or [],
        uncertain_segments=[],
    )


def test_flatten_note_skips_empty() -> None:
    note = ClinicalNote(sections={"a": "hello", "b": "", "c": "world"})
    assert flatten_note(note) == "hello world"


def test_extract_edit_pairs_finds_replace_opcodes() -> None:
    """difflib는 char-level diff. before/after는 fragment일 수 있으나
    context는 주변 문맥(전체 약물명 포함)을 보여줘야 한다."""
    raw = "환자가 엔드카벨 복용 중입니다"
    edited = "환자가 엔테카비르 복용 중입니다"
    pairs = extract_edit_pairs(raw, edited, max_context=20, min_len=1)
    assert pairs, "최소 1개의 replace opcode가 잡혀야 함"
    has_full_context = any(
        "엔드카벨" in p.before_ctx and "엔테카비르" in p.after_ctx
        for p in pairs
    )
    assert has_full_context


def test_extract_edit_pairs_filters_short_changes() -> None:
    raw = "AB"
    edited = "CD"
    pairs = extract_edit_pairs(raw, edited, max_context=20, min_len=4)
    assert pairs == []


def test_extract_edit_pairs_empty_inputs() -> None:
    assert extract_edit_pairs("", "abc", max_context=10, min_len=1) == []
    assert extract_edit_pairs("abc", "", max_context=10, min_len=1) == []


def test_extract_term_candidates_excludes_known_and_stopwords() -> None:
    text = "환자가 엔테카비르 복용 중. 새약물 처방."
    known = {"엔테카비르"}
    counter = extract_term_candidates(text, known)
    assert "엔테카비르" not in counter  # known
    assert "환자" not in counter        # stopword
    assert "새약물" in counter          # 후보


def test_extract_term_candidates_length_range() -> None:
    """한글 2-8자만 포착 (1자는 조사 노이즈, 9자+는 보통 결합어)."""
    text = "엔테카비르 푸로세미드 스피로노락톤 우르소데옥시콜산"  # 5,5,6,8 chars
    counter = extract_term_candidates(text, set())
    assert "엔테카비르" in counter       # 5자
    assert "푸로세미드" in counter       # 5자
    assert "스피로노락톤" in counter      # 6자
    assert "우르소데옥시콜산" in counter   # 8자


def test_load_known_terms_strips_comments(tmp_path: Path) -> None:
    f = tmp_path / "hints.txt"
    f.write_text(
        "# 주석은 무시\n"
        "약물: 엔테카비르, 푸로세미드\n"
        "# 또 주석\n"
        "검사: AST, ALT, 알부민\n",
        encoding="utf-8",
    )
    terms = load_known_terms(f)
    assert "엔테카비르" in terms
    assert "푸로세미드" in terms
    assert "알부민" in terms
    # AST 같은 영문은 한글 정규식이 안 잡음
    assert "AST" not in terms


def test_load_known_terms_missing_file(tmp_path: Path) -> None:
    assert load_known_terms(tmp_path / "missing.txt") == set()


def test_analyze_one_builds_case_analysis() -> None:
    fb = _make_fb(
        raw="환자가 엔드카벨 복용",
        corrected="환자가 엔테카비르 복용",
        edited_subj="환자가 엔테카비르 복용",
        applied=[AppliedReplacement(
            pattern="엔드카벨|엔드카베르",
            replace="엔테카비르",
            category="drug",
            count=1,
        )],
    )
    c = analyze_one(fb, index=0, max_context=20, min_len=2)
    assert c.index == 0
    assert c.format_id == "soap"
    assert c.raw_len == len(fb.raw_text)
    assert c.applied[0][0] == "엔드카벨|엔드카베르"
    assert c.applied[0][3] == 1
    # original_note == edited_note in this fixture, so distance = 0
    assert c.note_dist == 0


def test_analyze_one_section_changes() -> None:
    fb = EditFeedback(
        timestamp="2026-05-06T10:00:00",
        audio_duration_seconds=10.0,
        raw_text="abc",
        corrected_text="abc",
        format_id="soap",
        original_note=ClinicalNote(sections={"subjective": "원본 내용", "plan": "원본 plan"}),
        edited_note=ClinicalNote(sections={"subjective": "편집된 내용", "plan": "원본 plan"}),
        diffs=[],
        applied_replacements=[],
    )
    c = analyze_one(fb, index=0, max_context=20, min_len=2)
    assert "subjective" in c.section_changes
    assert "plan" not in c.section_changes  # 변경 없음
    assert c.n_sections_changed == 1


def test_aggregate_counts_rules_across_cases() -> None:
    cases = [
        CaseAnalysis(
            index=0, timestamp="t", format_id="soap",
            raw_len=10, corrected_len=10, edited_len=10, note_dist=0,
            n_sections_changed=0,
            applied=[("p1", "r1", "drug", 2)],
        ),
        CaseAnalysis(
            index=1, timestamp="t", format_id="soap",
            raw_len=10, corrected_len=10, edited_len=10, note_dist=0,
            n_sections_changed=0,
            applied=[("p1", "r1", "drug", 1), ("p2", "r2", "lab", 3)],
        ),
    ]
    rules = (
        PostprocessRule.compile("p1", "r1", "drug"),
        PostprocessRule.compile("p2", "r2", "lab"),
        PostprocessRule.compile("p3", "r3", "exam"),  # never fired
    )
    s = aggregate(cases, rules)
    assert s["total"] == 2
    assert s["rule_counts"]["p1"] == 3
    assert s["rule_counts"]["p2"] == 3
    assert any(r[0] == "p3" for r in s["never_fired"])
    assert not any(r[0] == "p1" for r in s["never_fired"])


def test_aggregate_empty_returns_total_zero() -> None:
    assert aggregate([], ())["total"] == 0


def test_render_markdown_smoke() -> None:
    fb = _make_fb()
    c = analyze_one(fb, index=0, max_context=20, min_len=2)
    s = aggregate([c], ())
    md = render_markdown([c], s, term_candidates=Counter(), max_context=20)
    assert "Edit-Log 분석 리포트" in md
    assert "1. 전체 통계" in md
    assert "2. 작동 중인 postprocess 룰" in md
    assert "4. STT 오류 후보" in md
    assert "레이어 매핑 가이드" in md


def test_render_markdown_empty() -> None:
    md = render_markdown([], {"total": 0}, term_candidates=Counter(), max_context=20)
    assert "Edit-Log 분석 리포트" in md
    assert "입력이 비어있음" in md


def test_render_json_valid() -> None:
    import json
    fb = _make_fb()
    c = analyze_one(fb, index=0, max_context=20, min_len=2)
    s = aggregate([c], ())
    js = render_json([c], s)
    parsed = json.loads(js)
    assert parsed["summary"]["total"] == 1
    assert len(parsed["cases"]) == 1
    assert parsed["cases"][0]["index"] == 0


def test_load_jsonl_skips_invalid_lines(tmp_path: Path) -> None:
    f = tmp_path / "log.jsonl"
    fb = _make_fb()
    f.write_text(
        fb.model_dump_json() + "\n"
        + "this is not json\n"
        + "\n"
        + fb.model_dump_json() + "\n",
        encoding="utf-8",
    )
    out = load_jsonl(f)
    assert len(out) == 2  # 2 valid + 1 invalid (skipped) + 1 blank (skipped)


def test_load_jsonl_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_jsonl(tmp_path / "nope.jsonl")
