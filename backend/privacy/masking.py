"""환자 식별자 마스킹. plan.md §7 PATTERNS.

저장(feedback log)/공유 시점에 적용. 의학 검사 수치(AST 85 등)는 영향받지 않도록
주민번호(13자리 + 하이픈)와 8자리 이상 단독 숫자(등록번호)만 매칭.
"""
import re

# (regex, replacement) 페어. 순서 중요 — 주민번호 먼저(더 specific) 그 후 등록번호.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{6}-\d{7}\b"), "[주민번호]"),
    # 8자리 이상 연속 숫자: 환자 등록번호. 의학 검사 수치는 보통 1-3자리이므로 충돌 거의 없음.
    (re.compile(r"\b\d{8,}\b"), "[등록번호]"),
]


def mask_identifiers(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
