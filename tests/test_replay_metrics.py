from backend.feedback.metrics import char_edit_distance, note_distance
from backend.soap.models import ClinicalNote


def test_char_distance_identical_zero() -> None:
    assert char_edit_distance("abc", "abc") == 0
    assert char_edit_distance("", "") == 0


def test_char_distance_pure_insert() -> None:
    assert char_edit_distance("abc", "abcde") == 2


def test_char_distance_pure_delete() -> None:
    assert char_edit_distance("abcde", "abc") == 2


def test_char_distance_replace() -> None:
    # "abc" → "axc": 1 char replaced
    assert char_edit_distance("abc", "axc") == 1


def test_char_distance_korean() -> None:
    # 한글 한 글자 교체 = 1
    assert char_edit_distance("간경변", "간세포암") > 0


def test_note_distance_identical() -> None:
    a = ClinicalNote(sections={"s": "hello", "p": "world"})
    b = ClinicalNote(sections={"s": "hello", "p": "world"})
    d = note_distance(a, b)
    assert d.total_distance == 0
    assert d.n_sections_changed == 0
    assert d.normalized == 0.0


def test_note_distance_one_section_changed() -> None:
    a = ClinicalNote(sections={"s": "hello", "p": "world"})
    b = ClinicalNote(sections={"s": "hello", "p": "WORLD"})
    d = note_distance(a, b)
    assert d.total_distance == 5
    assert d.n_sections_changed == 1


def test_note_distance_handles_disjoint_keys() -> None:
    # b에 새 섹션 추가, a에는 없음 → 합집합 기준
    a = ClinicalNote(sections={"s": "ab"})
    b = ClinicalNote(sections={"s": "ab", "extra": "xy"})
    d = note_distance(a, b)
    keys = {sd.section for sd in d.sections}
    assert keys == {"s", "extra"}
    assert d.total_distance == 2  # "" → "xy"


def test_note_distance_normalized_in_range() -> None:
    a = ClinicalNote(sections={"s": "abcdef"})
    b = ClinicalNote(sections={"s": "xyzwvu"})
    d = note_distance(a, b)
    assert 0.0 <= d.normalized <= 1.0
