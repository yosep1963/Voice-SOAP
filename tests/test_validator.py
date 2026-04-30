from backend.soap.models import SoapNote
from backend.soap.validator import validate_soap


def test_validator_passes_when_numbers_match() -> None:
    src = "AST 85, ALT 92, 빌리루빈 2.3입니다."
    note = SoapNote(objective="AST 85, ALT 92, 빌리루빈 2.3")
    report = validate_soap(src, note)
    assert report.passed
    assert report.warnings == []


def test_validator_flags_hallucinated_numbers() -> None:
    src = "AST 85입니다."
    note = SoapNote(objective="AST 85, ALT 200, 크레아티닌 1.5")  # 200, 1.5는 환각
    report = validate_soap(src, note)
    assert not report.passed
    assert "200" in report.extra_numbers
    assert "1.5" in report.extra_numbers
    assert any("환각" in w for w in report.warnings)


def test_validator_flags_empty_response() -> None:
    src = "환자 호소 텍스트."
    note = SoapNote()  # 모든 필드 빈 값
    report = validate_soap(src, note)
    assert not report.passed
    assert any("비어있음" in w for w in report.warnings)
