from backend.privacy.masking import mask_identifiers


def test_mask_resident_registration_number() -> None:
    src = "환자 800101-1234567 입니다."
    out = mask_identifiers(src)
    assert "[주민번호]" in out
    assert "800101-1234567" not in out


def test_mask_patient_id_8plus_digits() -> None:
    src = "등록번호 12345678"
    assert mask_identifiers(src) == "등록번호 [등록번호]"


def test_does_not_mask_lab_values() -> None:
    """의학 검사 수치는 1-3자리. 마스킹되면 안 됨."""
    src = "AST 85, ALT 92, 빌리루빈 2.3, 알부민 3.1, MELD 18, Child-Pugh B 7"
    out = mask_identifiers(src)
    for n in ["85", "92", "2.3", "3.1", "18", "7"]:
        assert n in out, f"숫자 {n}이 마스킹됨: {out!r}"


def test_does_not_mask_short_drug_doses() -> None:
    """약물 용량(30cc, 550mg, 0.5mg 등)도 마스킹 X."""
    src = "락툴로오스 30cc, 리팍시민 550mg, 엔테카비르 0.5mg"
    out = mask_identifiers(src)
    assert "30" in out and "550" in out and "0.5" in out
