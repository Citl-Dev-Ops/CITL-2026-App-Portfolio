from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

COURSE_TOKEN_RE = re.compile(
    r"\b(?P<subject>[A-Z]{2,6})(?P<joiner>\s*&\s*|\s+|&)?(?P<number>\d{3}[A-Z]?)\b"
)
CREDITS_RE = re.compile(r"\b(?P<credits>\d+(?:\.\d+)?)\s*(?:cr|credits?|units?)\b", re.IGNORECASE)
ITEM_NUMBER_RE = re.compile(
    r"\b(?:item|class|course)\s*(?:number|nbr|num|no\.?|#)?\s*[:#-]?\s*(?P<num>\d{4,6})\b",
    re.IGNORECASE,
)
CRN_RE = re.compile(r"\b(?P<num>\d{5})\b")
TERM_HEADER_RE = re.compile(r"\b(Fall|Winter|Spring|Summer)\b", re.IGNORECASE)
SEASON_ORDER = ["WINTER", "SPRING", "SUMMER", "FALL"]

YEAR_RE = re.compile(r"\b(?P<year>19[7-9]\d|20[0-2]\d)\b")
GRADE_RE = re.compile(
    r"(?:^|[ ,|\t])(?P<grade>A[+-]?|B[+-]?|C[+-]?|D[+-]?|F|CR|TC|TR|NC|NP|NF|IP|AU|W|I|P|S)(?=[ ,|\t.]|$)",
    re.IGNORECASE,
)

_PASSING_GRADES = {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "CR", "P", "TC", "S", "TR"}
_FAILING_GRADES = {"F", "NF", "NC", "NP"}
_INCOMPLETE_GRADES = {"W", "I", "AU", "NR", "IP"}

_WA_SBCTC_KEYWORDS = [
    "renton technical", "rtc", "rtcc",
    "bellevue college", "seattle central", "north seattle college", "south seattle college",
    "highline college", "green river college", "south puget sound community",
    "shoreline community", "cascadia college", "edmonds college", "everett community",
    "tacoma community", "pierce college", "clark college",
    "lower columbia college", "columbia basin college", "big bend community",
    "wenatchee valley college", "centralia college", "grays harbor college",
    "peninsula college", "olympic college", "skagit valley college",
    "whatcom community", "bellingham technical", "lake washington institute",
    "clover park technical", "bates technical", "walla walla community",
    "yakima valley college", "spokane community", "spokane falls",
    "sbctc", "ctclink",
]

_WA_UNIVERSITY_KEYWORDS = [
    "university of washington", "washington state university",
    "western washington university", "eastern washington university",
    "central washington university", "pacific lutheran university",
    "seattle university", "gonzaga university", "whitman college",
    "seattle pacific university", "university of puget sound",
]

_KNOWN_UNACCREDITED_KEYWORDS = [
    "university of phoenix", "devry university", "itt technical", "westwood college",
    "american intercontinental university", "corinthian college", "everest university",
    "vatterott college", "sanford-brown", "brighton college", "ashford university",
    "grand canyon university" , "national university", "argosy university",
]

_INTL_ACCREDITED_KEYWORDS = [
    "university of toronto", "mcgill university", "ubc", "university of british columbia",
    "oxford university", "cambridge university", "imperial college",
    "university of manchester", "university of london", "university of edinburgh",
    "university of melbourne", "university of sydney", "university of auckland",
    "national university of singapore", "hong kong university",
]
REGEX_PATTERNS: Dict[str, re.Pattern[str]] = {
    "course_code": COURSE_TOKEN_RE,
    "item_number": ITEM_NUMBER_RE,
    "prerequisite": re.compile(r"\b(prereq(?:uisite)?s?|co-?req(?:uisite)?s?)\b", re.IGNORECASE),
    "minimum_grade": re.compile(r"\b(min(?:imum)?\s*grade|grade\s+of\s+[ABCDF][+-]?)\b", re.IGNORECASE),
    "credits": re.compile(r"\b\d+(?:\.\d+)?\s*(?:cr|credits?|units?)\b", re.IGNORECASE),
    "transfer_mandate": re.compile(r"\b(sbctc|transfer|dta|articulation|equivalenc(?:y|ies))\b", re.IGNORECASE),
    "program_totals": re.compile(r"\b(total\s+credits|credits\s+required|program\s+credits)\b", re.IGNORECASE),
    "admin_approval": re.compile(
        r"\b(advisor|department|dean|instructor|administrator|program chair)\b.{0,35}\b(approval|required)\b",
        re.IGNORECASE,
    ),
    "hard_limit": re.compile(
        r"\b(hard\s+limit|cannot\s+transfer|not\s+transferable|max(?:imum)?\s+\d+(?:\.\d+)?\s*credits?)\b",
        re.IGNORECASE,
    ),
    "incompatibility": re.compile(
        r"\b(incompatible|not\s+equivalent|does\s+not\s+apply|excluded\s+from\s+transfer)\b",
        re.IGNORECASE,
    ),
}


