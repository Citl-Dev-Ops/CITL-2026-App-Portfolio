#!/usr/bin/env python3
"""flex_builder.py

Quick builder for CITL FLEX Troubleshooter.

This script invokes the existing `factbook-assistant/build_corpus_index.py`
to create a `flex_embeddings.json` corpus from the specified source (PDF).
It also writes a starter `Modelfile` and prints next steps for creating an EXE.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent
FACTBOOK_ASSISTANT = HERE.parent / "factbook-assistant"
BUILD_SCRIPT = FACTBOOK_ASSISTANT / "build_corpus_index.py"

# Default source as requested by the team
DEFAULT_PDF = Path(r"C:\Users\Doc_M\CITL\MAIN - The FLEX Team One Note - FULL.pdf")

def build_index(src: Path | str = DEFAULT_PDF, out: Path | str | None = None) -> Path:
    src = Path(src)
    if out is None:
        out = HERE / "flex_embeddings.json"
    out = Path(out)

    if not BUILD_SCRIPT.exists():
        raise SystemExit(f"Required build script not found: {BUILD_SCRIPT}")

    cmd = [sys.executable, str(BUILD_SCRIPT), "--src", str(src), "--out", str(out)]
    print("[INFO] Running index build:", " ".join(cmd))
    subprocess.check_call(cmd)

    print(f"[OK] Wrote corpus to: {out}")
    return out


def write_modelfile(outdir: Path = HERE) -> Path:
    mpath = outdir / "Modelfile"
    content = (
        "# CITL-COLOR: ops\n"
        "# CITL-BOTNAME: FLEX Troubleshooter\n"
        "# CITL-LANG: en\n"
        "# CITL-DESC: Troubleshooting assistant built from FLEX Team OneNote PDF\n\n"
        "FROM qwen2.5:7b\n\n"
        "SYSTEM \"\"\"\n"
        "You are the CITL FLEX Troubleshooter. Use the provided indexed corpus to answer\n"
        "questions about AV/IT, display profiles, driver triage, and room inspections.\n"
        "Answer ONLY from the provided knowledge base and state when information is not available.\n"
        "Keep answers concise and provide references to source pages when possible.\n"
        "\"\"\"\n\n"
        "USER \"\"\"\n"
        "You are a student-built Troubleshooter. Be accurate and avoid hallucinations.\n"
        "\"\"\"\n"
    )
    mpath.write_text(content, encoding="utf-8")
    print(f"[OK] Wrote Modelfile template: {mpath}")
    return mpath


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Bootstrap CITL FLEX Troubleshooter corpus + Modelfile")
    ap.add_argument("--src", default=str(DEFAULT_PDF), help="Source file or directory to index")
    ap.add_argument("--out", default=str(HERE / "flex_embeddings.json"), help="Output JSON corpus file")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        raise SystemExit(f"Source not found: {src}")

    out = build_index(src=src, out=Path(args.out))
    write_modelfile(HERE)

    print("\nNext steps:")
    print("- Edit 'Modelfile' to pick a different base model or system prompt.")
    print("- Use `query_flex.py` to test queries against the created corpus.")
    print("- To make a standalone EXE, use PyInstaller or your existing build scripts and point the spec to this folder.")


if __name__ == '__main__':
    main()
