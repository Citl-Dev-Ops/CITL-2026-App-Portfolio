from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from api.planner_core import course_key, normalize_course_code, to_float

DEFAULT_CLASS_SEARCH_MAIN_URL = (
    "https://csprd.ctclink.us/psc/csprd/EMPLOYEE/SA/s/"
    "WEBLIB_HCX_CM.H_CLASS_SEARCH.FieldFormula.IScript_Main"
)

HIGHPOINT_PAYLOAD_RE = re.compile(
    r"window\.highpoint\s*=\s*JSON\.parse\(decodeURIComponent\(escape\(atob\(`(?P<b64>[^`]+)`\)\)\)\);?"
)


def _decode_highpoint_payload(html: str) -> Dict[str, Any]:
    match = HIGHPOINT_PAYLOAD_RE.search(html or "")
    if not match:
        raise RuntimeError("Could not locate window.highpoint payload in class-search HTML.")
    b64 = match.group("b64")
    raw = base64.b64decode(b64)
    # Mirrors browser decodeURIComponent(escape(atob(...))) path.
    payload_text = raw.decode("latin1").encode("latin1").decode("utf-8", errors="ignore")
    obj = json.loads(payload_text)
    if not isinstance(obj, dict):
        raise RuntimeError("Decoded highpoint payload is not a JSON object.")
    return obj


def _class_search_api_url(class_search_main_url: str) -> str:
    url = (class_search_main_url or "").strip() or DEFAULT_CLASS_SEARCH_MAIN_URL
    if "IScript_Main" in url:
        return url.replace("IScript_Main", "IScript_ClassSearch")
    if "Main" in url:
        return url.replace("Main", "ClassSearch")
    return url


def _class_search_main_url(class_search_main_url: str) -> str:
    url = (class_search_main_url or "").strip() or DEFAULT_CLASS_SEARCH_MAIN_URL
    # The /psp path often wraps a shell page; /psc is the direct SA endpoint used by the JSON class search.
    if "/psp/" in url:
        url = url.replace("/psp/", "/psc/")
    return url


