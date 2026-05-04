"""LLM 프롬프트 빌더. 포맷 정의(yaml)에서 SYSTEM_PROMPT를 동적으로 빌드.

회귀 보증: hints/formats/soap.yaml로 빌드한 결과는
tests/fixtures/soap_system_prompt_golden.txt와 byte-for-byte 일치해야 함.
이 동등성이 깨지면 LLM 출력 품질 회귀 — 골든 파일도 의도적으로 동기화 필요.
"""
import json

from backend.soap.formats import FewShot, FormatDefinition, Section


def _compact_json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _output_template(sections: list[Section]) -> str:
    """`{"subjective":"","objective":"",...,"uncertain_segments":[]}` 형식."""
    ordered: dict[str, object] = {s.key: "" for s in sections}
    ordered["uncertain_segments"] = []
    return _compact_json(ordered)


def _few_shot_block(shot: FewShot, sections: list[Section]) -> str:
    """예시 출력 JSON을 섹션 정의 순서대로 직렬화 (yaml dict 순서에 의존하지 않음)."""
    ordered: dict[str, object] = {}
    for s in sections:
        ordered[s.key] = shot.output.get(s.key, "")
    ordered["uncertain_segments"] = shot.output.get("uncertain_segments", [])
    return f'{shot.label}\n입력: "{shot.input}"\n출력: {_compact_json(ordered)}'


def build_system_prompt(fmt: FormatDefinition) -> str:
    parts: list[str] = []
    parts.append(fmt.intro)
    parts.append("")
    parts.append("각 섹션 정의:")
    for s in fmt.sections:
        parts.append(f"- {s.key}: {s.definition}")
    parts.append("- uncertain_segments: 원문 중 모호하거나 불확실한 표현 (사용자 검토 필요)")
    parts.append("")
    parts.append("엄격한 규칙:")
    for i, rule in enumerate(fmt.strict_rules, start=1):
        parts.append(f"{i}. {rule}")
    parts.append("")
    parts.append("출력 형식:")
    parts.append(_output_template(fmt.sections))
    parts.append("")
    parts.append("다음은 분류 예시입니다.")

    for shot in fmt.few_shots:
        parts.append("")
        parts.append(_few_shot_block(shot, fmt.sections))

    parts.append("")  # 골든 파일 끝 newline과 동일
    return "\n".join(parts)


def build_user_prompt(transcript: str) -> str:
    return (
        "다음 외래 dictation을 SOAP JSON으로 구조화하세요. "
        "원문에 없는 정보는 절대 추가하지 마세요. "
        "명시되지 않은 섹션은 빈 문자열로 두세요.\n\n"
        f"---원문---\n{transcript}\n---끝---"
    )
