"""SOAP 엔드포인트 테스트. respx로 LM Studio 응답 모킹."""
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
def test_soap_endpoint_returns_structured_note() -> None:
    base = get_settings().llm_base_url
    respx.post(f"{base}/chat/completions").mock(
        return_value=_llm_response({
            "subjective": "60세 남자, B형 간염으로 인한 간경변 추적",
            "objective": "MELD 18, Child-Pugh B 7",
            "assessment": "B형 간염성 간경변, HCC 의심",
            "plan": "복부 CT 시행",
            "uncertain_segments": [],
        })
    )

    with TestClient(app) as client:
        r = client.post("/soap", json={"text": "60세 남자, MELD 18점, Child-Pugh B 7점."})

    assert r.status_code == 200
    body = r.json()
    assert body["note"]["subjective"].startswith("60세")
    assert body["validation"]["passed"] is True
    assert body["source_text"].startswith("60세")


@respx.mock
def test_soap_endpoint_strips_json_code_fence() -> None:
    """LLM이 ```json ... ``` 으로 감싸도 파싱 성공해야 함."""
    base = get_settings().llm_base_url
    fenced = "```json\n" + json.dumps({"subjective": "테스트", "objective": "", "assessment": "", "plan": "", "uncertain_segments": []}) + "\n```"
    respx.post(f"{base}/chat/completions").mock(
        return_value=httpx.Response(
            status_code=200,
            json={"choices": [{"message": {"content": fenced}}]},
        )
    )

    with TestClient(app) as client:
        r = client.post("/soap", json={"text": "테스트"})
    assert r.status_code == 200
    assert r.json()["note"]["subjective"] == "테스트"


@respx.mock
def test_soap_endpoint_502_on_llm_failure() -> None:
    base = get_settings().llm_base_url
    respx.post(f"{base}/chat/completions").mock(
        return_value=httpx.Response(status_code=500, text="server error")
    )

    with TestClient(app) as client:
        r = client.post("/soap", json={"text": "테스트"})
    assert r.status_code == 502


@respx.mock
def test_soap_endpoint_502_on_invalid_json() -> None:
    base = get_settings().llm_base_url
    respx.post(f"{base}/chat/completions").mock(
        return_value=httpx.Response(
            status_code=200,
            json={"choices": [{"message": {"content": "이건 JSON이 아닙니다"}}]},
        )
    )

    with TestClient(app) as client:
        r = client.post("/soap", json={"text": "테스트"})
    assert r.status_code == 502


def test_soap_endpoint_rejects_empty_text() -> None:
    with TestClient(app) as client:
        r = client.post("/soap", json={"text": ""})
    assert r.status_code == 422  # pydantic min_length validation