def _clean_search_params(search_params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(search_params, dict):
        return {}
    reserved = {"institution", "term", "page", "enrl_stat", "subject"}
    out: Dict[str, Any] = {}
    for key, value in search_params.items():
        k = str(key or "").strip()
        if not k:
            continue
        if k.lower() in reserved:
            continue
        if value is None:
            continue
        if isinstance(value, bool):
            out[k] = "Y" if value else "N"
            continue
        sv = str(value).strip()
        if not sv:
            continue
        out[k] = sv
    return out


def fetch_search_bootstrap(
    institution_code: str = "WA270",
    acad_career: str = "",
    class_search_main_url: str = DEFAULT_CLASS_SEARCH_MAIN_URL,
    timeout_seconds: int = 45,
) -> Dict[str, Any]:
    main_url = _class_search_main_url(class_search_main_url)
    params = {"institution": institution_code}
    if acad_career:
        params["acad_career"] = acad_career
    resp = requests.get(main_url, params=params, timeout=timeout_seconds)
    resp.raise_for_status()
    payload = _decode_highpoint_payload(resp.text)
    payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
    payload["class_search_main_url"] = main_url
    return payload


def _extract_term_rows(search_options: Dict[str, Any]) -> List[Dict[str, Any]]:
    terms = search_options.get("terms")
    if not isinstance(terms, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in terms:
        if not isinstance(row, dict):
            continue
        code = str(row.get("strm") or "").strip()
        if not code:
            continue
        out.append(
            {
                "term_code": code,
                "term_desc": str(row.get("descr") or "").strip() or code,
                "default": bool(row.get("default")),
            }
        )
    return out


def select_term_codes(
    search_options: Dict[str, Any],
    requested_term_codes: Optional[List[str]] = None,
    term_count: int = 3,
) -> List[str]:
    target_count = max(1, term_count)
    requested = [str(x).strip() for x in (requested_term_codes or []) if str(x).strip()]
    if requested:
        out: List[str] = []
        seen = set()
        for code in requested:
            if code in seen:
                continue
            seen.add(code)
            out.append(code)
            if len(out) >= target_count:
                return out[:target_count]
        return out[:target_count]

    term_rows = _extract_term_rows(search_options)
    if not term_rows:
        return []
    codes = [t["term_code"] for t in term_rows]
    default_code = next((t["term_code"] for t in term_rows if t.get("default")), None)
    default_code = default_code or str(search_options.get("selected_term") or "").strip() or codes[0]
    sorted_codes = sorted(codes, key=lambda x: int(re.sub(r"[^0-9]", "", x) or "0"))
    out = [default_code]
    if len(out) >= target_count:
        return out[:target_count]
    for code in sorted_codes:
        if code in out:
            continue
        if int(re.sub(r"[^0-9]", "", code) or "0") > int(re.sub(r"[^0-9]", "", default_code) or "0"):
            out.append(code)
        if len(out) >= target_count:
            return out[:target_count]
    for code in sorted_codes:
        if code in out:
            continue
        out.append(code)
        if len(out) >= target_count:
            return out[:target_count]
    return out[:target_count]


def _term_desc_map(search_options: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in _extract_term_rows(search_options):
        out[row["term_code"]] = row["term_desc"]
    return out


def _search_field_definitions(search_options: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = search_options.get("class_search_fields")
    if not isinstance(fields, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in fields:
        if not isinstance(row, dict):
            continue
        field_name = str(row.get("FIELDNAME") or "").strip()
        if not field_name:
            continue
        out.append(
            {
                "field_name": field_name,
                "label": str(row.get("DESCR") or field_name).strip() or field_name,
                "required": str(row.get("REQUIRED") or "").strip().upper() == "Y",
                "use": str(row.get("H_CX_CLS_SRCH_USE") or "").strip() or None,
            }
        )
    return out


def fetch_class_page(
    api_url: str,
    institution_code: str,
    term_code: str,
    page: int,
    enrl_stat: str = "O",
    subject: str = "",
    search_params: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 45,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "institution": institution_code,
        "term": term_code,
        "page": int(page),
        "enrl_stat": enrl_stat,
    }
    if subject:
        params["subject"] = subject
    params.update(_clean_search_params(search_params))
    resp = requests.get(api_url, params=params, timeout=timeout_seconds)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Class search response was not an object for term {term_code}.")
    return data


def fetch_all_classes_for_term(
    api_url: str,
    institution_code: str,
    term_code: str,
    enrl_stat: str = "O",
    subject: str = "",
    search_params: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 45,
) -> Dict[str, Any]:
    first = fetch_class_page(
        api_url=api_url,
        institution_code=institution_code,
        term_code=term_code,
        page=1,
        enrl_stat=enrl_stat,
        subject=subject,
        search_params=search_params,
        timeout_seconds=timeout_seconds,
    )
    page_count = int(first.get("pageCount") or 1)
    page_count = max(1, page_count)
    classes = list(first.get("classes") or [])
    for page in range(2, page_count + 1):
        data = fetch_class_page(
            api_url=api_url,
            institution_code=institution_code,
            term_code=term_code,
            page=page,
            enrl_stat=enrl_stat,
            subject=subject,
            search_params=search_params,
            timeout_seconds=timeout_seconds,
        )
        classes.extend(list(data.get("classes") or []))
    return {
        "page_count": page_count,
        "class_count": len(classes),
        "classes": classes,
    }


def _normalize_instructors(raw: Dict[str, Any]) -> str:
    names: List[str] = []
    instr = raw.get("instructors")
    if isinstance(instr, list):
        for item in instr:
            if isinstance(item, dict):
                nm = str(item.get("name") or item.get("instructor") or "").strip()
                if nm:
                    names.append(nm)
            elif isinstance(item, str):
                nm = item.strip()
                if nm:
                    names.append(nm)
    meetings = raw.get("meetings")
    if isinstance(meetings, list):
        for item in meetings:
            if not isinstance(item, dict):
                continue
            nm = str(item.get("instructor") or "").strip()
            if nm:
                names.append(nm)
    unique = sorted(set(names))
    return "; ".join(unique)


def _normalize_course_row(
    cls: Dict[str, Any],
    institution_code: str,
    term_code: str,
    term_desc: str,
    source_url: str,
) -> Optional[Dict[str, Any]]:
    subject = str(cls.get("subject") or "").strip()
    catalog_nbr = str(cls.get("catalog_nbr") or "").strip()
    if not subject or not catalog_nbr:
        return None
    code = normalize_course_code(f"{subject} {catalog_nbr}")
    ckey = course_key(code)
    if not ckey:
        return None
    raw_context: List[str] = []
    for key in (
        "descr",
        "subject_descr",
        "session_descr",
        "instruction_mode_descr",
        "location_descr",
        "campus_descr",
        "enrl_stat_descr",
        "rqmnt_designtn",
    ):
        val = str(cls.get(key) or "").strip()
        if val:
            raw_context.append(val)
    meetings = cls.get("meetings")
    if isinstance(meetings, list):
        for mtg in meetings:
            if not isinstance(mtg, dict):
                continue
            meeting_txt = " ".join(
                [
                    str(mtg.get("days") or "").strip(),
                    str(mtg.get("start_time") or "").strip(),
                    str(mtg.get("end_time") or "").strip(),
                    str(mtg.get("facility_descr") or "").strip(),
                    str(mtg.get("room") or "").strip(),
                    str(mtg.get("instructor") or "").strip(),
                ]
            ).strip()
            if meeting_txt:
                raw_context.append(meeting_txt)
    return {
        "institution_code": institution_code,
        "term": term_desc or term_code,
        "term_code": term_code,
        "course": code,
        "course_key": ckey,
        "title": cls.get("descr"),
        "credits": to_float(cls.get("units")),
        "raw_context": raw_context,
        "source_pdf": source_url,
        "source": "ctclink_live",
        "class_nbr": cls.get("class_nbr"),
        "section": cls.get("class_section"),
        "status": cls.get("class_stat"),
        "enrl_status": cls.get("enrl_stat_descr"),
        "delivery": cls.get("instruction_mode_descr") or cls.get("instruction_mode"),
        "instructor": _normalize_instructors(cls) or None,
        "campus": cls.get("campus"),
        "location": cls.get("location"),
        "start_dt": cls.get("start_dt"),
        "end_dt": cls.get("end_dt"),
    }


def build_live_offerings_snapshot(
    institution_code: str = "WA270",
    class_search_main_url: str = DEFAULT_CLASS_SEARCH_MAIN_URL,
    term_codes: Optional[List[str]] = None,
    term_count: int = 3,
    enrl_stat: str = "O",
    subject: str = "",
    acad_career: str = "",
    search_params: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 45,
) -> Dict[str, Any]:
    bootstrap = fetch_search_bootstrap(
        institution_code=institution_code,
        acad_career=acad_career,
        class_search_main_url=class_search_main_url,
        timeout_seconds=timeout_seconds,
    )
    search_options = bootstrap.get("search_options") if isinstance(bootstrap.get("search_options"), dict) else {}
    normalized_search_params = _clean_search_params(search_params)
    requested_term_codes = term_codes
    if not requested_term_codes:
        term_from_params = str(search_params.get("TERM") or search_params.get("term") or "").strip() if isinstance(search_params, dict) else ""
        if term_from_params:
            requested_term_codes = [term_from_params]
    class_search_main_url = str(
        (bootstrap.get("urls") or {}).get("classSearch")
        if isinstance(bootstrap.get("urls"), dict)
        else DEFAULT_CLASS_SEARCH_MAIN_URL
    )
    if not class_search_main_url:
        class_search_main_url = bootstrap.get("class_search_main_url") or DEFAULT_CLASS_SEARCH_MAIN_URL
    class_search_main_url = _class_search_main_url(str(class_search_main_url))
    class_search_api_url = _class_search_api_url(class_search_main_url)
    selected_term_codes = select_term_codes(search_options, requested_term_codes, term_count)
    term_desc_by_code = _term_desc_map(search_options)
    search_fields = _search_field_definitions(search_options)

    rows: List[Dict[str, Any]] = []
    term_summaries: List[Dict[str, Any]] = []
    seen = set()
    for code in selected_term_codes:
        term_data = fetch_all_classes_for_term(
            api_url=class_search_api_url,
            institution_code=institution_code,
            term_code=code,
            enrl_stat=enrl_stat,
            subject=subject,
            search_params=normalized_search_params,
            timeout_seconds=timeout_seconds,
        )
        term_desc = term_desc_by_code.get(code) or code
        for cls in term_data.get("classes", []):
            if not isinstance(cls, dict):
                continue
            row = _normalize_course_row(
                cls=cls,
                institution_code=institution_code,
                term_code=code,
                term_desc=term_desc,
                source_url=class_search_api_url,
            )
            if not row:
                continue
            dkey = (
                str(row.get("term_code") or ""),
                str(row.get("class_nbr") or ""),
                str(row.get("course_key") or ""),
                str(row.get("section") or ""),
            )
            if dkey in seen:
                continue
            seen.add(dkey)
            rows.append(row)
        term_summaries.append(
            {
                "term_code": code,
                "term_desc": term_desc,
                "page_count": term_data.get("page_count"),
                "class_count": term_data.get("class_count"),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "institution_code": institution_code,
        "class_search_main_url": class_search_main_url,
        "class_search_api_url": class_search_api_url,
        "enrl_stat": enrl_stat,
        "subject_filter": subject,
        "search_params": normalized_search_params,
        "search_fields": search_fields,
        "term_codes": selected_term_codes,
        "term_summaries": term_summaries,
        "row_count": len(rows),
        "rows": rows,
    }
