from fastapi.testclient import TestClient

from backend.main import app


def test_healthz_returns_ok_with_model() -> None:
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "whisper" in body["whisper_model"].lower()
    assert body["llm_model"]
    assert body["llm_base_url"].startswith("http")


def test_transcribe_rejects_non_wav_content_type() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/transcribe",
            files={"audio": ("foo.txt", b"not a wav", "text/plain")},
        )
    assert r.status_code == 415


def test_transcribe_rejects_empty_upload() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/transcribe",
            files={"audio": ("empty.wav", b"", "audio/wav")},
        )
    assert r.status_code == 400
