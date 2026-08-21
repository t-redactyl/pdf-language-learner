from fastapi.testclient import TestClient

from pdf_language_learner.app import app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_home_serves_reader() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "PDF language reader" in response.text


def test_translate_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post("/api/translate", json={"text": "Bonjour", "target_language": "English"})
    assert response.status_code == 503


def test_translate_rejects_blank_text() -> None:
    response = client.post("/api/translate", json={"text": "   ", "target_language": "English"})
    assert response.status_code == 422
