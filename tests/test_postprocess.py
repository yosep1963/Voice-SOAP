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


# === 외래 dictation 회귀 (2026-05-06) — 신규 룰 검증 ===
# 19 케이스 분석으로 도출된 룰들. 각 룰이 작동하면서 false positive 안 내는지 확인.

def _real_rules():
    repo_root = Path(__file__).resolve().parent.parent
    return load_postprocess_rules(repo_root / "hints" / "postprocess.yaml")


def test_new_drug_rules() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("환자에게 인유제 사용을 결정", rules)
    assert "이뇨제" in out and "인유제" not in out
    out, _ = apply_postprocess("Tully Fresh 시작", rules)
    assert "terlipressin" in out
    out, _ = apply_postprocess("Tully Free 투여 중", rules)
    assert "terlipressin" in out


def test_new_lab_rules() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("비료루빈 5.8", rules)
    assert "빌리루빈" in out
    out, _ = apply_postprocess("헤모글루빈 9.0", rules)
    assert "헤모글로빈" in out
    out, _ = apply_postprocess("ASD-LT는 정상", rules)
    assert "AST/ALT" in out
    out, _ = apply_postprocess("ASDLT 30입니다", rules)
    assert "AST/ALT" in out


def test_asd_lt_false_positive_guarded() -> None:
    """ASD 단독(심방중격결손)은 매칭되면 안 됨. lookahead로 'LT' 뒤 boundary 강제."""
    rules = _real_rules()
    out, _ = apply_postprocess("심장 ASD 의심", rules)
    assert "ASD" in out  # 그대로 보존
    assert "AST/ALT" not in out


def test_format_increase_typo() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("CRP 30으로 증거되어 있고", rules)
    assert "증가되어" in out and "증거되어" not in out


def test_intrahepatic_duct_transliteration() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("양쪽 인트라파틱 덕트 확장", rules)
    assert "intrahepatic duct" in out


def test_child_pugh_huk_variant() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("차일드 훅 A 8점", rules)
    assert "Child-Pugh" in out
    # 훅 A → Pugh A는 차일드 훅 룰이 먼저 적용되어 발생 안 함 (의도)
    out, _ = apply_postprocess("훅 B 7점", rules)
    assert "Pugh B" in out


def test_score_severity_typo() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("간경변 경도 평가", rules)
    assert "간경변 중증도" in out


def test_hepatitis_b_c_variants() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("비형간염 추적", rules)
    assert "B형간염" in out
    out, _ = apply_postprocess("비시간염", rules)
    assert "B형간염" in out
    out, _ = apply_postprocess("시형간염 5년", rules)
    assert "C형간염" in out


def test_diagnosis_transliteration_variants() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("아사이티스 동반", rules)
    assert "ascites" in out
    out, _ = apply_postprocess("시로시스로 진단", rules)
    assert "cirrhosis" in out
    out, _ = apply_postprocess("리플렉트리 ascites", rules)
    assert "refractory" in out


def test_symptom_finding_typos() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("복부평만 심함", rules)
    assert "복부팽만" in out
    out, _ = apply_postprocess("부품행만 심함", rules)
    assert "복부팽만" in out
    out, _ = apply_postprocess("간경변 소균이 보여", rules)
    assert "소견이 보" in out


def test_finding_english_transliterations() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("CT에서 멀티풀 리버 메스 발견", rules)
    assert "multiple liver mass" in out
    out, _ = apply_postprocess("디스텐데이션 관찰", rules)
    assert "distension" in out
    out, _ = apply_postprocess("디스텐테이션 관찰", rules)
    assert "distension" in out
    out, _ = apply_postprocess("Exposed Boto 확인", rules)
    assert "exposed vessel" in out
    out, _ = apply_postprocess("Expose Boto 보임", rules)
    assert "exposed vessel" in out


def test_exam_transliterations_and_typos() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("어드밍션 판넬 검사", rules)
    assert "Admission panel" in out
    out, _ = apply_postprocess("어드미션 판넬 검사", rules)
    assert "Admission panel" in out
    out, _ = apply_postprocess("CT 철령한 결과", rules)
    assert "시행한" in out


def test_ganchopa_extension_includes_jongpa() -> None:
    """기존 간총파|간청파 alternation에 간종파 추가."""
    rules = _real_rules()
    out, _ = apply_postprocess("간종파 검사 결과", rules)
    assert "간초음파" in out


def test_excluded_rules_do_not_fire() -> None:
    """보류한 위험 룰이 실수로 추가되지 않았는지 확인."""
    rules = _real_rules()
    # 엄청 부사는 그대로 보존
    out, _ = apply_postprocess("환자가 엄청 좋아졌다고 함", rules)
    assert "엄청" in out
    assert "음성이었음" not in out
    # 출혈 진단도 그대로 (정당한 임상 표현)
    out, _ = apply_postprocess("정맥류 출혈 진단은 명확", rules)
    assert "출혈 진단" in out
    assert "추정 진단" not in out


