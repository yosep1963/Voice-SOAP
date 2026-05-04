"""과거 환각 회귀 테스트 (Harness §Failure-to-Rule).

이 파일에 있는 테스트는 *과거에 실제로 발생한* STT/LLM 환각이 다시 발생하지
않도록 영구적으로 차단한다. 새 환각이 발견될 때마다 이 파일에 케이스를 추가한다.

각 테스트는 다음을 명시한다:
    1. 원본 환각 사례 (재현 입력 / 잘못된 출력)
    2. 영구 차단 위치 (어느 코드/설정이 가드인지)
    3. 가드가 사라지면 어떤 위험이 생기는지

회귀 테스트가 깨지면 "이건 그냥 갱신하면 된다"가 아니라 *왜 가드가 사라졌는지*
를 먼저 확인해야 한다. CLAUDE.md §"보안 표면" 및 plan.md §"변경 이력" 참조.
"""
from pathlib import Path
from unittest.mock import patch

from backend.stt.postprocess import apply_postprocess, load_postprocess_rules
from backend.stt.whisper_engine import transcribe_audio


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
POSTPROCESS_YAML = REPO_ROOT / "hints" / "postprocess.yaml"


# ---------------------------------------------------------------------------
# Case 1: "활활활..." 무한 반복 환각 (2026-04 사용자 녹음에서 발견)
# ---------------------------------------------------------------------------
# 증상:  사용자 녹음 중 침묵 구간에서 Whisper가 직전 segment 텍스트를 컨텍스트로
#        받아 같은 음절을 무한히 생성 ("활활활활활...").
# 가드:  backend/stt/whisper_engine.py:transcribe_audio 가 mlx_whisper.transcribe
#        호출 시 두 옵션을 반드시 전달해야 한다:
#           - condition_on_previous_text=False  (이전 segment 컨텍스트 차단)
#           - compression_ratio_threshold=2.0   (반복 감지 시 fallback temperature)
# 위험:  이 옵션이 사라지면 같은 환각이 다시 발생하고, 환자 dictation 중간에
#        의미 없는 반복 텍스트가 SOAP 입력으로 흘러간다 (LLM이 잘못된 진단으로
#        오해할 수 있음).

def test_whisper_disables_previous_text_conditioning() -> None:
    """transcribe_audio는 condition_on_previous_text=False를 반드시 전달한다."""
    with patch("backend.stt.whisper_engine.mlx_whisper.transcribe") as mock_transcribe, \
         patch("backend.stt.whisper_engine.get_audio_duration", return_value=10.0):
        mock_transcribe.return_value = {"text": "안녕하세요", "segments": []}
        transcribe_audio(Path("/fake/audio.wav"), model_repo="fake-model", prompt=None)

    assert mock_transcribe.called, "mlx_whisper.transcribe가 호출되어야 함"
    kwargs = mock_transcribe.call_args.kwargs
    assert kwargs.get("condition_on_previous_text") is False, (
        "condition_on_previous_text=False 가드가 제거됨. "
        "'활활활...' 반복 환각이 다시 발생할 수 있음. "
        "CLAUDE.md §'Whisper 호출 시그니처는 PoC와 의도적으로 다르다' 참조."
    )


def test_whisper_uses_strict_compression_ratio_threshold() -> None:
    """transcribe_audio는 compression_ratio_threshold=2.0을 반드시 전달한다."""
    with patch("backend.stt.whisper_engine.mlx_whisper.transcribe") as mock_transcribe, \
         patch("backend.stt.whisper_engine.get_audio_duration", return_value=10.0):
        mock_transcribe.return_value = {"text": "안녕하세요", "segments": []}
        transcribe_audio(Path("/fake/audio.wav"), model_repo="fake-model", prompt=None)

    kwargs = mock_transcribe.call_args.kwargs
    assert kwargs.get("compression_ratio_threshold") == 2.0, (
        "compression_ratio_threshold가 기본값(2.4)으로 돌아가면 반복 텍스트 감지가 "
        "느려져 '활활활...' 환각이 잡히지 않을 수 있음."
    )


# ---------------------------------------------------------------------------
# Case 2: "표로세미드" → LLM이 "토르세미드"로 환각 (약물 오인식, 가장 위험)
# ---------------------------------------------------------------------------
# 증상:  Whisper가 푸로세미드(Furosemide)를 "표로세미드"로 잘못 듣고, LLM이
#        문맥상 "비슷한 약물"이라며 토르세미드(Torsemide)로 자체 보정.
#        둘은 다른 약물이며 처방 오류로 직결되는 환각.
# 가드:  hints/postprocess.yaml 에 "표로세미드" → "푸로세미드" 룰이 LLM 호출
#        *전*에 적용되어야 한다.
# 위험:  이 룰이 사라지면 LLM이 다시 약물명을 환각할 수 있고, 의무기록에
#        잘못된 약물이 기재될 수 있음 (의료사고 직결).

