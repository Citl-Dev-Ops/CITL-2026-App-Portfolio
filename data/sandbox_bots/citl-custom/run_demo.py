#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
model = (os.environ.get("OLLAMA_MODEL") or "citl-custom").strip()
prompt_file = Path(os.environ.get("PROMPT_FILE") or "demo_prompt.txt")
prompt = os.environ.get("PROMPT")
if not prompt:
    prompt = prompt_file.read_text(encoding="utf-8", errors="ignore").strip()

payload = {"model": model, "prompt": prompt, "stream": False}
req = Request(
    host + "/api/generate",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(req, timeout=300) as r:
    data = json.loads(r.read().decode("utf-8", errors="ignore"))
print((data.get("response") or "").strip())
