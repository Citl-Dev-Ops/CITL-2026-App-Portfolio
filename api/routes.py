from flask import Flask, request, jsonify
from dotenv import load_dotenv

# IMPORTANT:
# This file must be run as a module:  python -m api.routes
# so the "api." package is resolvable.

from api.term_code_utils import get_term_code_from_text
from api.fetch_sbctc import fetch_schedule_sbctc

load_dotenv()

app = Flask(__name__)

@app.get("/")
def root():
    return jsonify({
        "service": "rtc-advising-backend",
        "ok": True,
        "routes": ["/health", "/api/term/convert", "/api/schedule/sbctc"]
    })

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.post("/api/term/convert")
def convert_term():
    data = request.get_json(silent=True) or {}
    term_text = (data.get("term_text") or "").strip()
    term_code = get_term_code_from_text(term_text)
    return jsonify({"term_text": term_text, "term_code": term_code})

@app.post("/api/schedule/sbctc")
def schedule_sbctc():
    """
    Accepts: { "term_text": "current|fall|winter|spring|summer|SPRING 2026", "subject": "ACCT", "campus": "380" }
    Returns: { term_text, term_code, count, data, warnings? }
    NEVER hard-crash -> if SBCTC fails, return 502 with details.
    """
    data = request.get_json(silent=True) or {}

    term_text = (data.get("term_text") or "").strip()
    subject   = (data.get("subject") or "").strip()
    campus    = (data.get("campus") or "").strip()

    try:
        term_code = get_term_code_from_text(term_text)
    except Exception as e:
        return jsonify({
            "error": "term_code_failed",
            "term_text": term_text,
            "detail": str(e)
        }), 400

    try:
        classes = fetch_schedule_sbctc(term=term_code, subject=subject, campus=campus)
        return jsonify({
            "term_text": term_text,
            "term_code": term_code,
            "count": len(classes),
            "data": classes
        })
    except Exception as e:
        # This is the key fix: do NOT crash with 500 + blank UI.
        return jsonify({
            "error": "sbctc_fetch_failed",
            "term_text": term_text,
            "term_code": term_code,
            "subject": subject,
            "campus": campus,
            "detail": str(e)
        }), 502

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
