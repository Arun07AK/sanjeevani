"""Voice layer for the Sanjeevani revival loop.

synthesize() turns an outreach message into an mp3 on disk and returns its
filename (served later via /audio/{file}). Two providers behind THE two seams
`_sarvam_tts` / `_openai_tts`: Sarvam Bulbul for Indic scripts (authentic native
voice), OpenAI TTS otherwise. Every failure is silent — the caller falls back to
text-only, so synthesize() returns None rather than raising.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

# data/audio at the repo root (parent of api/).
AUDIO_DIR = Path(__file__).resolve().parent.parent / "data" / "audio"

SARVAM_LANGS = {"hi", "te", "ta", "bn", "mr", "kn", "ml", "gu", "pa", "od"}

_dotenv_loaded = False
_client = None


def _load_env() -> None:
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv()
        _dotenv_loaded = True


def available() -> bool:
    """True if any TTS provider key is present."""
    _load_env()
    return bool(os.environ.get("SARVAM_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(timeout=30)
    return _client


def _sarvam_tts(text: str, lang: str) -> bytes | None:
    """Sarvam Bulbul TTS -> mp3 bytes, or None. Seam: patched in tests."""
    try:
        import httpx

        resp = httpx.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"API-Subscription-Key": os.environ["SARVAM_API_KEY"]},
            json={
                "text": text,
                "target_language_code": f"{lang}-IN",
                "model": "bulbul:v2",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return base64.b64decode(resp.json()["audios"][0])
    except Exception:
        return None


def _openai_tts(text: str) -> bytes | None:
    """OpenAI TTS -> mp3 bytes, or None. Seam: patched in tests."""

    def _call(model: str) -> bytes:
        resp = _get_client().audio.speech.create(
            model=model, voice="alloy", input=text
        )
        # SDK versions differ: newer exposes .content, streaming exposes .read().
        if hasattr(resp, "content"):
            return resp.content
        return resp.read()

    try:
        return _call("gpt-4o-mini-tts")
    except Exception:
        pass
    try:
        return _call("tts-1")
    except Exception:
        return None


def synthesize(text: str, lang: str, account_id: str, attempt: int) -> str | None:
    """Synthesize `text` to an mp3 and return its filename (relative to AUDIO_DIR).

    Returns None on any failure so the caller can degrade to text-only. Routing,
    caching and the file write live here; provider I/O lives in the two seams.
    """
    _load_env()
    digest = hashlib.sha1((text + lang).encode("utf-8")).hexdigest()[:8]
    fname = f"{account_id}-a{attempt}-{digest}.mp3"
    dest = AUDIO_DIR / fname

    # Cache: an existing file needs no provider call.
    if dest.exists():
        return fname

    sarvam_key = os.environ.get("SARVAM_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if sarvam_key and lang in SARVAM_LANGS:
        audio = _sarvam_tts(text, lang)
    elif openai_key:
        audio = _openai_tts(text)
    else:
        return None

    if not audio:
        return None

    try:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(audio)
    except Exception:
        return None
    return fname
