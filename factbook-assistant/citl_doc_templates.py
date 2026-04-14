#!/usr/bin/env python3
"""
citl_doc_templates.py
Template definitions, per-section LLM prompts, and Ollama model detection
for the CITL Document Composer.
"""
from __future__ import annotations

import base64
import http.client
import json
import queue
import re
import threading
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ollama model detection
# ---------------------------------------------------------------------------
OLLAMA_HOST = "localhost"
OLLAMA_PORT = 11434


def _param_float(details: dict) -> float:
    """Parse '14.8B' -> 14.8, '70B' -> 70.0, etc."""
    ps = details.get("parameter_size", "")
    m = re.search(r"([\d.]+)", str(ps))
    return float(m.group(1)) if m else 0.0


def _looks_vision_model(name: str, details: dict) -> bool:
    """Best-effort heuristic for vision-capable Ollama models."""
    text = " ".join(
        [
            str(name or ""),
            str(details.get("family", "")),
            " ".join(str(x) for x in (details.get("families") or [])),
            " ".join(str(x) for x in (details.get("capabilities") or [])),
        ]
    ).lower()
    vision_tokens = (
        "llava", "bakllava", "vision", "moondream",
        "qwen2-vl", "qwen2.5-vl", "qwen2.5vl",
        "minicpm-v", "internvl", "glm-4v",
    )
    if any(tok in text for tok in vision_tokens):
        return True
    return "clip" in text


def get_ollama_models() -> List[dict]:
    """
    Return all installed Ollama models sorted best-first.
    Rank: parameter count desc -> blob size desc -> modified_at desc.
    Each dict: {name, size_mb, params, display}.
    """
    try:
        conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=4)
        conn.request("GET", "/api/tags")
        resp = conn.getresponse()
        data = json.loads(resp.read())
    except Exception:
        return []

    models = []
    for m in data.get("models", []):
        details = m.get("details", {})
        params = _param_float(details)
        size_mb = m.get("size", 0) // (1024 * 1024)
        is_vision = _looks_vision_model(m.get("name", ""), details)
        display = f"{m['name']} ({params}B - {size_mb:,} MB)"
        if is_vision:
            display += "  [vision]"
        models.append({
            "name": m["name"],
            "params": params,
            "size_mb": size_mb,
            "is_vision": is_vision,
            "display": display,
            "modified_at": m.get("modified_at", ""),
        })

    models.sort(
        key=lambda x: (x["params"], x["size_mb"], x["modified_at"]),
        reverse=True,
    )
    return models


def get_best_model() -> Optional[str]:
    models = get_ollama_models()
    return models[0]["name"] if models else None


def get_best_vision_model() -> Optional[str]:
    for m in get_ollama_models():
        if m.get("is_vision"):
            return m["name"]
    return None


# ---------------------------------------------------------------------------
# Streaming generation
# ---------------------------------------------------------------------------
_SYSTEM = (
    "You are a professional technical writer producing documentation for CITL "
    "(Center for Information Technology and Learning) software applications.\n"
    "Audience: college students, instructors, and IT staff.\n"
    "Style: clear, authoritative, and accessible like a published software manual.\n"
    "IMPORTANT FORMATTING RULES:\n"
    "  - Write plain prose only, no markdown syntax.\n"
    "  - Do not use asterisks, pound signs, backticks, or underscores for formatting.\n"
    "  - Separate paragraphs with a blank line.\n"
    "  - For numbered steps write: 1. Description of step\n"
    "  - For nested GUI steps write: 1.1 Sub-step and 1.1.1 Deep sub-step\n"
    "  - For bullet points write: - Item text\n"
    "  - For GUI paths write: Menu Path: File > Export > Word (.docx)\n"
    "  - After each major procedural cluster include:\n"
    "    SCREENSHOT: concise description of what should be visible.\n"
    "  - Begin callouts with: TIP: NOTE: or WARNING:\n"
    "  - If screenshot evidence is provided, infer labels/buttons/dialogs and align steps to it.\n"
    "  - Do not start your response with 'Sure' or 'Of course'; begin directly.\n"
)


