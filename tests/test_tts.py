import hashlib

import pytest

from api import tts


@pytest.fixture
def audio_dir(tmp_path, monkeypatch):
    """Point AUDIO_DIR at a throwaway tmp dir; skip real dotenv."""
    d = tmp_path / "audio"
    monkeypatch.setattr(tts, "AUDIO_DIR", d)
    monkeypatch.setattr(tts, "_dotenv_loaded", True)
    return d


def _expected(text, lang, account_id, attempt):
    digest = hashlib.sha1((text + lang).encode("utf-8")).hexdigest()[:8]
    return f"{account_id}-a{attempt}-{digest}.mp3"


def _boom(*args, **kwargs):
    raise AssertionError("provider seam must not be called")


# ---------------------------------------------------------------- routing

def test_sarvam_routing_indic_lang(audio_dir, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "sv-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls = {}

    def fake_sarvam(text, lang):
        calls["sarvam"] = (text, lang)
        return b"MP3"

    monkeypatch.setattr(tts, "_sarvam_tts", fake_sarvam)
    monkeypatch.setattr(tts, "_openai_tts", _boom)

    fname = tts.synthesize("నమస్కారం", "te", "ACC-1", 2)
    assert calls["sarvam"] == ("నమస్కారం", "te")
    assert fname == _expected("నమస్కారం", "te", "ACC-1", 2)
    assert fname == "ACC-1-a2-" + fname.split("-a2-")[1]
    written = audio_dir / fname
    assert written.exists() and written.read_bytes() == b"MP3"


def test_openai_routing_no_sarvam_key(audio_dir, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls = {}

    def fake_openai(text):
        calls["openai"] = text
        return b"MP3"

    monkeypatch.setattr(tts, "_sarvam_tts", _boom)
    monkeypatch.setattr(tts, "_openai_tts", fake_openai)

    fname = tts.synthesize("hello", "en", "ACC-2", 1)
    assert calls["openai"] == "hello"
    assert fname == _expected("hello", "en", "ACC-2", 1)
    assert (audio_dir / fname).read_bytes() == b"MP3"


def test_sarvam_key_but_non_indic_lang_uses_openai(audio_dir, monkeypatch):
    # Sarvam key present but lang not in SARVAM_LANGS -> OpenAI path.
    monkeypatch.setenv("SARVAM_API_KEY", "sv-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(tts, "_sarvam_tts", _boom)
    monkeypatch.setattr(tts, "_openai_tts", lambda text: b"MP3")

    fname = tts.synthesize("hello", "en", "ACC-3", 1)
    assert fname == _expected("hello", "en", "ACC-3", 1)


# ---------------------------------------------------------------- cache

def test_cache_hit_skips_providers(audio_dir, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "sv-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(tts, "_sarvam_tts", _boom)
    monkeypatch.setattr(tts, "_openai_tts", _boom)

    fname = _expected("cached", "te", "ACC-4", 1)
    audio_dir.mkdir(parents=True)
    (audio_dir / fname).write_bytes(b"OLD")

    got = tts.synthesize("cached", "te", "ACC-4", 1)
    assert got == fname
    # untouched: neither seam ran, bytes unchanged
    assert (audio_dir / fname).read_bytes() == b"OLD"


# ---------------------------------------------------------------- failure

def test_both_providers_fail_returns_none(audio_dir, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "sv-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(tts, "_sarvam_tts", lambda text, lang: None)
    monkeypatch.setattr(tts, "_openai_tts", lambda text: None)

    got = tts.synthesize("nope", "te", "ACC-5", 1)
    assert got is None
    # no orphan file left behind
    assert not audio_dir.exists() or list(audio_dir.iterdir()) == []


def test_no_keys_available_false_and_no_seam_calls(audio_dir, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(tts, "_sarvam_tts", _boom)
    monkeypatch.setattr(tts, "_openai_tts", _boom)

    assert tts.available() is False
    assert tts.synthesize("hi", "te", "ACC-6", 1) is None
    assert not audio_dir.exists() or list(audio_dir.iterdir()) == []


# ---------------------------------------------------------------- determinism

def test_filename_deterministic(audio_dir, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.setattr(tts, "_openai_tts", lambda text: b"MP3")

    a = tts.synthesize("same text", "hi", "ACC-7", 3)
    # second call is a cache hit but must yield the identical filename
    b = tts.synthesize("same text", "hi", "ACC-7", 3)
    assert a == b == _expected("same text", "hi", "ACC-7", 3)
    # different attempt -> different filename
    c = tts.synthesize("same text", "hi", "ACC-7", 4)
    assert c != a
