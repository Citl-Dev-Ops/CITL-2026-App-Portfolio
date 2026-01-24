import os
import sys
from citl_factbook.retrieve import retrieve
from citl_factbook.ollama_client import ollama_generate
SYSTEM = """You are CITL Factbook Assistant.
Rules:
- Use ONLY the FACTBOOK EXCERPTS provided below.
- If the answer is not in the excerpts, output exactly: NOT FOUND IN FACTBOOK.
- Cite each claim with [doc_id].
"""
def main():
    if len(sys.argv) < 2:
        print('Usage: citl-factbook "your question"')
        raise SystemExit(2)
    question = " ".join(sys.argv[1:]).strip()
    # enforce backend variable (optional sanity check)
    backend = os.environ.get("CITL_LLM_BACKEND", "ollama").lower()
    if backend != "ollama":
        print("ERROR: CITL_LLM_BACKEND must be 'ollama'.")
        raise SystemExit(2)
    excerpts = retrieve(question, k=int(os.environ.get("CITL_TOPK", "6")))
    if not excerpts:
        # hard fail-safe so nobody thinks it's making stuff up
        print("NOT FOUND IN FACTBOOK.")
        raise SystemExit(0)
    context = "\n\n".join(
        f"[{d.get('id','?')}] {d.get('title','')}\n{d.get('text','')}"
        for d in excerpts
    )
    prompt = f"""{SYSTEM}
FACTBOOK EXCERPTS:
{context}
QUESTION:
{question}
ANSWER (with citations):
"""
    print(ollama_generate(prompt))
if __name__ == "__main__":
    main()
