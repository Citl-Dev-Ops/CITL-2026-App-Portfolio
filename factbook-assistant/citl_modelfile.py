"""
citl_modelfile.py — Parse CITL metadata from Ollama Modelfiles.

CITL metadata is stored as comment lines (ignored by Ollama):
    # CITL-COLOR:   ops
    # CITL-BOTNAME: FLEX Coach
    # CITL-LANG:    en
    # CITL-DESC:    Brief description of this bot

Supported keys (case-insensitive):
    COLOR    — palette name key from citl_theme.PALETTE_NAMES (default: ops)
    BOTNAME  — display name shown in the GUI toolbar
    LANG     — ISO 639-1 default source language for transcription
    DESC     — one-line description (informational)

Usage:
    from citl_modelfile import load_modelfile, parse_meta

    content, meta = load_modelfile("/path/to/Modelfile")
    # meta = {"color": "amber", "botname": "FLEX Coach", "lang": "en", "desc": ""}
"""

import re
from pathlib import Path
from typing import Optional

_META_RE = re.compile(r'^\s*#\s*CITL-([A-Z_]+)\s*:\s*(.+)', re.IGNORECASE)

DEFAULT_META: dict = {
    "color":   "ops",
    "botname": "",
    "lang":    "en",
    "desc":    "",
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_modelfile(path) -> tuple:
    """Read a Modelfile from disk. Returns (content: str, meta: dict)."""
    p = Path(path)
    content = p.read_text(encoding="utf-8", errors="replace")
    return content, parse_meta(content)


def parse_meta(content: str) -> dict:
    """Extract CITL-* metadata from Modelfile text. Returns dict with defaults."""
    meta = dict(DEFAULT_META)
    for line in content.splitlines():
        m = _META_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip().lower()
        val = m.group(2).strip()
        if key in meta:
            meta[key] = val
    return meta


def get_system_prompt(content: str) -> Optional[str]:
    """Extract the SYSTEM block text from a Modelfile, or None."""
    m = re.search(r'^SYSTEM\s+"""(.*?)"""', content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'^SYSTEM\s+"(.*?)"', content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def get_model_base(content: str) -> Optional[str]:
    """Extract the FROM line (base model name) from a Modelfile, or None."""
    m = re.search(r'^FROM\s+(\S+)', content, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None
