"""포맷 yaml 로더 + 시스템 프롬프트 빌더 테스트."""
from pathlib import Path

import pytest

from backend.soap.formats import (
    FormatDefinition,
    get_cached_format,
    load_format,
)
from backend.soap.prompts import build_system_prompt, build_user_prompt

FORMATS_DIR = Path(__file__).resolve().parents[1] / "hints" / "formats"
GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "soap_system_prompt_golden.txt"


def test_load_soap_format() -> None:
    fmt = load_format(FORMATS_DIR, "soap")
    assert fmt.id == "soap"
    assert fmt.name == "SOAP (재진)"
    assert {s.key for s in fmt.sections} == {"subjective", "objective", "assessment", "plan"}
    assert len(fmt.few_shots) == 5


def test_load_initial_visit_format() -> None:
    fmt = load_format(FORMATS_DIR, "initial_visit")
    assert fmt.id == "initial_visit"
    expected = {"cc", "pi", "past_hx", "family_hx", "pe", "imp", "plan"}
    assert {s.key for s in fmt.sections} == expected
    assert len(fmt.few_shots) == 5
    # 임상 원칙: 음주력은 PI와 Past Hx 양쪽에 들어가야 함
    # 예시 1(알코올성 간경변)이 이 패턴을 보여야 함
    shot1 = fmt.few_shots[0]
    assert "음주" in shot1.output["pi"]
    assert "음주" in shot1.output["past_hx"]


def test_initial_visit_system_prompt_builds_without_error() -> None:
    """initial_visit 포맷도 SYSTEM_PROMPT를 정상적으로 빌드 (구조적 검증)."""
    from backend.soap.prompts import build_system_prompt

    fmt = load_format(FORMATS_DIR, "initial_visit")
    prompt = build_system_prompt(fmt)
    # 7섹션 정의가 모두 포함
    for key in ["cc", "pi", "past_hx", "family_hx", "pe", "imp", "plan"]:
        assert f"- {key}:" in prompt
    # 출력 형식 7섹션 + uncertain_segments
    assert '"cc":""' in prompt
    assert '"plan":""' in prompt
    assert '"uncertain_segments":[]' in prompt


def test_load_format_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_format(tmp_path, "nonexistent")


def test_load_format_id_mismatch(tmp_path: Path) -> None:
    bad = tmp_path / "wrong.yaml"
    bad.write_text(
        "id: actually_other\nname: x\nintro: x\n"
        "sections: [{key: a, label: A, definition: x}]\n"
        "strict_rules: [r]\n"
        "few_shots: [{label: l, input: i, output: {a: '', uncertain_segments: []}}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="id mismatch"):
        load_format(tmp_path, "wrong")


def test_few_shot_unknown_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "x.yaml"
    p.write_text(
        "id: x\nname: x\nintro: x\n"
        "sections: [{key: a, label: A, definition: x}]\n"
        "strict_rules: [r]\n"
        "few_shots: [{label: l, input: i, output: {a: '', UNKNOWN: '', uncertain_segments: []}}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown keys"):
        load_format(tmp_path, "x")


def test_few_shot_missing_section_rejected(tmp_path: Path) -> None:
    p = tmp_path / "x.yaml"
    p.write_text(
        "id: x\nname: x\nintro: x\n"
        "sections: [{key: a, label: A, definition: x}, {key: b, label: B, definition: y}]\n"
        "strict_rules: [r]\n"
        "few_shots: [{label: l, input: i, output: {a: '', uncertain_segments: []}}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing section keys"):
        load_format(tmp_path, "x")


def test_soap_system_prompt_byte_equivalent_to_golden() -> None:
    """soap.yaml로 빌드한 SYSTEM_PROMPT가 골든 파일과 byte-for-byte 일치.
    이 동등성이 깨지면 LLM 출력 회귀 — 의도된 변경이면 골든 파일도 갱신할 것.
    """
    fmt = load_format(FORMATS_DIR, "soap")
    built = build_system_prompt(fmt)
    golden = GOLDEN_PATH.read_text(encoding="utf-8")
    assert built == golden, (
        f"build_system_prompt 출력이 골든과 다름.\n"
        f"--- BUILT (len={len(built)}) ---\n{built}\n"
        f"--- GOLDEN (len={len(golden)}) ---\n{golden}"
    )


def test_get_cached_format_returns_same_instance() -> None:
    a = get_cached_format(FORMATS_DIR, "soap")
    b = get_cached_format(FORMATS_DIR, "soap")
    assert a is b


def test_build_user_prompt_unchanged() -> None:
    """user prompt는 변경되지 않았음 (안전장치)."""
    out = build_user_prompt("테스트 dictation")
    assert "테스트 dictation" in out
    assert "다음 외래 dictation을 SOAP JSON으로" in out