def test_furosemide_hallucination_blocked_by_postprocess() -> None:
    rules = load_postprocess_rules(POSTPROCESS_YAML)
    sample = "복수 조절 위해 표로세미드 40mg 정량합니다."
    out, applied = apply_postprocess(sample, rules)

    assert "푸로세미드" in out, (
        "'표로세미드' → '푸로세미드' 후처리 룰이 사라짐. "
        "LLM이 '토르세미드'로 환각할 위험 — 다른 약물임. "
        "hints/postprocess.yaml의 category=drug 룰 확인."
    )
    assert "표로세미드" not in out, "원본 오인식이 그대로 남음"
    assert "토르세미드" not in out, "절대 등장해서는 안 되는 약물"

    drug_replacements = [a for a in applied if a.category == "drug"]
    assert any("푸로세미드" == a.replace for a in drug_replacements), (
        "drug 카테고리로 분류된 푸로세미드 치환이 기록되지 않음"
    )


# ---------------------------------------------------------------------------
# Case 3: "총 빌리루빈" → Whisper가 "청비루빈" 등으로 오인식
# ---------------------------------------------------------------------------
# 증상:  Whisper가 "총 빌리루빈"을 "청비루빈", "총비루빈", "청미를루빈" 등으로
#        다양하게 깨먹음. 검사명이 깨지면 LLM이 Object 섹션에 다른 검사로
#        해석하거나 빈 값으로 처리할 위험.
# 가드:  hints/postprocess.yaml 의 lab 카테고리 룰 (여러 변형 alternation).
# 위험:  검사명이 표준화되지 않으면 SOAP의 O(Objective) 섹션 정확도가 떨어지고,
#        후속 분석 (학습 시스템) 에서 같은 검사가 여러 형태로 분산 집계됨.

def test_total_bilirubin_hallucination_blocked_by_postprocess() -> None:
    rules = load_postprocess_rules(POSTPROCESS_YAML)

    variants = ["청비루빈", "총비루빈", "청미를루빈", "총미를루빈", "청빌루빈"]
    for variant in variants:
        sample = f"{variant} 2.5 mg/dL 입니다."
        out, _ = apply_postprocess(sample, rules)
        assert "총 빌리루빈" in out, (
            f"'{variant}' → '총 빌리루빈' 후처리 룰이 사라짐. "
            f"hints/postprocess.yaml category=lab 룰 확인."
        )
        assert variant not in out, f"원본 오인식 '{variant}' 가 그대로 남음"


# ---------------------------------------------------------------------------
# 메타 회귀: 후처리 사전이 LLM 호출 *전*에 적용되는 구조가 유지되는지
# ---------------------------------------------------------------------------
# 가드의 가드. 위 환각 차단은 모두 "postprocess 가 LLM 입력 만든다"는 전제에
# 의존한다. 이 구조가 깨지면 (예: process.py 가 raw_text 를 LLM에 직접 넘김)
# 후처리 사전이 무용지물이 되므로 별도 회귀로 잡는다.

def test_process_pipeline_uses_postprocessed_text_for_llm() -> None:
    """/process 엔드포인트가 raw_text 가 아닌 후처리된 text를 LLM에 넘기는지 확인.

    소스 정적 검사. 동작 검증은 tests/test_soap_endpoint.py 와
    tests/test_postprocess.py 가 별도 담당. 이 테스트는 *순서*가 깨지면
    잡는 것이 목적: apply_postprocess → structure_to_soap.
    """
    process_py = REPO_ROOT / "backend" / "api" / "process.py"
    src = process_py.read_text(encoding="utf-8")

    assert "apply_postprocess" in src, (
        "backend/api/process.py 가 apply_postprocess를 호출하지 않음. "
        "후처리 사전이 LLM 입력에 적용되지 않으면 모든 약물/검사명 환각 가드가 무력화됨."
    )
    assert "structure_to_soap" in src, "LLM 호출 자체가 사라짐"

    pp_idx = src.index("apply_postprocess")
    llm_idx = src.index("structure_to_soap(")
    assert pp_idx < llm_idx, (
        "apply_postprocess가 structure_to_soap *뒤에* 호출되도록 순서가 바뀜. "
        "LLM이 raw_text를 받게 되어 약물/검사명 환각 가드가 무력화됨."
    )

    # LLM에 raw_text를 직접 넘기는 명백한 안티패턴 차단
    assert "structure_to_soap(\n            transcription.raw_text" not in src, (
        "structure_to_soap에 transcription.raw_text를 직접 전달하면 후처리가 우회됨"
    )
