"""/note 엔드포인트 테스트 (포맷 일반화). respx로 LM Studio 모킹."""
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import app


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _llm_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
    )


@respx.mock
def test_note_endpoint_default_format_is_soap() -> None:
    """format_id 미지정 시 settings.default_format_id ('soap') 사용."""
    base = get_settings().llm_base_url
    respx.post(f"{base}/chat/completions").mock(
        return_value=_llm_response({
            "subjective": "60세 남자",
            "objective": "MELD 18",
            "assessment": "",
            "plan": "푸로세미드 처방",
            "uncertain_segments": [],
        })
    )

    with TestClient(app) as client:
        r = client.post("/note", json={"text": "60세 남자, MELD 18점."})

    assert r.status_code == 200
    body = r.json()
    assert body["format_id"] == "soap"
    assert body["note"]["sections"]["subjective"] == "60세 남자"
    assert body["note"]["sections"]["plan"] == "푸로세미드 처방"
    assert body["validation"]["passed"] is True


@respx.mock
def test_note_endpoint_initial_visit_format() -> None:
    base = get_settings().llm_base_url
    respx.post(f"{base}/chat/completions").mock(
        return_value=_llm_response({
            "cc": "황달",
            "pi": "3개월 전부터 식욕부진",
            "past_hx": "고혈압",
            "family_hx": "",
            "pe": "공막 황달",
            "imp": "알코올성 간경변",
            "plan": "복부 CT",
            "uncertain_segments": [],
        })
    )

    with TestClient(app) as client:
        r = client.post(
            "/note",
            json={"text": "55세 남자 황달...", "format_id": "initial_visit"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["format_id"] == "initial_visit"
    sections = body["note"]["sections"]
    assert set(sections.keys()) == {"cc", "pi", "past_hx", "family_hx", "pe", "imp", "plan"}
    assert sections["cc"] == "황달"
    assert sections["family_hx"] == ""  # 묻지 않은 가족력 default empty
    assert sections["imp"] == "알코올성 간경변"


@respx.mock
def test_note_endpoint_unknown_format_returns_404() -> None:
    with TestClient(app) as client:
        r = client.post("/note", json={"text": "테스트", "format_id": "nonexistent"})
    assert r.status_code == 404
    assert "nonexistent" in r.json()["detail"]


@respx.mock
def test_note_endpoint_502_on_llm_failure() -> None:
    base = get_settings().llm_base_url
    respx.post(f"{base}/chat/completions").mock(
        return_value=httpx.Response(status_code=500, text="server error")
    )

    with TestClient(app) as client:
        r = client.post("/note", json={"text": "테스트", "format_id": "soap"})
    assert r.status_code == 502


@respx.mock
def test_note_endpoint_initial_visit_keys_filtered_by_format() -> None:
    """LLM이 알 수 없는 키를 응답해도 format yaml 정의된 섹션만 sections dict에 포함."""
    base = get_settings().llm_base_url
    respx.post(f"{base}/chat/completions").mock(
        return_value=_llm_response({
            "cc": "테스트",
            "pi": "", "past_hx": "", "family_hx": "", "pe": "", "imp": "", "plan": "",
            "extra_unknown_key": "ignored",
            "uncertain_segments": [],
        })
    )

    with TestClient(app) as client:
        r = client.post("/note", json={"text": "테스트", "format_id": "initial_visit"})
    assert r.status_code == 200
    sections = r.json()["note"]["sections"]
    assert "extra_unknown_key" not in sections
    assert sections["cc"] == "테스트"


def test_note_endpoint_rejects_empty_text() -> None:
    with TestClient(app) as client:
        r = client.post("/note", json={"text": "", "format_id": "soap"})
    assert r.status_code == 422