def _encode_images_base64(image_paths: List[str]) -> List[str]:
    """Load image files and return base64 strings for Ollama multimodal input."""
    out: List[str] = []
    for raw in image_paths[:6]:
        if not raw:
            continue
        try:
            with open(raw, "rb") as fh:
                data = fh.read()
            if not data:
                continue
            if len(data) > 8 * 1024 * 1024:
                continue
            out.append(base64.b64encode(data).decode("ascii"))
        except Exception:
            continue
    return out


def _is_image_support_error(msg: str) -> bool:
    low = (msg or "").lower()
    return (
        "vision" in low
        or "image" in low
        or "multimodal" in low
        or "does not support" in low
        or "unsupported" in low
    )


def stream_generate(
    model: str,
    section_prompt: str,
    meta: dict,
    token_cb: Callable[[str], None],
    done_cb: Callable[[bool, str], None],
    image_paths: Optional[List[str]] = None,
    system_override: Optional[str] = None,
) -> None:
    """
    Non-blocking: starts a thread that streams Ollama tokens.
    token_cb(token_str) called for each token on the caller's thread via queue.
    done_cb(success, error_msg) called when complete.
    Uses a queue - caller must poll with stream_poll().
    Returns the queue for polling.
    """
    q: queue.Queue = queue.Queue()

    def _stream_once(image_payload: Optional[List[str]]) -> None:
        payload = {
            "model": model,
            "system": system_override if system_override else _SYSTEM,
            "prompt": _fill_prompt(section_prompt, meta),
            "stream": True,
        }
        if image_payload:
            payload["images"] = image_payload
        body = json.dumps(payload).encode("utf-8")
        conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=240)
        conn.request("POST", "/api/generate", body,
                     {"Content-Type": "application/json"})
        resp = conn.getresponse()
        if resp.status >= 400:
            err = resp.read().decode("utf-8", "ignore")
            raise RuntimeError(f"Ollama HTTP {resp.status}: {err}")
        for raw in resp:
            if not raw:
                continue
            obj = json.loads(raw.decode("utf-8", "ignore"))
            if obj.get("error"):
                raise RuntimeError(str(obj.get("error")))
            tok = obj.get("response", "")
            if tok:
                q.put(("token", tok))
            if obj.get("done"):
                return

    def _run():
        images = _encode_images_base64(image_paths or [])
        try:
            _stream_once(images if images else None)
            q.put(("done", None))
        except Exception as exc:
            # Fallback: if image input was rejected, retry as text-only.
            if images and _is_image_support_error(str(exc)):
                try:
                    q.put(("token", "\nNOTE: Attached screenshots were ignored because the selected model is not vision-capable.\n\n"))
                    _stream_once(None)
                    q.put(("done", None))
                    return
                except Exception as retry_exc:
                    q.put(("error", str(retry_exc)))
                    return
            q.put(("error", str(exc)))

    threading.Thread(target=_run, daemon=True).start()
    return q


def _fill_prompt(template: str, meta: dict) -> str:
    """Replace {app_name}, {version}, {topic}, {author} placeholders."""
    for key, val in meta.items():
        template = template.replace(f"{{{key}}}", str(val) if val else "")
    return template


# ---------------------------------------------------------------------------
# Template definitions
# Each section:
#   id       - unique key
#   title    - display + document heading
#   prompt   - LLM instruction (supports {app_name}, {version}, {topic}, {author})
#   required - always included (False = optional, shown but can be deleted)
# ---------------------------------------------------------------------------

def _make_section(sid, title, prompt, required=True):
    return {"id": sid, "title": title, "prompt": prompt,
            "required": required, "content": ""}


_INTRO_PROMPT = (
    "Write a professional Introduction section for a technical manual about {app_name}.\n"
    "Topic context: {topic}\n"
    "Cover: what the application does, who it is designed for, and what the reader "
    "will be able to accomplish after reading this document.\n"
    "Length: 2-3 focused paragraphs."
)

_REQUIREMENTS_PROMPT = (
    "Write a System Requirements section for {app_name} version {version}.\n"
    "Topic context: {topic}\n"
    "List: operating system, hardware minimums, software dependencies (Python, Ollama, "
    "FFmpeg if applicable), and network requirements.\n"
    "Present as a clear bulleted list followed by a brief paragraph."
)

