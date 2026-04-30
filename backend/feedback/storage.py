"""JSONL 추가 쓰기. 한 줄 = 한 EditFeedback 객체."""
from pathlib import Path

from backend.feedback.models import EditFeedback


def append_feedback(path: Path, feedback: EditFeedback) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(feedback.model_dump_json() + "\n")
