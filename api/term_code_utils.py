from datetime import datetime
# NOTE:
# SBCTC term code patterns vary by institution/system.
# This file is designed so students NEVER type numeric term codes.
#
# You will adjust mapping logic once you confirm your campus term scheme.
def normalize_term_text(term_text: str) -> str:
    return (term_text or "").strip().lower()
def infer_next_term_name(now: datetime) -> str:
    # Baseline rule (adjust as needed):
    # Jan-Mar: winter
    # Apr-Jun: spring
    # Jul-Sep: summer
    # Oct-Dec: fall
    m = now.month
    if m <= 3:
        return "spring"
    if m <= 6:
        return "summer"
    if m <= 9:
        return "fall"
    return "winter"
def get_term_code_from_text(term_text: str) -> str:
    """
    Returns a term code string that your schedule endpoint expects.
    Replace this logic with the confirmed SBCTC/ctcLink term code scheme.
    For now:
      - If user types 'fall/spring/summer/winter' we return a placeholder code pattern.
      - If user types a 4-digit numeric string, we pass it through unchanged.
    """
    t = normalize_term_text(term_text)
    # Pass-through if user already has numeric code
    if t.isdigit() and len(t) == 4:
        return t
    now = datetime.now()
    year2 = str(now.year)[-2:]  # last 2 digits
    if t in ("", "current", "now", "this term"):
        t = infer_next_term_name(now)
    # Placeholder mapping: YOU will replace once confirmed.
    # Example patterns some systems use: YY + quarter digit(s)
    # We keep it explicit and easy to edit.
    mapping = {
        "winter": f"{year2}51",
        "spring": f"{year2}53",
        "summer": f"{year2}54",
        "fall":   f"{year2}55",
    }
    # If unknown term, fall back to inferred next term
    if t not in mapping:
        t = infer_next_term_name(now)
    return mapping[t]