_INSTALL_PROMPT = (
    "Write a complete Installation section for {app_name} version {version}.\n"
    "Topic context: {topic}\n"
    "UI goal: {ui_goal}\n"
    "Screenshot evidence notes: {screenshot_notes}\n"
    "Attached screenshots: {screenshot_count}\n"
    "Cover: downloading or locating the installer, running it on Windows 10/11, "
    "first-launch verification. Number each step clearly.\n"
    "Include one NOTE about common pitfalls (UAC, antivirus, or PATH issues).\n"
    "Use nested step numbering (1, 1.1, 1.1.1), explicit menu paths, and "
    "SCREENSHOT lines after each major step cluster."
)

_CONFIG_PROMPT = (
    "Write a Configuration section for {app_name}.\n"
    "Topic context: {topic}\n"
    "UI goal: {ui_goal}\n"
    "Screenshot evidence notes: {screenshot_notes}\n"
    "Attached screenshots: {screenshot_count}\n"
    "Describe the main settings the user should review after installation: "
    "model selection, file paths, theme, and any feature toggles.\n"
    "Use nested step numbering, explicit menu paths, SCREENSHOT lines, "
    "and NOTE callouts where appropriate."
)

_USAGE_PROMPT = (
    "Write a comprehensive Usage Guide section for {app_name}.\n"
    "Topic context: {topic}\n"
    "UI goal: {ui_goal}\n"
    "Screenshot evidence notes: {screenshot_notes}\n"
    "Attached screenshots: {screenshot_count}\n"
    "Walk the reader through the primary workflow step-by-step: launching, "
    "navigating the interface, performing the main task, and saving or exporting results.\n"
    "Include nested step numbering, explicit menu paths, and SCREENSHOT lines "
    "after each major step cluster.\n"
    "Include a TIP on best practices and a WARNING about any data-loss risk."
)

_FEATURES_PROMPT = (
    "Write a Feature Reference section for {app_name}.\n"
    "Topic context: {topic}\n"
    "List and briefly describe each major feature or tab in the application. "
    "Use a heading for each feature group followed by a short paragraph."
)

_TROUBLESHOOT_PROMPT = (
    "Write a Troubleshooting section for {app_name}.\n"
    "Topic context: {topic}\n"
    "List at least five common problems a user may encounter, with a clear "
    "Problem / Cause / Solution structure for each entry."
)

_FAQ_PROMPT = (
    "Write an FAQ (Frequently Asked Questions) section for {app_name}.\n"
    "Topic context: {topic}\n"
    "Provide at least six Q&A pairs covering installation questions, "
    "common usage questions, and offline/network questions.\n"
    "Format as:  Q: question text   followed by   A: answer text."
)

_LICENSE_PROMPT = (
    "Write a License and Credits section for {app_name} version {version}.\n"
    "Author: {author}\n"
    "State that the software is developed by CITL (Center for Information Technology "
    "and Learning). Mention that it uses Ollama (MIT license) and Python (PSF license). "
    "Include a brief acknowledgments paragraph."
)

_OBJECTIVES_PROMPT = (
    "Write a Learning Objectives section for a training tutorial about {app_name}.\n"
    "Topic: {topic}\n"
    "List 4-6 measurable objectives using Bloom's Taxonomy action verbs "
    "(identify, demonstrate, configure, apply, evaluate).\n"
    "Follow the list with a one-paragraph overview of the tutorial structure."
)

_BACKGROUND_PROMPT = (
    "Write a Background and Context section for a training tutorial about {app_name}.\n"
    "Topic: {topic}\n"
    "Explain the problem this tool solves, relevant concepts the learner needs, "
    "and why this skill matters for IT/LLMOps career readiness.\n"
    "2-3 paragraphs, accessible to a first-year college student."
)

_EXERCISES_PROMPT = (
    "Write a Practice Exercises section for a training tutorial about {app_name}.\n"
    "Topic: {topic}\n"
    "Create three hands-on exercises of increasing difficulty. "
    "Each exercise: title, objective, step-by-step instructions, and expected outcome."
)

_TAKEAWAYS_PROMPT = (
    "Write a Key Takeaways section for a training tutorial about {app_name}.\n"
    "Topic: {topic}\n"
    "Summarize 5-7 key lessons from the tutorial as a bulleted list. "
    "Follow with a paragraph suggesting next steps and further learning resources."
)

