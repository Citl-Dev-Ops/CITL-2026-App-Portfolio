import csv
import html
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

import requests

SEARCHABLE_SUFFIXES = {
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".pdf",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".epub",
    ".gsheet",
    ".url",
}


def is_searchable_file(path: Path) -> bool:
    return path.suffix.lower() in SEARCHABLE_SUFFIXES


def extract_text(path: Path, max_chars: Optional[int] = None) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    text = ""
    try:
        if ext in (".txt", ".md"):
            text = p.read_text(encoding="utf-8", errors="ignore")
        elif ext in (".csv", ".tsv"):
            text = _read_delimited(p, delimiter="," if ext == ".csv" else "\t")
        elif ext == ".pdf":
            text = _read_pdf(p)
        elif ext in (".xlsx", ".xlsm"):
            text = _read_xlsx(p)
        elif ext == ".xls":
            text = _read_xls(p)
        elif ext == ".epub":
            text = _read_epub(p)
        elif ext in (".gsheet", ".url"):
            text = _read_google_sheet_link_file(p)
    except Exception:
        text = ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if max_chars and max_chars > 0 and len(text) > max_chars:
        return text[:max_chars]
    return text


def _read_delimited(path: Path, delimiter: str = ",") -> str:
    out: List[str] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        rdr = csv.reader(f, delimiter=delimiter)
        for row in rdr:
            out.append("\t".join(str(c) for c in row))
    return "\n".join(out)


def _read_pdf(path: Path) -> str:
    # Optional python path first.
    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(str(path))
        parts = []
        for pg in reader.pages:
            t = pg.extract_text() or ""
            if t:
                parts.append(t)
        if parts:
            return "\n\n".join(parts)
    except Exception:
        pass

    # System fallback.
    try:
        p = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="ignore",
            check=False,
        )
        if p.returncode == 0 and p.stdout:
            return p.stdout
    except Exception:
        pass
    return ""


def _read_xlsx(path: Path) -> str:
    # Preferred: openpyxl if available.
    try:
        import openpyxl  # type: ignore

        wb = openpyxl.load_workbook(filename=str(path), read_only=True, data_only=True)
        lines: List[str] = []
        for ws in wb.worksheets:
            lines.append(f"[Sheet] {ws.title}")
            for row in ws.iter_rows(values_only=True):
                vals = ["" if v is None else str(v) for v in row]
                if any(v.strip() for v in vals):
                    lines.append("\t".join(vals))
        wb.close()
        if lines:
            return "\n".join(lines)
    except Exception:
        pass

    # Fallback: parse Office Open XML directly.
    try:
        return _read_xlsx_via_xml(path)
    except Exception:
        return ""


