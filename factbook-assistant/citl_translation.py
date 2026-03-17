"""
citl_translation.py — Offline translation via argostranslate.

Language packs are downloaded once per machine (~100 MB each pair).
Translation itself is fully offline after install.

Usage:
    from citl_translation import translate, install_pair, is_pair_installed

    install_pair("en", "es")           # downloads ~100 MB once
    text = translate("Hello", "en", "es")  # -> "Hola"
"""

import threading
from typing import Optional, Callable

# ---------------------------------------------------------------------------
# Language catalog
# ---------------------------------------------------------------------------

LANGUAGES: dict = {
    "af": "Afrikaans",
    "ar": "Arabic",
    "az": "Azerbaijani",
    "zh": "Chinese",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "en": "English",
    "fi": "Finnish",
    "fr": "French",
    "de": "German",
    "el": "Greek",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "fa": "Persian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sk": "Slovak",
    "es": "Spanish",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
}

DEFAULT_LANGS = ("en", "es", "ar")

_install_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def translate(text: str, from_code: str, to_code: str) -> str:
    """
    Translate text offline using argostranslate.
    Raises RuntimeError if the language pair is not installed.
    """
    try:
        from argostranslate import translate as _at
    except ImportError:
        raise RuntimeError(
            "argostranslate is not installed. Run: pip install argostranslate"
        )

    installed = _at.get_installed_languages()
    src_lang = next((l for l in installed if l.code == from_code), None)
    if src_lang is None:
        raise RuntimeError(
            f"Source language '{from_code}' not installed. "
            f"Use install_pair('{from_code}', '{to_code}') first."
        )

    translation = src_lang.get_translation(to_code)
    if translation is None:
        raise RuntimeError(
            f"Translation pair {from_code} → {to_code} not installed. "
            f"Use install_pair('{from_code}', '{to_code}') first."
        )

    return translation.translate(text)


def install_pair(
    from_code: str,
    to_code: str,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Download and install the language pack for from_code → to_code.
    Thread-safe. Returns a status string.
    progress_cb(msg) is called with progress updates if provided.
    """
    def _emit(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    with _install_lock:
        try:
            from argostranslate import package as _pkg, translate as _at
        except ImportError:
            return "ERROR: argostranslate is not installed."

        _emit("Updating package index...")
        try:
            _pkg.update_package_index()
        except Exception as e:
            _emit(f"WARNING: Could not update package index: {e}")

        available = _pkg.get_available_packages()
        match = next(
            (p for p in available
             if p.from_code == from_code and p.to_code == to_code),
            None,
        )

        if match is None:
            return (
                f"No package found for {from_code} → {to_code}. "
                "Check argostranslate package index."
            )

        _emit(f"Downloading {from_code} → {to_code} (~{match.package_version or '?'}) ...")
        dl_path = match.download()
        _emit("Installing package...")
        _pkg.install_from_path(dl_path)
        _emit(f"Installed: {from_code} → {to_code}")
        return f"OK: {LANGUAGES.get(from_code, from_code)} → {LANGUAGES.get(to_code, to_code)}"


def is_pair_installed(from_code: str, to_code: str) -> bool:
    """Return True if the language pair is available for offline translation."""
    try:
        from argostranslate import translate as _at
        installed = _at.get_installed_languages()
        src = next((l for l in installed if l.code == from_code), None)
        if src is None:
            return False
        return src.get_translation(to_code) is not None
    except Exception:
        return False


def list_installed_pairs() -> list:
    """Return list of (from_code, to_code) tuples for installed pairs."""
    try:
        from argostranslate import translate as _at
        pairs = []
        for lang in _at.get_installed_languages():
            for t in lang.translations_from:
                pairs.append((lang.code, t.to_lang.code))
        return pairs
    except Exception:
        return []


def build_study_pairs(source: str, translated: str) -> list:
    """
    Align source and translated text into sentence pairs for vocabulary study.
    Returns list of (source_sentence, translated_sentence) tuples.
    Simple sentence-split approach.
    """
    import re
    _split = re.compile(r'(?<=[.!?])\s+')
    src_sents = _split.split(source.strip())
    tr_sents  = _split.split(translated.strip())
    count = min(len(src_sents), len(tr_sents))
    return list(zip(src_sents[:count], tr_sents[:count]))