_PREREQUISITES_PROMPT = (
    "Write a Prerequisites section for a walkthrough guide for {app_name}.\n"
    "Topic: {topic}\n"
    "List what the reader needs to have installed, configured, or know before "
    "starting this walkthrough. Use a bulleted checklist format."
)

_WALKTHROUGH_PROMPT = (
    "Write the main Walkthrough Steps section for {app_name}.\n"
    "Topic: {topic}\n"
    "UI goal: {ui_goal}\n"
    "Screenshot evidence notes: {screenshot_notes}\n"
    "Attached screenshots: {screenshot_count}\n"
    "Provide a detailed step-by-step walkthrough with nested numbering "
    "(1, 1.1, 1.1.1) for menu diving. "
    "Each step should describe exactly what to click, type, or observe. "
    "For each major step cluster include:\n"
    "Menu Path: A > B > C\n"
    "Expected Result: concise outcome\n"
    "SCREENSHOT: what should be visible\n"
    "Include TIP callouts for useful shortcuts and NOTE callouts for important observations."
)

_NEXT_STEPS_PROMPT = (
    "Write a Next Steps and Further Reading section for a walkthrough guide about {app_name}.\n"
    "Topic: {topic}\n"
    "Suggest 3-5 logical follow-on tasks or topics the reader can explore. "
    "Mention related CITL tools where relevant."
)

_OVERVIEW_QREF_PROMPT = (
    "Write a concise Application Overview for a quick reference card about {app_name}.\n"
    "Topic: {topic}\n"
    "Maximum 4 sentences. Focus on the single core purpose and top three capabilities."
)

_COMMANDS_QREF_PROMPT = (
    "Write a Key Commands and Shortcuts section for a quick reference card for {app_name}.\n"
    "Topic: {topic}\n"
    "List the most important keyboard shortcuts, button actions, and command-line "
    "options as a two-column table (Action | How to do it).\n"
    "Use plain text table format:  Action  |  Method"
)

_TIPS_QREF_PROMPT = (
    "Write a Tips and Warnings section for a quick reference card for {app_name}.\n"
    "Topic: {topic}\n"
    "Provide 4 tips and 2 warnings that experienced users find most valuable. "
    "Keep each item to one or two sentences."
)

_CHECKLIST_PROMPT = (
    "Write a Pre-Installation Checklist for {app_name} version {version}.\n"
    "List each item the installer must verify before running the installer. "
    "Format as a bulleted checklist: - [ ] item description"
)

_VERIFY_PROMPT = (
    "Write a Post-Installation Verification section for {app_name} version {version}.\n"
    "Topic: {topic}\n"
    "UI goal: {ui_goal}\n"
    "Screenshot evidence notes: {screenshot_notes}\n"
    "Attached screenshots: {screenshot_count}\n"
    "Describe 3-5 tests the user should perform to confirm successful installation: "
    "launch the app, check a key feature, verify connectivity to Ollama, etc.\n"
    "Use explicit menu paths, Expected Result lines, and SCREENSHOT lines."
)

_SCREENSHOT_MAP_PROMPT = (
    "Write a Screenshot Evidence Map section for {app_name}.\n"
    "Topic: {topic}\n"
    "UI goal: {ui_goal}\n"
    "Screenshot evidence notes: {screenshot_notes}\n"
    "Attached screenshots: {screenshot_count}\n"
    "Purpose: reserve numbered screenshot slots so trainers can paste CITL-relevant "
    "captures after generation.\n"
    "Format requirements:\n"
    "1. Use top-level numbered entries for each major step cluster.\n"
    "2. Under each entry include:\n"
    "   Menu Path: A > B > C\n"
    "   Expected Result: concise outcome\n"
    "   SCREENSHOT: concise capture description\n"
    "3. Provide at least 6 entries for walkthrough-style documents.\n"
    "4. Ensure each SCREENSHOT line describes exactly what should be visible."
)

_UNINSTALL_PROMPT = (
    "Write an Uninstallation section for {app_name}.\n"
    "Describe how to cleanly remove the application from Windows 10/11, "
    "including removing the virtual environment, registry entries (if any), "
    "and leftover data folders."
)


