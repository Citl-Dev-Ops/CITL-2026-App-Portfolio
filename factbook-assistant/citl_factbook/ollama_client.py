import os
import requests
def ollama_generate(prompt: str) -> str:
    model = os.environ.get("CITL_LLM_MODEL", "llama3.1:8b")
    host = os.environ.get("CITL_OLLAMA_HOST", "http://localhost:11434")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": float(os.environ.get("CITL_TEMP", "0.2")),
            "num_ctx": int(os.environ.get("CITL_NUM_CTX", "4096")),
        },
    }
    r = requests.post(f"{host}/api/generate", json=payload, timeout=600)
    r.raise_for_status()
    return r.json().get("response", "").strip()
