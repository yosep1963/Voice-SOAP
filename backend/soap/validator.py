"""환각 검증. 원문에 없는 숫자가 SOAP에 등장하면 경고."""
import re

from backend.soap.models import SoapNote, ValidationReport

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _extract_numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _soap_combined(note: SoapNote) -> str:
    return " ".join([note.subjective, note.objective, note.assessment, note.plan])


def validate_soap(source_text: str, note: SoapNote) -> ValidationReport:
    source_numbers = _extract_numbers(source_text)
    soap_numbers = _extract_numbers(_soap_combined(note))
    extra = sorted(soap_numbers - source_numbers)

    warnings: list[str] = []
    if extra:
        warnings.append(
            f"원문에 없는 숫자 {len(extra)}개가 SOAP에 등장: {', '.join(extra)} "
            "— 환각 의심, 사용자 확인 필요"
        )
    if not note.subjective and not note.objective and not note.assessment and not note.plan:
        warnings.append("모든 SOAP 섹션이 비어있음 — LLM 응답 파싱 실패 가능")

    return ValidationReport(
        passed=len(warnings) == 0,
        warnings=warnings,
        extra_numbers=extra,
    )
