"""두 ClinicalNote 사이의 거리 측정.

사용처:
- POST /feedback의 사후 분석 (사용자가 LLM 출력을 얼마나 고쳤나)
- tools/eval/replay_edits.py — 새 LLM 결과가 사용자 gold(edited_note)에 얼마나 가까운지

거리 정의: difflib SequenceMatcher 기반의 문자 단위 편집 연산 수
(insert + delete + replace). 진짜 Levenshtein은 아니지만, stdlib만 쓰면서
"고치는 데 몇 글자 만져야 했나"의 직관적 근사. 결정적이라 회귀 비교에 적합.
"""
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from backend.soap.models import ClinicalNote


def char_edit_distance(a: str, b: str) -> int:
    """두 문자열의 편집 연산 수. 동일하면 0."""
    if a == b:
        return 0
    sm = SequenceMatcher(None, a, b, autojunk=False)
    distance = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            distance += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            distance += i2 - i1
        elif tag == "insert":
            distance += j2 - j1
    return distance


class SectionDistance(BaseModel):
    section: str
    distance: int = Field(ge=0)
    len_a: int = Field(ge=0)
    len_b: int = Field(ge=0)
    changed: bool


class NoteDistance(BaseModel):
    """한 쌍의 ClinicalNote 거리. 키 합집합 기준."""

    sections: list[SectionDistance]
    total_distance: int = Field(ge=0)
    total_len_a: int = Field(ge=0)
    total_len_b: int = Field(ge=0)
    n_sections_changed: int = Field(ge=0)

    @property
    def normalized(self) -> float:
        """0(동일) ~ 1(완전 다름). 두 노트 길이의 max로 정규화."""
        denom = max(self.total_len_a, self.total_len_b)
        return self.total_distance / denom if denom else 0.0


def note_distance(a: ClinicalNote, b: ClinicalNote) -> NoteDistance:
    """두 ClinicalNote의 섹션별 거리. 키 집합이 달라도 합집합 기준으로 처리."""
    keys = sorted(set(a.sections) | set(b.sections))
    sections: list[SectionDistance] = []
    total_d = 0
    total_la = 0
    total_lb = 0
    n_changed = 0
    for k in keys:
        sa = a.sections.get(k, "")
        sb = b.sections.get(k, "")
        d = char_edit_distance(sa, sb)
        changed = sa != sb
        sections.append(
            SectionDistance(section=k, distance=d, len_a=len(sa), len_b=len(sb), changed=changed)
        )
        total_d += d
        total_la += len(sa)
        total_lb += len(sb)
        if changed:
            n_changed += 1
    return NoteDistance(
        sections=sections,
        total_distance=total_d,
        total_len_a=total_la,
        total_len_b=total_lb,
        n_sections_changed=n_changed,
    )
