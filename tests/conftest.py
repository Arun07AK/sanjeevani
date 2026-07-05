import pytest


@pytest.fixture(autouse=True)
def _no_real_providers(monkeypatch):
    """Keep the suite hermetic: blank provider keys so llm/tts fall back.

    Empty-string (not delenv) because load_dotenv(override=False) would
    re-inject a deleted var from .env; an existing empty value stays empty.
    Tests that exercise provider routing set their own values explicitly.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("SARVAM_API_KEY", "")
