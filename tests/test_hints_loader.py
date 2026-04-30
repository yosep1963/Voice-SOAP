from pathlib import Path

import pytest

from backend.stt.hints_loader import load_hints


def test_load_hints_strips_comments_and_blank_lines(tmp_path: Path) -> None:
    f = tmp_path / "hints.txt"
    f.write_text(
        "# 주석\n"
        "\n"
        "간경변, 정맥류.\n"
        "  # 앞에 공백 있는 주석도 무시\n"
        "MELD, Child-Pugh.\n",
        encoding="utf-8",
    )
    out = load_hints(f)
    assert out == "간경변, 정맥류. MELD, Child-Pugh."


def test_load_hints_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_hints(tmp_path / "does_not_exist.txt")


def test_load_hints_real_medical_hints_file() -> None:
    """레포지토리의 실제 medical_hints.txt가 비어있지 않게 로딩되는지 검증."""
    repo_root = Path(__file__).resolve().parent.parent
    hints = load_hints(repo_root / "hints" / "medical_hints.txt")
    assert "간경변" in hints
    assert "MELD" in hints
    assert "#" not in hints  # 주석은 제거되어야 함
    assert len(hints) > 200