TEMPLATES: Dict[str, List[dict]] = {

    "Technical Manual": [
        _make_section("cover",        "Cover Page",           "",               True),
        _make_section("intro",        "1. Introduction",      _INTRO_PROMPT),
        _make_section("requirements", "2. System Requirements",_REQUIREMENTS_PROMPT),
        _make_section("install",      "3. Installation",      _INSTALL_PROMPT),
        _make_section("config",       "4. Configuration",     _CONFIG_PROMPT),
        _make_section("usage",        "5. Usage Guide",       _USAGE_PROMPT),
        _make_section("screenshot_map", "6. Screenshot Evidence Map", _SCREENSHOT_MAP_PROMPT),
        _make_section("features",     "7. Feature Reference", _FEATURES_PROMPT),
        _make_section("troubleshoot", "8. Troubleshooting",   _TROUBLESHOOT_PROMPT),
        _make_section("faq",          "9. FAQ",               _FAQ_PROMPT),
        _make_section("license",      "10. License & Credits", _LICENSE_PROMPT),
    ],

    "App Walkthrough": [
        _make_section("cover",        "Cover Page",         "",                   True),
        _make_section("prereqs",      "Prerequisites",      _PREREQUISITES_PROMPT),
        _make_section("walkthrough",  "Step-by-Step Walkthrough", _WALKTHROUGH_PROMPT),
        _make_section("screenshot_map", "Screenshot Evidence Map", _SCREENSHOT_MAP_PROMPT),
        _make_section("troubleshoot", "Common Issues",      _TROUBLESHOOT_PROMPT),
        _make_section("next_steps",   "Next Steps",         _NEXT_STEPS_PROMPT),
    ],

    "Training Tutorial": [
        _make_section("cover",       "Cover Page",          "",                  True),
        _make_section("objectives",  "Learning Objectives", _OBJECTIVES_PROMPT),
        _make_section("background",  "Background & Context",_BACKGROUND_PROMPT),
        _make_section("walkthrough", "Step-by-Step Instructions", _WALKTHROUGH_PROMPT),
        _make_section("screenshot_map", "Screenshot Evidence Map", _SCREENSHOT_MAP_PROMPT),
        _make_section("exercises",   "Practice Exercises",  _EXERCISES_PROMPT),
        _make_section("takeaways",   "Key Takeaways",       _TAKEAWAYS_PROMPT),
        _make_section("next_steps",  "Additional Resources",_NEXT_STEPS_PROMPT),
    ],

    "Quick Reference Card": [
        _make_section("cover",    "Cover Page",         "",                  True),
        _make_section("overview", "App Overview",       _OVERVIEW_QREF_PROMPT),
        _make_section("commands", "Key Commands",       _COMMANDS_QREF_PROMPT),
        _make_section("tips",     "Tips & Warnings",    _TIPS_QREF_PROMPT),
        _make_section("screenshot_map", "Screenshot Evidence Map", _SCREENSHOT_MAP_PROMPT),
    ],

    "Installation Guide": [
        _make_section("cover",      "Cover Page",                "",                True),
        _make_section("prereqs",    "Prerequisites",             _PREREQUISITES_PROMPT),
        _make_section("checklist",  "Pre-Installation Checklist",_CHECKLIST_PROMPT),
        _make_section("install",    "Installation Steps",        _INSTALL_PROMPT),
        _make_section("verify",     "Post-Installation Verification", _VERIFY_PROMPT),
        _make_section("screenshot_map", "Screenshot Evidence Map", _SCREENSHOT_MAP_PROMPT),
        _make_section("troubleshoot","Troubleshooting",          _TROUBLESHOOT_PROMPT),
        _make_section("uninstall",  "Uninstallation",            _UNINSTALL_PROMPT),
    ],
}

# ──────────────────────────────────────────────────────────────────────────────
#  Grant / Proposal  and  State Policy Brief  templates
# ──────────────────────────────────────────────────────────────────────────────

