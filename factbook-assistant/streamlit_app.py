import os
import sys
import subprocess
import streamlit as st

st.set_page_config(page_title="CITL Factbook Assistant", layout="wide")
st.title("CITL Factbook Assistant (Local Ollama + RAG)")

ollama = os.getenv("OLLAMA_HOST") or os.getenv("CITL_OLLAMA_HOST") or "http://127.0.0.1:11434"
model  = os.getenv("FACTBOOK_MODEL") or "mistral:7b-instruct"
embed  = os.getenv("FACTBOOK_EMBED") or "nomic-embed-text"

st.write(f"**Ollama Host:** `{ollama}`")
st.write(f"**LLM Model:** `{model}`   |   **Embed Model:** `{embed}`")

q = st.text_area("Question", height=160, placeholder="Example: Tell me about Japan (government, economy, geography).")
col1, col2 = st.columns([1, 3])
run = col1.button("Run", type="primary")
show = col2.checkbox("Show command used", value=False)

def run_cli(question: str):
    script = os.path.join(os.path.dirname(__file__), "query_factbook.py")
    exe = sys.executable

    # Try common styles (positional first)
    candidates = [
        [exe, script, question],
        [exe, script, "--query", question],
        [exe, script, "--question", question],
        [exe, script, "-q", question],
        [exe, script, "--prompt", question],
    ]

    last = ""
    for cmd in candidates:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
            if show:
                st.code(" ".join(cmd), language="bash")
            if p.returncode == 0:
                return 0, out.strip()
            last = out.strip()
        except subprocess.TimeoutExpired:
            return 124, "ERROR: timed out after 900 seconds"

    return 1, last or "ERROR: query failed (no output)"

if run:
    question = q.strip()
    if not question:
        st.warning("Type a question first.")
    else:
        with st.spinner("Querying Factbook…"):
            rc, out = run_cli(question)
        if rc == 0:
            st.success("Done")
            st.markdown(out if out else "(no output)")
        else:
            st.error("Failed")
            st.text(out)
