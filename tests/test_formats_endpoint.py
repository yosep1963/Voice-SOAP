"""GET /formats — 사용 가능 포맷 목록 + 메타데이터 노출 검증."""
import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import app


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_formats_endpoint_returns_both_formats() -> None:
    with TestClient(app) as client:
        r = client.get("/formats")
    assert r.status_code == 200
    body = r.json()
    assert body["default_id"] == "soap"
    ids = [f["id"] for f in body["formats"]]
    assert "soap" in ids
    assert "initial_visit" in ids


def test_formats_endpoint_includes_section_metadata() -> None:
    with TestClient(app) as client:
        r = client.get("/formats")
    body = r.json()
    soap = next(f for f in body["formats"] if f["id"] == "soap")
    section_keys = [s["key"] for s in soap["sections"]]
    assert section_keys == ["subjective", "objective", "assessment", "plan"]
    # 라벨 존재 확인 (UI 렌더용)
    assert all("label" in s and s["label"] for s in soap["sections"])


def test_formats_endpoint_initial_visit_has_seven_sections() -> None:
    with TestClient(app) as client:
        r = client.get("/formats")
    body = r.json()
    iv = next(f for f in body["formats"] if f["id"] == "initial_visit")
    section_keys = [s["key"] for s in iv["sections"]]
    assert section_keys == ["cc", "pi", "past_hx", "family_hx", "pe", "imp", "plan"]