_GRANT_SYSTEM = (
    "You are a professional grant writer and workforce-development policy author "
    "producing institutional documents for a Washington State community college.\n"
    "Audience: state education officials, grant reviewers, and technology agency "
    "representatives who may not have deep IT backgrounds.\n"
    "Style: authoritative, evidence-based, clearly structured — like a published "
    "policy report or federal grant application.\n"
    "IMPORTANT FORMATTING RULES:\n"
    "  - Write plain prose only. No markdown symbols (no *, #, `, _).\n"
    "  - Separate paragraphs with a blank line.\n"
    "  - For bullet points write: - Item text\n"
    "  - For two-column tables write: Column A | Column B on each row, "
    "    with a separator row of dashes after the header.\n"
    "  - Begin callouts with: NOTE: or IMPORTANT:\n"
    "  - Do not start your response with 'Sure' or 'Of course'; begin directly.\n"
    "  - Avoid jargon — when a technical term is unavoidable, define it on first use.\n"
)

def _mg(sid, title, prompt, required=True):
    """Make a grant section with its own system prompt override."""
    s = _make_section(sid, title, prompt, required)
    s["system_prompt"] = _GRANT_SYSTEM
    return s


# ── Section prompts ───────────────────────────────────────────────────────────

_GRANT_EXEC_SUMMARY = (
    "Write an Executive Summary for a state grant proposal titled '{topic}'.\n"
    "Organization: {author}\n"
    "The summary must cover in 3-4 paragraphs:\n"
    "1. What the program is and its primary purpose.\n"
    "2. The specific workforce problem it addresses (use the phrase 'credential bifurcation' "
    "if relevant, and explain it in plain language).\n"
    "3. Why this approach is uniquely positioned to serve community college students "
    "(offline-first, no licensing fees, USB-portable).\n"
    "4. A brief statement of the funding request and intended outcomes.\n"
    "Write for a reader who may spend 90 seconds on this page before deciding to read further."
)

_GRANT_WORKFORCE_PROBLEM = (
    "Write a 'Workforce Problem and Context' section for a grant proposal about '{topic}'.\n"
    "Organization: {author}\n"
    "This section should:\n"
    "1. Explain the widening gap between AI-adjacent IT skills that employers demand "
    "and the credentials most community college graduates hold.\n"
    "2. Describe the 'credential bifurcation' occurring in IT labor markets: "
    "routine IT tasks being automated while AI-augmented IT roles are growing.\n"
    "3. Reference relevant labor market indicators for Washington State "
    "(ESD tech sector reports, CompTIA workforce data, LinkedIn/Indeed trends).\n"
    "4. Explain why four-year universities have adapted to this shift but community "
    "and technical colleges have not yet caught up.\n"
    "5. Explain the equity dimension: CTC students often cannot access cloud AI tools "
    "due to internet, account, or budget barriers.\n"
    "Length: 3-4 substantial paragraphs. Use specific, credible-sounding evidence.\n"
    "Avoid overstatement — frame claims as 'consistent with available data' rather than "
    "absolute facts."
)

_GRANT_SOLUTION_OVERVIEW = (
    "Write a 'Solution Overview' section for a grant proposal about '{topic}'.\n"
    "Organization: {author}\n"
    "Describe the CITL AI Workforce Training Application Suite as a solution to the "
    "workforce problem identified in the previous section.\n"
    "Cover:\n"
    "- What the suite is: a collection of locally-deployed, offline, AI-powered tools\n"
    "- How it is delivered: runs on existing lab hardware, USB-portable, no licenses\n"
    "- The range of skills it trains: from AI model operations to AV/IT support\n"
    "- How it produces portfolio evidence: each tool generates exportable work products\n"
    "- Why it is accessible to all students: offline-first, no accounts, cross-platform\n"
    "Length: 2-3 paragraphs. Use plain language accessible to a non-technical grant reviewer."
)

_GRANT_APP_ENTRY = (
    "Write a program component description for a grant proposal about the following "
    "application: {app_name}.\n"
    "Parent program: {topic}\n"
    "Organization: {author}\n"
    "Structure this entry with the following sub-sections:\n"
    "1. What It Does: 2-3 sentences in plain language, no jargon.\n"
    "2. Skills Trained: a bulleted list of 4-6 professional skills with a brief note "
    "on how the tool trains each.\n"
    "3. Portfolio Output: a bulleted list of 2-4 specific, exportable work products "
    "the student takes away.\n"
    "4. Employer Demand: 1 paragraph connecting these skills to Washington State hiring data "
    "or industry trends.\n"
    "Keep each entry concise but complete — a grant reviewer reading this should be able "
    "to quickly understand the training value."
)

