#!/usr/bin/env python3
"""
Build a polished 8.5x11 CITL Workstudy flyer PDF.

Quality gate:
- Final export requires all three screenshots.
- Template export (with placeholders) is allowed for layout review only.
"""

from __future__ import annotations

import argparse
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


PAGE_W = 612.0   # 8.5 in * 72
PAGE_H = 792.0   # 11 in * 72


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _hex_color(rgb: str) -> Tuple[float, float, float]:
    s = rgb.strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"Invalid RGB hex color: {rgb}")
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return (r, g, b)


def _wrap_by_chars(text: str, max_chars: int) -> List[str]:
    return textwrap.wrap(
        text.strip(),
        width=max_chars,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _jpeg_size(path: Path) -> Tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 4 or data[0:2] != b"\xFF\xD8":
        raise ValueError(f"Not a JPEG file: {path}")

    i = 2
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while i + 8 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        while marker == 0xFF and i < len(data):
            marker = data[i]
            i += 1
        if marker in (0xD8, 0xD9):
            continue
        if i + 2 > len(data):
            break
        seg_len = int.from_bytes(data[i:i + 2], "big")
        if seg_len < 2 or i + seg_len > len(data):
            break
        if marker in sof_markers:
            if i + 7 > len(data):
                break
            h = int.from_bytes(data[i + 3:i + 5], "big")
            w = int.from_bytes(data[i + 5:i + 7], "big")
            if w > 0 and h > 0:
                return (w, h)
            break
        i += seg_len
    raise ValueError(f"Could not read JPEG size: {path}")


@dataclass
class JpegImage:
    path: Path
    width: int
    height: int
    data: bytes
    object_id: int = 0
    name: str = ""


class PdfWriter:
    def __init__(self) -> None:
        self.objects: List[bytes] = []

    def add_obj(self, payload: bytes) -> int:
        self.objects.append(payload)
        return len(self.objects)

    def build(self, root_id: int) -> bytes:
        out = bytearray()
        out.extend(b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n")
        offsets = [0]
        for idx, obj in enumerate(self.objects, start=1):
            offsets.append(len(out))
            out.extend(f"{idx} 0 obj\n".encode("ascii"))
            out.extend(obj)
            out.extend(b"\nendobj\n")

        xref_pos = len(out)
        out.extend(f"xref\n0 {len(self.objects) + 1}\n".encode("ascii"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
        out.extend(
            (
                f"trailer\n<< /Size {len(self.objects) + 1} /Root {root_id} 0 R >>\n"
                f"startxref\n{xref_pos}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(out)


def _text_cmd(x: float, y: float, font: str, size: float, text: str) -> str:
    return f"BT /{font} {size:.2f} Tf {x:.2f} {y:.2f} Td ({_esc(text)}) Tj ET"


def _rect_fill_cmd(x: float, y: float, w: float, h: float, rgb: str) -> str:
    r, g, b = _hex_color(rgb)
    return f"{r:.4f} {g:.4f} {b:.4f} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f"


def _rect_stroke_cmd(x: float, y: float, w: float, h: float, rgb: str, lw: float = 1.0) -> str:
    r, g, b = _hex_color(rgb)
    return f"{r:.4f} {g:.4f} {b:.4f} RG {lw:.2f} w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S"


def _draw_image_cmd(
    image_name: str,
    img_w: int,
    img_h: int,
    box_x: float,
    box_y: float,
    box_w: float,
    box_h: float,
) -> str:
    if img_w <= 0 or img_h <= 0:
        return ""
    scale = min(box_w / float(img_w), box_h / float(img_h))
    draw_w = float(img_w) * scale
    draw_h = float(img_h) * scale
    draw_x = box_x + (box_w - draw_w) / 2.0
    draw_y = box_y + (box_h - draw_h) / 2.0
    return (
        f"q {box_x:.2f} {box_y:.2f} {box_w:.2f} {box_h:.2f} re W n "
        f"{draw_w:.2f} 0 0 {draw_h:.2f} {draw_x:.2f} {draw_y:.2f} cm /{image_name} Do Q"
    )


def build_flyer(
    output_pdf: Path,
    screenshots: List[Optional[Path]],
    allow_placeholders: bool,
    publish_tag: str,
) -> None:
    # Final quality gate.
    if not allow_placeholders and any(p is None for p in screenshots):
        raise RuntimeError(
            "Final export blocked: all three screenshots are required. "
            "Use --allow-placeholders only for template review."
        )

    images: List[Optional[JpegImage]] = []
    for p in screenshots:
        if p is None:
            images.append(None)
            continue
        rp = p.expanduser().resolve()
        if not rp.exists():
            raise FileNotFoundError(f"Screenshot not found: {rp}")
        if rp.suffix.lower() not in (".jpg", ".jpeg"):
            raise ValueError(f"Only JPG/JPEG currently supported in this builder: {rp}")
        w, h = _jpeg_size(rp)
        images.append(JpegImage(path=rp, width=w, height=h, data=rp.read_bytes()))

    pdf = PdfWriter()

    # Fonts.
    font_regular_id = pdf.add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold_id = pdf.add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    # Image XObjects.
    for i, img in enumerate(images, start=1):
        if img is None:
            continue
        payload = (
            (
                f"<< /Type /XObject /Subtype /Image /Width {img.width} /Height {img.height} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                f"/Length {len(img.data)} >>\nstream\n"
            ).encode("ascii")
            + img.data
            + b"\nendstream"
        )
        img.object_id = pdf.add_obj(payload)
        img.name = f"Im{i}"

    # Layout.
    ops: List[str] = []
    c_bg = "#f5f7fb"
    c_hero = "#2a0f16"
    c_hero_2 = "#3a1622"
    c_ink = "#10263e"
    c_muted = "#4d5d73"
    c_accent = "#d9a441"
    c_box = "#dce4ef"
    c_line = "#7f94b2"
    c_badge = "#1d3659"

    ops.append(_rect_fill_cmd(0, 0, PAGE_W, PAGE_H, c_bg))
    ops.append(_rect_fill_cmd(0, 724, PAGE_W, 68, c_hero))
    ops.append(_rect_fill_cmd(0, 714, PAGE_W, 10, c_hero_2))
    ops.append(_rect_fill_cmd(0, 708, PAGE_W, 6, c_accent))
    ops.append(_text_cmd(44, 760, "F2", 25, "CITL Workstudy Recruitment Flyer"))
    ops.append(_text_cmd(44, 740, "F1", 11.5, "Human-in-the-Loop LLMOps | Technical Writing | Portfolio Projects"))

    ops.append(_text_cmd(44, 686, "F2", 14, "AI Anxiety Is Real. Uptraining Is the Practical Response."))
    intro_lines = _wrap_by_chars(
        "CITL Workstudy closes the formal training gap by giving students supervised, real-project execution experience "
        "across LLMOps operations, technical communication, and AI quality control workflows.",
        98,
    )
    y = 668.0
    for ln in intro_lines:
        ops.append(_text_cmd(44, y, "F1", 10.5, ln))
        y -= 14

    # Two boxed columns.
    left_x, right_x = 44.0, 320.0
    col_w = 248.0
    box_top = 620.0
    box_h = 150.0
    ops.append(_rect_fill_cmd(left_x, box_top - box_h, col_w, box_h, c_box))
    ops.append(_rect_stroke_cmd(left_x, box_top - box_h, col_w, box_h, c_line, 1.2))
    ops.append(_rect_fill_cmd(right_x, box_top - box_h, col_w, box_h, "#e8edf5"))
    ops.append(_rect_stroke_cmd(right_x, box_top - box_h, col_w, box_h, c_line, 1.2))

    ops.append(_text_cmd(left_x + 12, box_top - 22, "F2", 12, "What Students Build"))
    for i, b in enumerate(
        [
            "Technical walkthrough manuals with evidence mapping",
            "Prompt QA + human verification workflows",
            "Screen recordings + instructional media",
            "Portfolio-ready LLMOps documentation",
        ]
    ):
        ops.append(_text_cmd(left_x + 14, box_top - 44 - (i * 22), "F1", 9.8, f"- {b}"))

    ops.append(_text_cmd(right_x + 12, box_top - 22, "F2", 12, "Career Readiness Outcomes"))
    for i, b in enumerate(
        [
            "Applied AI workflow competency employers can verify",
            "Execution evidence for interviews and portfolios",
            "Hands-on stop-gap for limited formal LLM training",
            "Cross-functional IT + communication capability",
        ]
    ):
        for j, ln in enumerate(_wrap_by_chars(f"- {b}", 36)):
            ops.append(_text_cmd(right_x + 14, box_top - 44 - ((i * 24) + (j * 12)), "F1", 9.4, ln))

    # CTA bar.
    ops.append(_rect_fill_cmd(44, 434, 524, 44, "#eff4fb"))
    ops.append(_rect_stroke_cmd(44, 434, 524, 44, "#4f6f99", 1.4))
    ops.append(_text_cmd(56, 460, "F2", 11.8, "Apply to CITL Workstudy: build practical confidence with supervised real-project AI operations."))
    ops.append(_text_cmd(56, 444, "F1", 9.4, "Default policy: students create and edit their own artifacts; shared originals remain protected."))

    # Screenshot section.
    ops.append(_text_cmd(44, 412, "F2", 13, "Required Numbered Screenshots"))
    shot_specs = [
        ("#1 Program onboarding and application path", 44.0, 250.0),
        ("#2 Active project board and execution flow", 222.0, 250.0),
        ("#3 Before/after walkthrough quality sample", 400.0, 250.0),
    ]
    shot_w = 168.0
    shot_h = 132.0
    for idx, (label, sx, sy) in enumerate(shot_specs, start=1):
        ops.append(_rect_fill_cmd(sx, sy, shot_w, shot_h, "#eef2f8"))
        ops.append(_rect_stroke_cmd(sx, sy, shot_w, shot_h, c_line, 1.2))
        # Badge.
        ops.append(_rect_fill_cmd(sx + 6, sy + shot_h - 24, 22, 18, c_badge))
        ops.append(_text_cmd(sx + 12, sy + shot_h - 20, "F2", 9, str(idx)))
        img = images[idx - 1]
        if img is not None:
            ops.append(_draw_image_cmd(img.name, img.width, img.height, sx + 4, sy + 4, shot_w - 8, shot_h - 30))
        else:
            ops.append(_text_cmd(sx + 14, sy + 62, "F2", 10, "SCREENSHOT REQUIRED"))
            ops.append(_text_cmd(sx + 14, sy + 46, "F1", 8.7, "Provide JPG/JPEG to finalize export"))
        for j, ln in enumerate(_wrap_by_chars(label, 30)):
            ops.append(_text_cmd(sx + 2, sy - 14 - (j * 11), "F1", 8.3, ln))

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    status = "TEMPLATE REVIEW" if allow_placeholders else "FINAL"
    ops.append(_text_cmd(44, 24, "F1", 8.0, f"{publish_tag} | {status} | generated {stamp}"))
    ops.append(_text_cmd(410, 24, "F1", 8.0, "CITL Technical Writing Pipeline"))

    content_data = ("\n".join(ops)).encode("latin-1", errors="replace")
    content_obj = (
        f"<< /Length {len(content_data)} >>\nstream\n".encode("ascii")
        + content_data
        + b"\nendstream"
    )
    content_id = pdf.add_obj(content_obj)

    # Resources.
    xobj_entries = []
    for img in images:
        if img is not None:
            xobj_entries.append(f"/{img.name} {img.object_id} 0 R")
    xobj_text = "<< " + " ".join(xobj_entries) + " >>" if xobj_entries else "<< >>"
    resources = (
        f"<< /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> "
        f"/XObject {xobj_text} >>"
    )

    page_id = pdf.add_obj(
        (
            f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 {int(PAGE_W)} {int(PAGE_H)}] "
            f"/Resources {resources} /Contents {content_id} 0 R >>"
        ).encode("ascii")
    )
    pages_id = pdf.add_obj(f"<< /Type /Pages /Kids [{page_id} 0 R] /Count 1 >>".encode("ascii"))
    catalog_id = pdf.add_obj(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    # Patch parent reference now that pages object id is known.
    page_payload = (
        (
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {int(PAGE_W)} {int(PAGE_H)}] "
            f"/Resources {resources} /Contents {content_id} 0 R >>"
        ).encode("ascii")
    )
    pdf.objects[page_id - 1] = page_payload

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    output_pdf.write_bytes(pdf.build(catalog_id))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tutorial_projects/citl_workstudy_flyer_8_5x11_polished.pdf")
    ap.add_argument("--s1", default="")
    ap.add_argument("--s2", default="")
    ap.add_argument("--s3", default="")
    ap.add_argument("--allow-placeholders", action="store_true")
    ap.add_argument("--tag", default="CITL Workstudy Campaign")
    args = ap.parse_args()

    shots: List[Optional[Path]] = []
    for raw in (args.s1, args.s2, args.s3):
        txt = (raw or "").strip()
        shots.append(Path(txt) if txt else None)

    build_flyer(
        output_pdf=Path(args.out).expanduser().resolve(),
        screenshots=shots,
        allow_placeholders=bool(args.allow_placeholders),
        publish_tag=args.tag,
    )
    print(Path(args.out).expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

