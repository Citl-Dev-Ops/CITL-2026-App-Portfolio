import os
import requests
SBCTC_BASE = os.getenv("SBCTC_BASE", "https://classes.sbctc.edu/api")
def fetch_schedule_sbctc(term: str, subject: str = "", campus: str = "") -> list[dict]:
    """
    Calls SBCTC public schedule endpoint.
    Returns list of class dicts (normalized from response).
    """
    url = f"{SBCTC_BASE}/Schedule/Search"
    payload = {"term": term}
    if subject:
        payload["subject"] = subject
    if campus:
        payload["campus"] = campus
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    # expected: { "data": [ ... ] }
    return data.get("data", [])
