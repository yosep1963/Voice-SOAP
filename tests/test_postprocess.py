from pathlib import Path

import pytest

from backend.stt.postprocess import (
    apply_postprocess,
    get_cached_rules,
    load_postprocess_rules,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "rules.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_rules_basic(tmp_path: Path) -> None:
    p = _write(tmp_path, """
- pattern: "퓨로스마이드"
  replace: "푸로세미드"
  category: drug
""")
    rules = load_postprocess_rules(p)
    assert len(rules) == 1
    assert rules[0].pattern == "퓨로스마이드"
    assert rules[0].category == "drug"


def test_load_rules_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_postprocess_rules(tmp_path / "nonexistent.yaml")


def test_load_rules_default_category(tmp_path: Path) -> None:
    p = _write(tmp_path, '- {pattern: "x", replace: "y"}\n')
    rules = load_postprocess_rules(p)
    assert rules[0].category == "uncategorized"


def test_load_rules_invalid_regex(tmp_path: Path) -> None:
    p = _write(tmp_path, '- {pattern: "[invalid", replace: "x"}\n')
    with pytest.raises(ValueError, match="invalid regex"):
        load_postprocess_rules(p)


def test_load_rules_missing_required_field(tmp_path: Path) -> None:
    p = _write(tmp_path, '- {pattern: "x"}\n')
    with pytest.raises(ValueError, match="missing required field"):
        load_postprocess_rules(p)


def test_load_rules_empty_file(tmp_path: Path) -> None:
    p = _write(tmp_path, "")
    rules = load_postprocess_rules(p)
    assert rules == []


def test_apply_basic_replacement(tmp_path: Path) -> None:
    p = _write(tmp_path, '- {pattern: "표로세미드", replace: "푸로세미드", category: drug}\n')
    rules = load_postprocess_rules(p)
    out, applied = apply_postprocess("표로세미드 40mg 처방", rules)
    assert out == "푸로세미드 40mg 처방"
    assert len(applied) == 1
    assert applied[0].count == 1
    assert applied[0].category == "drug"


def test_apply_alternation(tmp_path: Path) -> None:
    p = _write(tmp_path, '- {pattern: "엔드카벨|엔드카베르", replace: "엔테카비르"}\n')
    rules = load_postprocess_rules(p)
    out, applied = apply_postprocess("엔드카벨과 엔드카베르 둘 다", rules)
    assert out == "엔테카비르과 엔테카비르 둘 다"
    assert applied[0].count == 2


def test_apply_no_match(tmp_path: Path) -> None:
    p = _write(tmp_path, '- {pattern: "표로세미드", replace: "푸로세미드"}\n')
    rules = load_postprocess_rules(p)
    out, applied = apply_postprocess("아무 관계 없는 텍스트", rules)
    assert out == "아무 관계 없는 텍스트"
    assert applied == []


def test_real_postprocess_yaml_loads_and_catches_known_misrecognitions() -> None:
    """실제 hints/postprocess.yaml로 PoC 결과의 알려진 오인식이 잡히는지 회귀 테스트."""
    repo_root = Path(__file__).resolve().parent.parent
    rules = load_postprocess_rules(repo_root / "hints" / "postprocess.yaml")
    assert len(rules) > 5

    poc_text = (
        "복수조절 위해, 표로세미드 40mg, 스피르녹톤 100mg 정량합니다. "
        "엔드카벨 0.5mg 매일 복용 중이며, HVDNA 검출되지 않습니다. "
        "디팍시민 550mg 처방. AST85, ELT92 입니다. 차일드푸 B7점."
    )
    out, applied = apply_postprocess(poc_text, rules)

    # 위험도 높은 약물명 보정 검증
    assert "푸로세미드" in out
    assert "표로세미드" not in out
    assert "스피로노락톤" in out
    assert "엔테카비르" in out
    assert "리팍시민" in out
    # 검사명/포맷 정리
    assert "HBV DNA" in out
    assert "AST 85" in out
    assert "ALT 92" in out
    assert "Child-Pugh" in out

    # 적용된 replacement 카테고리에 drug 포함
    categories = {a.category for a in applied}
    assert "drug" in categories


def test_get_cached_rules_returns_same_instance(tmp_path: Path) -> None:
    p = _write(tmp_path, '- {pattern: "x", replace: "y"}\n')
    a = get_cached_rules(p)
    b = get_cached_rules(p)
    assert a is b  # lru_cache 동일 인스턴스
    get_cached_rules.cache_clear()
