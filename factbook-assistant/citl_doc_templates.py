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

# â”€â”€ Ollama model detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
    Rank: parameter count desc â†’ blob size desc â†’ modified_at desc.
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
        display = f"{m['name']}  ({params}B  ·  {size_mb:,} MB)"
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


# â”€â”€ Streaming generation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
) -> None:
    """
    Non-blocking: starts a thread that streams Ollama tokens.
    token_cb(token_str) called for each token on the caller's thread via queue.
    done_cb(success, error_msg) called when complete.
    Uses a queue â€” caller must poll with stream_poll().
    Returns the queue for polling.
    """
    q: queue.Queue = queue.Queue()

    def _stream_once(image_payload: Optional[List[str]]) -> None:
        payload = {
            "model": model,
            "system": _SYSTEM,
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


# â”€â”€ Template definitions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Each section:
#   id       â€” unique key
#   title    â€” display + document heading
#   prompt   â€” LLM instruction (supports {app_name}, {version}, {topic}, {author})
#   required â€” always included (False = optional, shown but can be deleted)

def _make_section(sid, title, prompt, required=True):
    return {"id": sid, "title": title, "prompt": prompt,
            "required": required, "content": ""}


_INTRO_PROMPT = (
    "Write a professional Introduction section for a technical manual about {app_name}.\n"
    "Topic context: {topic}\n"
    "Cover: what the application does, who it is designed for, and what the reader "
    "will be able to accomplish after reading this document.\n"
    "Length: 2â€“3 focused paragraphs."
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
    "List 4â€“6 measurable objectives using Bloom's Taxonomy action verbs "
    "(identify, demonstrate, configure, apply, evaluate).\n"
    "Follow the list with a one-paragraph overview of the tutorial structure."
)

_BACKGROUND_PROMPT = (
    "Write a Background and Context section for a training tutorial about {app_name}.\n"
    "Topic: {topic}\n"
    "Explain the problem this tool solves, relevant concepts the learner needs, "
    "and why this skill matters for IT/LLMOps career readiness.\n"
    "2â€“3 paragraphs, accessible to a first-year college student."
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
    "Summarize 5â€“7 key lessons from the tutorial as a bulleted list. "
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
    "Suggest 3â€“5 logical follow-on tasks or topics the reader can explore. "
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
    "Describe 3â€“5 tests the user should perform to confirm successful installation: "
    "launch the app, check a key feature, verify connectivity to Ollama, etc.\n"
    "Use explicit menu paths, Expected Result lines, and SCREENSHOT lines."
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
        _make_section("features",     "6. Feature Reference", _FEATURES_PROMPT),
        _make_section("troubleshoot", "7. Troubleshooting",   _TROUBLESHOOT_PROMPT),
        _make_section("faq",          "8. FAQ",               _FAQ_PROMPT),
        _make_section("license",      "9. License & Credits", _LICENSE_PROMPT),
    ],

    "App Walkthrough": [
        _make_section("cover",        "Cover Page",         "",                   True),
        _make_section("prereqs",      "Prerequisites",      _PREREQUISITES_PROMPT),
        _make_section("walkthrough",  "Step-by-Step Walkthrough", _WALKTHROUGH_PROMPT),
        _make_section("troubleshoot", "Common Issues",      _TROUBLESHOOT_PROMPT),
        _make_section("next_steps",   "Next Steps",         _NEXT_STEPS_PROMPT),
    ],

    "Training Tutorial": [
        _make_section("cover",       "Cover Page",          "",                  True),
        _make_section("objectives",  "Learning Objectives", _OBJECTIVES_PROMPT),
        _make_section("background",  "Background & Context",_BACKGROUND_PROMPT),
        _make_section("walkthrough", "Step-by-Step Instructions", _WALKTHROUGH_PROMPT),
        _make_section("exercises",   "Practice Exercises",  _EXERCISES_PROMPT),
        _make_section("takeaways",   "Key Takeaways",       _TAKEAWAYS_PROMPT),
        _make_section("next_steps",  "Additional Resources",_NEXT_STEPS_PROMPT),
    ],

    "Quick Reference Card": [
        _make_section("cover",    "Cover Page",         "",                  True),
        _make_section("overview", "App Overview",       _OVERVIEW_QREF_PROMPT),
        _make_section("commands", "Key Commands",       _COMMANDS_QREF_PROMPT),
        _make_section("tips",     "Tips & Warnings",    _TIPS_QREF_PROMPT),
    ],

    "Installation Guide": [
        _make_section("cover",      "Cover Page",                "",                True),
        _make_section("prereqs",    "Prerequisites",             _PREREQUISITES_PROMPT),
        _make_section("checklist",  "Pre-Installation Checklist",_CHECKLIST_PROMPT),
        _make_section("install",    "Installation Steps",        _INSTALL_PROMPT),
        _make_section("verify",     "Post-Installation Verification", _VERIFY_PROMPT),
        _make_section("troubleshoot","Troubleshooting",          _TROUBLESHOOT_PROMPT),
        _make_section("uninstall",  "Uninstallation",            _UNINSTALL_PROMPT),
    ],
}

TEMPLATE_NAMES = list(TEMPLATES.keys())


def get_sections(template_name: str) -> List[dict]:
    """Return a deep copy of the section list for a template."""
    import copy
    return copy.deepcopy(TEMPLATES.get(template_name, []))