def _read_xlsx_via_xml(path: Path) -> str:
    import xml.etree.ElementTree as ET

    ns = {
        "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    shared: List[str] = []
    lines: List[str] = []

    with zipfile.ZipFile(path, "r") as zf:
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(".//s:si", ns):
                txt = "".join(t.text or "" for t in si.findall(".//s:t", ns)).strip()
                shared.append(txt)

        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in zf.namelist():
            rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in rel_root:
                rid = rel.attrib.get("Id")
                target = rel.attrib.get("Target")
                if rid and target:
                    rels[rid] = target.lstrip("/")

        for sheet in wb.findall(".//s:sheet", ns):
            sname = sheet.attrib.get("name", "Sheet")
            rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rels.get(rid or "", "")
            if not target:
                continue
            if not target.startswith("xl/"):
                target = "xl/" + target
            if target not in zf.namelist():
                continue
            lines.append(f"[Sheet] {sname}")
            ws = ET.fromstring(zf.read(target))
            for row in ws.findall(".//s:row", ns):
                vals: List[str] = []
                for c in row.findall("s:c", ns):
                    ctype = c.attrib.get("t", "")
                    if ctype == "inlineStr":
                        tnode = c.find("s:is/s:t", ns)
                        vals.append((tnode.text or "").strip() if tnode is not None else "")
                        continue
                    v = c.find("s:v", ns)
                    if v is None or v.text is None:
                        vals.append("")
                        continue
                    raw = v.text
                    if ctype == "s":
                        try:
                            idx = int(raw)
                            vals.append(shared[idx] if 0 <= idx < len(shared) else raw)
                        except Exception:
                            vals.append(raw)
                    else:
                        vals.append(raw)
                if any(x.strip() for x in vals):
                    lines.append("\t".join(vals))

    return "\n".join(lines)


def _read_xls(path: Path) -> str:
    # pandas can read legacy xls if xlrd is installed in environment.
    try:
        import pandas as pd  # type: ignore

        xls = pd.ExcelFile(path)
        lines: List[str] = []
        for sheet in xls.sheet_names:
            lines.append(f"[Sheet] {sheet}")
            df = xls.parse(sheet, dtype=str, header=None)
            for row in df.itertuples(index=False):
                vals = ["" if v is None else str(v) for v in row]
                if any(v.strip() for v in vals):
                    lines.append("\t".join(vals))
        if lines:
            return "\n".join(lines)
    except Exception:
        pass

    # Last fallback: binary strings extraction.
    try:
        p = subprocess.run(
            ["strings", "-a", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="ignore",
            check=False,
        )
        if p.returncode == 0 and p.stdout:
            return p.stdout
    except Exception:
        pass
    return ""


def _read_epub(path: Path) -> str:
    # Optional high-level parser.
    try:
        from ebooklib import epub  # type: ignore
        from ebooklib import ITEM_DOCUMENT  # type: ignore

        book = epub.read_epub(str(path))
        parts: List[str] = []
        for item in book.get_items():
            if item.get_type() != ITEM_DOCUMENT:
                continue
            data = item.get_content().decode("utf-8", errors="ignore")
            text = _strip_html(data)
            if text:
                parts.append(text)
        if parts:
            return "\n\n".join(parts)
    except Exception:
        pass

    # Fallback: parse zipped XHTML/HTML documents.
    try:
        parts: List[str] = []
        with zipfile.ZipFile(path, "r") as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
            for name in names:
                try:
                    raw = zf.read(name).decode("utf-8", errors="ignore")
                except Exception:
                    continue
                text = _strip_html(raw)
                if text:
                    parts.append(text)
        return "\n\n".join(parts)
    except Exception:
        return ""


def _strip_html(s: str) -> str:
    t = re.sub(r"(?is)<script.*?>.*?</script>", " ", s)
    t = re.sub(r"(?is)<style.*?>.*?</style>", " ", t)
    t = re.sub(r"(?is)<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


def _read_google_sheet_link_file(path: Path) -> str:
    url = _extract_url_from_link_file(path)
    if not url:
        return ""
    csv_url = _google_sheet_csv_url(url)
    if not csv_url:
        return ""
    try:
        r = requests.get(csv_url, timeout=30)
        if r.status_code >= 400 or not r.text:
            return ""
        # Parse CSV from response to normalize separators.
        f = io.StringIO(r.text)
        rdr = csv.reader(f)
        rows = ["\t".join(str(c) for c in row) for row in rdr]
        return "\n".join(rows)
    except Exception:
        return ""


def _extract_url_from_link_file(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    ext = path.suffix.lower()
    if ext == ".gsheet":
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                u = obj.get("url") or obj.get("doc_url")
                return str(u or "").strip()
        except Exception:
            pass
    # Windows .url and generic text fallback.
    m = re.search(r"(?im)^\s*URL\s*=\s*(\S+)\s*$", raw)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"https?://\S+", raw)
    return (m2.group(0).strip() if m2 else "")


def _google_sheet_csv_url(url: str) -> str:
    if not url:
        return ""
    try:
        u = urlparse(url)
    except Exception:
        return ""
    if "docs.google.com" not in (u.netloc or ""):
        return ""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", u.path or "")
    if not m:
        return ""
    sheet_id = m.group(1)
    qs = parse_qs(u.query or "")
    gid = (qs.get("gid") or [""])[0]
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        base += f"&gid={gid}"
    return base