def extract_text_from_pdf(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as e:
        raise RuntimeError(f"Missing dependency pypdf. Install with pip install pypdf. ({e})")
    reader = PdfReader(str(pdf_path))
    texts: List[str] = []
    for page in reader.pages:
        t = page.extract_text() or ""
        if t.strip():
            texts.append(t)
    text = "\n".join(texts)
    text = text.replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_garbled_pdf_text(text: str) -> bool:
    sample = (text or "")[:20000]
    if not sample.strip():
        return True
    total_chars = len(sample)
    alpha = sum(1 for ch in sample if ch.isalpha())
    digits = sum(1 for ch in sample if ch.isdigit())
    alnum = sum(1 for ch in sample if ch.isalnum())
    slash_count = sample.count("/")
    word_like = re.findall(r"[A-Za-z]{3,}", sample)

    if alnum > 0 and (alpha / max(alnum, 1)) < 0.18:
        return True
    if slash_count > max(40, int(total_chars * 0.06)) and alpha < digits:
        return True
    if len(re.findall(r"\S+", sample)) >= 100 and len(word_like) < 10:
        return True
    if re.search(r"(?:i255/){2,}", sample):
        return True
    return False


def extract_text_with_ocr_fallback(pdf_path: Path) -> Tuple[str, Dict[str, Any]]:
    base_text = extract_text_from_pdf(pdf_path)
    warnings: List[str] = []
    if base_text.strip() and not _looks_like_garbled_pdf_text(base_text):
        return base_text, {"method": "pypdf", "ocr_used": False, "warnings": []}
    if base_text.strip():
        warnings.append("Primary PDF text looked garbled; OCR fallback attempted.")

    ocr_text_parts: List[str] = []
    try:
        import pytesseract  # type: ignore
        import pypdfium2 as pdfium  # type: ignore
    except Exception as e:
        warnings.append(f"OCR dependencies unavailable: {e}")
        return "", {"method": "none", "ocr_used": False, "warnings": warnings}

    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
        for i in range(len(pdf)):
            page = pdf[i]
            pil_img = page.render(scale=2).to_pil()
            txt = pytesseract.image_to_string(pil_img) or ""
            if txt.strip():
                ocr_text_parts.append(txt)
        try:
            pdf.close()
        except Exception:
            pass
    except Exception as e:
        warnings.append(f"OCR render/recognition failed: {e}")
        return "", {"method": "none", "ocr_used": False, "warnings": warnings}

    text = "\n".join(ocr_text_parts).strip()
    if not text:
        warnings.append("OCR completed but no text was recovered.")
        return "", {"method": "ocr", "ocr_used": True, "warnings": warnings}
    return text, {"method": "ocr", "ocr_used": True, "warnings": warnings}


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s or "unknown"


def normalize_course_code(raw: str) -> str:
    if not raw:
        return ""
    txt = re.sub(r"\s+", " ", str(raw).strip().upper())
    m = COURSE_TOKEN_RE.search(txt)
    if not m:
        return txt
    subj = m.group("subject").upper()
    num = m.group("number").upper()
    joiner = "&" if "&" in (m.group("joiner") or "") else " "
    return f"{subj}{joiner}{num}"


def course_key(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def course_parts(code: str) -> Tuple[Optional[str], Optional[str], bool]:
    n = normalize_course_code(code)
    m = COURSE_TOKEN_RE.search(n)
    if not m:
        return None, None, False
    return m.group("subject").upper(), m.group("number").upper(), "&" in n


def extract_credits_from_line(line: str) -> Optional[float]:
    m = CREDITS_RE.search(line)
    if m:
        try:
            return float(m.group("credits"))
        except ValueError:
            return None
    nums = [float(x) for x in re.findall(r"\b\d+(?:\.\d+)?\b", line)]
    for n in reversed(nums):
        if 0.5 <= n <= 20:
            return float(n)
    return None


def extract_item_number(line: str) -> Optional[str]:
    m = ITEM_NUMBER_RE.search(line)
    if m:
        return m.group("num")
    lower = line.lower()
    if "crn" in lower or "class #" in lower or "class number" in lower or "item" in lower:
        m2 = CRN_RE.search(line)
        if m2:
            return m2.group("num")
    return None


def extract_courses_from_line(line: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in COURSE_TOKEN_RE.finditer(line.upper()):
        normalized = normalize_course_code(m.group(0))
        subject, catalog, has_amp = course_parts(normalized)
        if not subject or not catalog:
            continue
        out.append(
            {
                "course_code": normalized,
                "course_key": course_key(normalized),
                "subject": subject,
                "catalog_number": catalog,
                "has_ampersand": has_amp,
            }
        )
    return out


def extract_grade_from_line(line: str) -> Optional[str]:
    upper = line.upper()
    code_m = COURSE_TOKEN_RE.search(upper)
    start = code_m.end() if code_m else 0
    # Skip past credit notation so we don't confuse "CR" in "5 CR" with a grade
    credits_m = CREDITS_RE.search(upper, start)
    if credits_m:
        start = credits_m.end()
    segment = " " + upper[start:] + " "
    m = GRADE_RE.search(segment)
    return m.group("grade").upper().strip() if m else None


def _extract_institution_hint(lines: List[str]) -> str:
    for line in lines[:40]:
        if re.search(r"(community college|technical college|vocational institute|university|college)", line, re.IGNORECASE):
            if 10 <= len(line) <= 90 and not re.search(r"\b(credits?|cr\b|grade|term|gpa|total)\b", line, re.IGNORECASE):
                return line.strip()
        m = re.search(r"(?:institution|school|college|from)\s*[:–-]\s*(.+)", line, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _classify_institution(institution_text: str) -> str:
    if not institution_text:
        return "unknown"
    lower = institution_text.lower()
    for kw in _KNOWN_UNACCREDITED_KEYWORDS:
        if kw in lower:
            return "likely_unaccredited"
    for kw in _WA_SBCTC_KEYWORDS:
        if kw in lower:
            return "wa_sbctc"
    for kw in _WA_UNIVERSITY_KEYWORDS:
        if kw in lower:
            return "wa_university"
    for kw in _INTL_ACCREDITED_KEYWORDS:
        if kw in lower:
            return "intl_accredited"
    if re.search(r"(community college|technical college|vocational)", lower):
        return "us_accredited"
    if re.search(r"\b(university|college|institute of technology)\b", lower):
        return "us_accredited"
    return "unknown"


_GRADE_POINTS: Dict[str, float] = {
    "A+": 4.0, "A": 4.0, "A-": 3.7,
    "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7,
    "D+": 1.3, "D": 1.0, "D-": 0.7,
    "F": 0.0, "NF": 0.0, "NC": 0.0, "NP": 0.0,
    "CR": 3.0, "P": 3.0, "TC": 3.0, "TR": 3.0, "S": 3.0,
}

_RUNNING_START_KEYWORDS = [
    "running start", "running-start", "high school", "hs dual",
    "dual enrollment", "early college", "rs program",
]
_WAIVED_KEYWORDS = [
    "waived", "waiver", "substituted", "sub:", "override",
    "advisor approved", "dept approved", "exception granted",
]


def _is_remedial(catalog_number: Optional[str]) -> bool:
    if not catalog_number:
        return False
    m = re.search(r"\d+", catalog_number)
    return bool(m and int(m.group()) < 100)


def _is_running_start(institution_hint: str, source_line: str) -> bool:
    combined = (institution_hint + " " + source_line).lower()
    return any(kw in combined for kw in _RUNNING_START_KEYWORDS)


def _is_waived(source_line: str) -> bool:
    low = (source_line or "").lower()
    return any(kw in low for kw in _WAIVED_KEYWORDS)


def classify_provision_status(
    has_ampersand: bool,
    grade: Optional[str],
    institution_class: str,
    year: Optional[int],
    catalog_number: Optional[str] = None,
    institution_hint: str = "",
    source_line: str = "",
) -> Tuple[str, str]:
    current_year = datetime.now().year
    grade_upper = (grade or "").upper().strip()
    is_passing = grade_upper in _PASSING_GRADES
    is_failing = grade_upper in _FAILING_GRADES
    has_grade = bool(grade_upper)
    years_ago = (current_year - year) if year else None
    too_old = years_ago is not None and years_ago > 40
    somewhat_old = years_ago is not None and 30 < years_ago <= 40

    # ── Waived / Substituted — advisor already acted ──────────────────────
    if _is_waived(source_line):
        return (
            "waived_substituted",
            "This course appears to have been waived, substituted, or manually approved by an advisor. It should already be counted in your degree audit. Confirm with your advisor that the substitution is recorded in the system.",
        )

    # ── Audit — no credit awarded ─────────────────────────────────────────
    if grade_upper == "AU":
        return (
            "audit",
            "Course was taken as an Audit (AU) — no credit is awarded. Audited courses do not count toward degree requirements or transfer credit.",
        )

    # ── In Progress — currently enrolled ─────────────────────────────────
    if grade_upper == "IP":
        return (
            "in_progress",
            "Course is marked In Progress (IP) — you are currently enrolled. Once a final passing grade is posted, this course may be re-evaluated. Do not count this toward completed credits until the grade is finalized.",
        )

    # ── Remedial / Pre-College — catalog number below 100 ────────────────
    if _is_remedial(catalog_number):
        return (
            "remedial",
            f"Course number {catalog_number} indicates a pre-college or developmental course (numbered below 100). Remedial courses do not transfer and do not count toward degree credit hours at RTC. They may be required for placement but are not part of degree completion.",
        )

    # ── Running Start / Dual Credit ───────────────────────────────────────
    if _is_running_start(institution_hint, source_line):
        if is_passing:
            return (
                "dual_credit",
                "This course appears to be from a Running Start or dual-enrollment program. Running Start credits taken at a WA state community or technical college are generally eligible if the course meets degree requirements. Bring your college transcript (not just your high school transcript) to your advisor appointment.",
            )
        return (
            "inconclusive",
            "Running Start or dual-credit course detected, but no passing grade was found. Eligibility depends on final grade posted on the college transcript. Contact your advisor.",
        )

    # ── Unaccredited institution ──────────────────────────────────────────
    if institution_class == "likely_unaccredited":
        return (
            "not_eligible",
            "This course is from an institution with known accreditation concerns. Credits from unaccredited or closed schools are generally not transferable. Please bring documentation for advisor review.",
        )

    # ── Failing / No Credit ───────────────────────────────────────────────
    if is_failing:
        return (
            "not_eligible",
            f"Grade '{grade}' does not meet transfer requirements. Only passing grades (C or better, CR, P) are considered for transfer. Failed courses cannot be counted toward degree completion.",
        )
    if grade_upper == "W":
        return (
            "not_eligible",
            "Course was withdrawn (W). Withdrawn courses do not count toward transfer credit and are not eligible for degree application.",
        )

    # ── Too old ───────────────────────────────────────────────────────────
    if too_old:
        return (
            "inconclusive",
            f"This course appears to be from {year} — more than 40 years ago. Very old coursework may need individual assessment to determine if it remains equivalent to current curriculum standards. Please bring documentation.",
        )

    # ── Other incomplete statuses ─────────────────────────────────────────
    if grade_upper in _INCOMPLETE_GRADES:
        return (
            "inconclusive",
            f"Grade '{grade}' indicates the course is not yet complete or is under review. Eligibility is pending a final grade. Contact your advisor once the grade is posted.",
        )

    # ── High Likelihood — WA state & transfer designation ────────────────
    if has_ampersand and is_passing and institution_class in ("wa_sbctc", "wa_university"):
        age_note = f" (completed approximately {years_ago} years ago)" if somewhat_old else ""
        return (
            "high_likelihood",
            f"This course has an official WA state transfer designation (&) with a passing grade from a Washington state institution{age_note}. Very likely to be accepted toward your degree. Final determination is made during an official degree audit — this is a provisional assessment only.",
        )

    # ── Somewhat Likely ───────────────────────────────────────────────────
    if is_passing and institution_class in ("wa_sbctc", "wa_university"):
        age_note = f" (completed approximately {years_ago} years ago — please confirm currency)" if somewhat_old else ""
        return (
            "somewhat_likely",
            f"Passing grade from a Washington state institution{age_note}. May be eligible as a transfer, elective, or general education course. Lacks a formal transfer (&) designation, so final eligibility requires advisor review.",
        )
    if has_ampersand and is_passing:
        return (
            "somewhat_likely",
            "Course has a transfer designation (&) with a passing grade. Institution could not be confirmed as part of the WA state system — eligibility requires verification. Likely applicable as transfer credit.",
        )
    if is_passing and institution_class in ("us_accredited", "intl_accredited"):
        age_note = f" (completed approximately {years_ago} years ago — verify currency)" if somewhat_old else ""
        return (
            "somewhat_likely",
            f"Passing grade from an accredited institution{age_note}. May be eligible as a transfer elective or general education course. Final determination requires an official degree audit.",
        )
    if not has_grade and institution_class in ("wa_sbctc", "wa_university"):
        return (
            "somewhat_likely",
            "Course appears to be from a WA state institution, but no grade was detected. Likely eligible pending grade verification — please bring your original transcript.",
        )

    # ── Inconclusive ──────────────────────────────────────────────────────
    if is_passing and institution_class == "unknown":
        return (
            "inconclusive",
            "A passing grade was detected, but the institution could not be confirmed as accredited. This course may still be eligible — your advisor will need to verify institutional accreditation status.",
        )
    return (
        "inconclusive",
        "Insufficient information was detected to determine eligibility. This may be due to unclear grade data, an unidentifiable institution, or ambiguous transcript formatting. Bring your original transcript to your advisor appointment for manual review.",
    )


def _apply_repeated_flags(courses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mark earlier, lower-grade attempts of the same course as 'repeated'."""
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for c in courses:
        by_key.setdefault(c["course_key"], []).append(c)
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        # Sort by grade points descending so best grade is first
        def _gp(c: Dict[str, Any]) -> float:
            return _GRADE_POINTS.get((c.get("grade") or "").upper(), 2.0)
        group.sort(key=_gp, reverse=True)
        for earlier in group[1:]:
            if earlier.get("provision_status") not in ("not_eligible", "remedial", "audit"):
                earlier["provision_status"] = "repeated"
                earlier["provision_reason"] = (
                    f"You have taken this course more than once. Only the highest-grade attempt "
                    f"(grade: {group[0].get('grade') or 'unknown'}) is counted toward degree requirements. "
                    f"This earlier attempt (grade: {earlier.get('grade') or 'unknown'}) is recorded "
                    f"on your transcript but does not add additional credit."
                )
    return courses


def parse_transcript_text(text: str) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: List[Dict[str, Any]] = []
    seen: set[Tuple[str, Optional[str], Optional[float], int]] = set()

    institution_hint = _extract_institution_hint(lines)
    current_year: Optional[int] = None

    for idx, line in enumerate(lines, start=1):
        year_m = YEAR_RE.search(line)
        if year_m:
            current_year = int(year_m.group("year"))

        course_hits = extract_courses_from_line(line)
        if not course_hits:
            continue
        credits = extract_credits_from_line(line)
        item_number = extract_item_number(line)
        grade = extract_grade_from_line(line)

        for hit in course_hits:
            key = (hit["course_key"], item_number, credits, idx)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    **hit,
                    "credits": credits,
                    "item_number": item_number,
                    "line_no": idx,
                    "source_line": line[:260],
                    "grade": grade,
                    "year_hint": current_year,
                    "institution_hint": institution_hint,
                }
            )

    dedup: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
    for row in out:
        dkey = (row["course_key"], row.get("item_number"))
        if dkey not in dedup:
            dedup[dkey] = row
            continue
        prev = dedup[dkey]
        if prev.get("credits") is None and row.get("credits") is not None:
            dedup[dkey] = row
    return list(dedup.values())


def normalize_transcript_courses(courses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in courses:
        if not isinstance(row, dict):
            continue
        raw_course = str(row.get("course_code") or row.get("course") or "").strip()
        if not raw_course:
            continue
        normalized = normalize_course_code(raw_course)
        ck = course_key(normalized)
        if not ck:
            continue
        subject, catalog, has_amp = course_parts(normalized)
        grade = str(row.get("grade") or "").strip() or None
        year_hint = row.get("year_hint")
        institution_hint = str(row.get("institution_hint") or "").strip()
        source_line = str(row.get("source_line") or "")
        institution_class = _classify_institution(institution_hint)
        provision_status, provision_reason = classify_provision_status(
            has_ampersand=has_amp,
            grade=grade,
            institution_class=institution_class,
            year=int(year_hint) if year_hint else None,
            catalog_number=catalog,
            institution_hint=institution_hint,
            source_line=source_line,
        )
        out.append(
            {
                "course_code": normalized,
                "course_key": ck,
                "subject": subject,
                "catalog_number": catalog,
                "has_ampersand": has_amp,
                "credits": to_float(row.get("credits")),
                "item_number": str(row.get("item_number") or "").strip() or None,
                "source_line": row.get("source_line"),
                "line_no": row.get("line_no"),
                "grade": grade,
                "year_hint": year_hint,
                "institution_hint": institution_hint or None,
                "institution_class": institution_class,
                "provision_status": provision_status,
                "provision_reason": provision_reason,
            }
        )
    dedup: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
    for row in out:
        k = (row["course_key"], row.get("item_number"))
        if k not in dedup:
            dedup[k] = row
            continue
        prev = dedup[k]
        if prev.get("credits") is None and row.get("credits") is not None:
            dedup[k] = row
    return _apply_repeated_flags(list(dedup.values()))


def build_provision_summary(courses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate provision status counts and list for session context."""
    counts: Dict[str, int] = {}
    for c in courses:
        s = c.get("provision_status", "inconclusive")
        counts[s] = counts.get(s, 0) + 1
    return {
        "total": len(courses),
        "counts": counts,
        "institution_hint": next(
            (c["institution_hint"] for c in courses if c.get("institution_hint")), None
        ),
        "year_range": sorted(
            {c["year_hint"] for c in courses if c.get("year_hint")}
        ) or None,
    }


_NAME_LABEL_RE = re.compile(
    r"(?:student(?:\s+name)?|name|student\s+id)\s*[:\-]\s*(?P<name>[A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+){1,4})",
    re.IGNORECASE,
)
_CAPS_NAME_RE = re.compile(
    r"^(?P<name>[A-Z][A-Z\-']{1,20}(?:\s+[A-Z][A-Z\-']{1,20}){1,3})\s*$"
)
_TITLE_NAME_RE = re.compile(
    r"^(?P<name>[A-Z][a-z\-']{1,20}(?:\s+[A-Z][a-z\-']{1,20}){1,3})\s*$"
)
_SKIP_WORDS = {
    "TRANSCRIPT", "ACADEMIC", "OFFICIAL", "UNOFFICIAL", "RECORD", "COLLEGE",
    "UNIVERSITY", "INSTITUTE", "SCHOOL", "COMMUNITY", "TECHNICAL", "RENTON",
    "HIGHLINE", "DEGREE", "PROGRESS", "REPORT", "AUDIT", "GRADE", "CREDITS",
    "PAGE", "DATE", "TERM", "FALL", "WINTER", "SPRING", "SUMMER",
}


def extract_student_name(text: str) -> Optional[str]:
    """Scan the first 80 lines of a transcript for a student name."""
    lines = text.split("\n")[:80]
    # Pass 1: look for explicit label patterns
    for line in lines:
        m = _NAME_LABEL_RE.search(line)
        if m:
            candidate = m.group("name").strip()
            if 5 <= len(candidate) <= 60 and " " in candidate:
                return candidate.title()
    # Pass 2: all-caps name lines (e.g. "MCDOWELL ANDREW")
    for line in lines:
        line = line.strip()
        m = _CAPS_NAME_RE.match(line)
        if m:
            candidate = m.group("name").strip()
            words = candidate.split()
            if 2 <= len(words) <= 4 and not any(w in _SKIP_WORDS for w in words):
                return candidate.title()
    # Pass 3: Title-case isolated name lines
    for line in lines:
        line = line.strip()
        m = _TITLE_NAME_RE.match(line)
        if m:
            candidate = m.group("name").strip()
            words = candidate.split()
            if 2 <= len(words) <= 4 and not any(w.upper() in _SKIP_WORDS for w in words):
                return candidate
    return None


def student_slug(name: str) -> str:
    """'Andrew McDowell' → 'andrew_mcdowell'"""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower().strip())
    return slug.strip("_") or "unknown"


def build_transcript_llm_context(courses: List[Dict[str, Any]], max_courses: int = 40) -> str:
    """Compact transcript summary for injecting into LLM chat prompts."""
    if not courses:
        return ""
    summary = build_provision_summary(courses)
    lines = [
        "[Student Transcript — Provisional Eligibility Assessment]",
        f"Institution: {summary['institution_hint'] or 'Unknown'}",
        f"Years on file: {', '.join(str(y) for y in (summary['year_range'] or []))}",
        f"Total courses detected: {summary['total']}",
        "Status counts: " + "  |  ".join(
            f"{k.replace('_', ' ').title()}: {v}" for k, v in summary["counts"].items()
        ),
        "",
        "Courses:",
    ]
    for c in courses[:max_courses]:
        grade = c.get("grade") or "—"
        credits = f"{c.get('credits')} cr" if c.get("credits") else "—"
        status = (c.get("provision_status") or "inconclusive").replace("_", " ")
        amp = " [&]" if c.get("has_ampersand") else ""
        lines.append(
            f"  {c['course_code']}{amp}  grade={grade}  {credits}  [{status}]"
        )
    if len(courses) > max_courses:
        lines.append(f"  ... and {len(courses) - max_courses} more courses")
    lines.append(
        "\nNote: All statuses are PROVISIONAL. Final determination requires an official advisor degree audit."
    )
    return "\n".join(lines)


def extract_course_items_from_lines(lines: List[str]) -> List[Dict[str, Any]]:
    required: Dict[str, Dict[str, Any]] = {}
    current_term_hint: Optional[str] = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        term_match = TERM_HEADER_RE.search(line)
        if term_match and len(line) <= 42:
            current_term_hint = term_match.group(1).upper()
            continue
        for hit in extract_courses_from_line(line):
            key = hit["course_key"]
            if key in required:
                continue
            required[key] = {
                "course_code": hit["course_code"],
                "course_key": key,
                "subject": hit["subject"],
                "catalog_number": hit["catalog_number"],
                "has_ampersand": hit["has_ampersand"],
                "credits": extract_credits_from_line(line),
                "item_number": extract_item_number(line),
                "term_hint": current_term_hint,
                "source_line": line[:260],
            }
    return list(required.values())


def guess_program_name(text: str, fallback: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()[:40] if ln.strip()]
    if not lines:
        return fallback
    candidates = []
    for ln in lines:
        if len(ln) < 6:
            continue
        if re.fullmatch(r"\d+", ln):
            continue
        if "page" in ln.lower():
            continue
        candidates.append(ln)
    return max(candidates, key=len) if candidates else fallback


def guess_award(text: str) -> Optional[str]:
    m = re.search(r"\b(AAS-?T|AAS|AA|AS|BAS|Certificate|Cert)\b", text, re.IGNORECASE)
    return m.group(1) if m else None


def guess_total_credits(text: str) -> Optional[float]:
    m = re.search(
        r"(Total\s+Credits|Program\s+Credits|Credits\s+Required)\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    try:
        return float(m.group(2))
    except ValueError:
        return None


def normalize_program_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    program_name = str(
        doc.get("program_name")
        or doc.get("name")
        or doc.get("title")
        or doc.get("program")
        or "Unknown Program"
    ).strip()
    program_id = str(doc.get("program_id") or slugify(program_name))

    required_input: List[Any] = []
    for key in ("required_courses", "required", "courses"):
        if isinstance(doc.get(key), list):
            required_input.extend(doc[key])

    if isinstance(doc.get("terms"), list):
        for block in doc["terms"]:
            if not isinstance(block, dict):
                continue
            items = block.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        required_input.append({**item, "term_hint": block.get("term")})

    normalized_required: Dict[str, Dict[str, Any]] = {}
    for item in required_input:
        if isinstance(item, str):
            hit = extract_courses_from_line(item)
            if not hit:
                continue
            first = hit[0]
            normalized_required[first["course_key"]] = {
                **first,
                "credits": None,
                "item_number": None,
                "term_hint": None,
                "source_line": item[:260],
            }
            continue
        if not isinstance(item, dict):
            continue
        raw_course = str(item.get("course_code") or item.get("course") or item.get("code") or "").strip()
        if not raw_course:
            raw_line = str(item.get("raw") or item.get("source_line") or "")
            hits = extract_courses_from_line(raw_line)
            if not hits:
                continue
            raw_course = hits[0]["course_code"]
        normalized = normalize_course_code(raw_course)
        ck = course_key(normalized)
        subject, catalog, has_amp = course_parts(normalized)
        if not ck:
            continue
        normalized_required[ck] = {
            "course_code": normalized,
            "course_key": ck,
            "subject": subject,
            "catalog_number": catalog,
            "has_ampersand": has_amp,
            "credits": to_float(item.get("credits")),
            "item_number": str(item.get("item_number") or "").strip() or None,
            "term_hint": str(item.get("term_hint") or item.get("term") or "").strip() or None,
            "source_line": str(item.get("source_line") or item.get("raw") or "")[:260] or None,
        }

    return {
        "program_id": program_id,
        "program_name": program_name,
        "award": doc.get("award") or doc.get("credential_type"),
        "institution": doc.get("institution"),
        "total_credits_required": to_float(doc.get("total_credits_required") or doc.get("total_credits")),
        "required_courses": list(normalized_required.values()),
        "elective_groups": doc.get("elective_groups") if isinstance(doc.get("elective_groups"), list) else [],
        "notes": doc.get("notes") if isinstance(doc.get("notes"), list) else [],
        "source": doc.get("source") or doc.get("source_pdf") or "json_import",
    }


def normalize_program_from_pdf(text: str, source_pdf: str, fallback_name: str) -> Dict[str, Any]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    required_courses = extract_course_items_from_lines(lines)
    program_name = guess_program_name(text, fallback_name)
    notes = [
        ln[:240]
        for ln in lines
        if re.search(r"\b(prereq|prerequisite|minimum grade|application|transfer|sbctc|residency)\b", ln, re.IGNORECASE)
    ][:40]
    return {
        "program_id": slugify(program_name),
        "program_name": program_name,
        "award": guess_award(text),
        "institution": None,
        "total_credits_required": guess_total_credits(text),
        "required_courses": required_courses,
        "elective_groups": [],
        "notes": notes,
        "source": source_pdf,
    }


def normalize_transfer_rule(rule: Dict[str, Any], default_id: str) -> Dict[str, Any]:
    rtype = str(rule.get("type") or "").strip()
    out = {
        "id": str(rule.get("id") or default_id),
        "type": rtype,
        "description": str(rule.get("description") or "").strip() or None,
    }
    if rtype == "min_transfer_credits":
        out["min"] = float(rule.get("min") or rule.get("value") or 0)
    elif rtype == "requires_course":
        course = normalize_course_code(str(rule.get("course") or rule.get("course_code") or ""))
        out["course_code"] = course
        out["course_key"] = course_key(course)
    elif rtype == "any_of_courses":
        raw = rule.get("courses") if isinstance(rule.get("courses"), list) else []
        keys = []
        courses = []
        for c in raw:
            if not isinstance(c, str):
                continue
            n = normalize_course_code(c)
            k = course_key(n)
            if not k:
                continue
            courses.append(n)
            keys.append(k)
        out["choose"] = int(rule.get("choose") or rule.get("count") or 1)
        out["courses"] = courses
        out["course_keys"] = keys
    elif rtype == "min_courses_with_prefix":
        prefixes = [str(x).strip().upper() for x in (rule.get("prefixes") or []) if str(x).strip()]
        out["prefixes"] = prefixes
        out["min_count"] = int(rule.get("min_count") or rule.get("min") or 1)
    elif rtype == "min_courses_with_ampersand":
        out["min_count"] = int(rule.get("min_count") or rule.get("min") or 1)
    elif rtype == "requires_item_number":
        out["item_number"] = str(rule.get("item_number") or "").strip() or None
    elif rtype == "min_credits_in_prefixes":
        prefixes = [str(x).strip().upper() for x in (rule.get("prefixes") or []) if str(x).strip()]
        out["prefixes"] = prefixes
        out["min"] = float(rule.get("min") or 0)
    elif rtype == "max_transfer_credits":
        out["max"] = float(rule.get("max") or rule.get("value") or 0)
    elif rtype in {"disallow_courses", "admin_approval_if_missing_courses", "hard_block_if_missing_courses"}:
        raw = rule.get("courses") if isinstance(rule.get("courses"), list) else []
        single_course = str(rule.get("course") or rule.get("course_code") or "").strip()
        if single_course:
            raw.append(single_course)
        raw_keys = [str(x).strip() for x in (rule.get("course_keys") or []) if str(x).strip()]
        course_codes: List[str] = []
        course_keys: List[str] = []
        for c in raw:
            if not isinstance(c, str):
                continue
            normalized = normalize_course_code(c)
            ckey = course_key(normalized)
            if not ckey:
                continue
            course_codes.append(normalized)
            course_keys.append(ckey)
        for key in raw_keys:
            if key not in course_keys:
                course_keys.append(key)
        out["courses"] = course_codes
        out["course_keys"] = course_keys
        out["min_missing"] = int(rule.get("min_missing") or rule.get("min") or 1)
    return out


def normalize_transfer_rules(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {"equivalencies": [], "sbctc_mandates": [], "institution_mandates": {}}
    if isinstance(doc.get("equivalencies"), list):
        for i, e in enumerate(doc["equivalencies"], start=1):
            if not isinstance(e, dict):
                continue
            f = normalize_course_code(str(e.get("from") or e.get("source") or ""))
            t = normalize_course_code(str(e.get("to") or e.get("target") or ""))
            if not f or not t:
                continue
            out["equivalencies"].append(
                {
                    "id": str(e.get("id") or f"equiv_{i}"),
                    "from": f,
                    "to": t,
                    "from_key": course_key(f),
                    "to_key": course_key(t),
                }
            )
    raw_sbctc: List[Dict[str, Any]] = []
    if isinstance(doc.get("sbctc_mandates"), list):
        raw_sbctc.extend([x for x in doc["sbctc_mandates"] if isinstance(x, dict)])
    if isinstance(doc.get("sbctc"), dict) and isinstance(doc["sbctc"].get("rules"), list):
        raw_sbctc.extend([x for x in doc["sbctc"]["rules"] if isinstance(x, dict)])
    for i, rule in enumerate(raw_sbctc, start=1):
        out["sbctc_mandates"].append(normalize_transfer_rule(rule, f"sbctc_{i}"))
    inst_out: Dict[str, List[Dict[str, Any]]] = {}
    if isinstance(doc.get("institution_mandates"), dict):
        for inst, rules in doc["institution_mandates"].items():
            if not isinstance(rules, list):
                continue
            rset = [normalize_transfer_rule(r, f"{slugify(str(inst))}_{i}") for i, r in enumerate(rules, start=1) if isinstance(r, dict)]
            if rset:
                inst_out[str(inst)] = rset
    if isinstance(doc.get("institutions"), list):
        for entry in doc["institutions"]:
            if not isinstance(entry, dict):
                continue
            inst_name = str(entry.get("institution") or entry.get("name") or "").strip()
            if not inst_name:
                continue
            reqs = entry.get("requirements") if isinstance(entry.get("requirements"), list) else []
            inst_out.setdefault(inst_name, [])
            for i, rule in enumerate(reqs, start=1):
                if isinstance(rule, dict):
                    inst_out[inst_name].append(normalize_transfer_rule(rule, f"{slugify(inst_name)}_{i}"))
    out["institution_mandates"] = inst_out
    return out


def equivalency_graph(rules: Dict[str, Any]) -> Dict[str, set[str]]:
    graph: Dict[str, set[str]] = defaultdict(set)
    for eq in rules.get("equivalencies", []):
        fk = eq.get("from_key")
        tk = eq.get("to_key")
        if not fk or not tk:
            continue
        graph[fk].add(tk)
        graph[tk].add(fk)
    return graph


def expand_key_set(keys: set[str], graph: Dict[str, set[str]]) -> set[str]:
    out = set(keys)
    queue = list(keys)
    while queue:
        k = queue.pop()
        for n in graph.get(k, set()):
            if n in out:
                continue
            out.add(n)
            queue.append(n)
    return out


def build_course_key_index(course_index_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    key_index: Dict[str, Dict[str, Any]] = {}
    for row in course_index_rows:
        code = normalize_course_code(str(row.get("course") or ""))
        ckey = course_key(code)
        if not ckey:
            continue
        entry = key_index.setdefault(
            ckey,
            {"course_key": ckey, "course_code": code, "titles": Counter(), "credits": Counter(), "terms": set(), "term_seasons": set(), "raw_count": 0},
        )
        entry["raw_count"] += 1
        title = str(row.get("title") or "").strip()
        if title:
            entry["titles"][title] += 1
        cr = to_float(row.get("credits"))
        if cr is not None:
            entry["credits"][cr] += 1
        term = str(row.get("term") or "").upper()
        if term:
            entry["terms"].add(term)
            for season in SEASON_ORDER:
                if season in term:
                    entry["term_seasons"].add(season)
    out: Dict[str, Dict[str, Any]] = {}
    for key, val in key_index.items():
        top_title = val["titles"].most_common(1)[0][0] if val["titles"] else None
        credits_guess = float(val["credits"].most_common(1)[0][0]) if val["credits"] else None
        out[key] = {
            "course_key": key,
            "course_code": val["course_code"],
            "title": top_title,
            "credits_guess": credits_guess,
            "terms": sorted(list(val["terms"])),
            "term_seasons": sorted(list(val["term_seasons"])),
            "raw_count": val["raw_count"],
        }
    return out


def evaluate_rule(
    rule: Dict[str, Any],
    course_rows: List[Dict[str, Any]],
    expanded_keys: set[str],
    total_credits: float,
) -> Dict[str, Any]:
    rtype = rule.get("type")
    out = {
        "id": rule.get("id"),
        "type": rtype,
        "description": rule.get("description"),
        "ok": False,
        "need": None,
        "have": None,
    }
    prefix_count = Counter([str(r.get("subject") or "").upper() for r in course_rows if r.get("subject")])
    amp_count = sum(1 for r in course_rows if r.get("has_ampersand"))
    item_numbers = {str(r.get("item_number")) for r in course_rows if r.get("item_number")}

    if rtype == "min_transfer_credits":
        need = float(rule.get("min") or 0)
        out["need"] = need
        out["have"] = total_credits
        out["ok"] = total_credits >= need
        return out
    if rtype == "requires_course":
        key = str(rule.get("course_key") or "")
        out["need"] = rule.get("course_code") or key
        out["have"] = key in expanded_keys
        out["ok"] = key in expanded_keys
        return out
    if rtype == "any_of_courses":
        keys = [str(x) for x in (rule.get("course_keys") or [])]
        choose = int(rule.get("choose") or 1)
        hits = [k for k in keys if k in expanded_keys]
        out["need"] = choose
        out["have"] = len(hits)
        out["hits"] = hits
        out["ok"] = len(hits) >= choose
        return out
    if rtype == "min_courses_with_prefix":
        prefixes = [str(x).upper() for x in (rule.get("prefixes") or [])]
        need = int(rule.get("min_count") or 1)
        have = sum(prefix_count.get(p, 0) for p in prefixes)
        out["need"] = need
        out["have"] = have
        out["prefixes"] = prefixes
        out["ok"] = have >= need
        return out
    if rtype == "min_courses_with_ampersand":
        need = int(rule.get("min_count") or 1)
        out["need"] = need
        out["have"] = amp_count
        out["ok"] = amp_count >= need
        return out
    if rtype == "requires_item_number":
        required_item = rule.get("item_number")
        if required_item:
            out["need"] = required_item
            out["have"] = required_item in item_numbers
            out["ok"] = required_item in item_numbers
        else:
            out["need"] = "any item number"
            out["have"] = len(item_numbers)
            out["ok"] = len(item_numbers) > 0
        return out
    if rtype == "min_credits_in_prefixes":
        prefixes = [str(x).upper() for x in (rule.get("prefixes") or [])]
        need = float(rule.get("min") or 0)
        have = 0.0
        for row in course_rows:
            prefix = str(row.get("subject") or "").upper()
            if prefix not in prefixes:
                continue
            have += float(row.get("credits") or 0)
        out["need"] = need
        out["have"] = round(have, 3)
        out["prefixes"] = prefixes
        out["ok"] = have >= need
        return out
    if rtype == "max_transfer_credits":
        limit = float(rule.get("max") or 0)
        out["need"] = limit
        out["have"] = total_credits
        out["ok"] = total_credits <= limit
        if not out["ok"]:
            out["hard_block"] = True
        return out
    if rtype == "disallow_courses":
        keys = [str(x) for x in (rule.get("course_keys") or []) if str(x)]
        hits = [k for k in keys if k in expanded_keys]
        out["need"] = "no listed disallowed courses"
        out["have"] = len(hits)
        out["hits"] = hits
        out["ok"] = len(hits) == 0
        if hits:
            out["hard_block"] = True
        return out
    if rtype == "admin_approval_if_missing_courses":
        keys = [str(x) for x in (rule.get("course_keys") or []) if str(x)]
        min_missing = int(rule.get("min_missing") or 1)
        missing = [k for k in keys if k not in expanded_keys]
        requires_approval = len(missing) >= min_missing and len(keys) > 0
        out["need"] = f"approval if missing >= {min_missing}"
        out["have"] = len(missing)
        out["missing"] = missing
        out["ok"] = not requires_approval
        if requires_approval:
            out["approval_required"] = True
        return out
    if rtype == "hard_block_if_missing_courses":
        keys = [str(x) for x in (rule.get("course_keys") or []) if str(x)]
        min_missing = int(rule.get("min_missing") or 1)
        missing = [k for k in keys if k not in expanded_keys]
        hard_block = len(missing) >= min_missing and len(keys) > 0
        out["need"] = f"missing < {min_missing}"
        out["have"] = len(missing)
        out["missing"] = missing
        out["ok"] = not hard_block
        if hard_block:
            out["hard_block"] = True
        return out
    out["need"] = "supported rule type"
    out["have"] = "unknown"
    out["error"] = f"Unsupported rule type: {rtype}"
    return out


def suggest_programs(
    transcript_courses: List[Dict[str, Any]],
    programs: List[Dict[str, Any]],
    rules: Dict[str, Any],
    limit: int,
) -> List[Dict[str, Any]]:
    if not transcript_courses or not programs:
        return []
    keys = {r.get("course_key") for r in transcript_courses if r.get("course_key")}
    graph = equivalency_graph(rules)
    expanded = expand_key_set(set(keys), graph)
    suggestions: List[Dict[str, Any]] = []
    for p in programs:
        required = p.get("required_courses") or []
        required_keys = [str(x.get("course_key")) for x in required if isinstance(x, dict) and x.get("course_key")]
        if not required_keys:
            continue
        matched = [k for k in required_keys if k in expanded]
        ratio = len(matched) / max(len(required_keys), 1)
        missing_preview = []
        for item in required:
            if not isinstance(item, dict):
                continue
            if item.get("course_key") in expanded:
                continue
            missing_preview.append(item.get("course_code") or item.get("course_key"))
            if len(missing_preview) >= 6:
                break
        suggestions.append(
            {
                "program_id": p.get("program_id"),
                "program_name": p.get("program_name"),
                "award": p.get("award"),
                "match_ratio": round(ratio, 4),
                "matched_required": len(matched),
                "required_total": len(required_keys),
                "remaining_required": max(len(required_keys) - len(matched), 0),
                "missing_preview": missing_preview,
            }
        )
    suggestions.sort(key=lambda x: (-x["match_ratio"], x["remaining_required"], x["program_name"] or ""))
    return suggestions[: max(1, min(limit, 20))]


def term_from_string(value: str) -> Tuple[str, int]:
    t = (value or "").strip().upper()
    m = re.search(r"(WINTER|SPRING|SUMMER|FALL)\s+(\d{4})", t)
    if m:
        return m.group(1), int(m.group(2))
    now = datetime.now()
    if now.month <= 3:
        season = "WINTER"
    elif now.month <= 6:
        season = "SPRING"
    elif now.month <= 9:
        season = "SUMMER"
    else:
        season = "FALL"
    return season, now.year


def next_term(season: str, year: int) -> Tuple[str, int]:
    try:
        idx = SEASON_ORDER.index(season)
    except ValueError:
        return "WINTER", year + 1
    if idx == len(SEASON_ORDER) - 1:
        return "WINTER", year + 1
    return SEASON_ORDER[idx + 1], year


def plan_terms(
    missing_courses: List[Dict[str, Any]],
    begin_term: str,
    max_credits_per_term: float,
    horizon_terms: int,
    catalog_by_key: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    season, year = term_from_string(begin_term)
    work = []
    for item in missing_courses:
        ckey = item.get("course_key")
        if not ckey:
            continue
        catalog = catalog_by_key.get(ckey, {})
        credits = to_float(item.get("credits"))
        if credits is None:
            credits = to_float(catalog.get("credits_guess"))
        if credits is None:
            credits = 5.0
        term_hint = str(item.get("term_hint") or "").upper()
        term_hint_season = None
        for ss in SEASON_ORDER:
            if ss in term_hint:
                term_hint_season = ss
                break
        work.append(
            {
                **item,
                "credits": credits,
                "availability_seasons": list(catalog.get("term_seasons") or []),
                "term_hint_season": term_hint_season,
                "planned": False,
            }
        )

    work.sort(
        key=lambda x: (
            0 if x.get("term_hint_season") else 1,
            0 if x.get("availability_seasons") else 1,
            x.get("course_code") or "",
        )
    )

    pathway: List[Dict[str, Any]] = []
    for _ in range(max(1, horizon_terms)):
        term_label = f"{season} {year}"
        remaining_credit_cap = max_credits_per_term
        term_courses: List[Dict[str, Any]] = []
        for item in work:
            if item["planned"]:
                continue
            credits = float(item.get("credits") or 5.0)
            availability = [str(x).upper() for x in (item.get("availability_seasons") or [])]
            term_hint = item.get("term_hint_season")
            if term_hint and term_hint != season and len(work) > 2:
                continue
            if availability and season not in availability and len(work) > 2:
                continue
            if credits > remaining_credit_cap and term_courses:
                continue
            term_courses.append(
                {
                    "course_code": item.get("course_code"),
                    "course_key": item.get("course_key"),
                    "credits": credits,
                    "term_hint": item.get("term_hint"),
                    "availability_seasons": availability,
                    "item_number": item.get("item_number"),
                }
            )
            item["planned"] = True
            remaining_credit_cap -= credits
            if remaining_credit_cap < 1.0:
                break
        if not term_courses:
            for item in work:
                if item["planned"]:
                    continue
                credits = float(item.get("credits") or 5.0)
                term_courses.append(
                    {
                        "course_code": item.get("course_code"),
                        "course_key": item.get("course_key"),
                        "credits": credits,
                        "term_hint": item.get("term_hint"),
                        "availability_seasons": item.get("availability_seasons") or [],
                        "item_number": item.get("item_number"),
                    }
                )
                item["planned"] = True
                break
        if term_courses:
            pathway.append(
                {
                    "term": term_label,
                    "planned_credits": round(sum(float(c.get("credits") or 0) for c in term_courses), 3),
                    "courses": term_courses,
                }
            )
        season, year = next_term(season, year)
        if all(x["planned"] for x in work):
            break
    remaining = [
        {
            "course_code": x.get("course_code"),
            "course_key": x.get("course_key"),
            "credits": x.get("credits"),
            "term_hint": x.get("term_hint"),
            "item_number": x.get("item_number"),
        }
        for x in work
        if not x["planned"]
    ]
    return pathway, remaining


def estimate_pace_scenarios(
    remaining_credits: float,
    tuition_per_credit: Optional[float],
    fees_per_term: float,
    books_per_term: float,
) -> Dict[str, Dict[str, Any]]:
    pace_credit_targets = {"full_time": 15.0, "part_time": 8.0, "casual": 4.0}
    out: Dict[str, Dict[str, Any]] = {}
    for mode, credits_per_term in pace_credit_targets.items():
        terms = int(math.ceil((remaining_credits or 0.0) / credits_per_term)) if remaining_credits > 0 else 0
        tuition_est = None
        if tuition_per_credit is not None:
            tuition_est = round((remaining_credits * tuition_per_credit) + (terms * (fees_per_term + books_per_term)), 2)
        out[mode] = {
            "credits_per_term": credits_per_term,
            "estimated_terms": terms,
            "estimated_tuition_total": tuition_est,
            "estimated_fees_books_total": round(terms * (fees_per_term + books_per_term), 2),
        }
    return out


def extract_regex_findings(text: str, source_id: str, source_title: str, max_per_pattern: int = 200) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    findings: List[Dict[str, Any]] = []
    pattern_counts = defaultdict(int)
    for line_no, line in enumerate(lines, start=1):
        for pname, pattern in REGEX_PATTERNS.items():
            if pattern_counts[pname] >= max_per_pattern:
                continue
            for m in pattern.finditer(line):
                findings.append(
                    {
                        "id": f"{source_id}:{pname}:{line_no}:{m.start()}",
                        "source_id": source_id,
                        "source_title": source_title,
                        "pattern": pname,
                        "match": m.group(0),
                        "line_no": line_no,
                        "text": line[:300],
                    }
                )
                pattern_counts[pname] += 1
                if pattern_counts[pname] >= max_per_pattern:
                    break
    return findings


def build_regex_corpus_records(
    programs: List[Dict[str, Any]],
    course_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for p in programs:
        pname = str(p.get("program_name") or p.get("program_id") or "program")
        psource = str(p.get("source") or pname)
        text_parts: List[str] = []
        for r in p.get("required_courses") or []:
            if isinstance(r, dict):
                bits = [str(r.get("course_code") or ""), str(r.get("source_line") or ""), str(r.get("term_hint") or "")]
                text_parts.append(" ".join([x for x in bits if x]).strip())
        for note in p.get("notes") or []:
            if isinstance(note, str):
                text_parts.append(note)
        findings = extract_regex_findings("\n".join(text_parts), source_id=f"program:{p.get('program_id')}", source_title=pname)
        records.extend(findings)
        # Include a lightweight source summary record for keyword search.
        records.append(
            {
                "id": f"program-summary:{p.get('program_id')}",
                "source_id": f"program:{p.get('program_id')}",
                "source_title": pname,
                "pattern": "summary",
                "match": p.get("award") or "",
                "line_no": 0,
                "text": f"Program {pname} requires {len(p.get('required_courses') or [])} courses. Source: {psource}",
            }
        )

    for idx, row in enumerate(course_rows):
        course = str(row.get("course") or "")
        term = str(row.get("term") or "")
        title = str(row.get("title") or "")
        ctx = " ".join(row.get("raw_context") or [])
        blob = "\n".join([course, title, term, ctx]).strip()
        if not blob:
            continue
        source_id = f"schedule:{idx}"
        records.extend(extract_regex_findings(blob, source_id=source_id, source_title=f"{course} {term}"))
    return records


def regex_search(records: List[Dict[str, Any]], query: str, k: int = 25) -> List[Dict[str, Any]]:
    q_terms = [w for w in re.split(r"\s+", query.lower().strip()) if w]
    if not q_terms:
        return []
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for rec in records:
        hay = f"{rec.get('source_title','')} {rec.get('pattern','')} {rec.get('match','')} {rec.get('text','')}".lower()
        score = sum(1 for w in q_terms if w in hay)
        if score > 0:
            scored.append((score, rec))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[: max(1, min(k, 200))]]


def _text_from_non_pdf(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if not raw.strip():
        return ""
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(raw)
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception:
            return raw
    return raw


def build_regex_corpus_from_documents(
    source_paths: List[Path],
    max_chars_per_doc: int = 400_000,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {
        "documents_seen": 0,
        "documents_indexed": 0,
        "documents_failed": 0,
        "ocr_documents": 0,
        "warnings": [],
    }
    for path in source_paths:
        if not path.exists() or not path.is_file():
            continue
        stats["documents_seen"] += 1
        meta: Dict[str, Any] = {"method": "text", "ocr_used": False, "warnings": []}
        try:
            if path.suffix.lower() == ".pdf":
                text, meta = extract_text_with_ocr_fallback(path)
            else:
                text = _text_from_non_pdf(path)
        except Exception as e:
            stats["documents_failed"] += 1
            stats["warnings"].append(f"{path}: {e}")
            continue

        if meta.get("ocr_used"):
            stats["ocr_documents"] += 1
        if meta.get("warnings"):
            for w in meta["warnings"][:4]:
                stats["warnings"].append(f"{path}: {w}")

        text = (text or "").strip()
        if not text:
            continue
        if len(text) > max_chars_per_doc:
            text = text[:max_chars_per_doc]

        sid = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:14]
        source_id = f"doc:{sid}"
        source_title = path.name
        findings = extract_regex_findings(text, source_id=source_id, source_title=source_title)
        for rec in findings:
            rec["source_path"] = str(path)
            rec["extract_method"] = meta.get("method")
            rec["ocr_used"] = bool(meta.get("ocr_used"))
        records.extend(findings)
        records.append(
            {
                "id": f"{source_id}:summary",
                "source_id": source_id,
                "source_title": source_title,
                "source_path": str(path),
                "pattern": "summary",
                "match": "",
                "line_no": 0,
                "text": f"Indexed document {path.name} ({path.suffix.lower() or 'unknown'}) with method={meta.get('method')}.",
                "extract_method": meta.get("method"),
                "ocr_used": bool(meta.get("ocr_used")),
            }
        )
        stats["documents_indexed"] += 1

    if len(stats["warnings"]) > 40:
        stats["warnings"] = stats["warnings"][:40]
    return records, stats