# === 외래 dictation 회귀 2회차 (2026-05-06) — HCC 84세 케이스 ===

def test_pulse_rate_transliteration() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("펄스 라이트 78회", rules)
    assert "Pulse rate" in out
    out, _ = apply_postprocess("펄스라이트 80", rules)
    assert "Pulse rate" in out


def test_body_temperature_transliteration() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("바디 템프리션은 36도", rules)
    assert "Body temperature" in out
    out, _ = apply_postprocess("바디 템퍼리션 37", rules)
    assert "Body temperature" in out


def test_birinrubi_added_to_bilirubin_rule() -> None:
    """기존 비료루빈|비루리빈 룰에 비린루비 추가."""
    rules = _real_rules()
    out, _ = apply_postprocess("비린루비는 1.1", rules)
    assert "빌리루빈" in out
    # 기존 변형도 여전히 작동
    out, _ = apply_postprocess("비료루빈 5.8", rules)
    assert "빌리루빈" in out


def test_soahki_internal_med_typo() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("환자가 소아기내과로 전과되었습니다", rules)
    assert "소화기내과" in out


def test_liver_dynamic_ct_dianamik_variant() -> None:
    """기존 룰에 다이나믹(ㅏ) 변형 추가."""
    rules = _real_rules()
    out, _ = apply_postprocess("리버다이나믹CT 촬영", rules)
    assert "Liver dynamic CT" in out
    # 기존 다이너믹(ㅓ)도 여전히 작동
    out, _ = apply_postprocess("리버 다이너믹 CT", rules)
    assert "Liver dynamic CT" in out


def test_thc_added_to_tace_rule() -> None:
    """기존 TAC|TEC 룰에 THC 추가. lookahead([를을시계])로 cannabinoid 컨텍스트 충돌 회피."""
    rules = _real_rules()
    # 직접 후속 한국어 조사·명사 — 매칭
    out, _ = apply_postprocess("THC를 시행해서 치료", rules)
    assert "TACE" in out
    out, _ = apply_postprocess("THC시술 계획", rules)
    assert "TACE" in out
    # 공백·다른 단어 후속 — 매칭 안 됨 (cannabinoid 의미 보존)
    out, _ = apply_postprocess("THC 농도 검사", rules)
    assert "THC" in out
    assert "TACE" not in out


def test_user_case_full_round_trip() -> None:
    """2026-05-06 HCC 84세 케이스의 STT 결과에 모든 신규 룰이 정상 작동하는지 통합 확인."""
    rules = _real_rules()
    sample = (
        "환자의 혈압은 BP 120-80, 펄스 라이트 78회, 바디 템프리션은 36도, "
        "비린루비는 1.1로 정상. 리버다이나믹CT 촬영. 소아기내과로 전과. "
        "THC를 시행해서 간세포암을 치료할 예정."
    )
    out, applied = apply_postprocess(sample, rules)
    assert "Pulse rate" in out
    assert "Body temperature" in out
    assert "빌리루빈" in out
    assert "Liver dynamic CT" in out
    assert "소화기내과" in out
    assert "TACE" in out
    # 6 신규/확장 룰 모두 fire
    assert len(applied) == 6


# === 외래 dictation 회귀 3회차 (2026-05-06) — turbo 모델 전환 후 신규 변형 ===

def test_childful_to_child_pugh() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("Childful Class A 6점", rules)
    assert "Child-Pugh" in out
    assert "Childful" not in out


def test_meldr_to_meld() -> None:
    rules = _real_rules()
    out, _ = apply_postprocess("Meldr 점수는 12점", rules)
    assert "MELD" in out
    assert "Meldr" not in out


def test_gan_uhyeop_to_uyeop() -> None:
    """간 우협 → 간 우엽. '우협' 단독은 매치 안 됨 (간 접두 한정)."""
    rules = _real_rules()
    out, _ = apply_postprocess("간 우협의 5cm 크기", rules)
    assert "간 우엽" in out
    assert "우협" not in out
    # '간' 없는 '우협'은 보존 (안전성 검증)
    out, _ = apply_postprocess("우협 단독은 변경 안 됨", rules)
    assert "우협" in out


def test_soahki_internal_med_with_space() -> None:
    """기존 '소아기내과' 룰을 '소아기\\s*내과'로 확장. 공백 변형도 매치."""
    rules = _real_rules()
    out, _ = apply_postprocess("소아기 내과로 전과", rules)
    assert "소화기내과" in out
    # 기존 공백 없는 변형도 여전히 작동
    out, _ = apply_postprocess("소아기내과로 전과", rules)
    assert "소화기내과" in out