_GRANT_SKILLS_MATRIX = (
    "Write a 'Skills Matrix and Portfolio Summary' section for a grant proposal about '{topic}'.\n"
    "Organization: {author}\n"
    "Produce a clear written summary (not a markdown table — use plain prose) that:\n"
    "1. Lists the 10-12 key skill categories trained across the suite.\n"
    "2. For each category, names which tools train it and characterizes "
    "employer demand in Washington State as 'Very High', 'High', or 'Steady'.\n"
    "3. Explains in a closing paragraph why the suite's portfolio-first design "
    "gives students a competitive advantage over credential-only candidates.\n"
    "Format as a narrative followed by a plain-text two-column reference list:\n"
    "Skill Category | Demand Level"
)

_GRANT_EQUITY = (
    "Write an 'Institutional Equity and Accessibility' section for a grant proposal "
    "about '{topic}'.\n"
    "Organization: {author}\n"
    "This section should address how the program removes technology access barriers for:\n"
    "- Students with unreliable home internet\n"
    "- Students on shared lab machines with restricted internet access\n"
    "- Programs with limited per-student software budgets\n"
    "- Students who need to continue work at home, at libraries, or on personal hardware\n"
    "Explain how USB-portable deployment, offline-first design, cross-platform "
    "compatibility (Windows + Ubuntu), and no-account operation each address these "
    "equity dimensions.\n"
    "Connect to WA State Digital Equity Act where appropriate.\n"
    "Length: 2-3 paragraphs."
)

_GRANT_BUDGET = (
    "Write a 'Budget Justification' section for a grant proposal about '{topic}'.\n"
    "Organization: {author}\n"
    "This suite was developed in-house with no vendor contracts or licensing fees.\n"
    "The primary cost categories are:\n"
    "- Developer / faculty FTE for ongoing tool development and maintenance\n"
    "- Lab hardware upgrades (RAM — local AI models require 16-32 GB)\n"
    "- USB media stock for portable deployment program\n"
    "- Student portfolio hosting (GitHub or institutional git server)\n"
    "- Faculty professional development for tool integration\n"
    "Write a 2-paragraph narrative that:\n"
    "1. Explains why the in-house development model is cost-efficient and sustainable.\n"
    "2. Justifies each cost category in terms of student outcomes.\n"
    "Avoid giving specific dollar amounts — frame in terms of FTE categories and "
    "capital vs. recurring costs."
)

_GRANT_ALIGNMENT = (
    "Write a 'Funding Alignment' section for a grant proposal about '{topic}'.\n"
    "Organization: {author}\n"
    "Map this program to the following funding categories. For each, write 1-2 sentences "
    "explaining the specific alignment:\n"
    "- WIOA Title I (Workforce Innovation and Opportunity Act)\n"
    "- WIOA Title II (Adult Education and Family Literacy)\n"
    "- Carl D. Perkins Career and Technical Education Act\n"
    "- SBCTC Strong Workforce Initiative (Washington State)\n"
    "- Washington State Digital Equity Act\n"
    "- Governor's Office AI Strategy (if applicable)\n"
    "- OSPI K-12 Computer Science Pathway (dual-credit articulation opportunity)\n"
    "Keep language crisp and specific to what this program actually does."
)

_GRANT_CONCLUSION = (
    "Write a Conclusion section for a grant proposal about '{topic}'.\n"
    "Organization: {author}\n"
    "The conclusion should:\n"
    "1. Restate the core problem (credential gap in AI-adjacent IT skills) in 1 sentence.\n"
    "2. Restate the solution (CITL suite: offline, portable, portfolio-producing) in 2 sentences.\n"
    "3. Make a clear, specific call to action for the grant reviewer.\n"
    "4. End with a single memorable closing sentence about the impact on students.\n"
    "Length: 1 substantive paragraph. Do not repeat earlier detail — synthesize and close."
)

_POLICY_BRIEF_OVERVIEW = (
    "Write a one-page Policy Overview for a state technology policy brief about '{topic}'.\n"
    "Organization: {author}\n"
    "Structure:\n"
    "1. The Situation (1 paragraph): what is changing in the IT labor market and why CTCs "
    "are currently not equipped to respond.\n"
    "2. The Opportunity (1 paragraph): what the CITL suite does and what it costs the state "
    "(hint: zero licensing cost).\n"
    "3. The Ask (1 short paragraph): what the institution needs from the state "
    "(funding for FTE, hardware, and faculty development).\n"
    "Write for a legislator or department director who has 3 minutes to read this."
)

