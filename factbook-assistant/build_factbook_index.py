#!/usr/bin/env python3
import sys, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYEXE = sys.executable

src = str(ROOT / "library")
out = str(ROOT / "factbook_embeddings.json")
chunk = None

argv = sys.argv[1:]
i=0
while i < len(argv):
    a = argv[i]
    if a == "--src" and i+1 < len(argv): src = argv[i+1]; i += 2; continue
    if a == "--out" and i+1 < len(argv): out = argv[i+1]; i += 2; continue
    if a == "--chunk" and i+1 < len(argv): chunk = argv[i+1]; i += 2; continue
    i += 1

cmd = [PYEXE, str(ROOT / "build_corpus_index.py"), "--src", src, "--out", out]
if chunk:
    cmd += ["--chunk", str(chunk)]

print("== Rebuild Factbook Index (wrapper) ==")
print("$ " + " ".join(cmd))
sys.exit(subprocess.call(cmd, cwd=str(ROOT)))
