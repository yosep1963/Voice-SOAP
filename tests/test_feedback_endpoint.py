"""POST /feedback 엔드포인트 + JSONL 저장 + 마스킹 검증."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import app


@pytest.fixture
def feedback_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log_path = tmp_path / "edits.jsonl"
    monkeypatch.setenv("VOICE_SOAP_FEEDBACK_LOG_PATH", str(log_path))
    get_settings.cache_clear()
    yield log_path
    get_settings.cache_clear()


def _make_payload(**overrides) -> dict:
    base = {
        "timestamp": "2026-04-29T12:00:00Z",
        "audio_duration_seconds": 60.0,
        "raw_text": "60세 남자 환자",
        "corrected_text": "60세 남자 환자",
        "format_id": "soap",
        "original_note": {
            "sections": {
                "subjective": "60세 남자 환자",
                "objective": "MELD 18",
                "assessment": "",
                "plan": "푸로세미드 처방",
            },
            "uncertain_segments": [],
        },
        "edited_note": {
            "sections": {
                "subjective": "60세 남자 환자",
                "objective": "MELD 18",
                "assessment": "B형 간염성 간경변",  # 사용자가 직접 채움
                "plan": "푸로세미드 40mg 처방",  # 사용자가 용량 추가
            },
            "uncertain_segments": [],
        },
        "diffs": [
            {"section": "subjective", "original": "60세 남자 환자", "edited": "60세 남자 환자", "changed": False},
            {"section": "objective", "original": "MELD 18", "edited": "MELD 18", "changed": False},
            {"section": "assessment", "original": "", "edited": "B형 간염성 간경변", "changed": True},
            {"section": "plan", "original": "푸로세미드 처방", "edited": "푸로세미드 40mg 처방", "changed": True},
        ],
        "applied_replacements": [],
        "uncertain_segments": [],
    }
    base.update(overrides)
    return base


def test_feedback_writes_jsonl_with_edited_count(feedback_log: Path) -> None:
    with TestClient(app) as client:
        r = client.post("/feedback", json=_make_payload())
    assert r.status_code == 200
    assert r.json()["edited_sections"] == 2

    line = feedback_log.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["edited_note"]["sections"]["assessment"] == "B형 간염성 간경변"
    assert record["timestamp"] == "2026-04-29T12:00:00Z"
    assert record["format_id"] == "soap"


def test_feedback_appends_multiple_lines(feedback_log: Path) -> None:
    with TestClient(app) as client:
        client.post("/feedback", json=_make_payload(timestamp="2026-04-29T12:00:00Z"))
        client.post("/feedback", json=_make_payload(timestamp="2026-04-29T12:01:00Z"))

    lines = [l for l in feedback_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2


def test_feedback_masks_identifiers(feedback_log: Path) -> None:
    payload = _make_payload(
        raw_text="환자 800101-1234567, 등록번호 12345678 외래 진료",
    )
    with TestClient(app) as client:
        r = client.post("/feedback", json=payload)
    assert r.status_code == 200

    record = json.loads(feedback_log.read_text(encoding="utf-8").strip())
    assert "[주민번호]" in record["raw_text"]
    assert "[등록번호]" in record["raw_text"]
    assert "800101-1234567" not in record["raw_text"]
    assert "12345678" not in record["raw_text"]
