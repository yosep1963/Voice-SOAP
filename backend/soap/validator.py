"""환각 검증. 원문에 없는 숫자가 응답에 등장하면 경고."""
import re

from backend.soap.models import ClinicalNote, SoapNote, ValidationReport

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _extract_numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _combined(note: ClinicalNote) -> str:
    return " ".join(note.sections.values())


def validate_clinical(source_text: str, note: ClinicalNote) -> ValidationReport:
    source_numbers = _extract_numbers(source_text)
    note_numbers = _extract_numbers(_combined(note))
    extra = sorted(note_numbers - source_numbers)

    warnings: list[str] = []
    if extra:
        warnings.append(
            f"원문에 없는 숫자 {len(extra)}개가 응답에 등장: {', '.join(extra)} "
            "— 환각 의심, 사용자 확인 필요"
        )
    if not any(note.sections.values()):
        warnings.append("모든 섹션이 비어있음 — LLM 응답 파싱 실패 가능")

    return ValidationReport(
        passed=len(warnings) == 0,
        warnings=warnings,
        extra_numbers=extra,
    )


def validate_soap(source_text: str, note: SoapNote) -> ValidationReport:
    """후방호환. SoapNote 4섹션을 ClinicalNote로 변환 후 검증."""
    clinical = ClinicalNote(
        sections={
            "subjective": note.subjective,
            "objective": note.objective,
            "assessment": note.assessment,
            "plan": note.plan,
        },
        uncertain_segments=note.uncertain_segments,
    )
    return validate_clinical(source_text, clinical)
