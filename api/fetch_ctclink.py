import os
import requests
CTCLINK_BASE = os.getenv(
    "CTCLINK_BASE",
    "https://csprd.ctclink.us/psp/csprd/EMPLOYEE/PSFT_CS/s/WEBLIB_HCX_CM.H_CLASS_SEARCH.FieldFormula.IScript_Main"
)
def fetch_schedule_ctclink(institution: str, term: str, page: int = 1) -> str:
    """
    ctcLink public search endpoint often returns HTML or JSON-like output.
    This starter returns raw text so you can inspect & then parse.
    """
    params = {
        "institution": institution,
        "term": term,
        "page": str(page),
    }
    r = requests.get(CTCLINK_BASE, params=params, timeout=30)
    r.raise_for_status()
    return r.text