_POLICY_BRIEF_EVIDENCE = (
    "Write an 'Evidence and Data' section for a state technology policy brief about '{topic}'.\n"
    "Organization: {author}\n"
    "In 2-3 tight paragraphs, summarize:\n"
    "- Labor market evidence for AI-adjacent IT skill demand in Washington State\n"
    "- The credential gap facing CTC graduates specifically\n"
    "- Evidence that portfolio-based candidates outperform credential-only candidates in "
    "hiring outcomes\n"
    "Cite source types (LinkedIn Workforce Report, CompTIA, WA ESD) without fabricating "
    "specific statistics. Frame as 'consistent with published data' where appropriate."
)

_POLICY_BRIEF_RECOMMENDATIONS = (
    "Write a 'Recommendations' section for a state technology policy brief about '{topic}'.\n"
    "Organization: {author}\n"
    "Provide 4-5 numbered policy recommendations that a state official could act on. "
    "Each recommendation should:\n"
    "- Be specific and actionable\n"
    "- Reference this program or similar in-house AI training initiatives\n"
    "- Note the expected student or workforce outcome\n"
    "Examples might include: funding for faculty AI training, hardware capital grants, "
    "USB deployment program support, dual-credit articulation with K-12.\n"
    "Keep each recommendation to 2-3 sentences."
)


# ── Register templates ────────────────────────────────────────────────────────

TEMPLATES["Grant / Proposal"] = [
    _make_section("cover",       "Cover Page",             "",                   True),
    _mg("exec_summary",  "Executive Summary",      _GRANT_EXEC_SUMMARY),
    _mg("problem",       "Part I — Workforce Problem & Context",
                                                   _GRANT_WORKFORCE_PROBLEM),
    _mg("solution",      "Part II — Solution Overview",
                                                   _GRANT_SOLUTION_OVERVIEW),
    _mg("app_01",        "App 1 — Description",    _GRANT_APP_ENTRY,      False),
    _mg("app_02",        "App 2 — Description",    _GRANT_APP_ENTRY,      False),
    _mg("app_03",        "App 3 — Description",    _GRANT_APP_ENTRY,      False),
    _mg("app_04",        "App 4 — Description",    _GRANT_APP_ENTRY,      False),
    _mg("app_05",        "App 5 — Description",    _GRANT_APP_ENTRY,      False),
    _mg("skills_matrix", "Part III — Skills Matrix & Portfolio Summary",
                                                   _GRANT_SKILLS_MATRIX),
    _mg("equity",        "Part IV — Equity & Accessibility",
                                                   _GRANT_EQUITY),
    _mg("budget",        "Part V — Budget Justification",
                                                   _GRANT_BUDGET),
    _mg("alignment",     "Part VI — Funding Alignment",
                                                   _GRANT_ALIGNMENT),
    _mg("conclusion",    "Conclusion",             _GRANT_CONCLUSION),
]

TEMPLATES["State Policy Brief"] = [
    _make_section("cover",           "Cover Page",          "",                    True),
    _mg("overview",      "Policy Overview",         _POLICY_BRIEF_OVERVIEW),
    _mg("evidence",      "Evidence & Data",         _POLICY_BRIEF_EVIDENCE),
    _mg("app_highlight", "Program Highlights",      _GRANT_APP_ENTRY,      False),
    _mg("equity",        "Equity & Access",         _GRANT_EQUITY),
    _mg("alignment",     "Funding Alignment",       _GRANT_ALIGNMENT),
    _mg("recs",          "Recommendations",         _POLICY_BRIEF_RECOMMENDATIONS),
    _mg("conclusion",    "Conclusion",              _GRANT_CONCLUSION),
]

TEMPLATE_NAMES = list(TEMPLATES.keys())


def get_sections(template_name: str) -> List[dict]:
    """Return a deep copy of the section list for a template."""
    import copy
    return copy.deepcopy(TEMPLATES.get(template_name, []))


