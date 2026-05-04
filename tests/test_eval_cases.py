from pathlib import Path

import pytest

from backend.eval.cases import SyntheticCase, load_case, load_cases


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


_VALID = """
id: drug_amb_01
format_id: soap
trap_type: drug_ambiguity
source_text: 60세 남자 환자 푸로세미드 40mg 처방 중입니다.
expected_behavior: 푸로세미드를 plan에 정확히 기재. 토르세미드 등 유사 약물로 변환 금지.
known_pitfalls:
  - LLM이 푸로세미드를 토르세미드로 잘못 추측
  - 용량 40mg을 누락
is_synthetic: true
review_status: approved
"""


def test_load_valid_case(tmp_path: Path) -> None:
    p = _write(tmp_path / "drug_amb_01.yaml", _VALID)
    case = load_case(p)
    assert case.id == "drug_amb_01"
    assert case.trap_type == "drug_ambiguity"
    assert case.is_synthetic is True
    assert len(case.known_pitfalls) == 2


def test_is_synthetic_false_is_rejected(tmp_path: Path) -> None:
    """PHI guard — is_synthetic=False는 schema 단계에서 거부."""
    p = _write(tmp_path / "bad.yaml", _VALID.replace("is_synthetic: true", "is_synthetic: false"))
    with pytest.raises(ValueError, match="must be True"):
        load_case(p)


def test_is_synthetic_missing_is_rejected(tmp_path: Path) -> None:
    """기본값을 두지 않음 — 명시적 is_synthetic 선언 강제."""
    body = _VALID.replace("is_synthetic: true\n", "")
    p = _write(tmp_path / "bad.yaml", body)
    with pytest.raises(ValueError):
        load_case(p)


def test_unknown_trap_type_rejected(tmp_path: Path) -> None:
    body = _VALID.replace("trap_type: drug_ambiguity", "trap_type: bogus_trap")
    p = _write(tmp_path / "bad.yaml", body)
    with pytest.raises(ValueError):
        load_case(p)


def test_extra_fields_rejected(tmp_path: Path) -> None:
    """yaml 오타 catch — 알 수 없는 필드는 schema 거부."""
    body = _VALID + "extra_unknown_field: oops\n"
    p = _write(tmp_path / "bad.yaml", body)
    with pytest.raises(ValueError):
        load_case(p)


def test_short_source_text_rejected(tmp_path: Path) -> None:
    body = _VALID.replace(
        "source_text: 60세 남자 환자 푸로세미드 40mg 처방 중입니다.",
        "source_text: x",
    )
    p = _write(tmp_path / "bad.yaml", body)
    with pytest.raises(ValueError):
        load_case(p)


def test_load_cases_skips_pending_by_default(tmp_path: Path) -> None:
    _write(tmp_path / "a.yaml", _VALID)  # approved
    _write(tmp_path / "b.yaml", _VALID.replace("drug_amb_01", "drug_amb_02").replace("approved", "pending"))
    _write(tmp_path / "c.yaml", _VALID.replace("drug_amb_01", "drug_amb_03").replace("approved", "rejected"))
    cases = load_cases(tmp_path)
    assert len(cases) == 1
    assert cases[0].id == "drug_amb_01"


def test_load_cases_include_pending(tmp_path: Path) -> None:
    _write(tmp_path / "a.yaml", _VALID)
    _write(tmp_path / "b.yaml", _VALID.replace("drug_amb_01", "drug_amb_02").replace("approved", "pending"))
    cases = load_cases(tmp_path, include_pending=True)
    assert len(cases) == 2
    assert {c.id for c in cases} == {"drug_amb_01", "drug_amb_02"}


def test_load_cases_duplicate_id_rejected(tmp_path: Path) -> None:
    _write(tmp_path / "a.yaml", _VALID)
    _write(tmp_path / "b.yaml", _VALID)  # 같은 id
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(tmp_path)


def test_load_cases_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_cases(tmp_path / "ghost")
