"""
citl_translation.py - Offline translation via argostranslate.

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

def _lang_code(lang_obj) -> str:
    """Return language code from argostranslate language object variants."""
    return getattr(lang_obj, "code", str(lang_obj))


def _find_lang(installed, code: str):
    """Find a language object by code across argostranslate versions."""
    return next((l for l in installed if _lang_code(l) == code), None)

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
    src_lang = _find_lang(installed, from_code)
    if src_lang is None:
        raise RuntimeError(
            f"Source language '{from_code}' not installed. "
            f"Use install_pair('{from_code}', '{to_code}') first."
        )

    dst_lang = _find_lang(installed, to_code)
    translation = None
    if dst_lang is not None:
        try:
            translation = src_lang.get_translation(dst_lang)
        except Exception:
            translation = None
    if translation is None:
        try:
            translation = src_lang.get_translation(to_code)
        except Exception:
            translation = None
    if translation is None:
        raise RuntimeError(
            f"Translation pair {from_code} -> {to_code} not installed. "
            f"Use install_pair('{from_code}', '{to_code}') first."
        )

    return translation.translate(text)


def install_pair(
    from_code: str,
    to_code: str,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Download and install the language pack for from_code -> to_code.
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
                f"No package found for {from_code} -> {to_code}. "
                "Check argostranslate package index."
            )

        _emit(f"Downloading {from_code} -> {to_code} (~{match.package_version or '?'}) ...")
        dl_path = match.download()
        _emit("Installing package...")
        _pkg.install_from_path(dl_path)
        _emit(f"Installed: {from_code} -> {to_code}")
        return f"OK: {LANGUAGES.get(from_code, from_code)} -> {LANGUAGES.get(to_code, to_code)}"


def is_pair_installed(from_code: str, to_code: str) -> bool:
    """Return True if the language pair is available for offline translation."""
    try:
        from argostranslate import translate as _at
        installed = _at.get_installed_languages()
        src = _find_lang(installed, from_code)
        if src is None:
            return False
        dst = _find_lang(installed, to_code)
        try:
            if dst is not None and src.get_translation(dst) is not None:
                return True
        except Exception:
            pass
        try:
            return src.get_translation(to_code) is not None
        except Exception:
            return False
    except Exception:
        return False


def list_installed_pairs() -> list:
    """Return list of (from_code, to_code) tuples for installed pairs."""
    try:
        from argostranslate import translate as _at
        pairs = []
        for lang in _at.get_installed_languages():
            from_code = _lang_code(lang)
            translations = getattr(lang, "translations_from", None) or []
            for t in translations:
                to_lang = getattr(t, "to_lang", None)
                to_code = _lang_code(to_lang) if to_lang is not None else ""
                if from_code and to_code:
                    pairs.append((from_code, to_code))
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
