"""의학용어 힌트 사전 로더. Whisper의 initial_prompt로 주입된다."""
from pathlib import Path


def load_hints(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Hints file not found: {path}")

    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return " ".join(lines)
