"""
CITL Technical Writing and Tutorial Creator
-------------------------------------------
Unified workflow hub for documentation + tutorial production.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
except Exception:
    print("tkinter is required for CITL Technical Writing and Tutorial Creator.")
    sys.exit(1)

try:
    from citl_doc_templates import TEMPLATE_NAMES, get_best_model, get_ollama_models, get_sections
except Exception:
    TEMPLATE_NAMES = []  # type: ignore
    get_best_model = lambda: ""  # type: ignore
    get_ollama_models = lambda: []  # type: ignore
    get_sections = lambda _name: []  # type: ignore


APP_NAME = "CITL Technical Writing and Tutorial Creator"
APP_VERSION = "v0.1"
READONLY_SYNC_DIR_NAME = "onenote_readonly"
ARTICLE_META_NAME = "article_meta.json"

HERE = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    env_repo = os.environ.get("CITL_REPO", "").strip()
    if env_repo and Path(env_repo).is_dir():
        REPO = Path(env_repo)
    else:
        REPO = Path(sys.executable).resolve().parent.parent.parent
else:
    REPO = HERE.parent

WORKSPACES_DIR = REPO / "tutorial_projects"

TOOLS = {
    "doc_composer": REPO / "factbook-assistant" / "citl_doc_composer.py",
    "screen_recorder": REPO / "factbook-assistant" / "citl_screen_recorder.py",
    "video_editor": REPO / "factbook-assistant" / "citl_video_post_editor.py",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}

COLORS = {
    "bg": "#0b1220",
    "panel": "#111c31",
    "card": "#16263f",
    "card_alt": "#0f1a2b",
    "border": "#2e75b6",
    "text": "#e7eef7",
    "muted": "#8ea5c2",
    "accent": "#2e75b6",
    "accent_hi": "#4d8fcc",
}
FONT = "Segoe UI" if sys.platform == "win32" else "Ubuntu"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return slug or "project"


def _open_in_file_manager(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def build_workstudy_flyer_markdown() -> str:
    return (
        "# Join CITL Workstudy: Build Real LLMOps Experience\n\n"
        "## AI Is Changing Hiring. We Help You Prepare, Not Panic.\n\n"
        "Students are feeling growing anxiety about jobs and AI disruption. The reality is nuanced: AI is reshaping roles, and it is also creating new workflows that need people who can guide, verify, secure, and operationalize these systems.\n\n"
        "CITL Workstudy is a practical stop-gap for the formal training gap. Most degree plans still do not include hands-on LLMOps execution, model governance, or human-in-the-loop quality assurance. We do.\n\n"
        "## Why This Matters Right Now\n\n"
        "1. Employers increasingly ask for applied AI workflow competency, not just theory.\n"
        "2. New AI-adjacent job titles are appearing across IT, operations, education technology, analytics, and support.\n"
        "3. Labor outlook sources (including U.S. Bureau of Labor Statistics occupational outlook data) continue to show demand for technology roles where AI-enabled workflows are becoming standard.\n\n"
        "## What You Will Build in CITL\n\n"
        "- Technical walkthrough manuals with screenshot evidence mapping.\n"
        "- Human-in-the-loop QA pipelines for LLM outputs.\n"
        "- CITL app demos, screen recordings, and instructional videos.\n"
        "- Portfolio-ready documentation showing reproducible process quality.\n"
        "- Practical prompt and retrieval workflows tied to real campus tasks.\n\n"
        "## Portfolio Outcomes You Can Show Recruiters\n\n"
        "1. A documented LLMOps workflow from prompt design to verified output.\n"
        "2. A full technical guide with troubleshooting paths and screenshot references.\n"
        "3. A short tutorial video proving communication, execution, and process ownership.\n\n"
        "## The Training Gap Is Real\n\n"
        "Many institutions and employers report that AI tool adoption is moving faster than formal training programs. CITL helps close that gap with supervised, real-project practice that turns uncertainty into demonstrated skill.\n\n"
        "## Who Should Apply\n\n"
        "- Students in IT, education, communications, business, design, and related disciplines.\n"
        "- Students with little AI background but strong reliability and curiosity.\n"
        "- Students who want concrete project evidence, not just certificates.\n\n"
        "## Start Here\n\n"
        "Apply to CITL Workstudy and begin building practical LLMOps confidence through guided projects, peer collaboration, and publishable deliverables.\n\n"
        "SCREENSHOT #1: Program landing page with application steps.\n"
        "SCREENSHOT #2: Example student project board.\n"
        "SCREENSHOT #3: Sample before/after technical walkthrough output.\n"
    )


class TutorialCreatorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.configure(bg=COLORS["bg"])
        self.root.geometry("1440x920")
        self.root.minsize(1120, 760)

        self.workspace_var = tk.StringVar(value="")
        self.project_title_var = tk.StringVar(value="New CITL Walkthrough")
        self.app_name_var = tk.StringVar(value="CITL App")
        self.current_user = (os.environ.get("USERNAME", "").strip() or os.environ.get("USER", "").strip() or "citl_user")
        self.author_var = tk.StringVar(value=self.current_user or "CITL Author")
        self.audience_var = tk.StringVar(value="Staff and faculty")
        self.available_templates = ["Blank Article"] + [x for x in TEMPLATE_NAMES if x != "Blank Article"]
        self.template_var = tk.StringVar(value="Blank Article")
        self.style_var = tk.StringVar(value="Staff Walkthrough Blue")
        self.model_var = tk.StringVar(value="")
        self.editor_font_var = tk.StringVar(value="Georgia")
        self.editor_size_var = tk.StringVar(value="13")
        self.editor_style_var = tk.StringVar(value="Body")
        self.prompt_addendum_var = tk.StringVar(
            value="Keep it concise, procedural, and suitable for publishing."
        )
        self.onenote_source_var = tk.StringVar(
            value=os.environ.get("CITL_ONENOTE_DB", "").strip()
        )
        self.supervisor_unlocked = False
        self.supervisor_status_var = tk.StringVar(value="Student mode: edit own articles only")
        self.archive_paths: List[Path] = []
        self.archive_index: Dict[str, dict] = {}
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self._bind_shortcuts()
        self._populate_models()
        WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
        self._append_log(f"{APP_NAME} {APP_VERSION}\n")
        self._append_log(f"[REPO] {REPO}\n")

    def _panel(self, parent, *, alt: bool = False):
        return tk.Frame(
            parent,
            bg=COLORS["card_alt" if alt else "card"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
        )

    def _btn(self, parent, text: str, command, *, accent: bool = False):
        bg = COLORS["accent"] if accent else "#233b5d"
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=COLORS["text"],
            activebackground=COLORS["accent_hi"] if accent else "#2f4b73",
            activeforeground=COLORS["text"],
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            font=(FONT, 10, "bold"),
            cursor="hand2",
            wraplength=220,
            justify="center",
        )

    def _build_ui(self) -> None:
        self.root.rowconfigure(2, weight=1)
        self.root.columnconfigure(0, weight=1)

        header = tk.Frame(self.root, bg=COLORS["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        tk.Label(
            header,
            text="CITL Technical Writing and Tutorial Creator",
            bg=COLORS["bg"],
            fg=COLORS["accent"],
            font=(FONT, 22, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="Comprehensive hub for guides, walkthroughs, screenshots, and tutorial video pipelines",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=(FONT, 10),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        top_actions = self._panel(self.root, alt=True)
        top_actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        for c in range(5):
            top_actions.columnconfigure(c, weight=1)
        self._btn(top_actions, "Create Workspace", self.on_create_workspace, accent=True).grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        self._btn(top_actions, "Load Workspace", self.on_load_workspace).grid(row=0, column=1, padx=8, pady=8, sticky="ew")
        self._btn(top_actions, "Save Project", self.on_save_project).grid(row=0, column=2, padx=8, pady=8, sticky="ew")
        self._btn(top_actions, "Open Workspace Folder", self.on_open_workspace).grid(row=0, column=3, padx=8, pady=8, sticky="ew")
        self._btn(top_actions, "Export OneNote Markdown", self.on_export_markdown).grid(row=0, column=4, padx=8, pady=8, sticky="ew")

        body = tk.PanedWindow(self.root, orient="horizontal", sashrelief="flat", bg=COLORS["bg"])
        body.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self._build_left(body)
        self._build_right(body)

        log_panel = self._panel(self.root)
        log_panel.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 14))
        log_panel.rowconfigure(1, weight=1)
        log_panel.columnconfigure(0, weight=1)
        tk.Label(log_panel, text="Activity Log", bg=COLORS["card"], fg=COLORS["accent"], font=(FONT, 11, "bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 4)
        )
        self.log = scrolledtext.ScrolledText(
            log_panel,
            wrap="word",
            bg="#0b1628",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            bd=0,
            font=("Consolas", 9),
        )
        self.log.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        status = tk.Label(
            self.root,
            textvariable=self.status_var,
            bg=COLORS["card"],
            fg=COLORS["text"],
            anchor="w",
            padx=10,
            pady=8,
            font=(FONT, 9),
        )
        status.grid(row=4, column=0, sticky="ew")

    def _meta_row(self, parent, label: str, var: tk.StringVar, row: int) -> None:
        tk.Label(parent, text=label, bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 9, "bold")).grid(
            row=row * 2 - 1, column=0, sticky="w", padx=12, pady=(6, 2)
        )
        ttk.Entry(parent, textvariable=var).grid(row=row * 2, column=0, sticky="ew", padx=12)

    def _build_left(self, body: tk.PanedWindow) -> None:
        left = self._panel(body)
        left.configure(width=360)
        body.add(left, minsize=320)
        left.columnconfigure(0, weight=1)

        tk.Label(left, text="Project Setup", bg=COLORS["card"], fg=COLORS["accent"], font=(FONT, 12, "bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 8)
        )
        self._meta_row(left, "Workspace", self.workspace_var, 1)
        self._meta_row(left, "Project Title", self.project_title_var, 2)
        self._meta_row(left, "App / System", self.app_name_var, 3)
        self._meta_row(left, "Author", self.author_var, 4)
        self._meta_row(left, "Audience", self.audience_var, 5)

        tk.Label(left, text="Template", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 9, "bold")).grid(
            row=11, column=0, sticky="w", padx=12, pady=(10, 2)
        )
        ttk.Combobox(
            left,
            textvariable=self.template_var,
            values=self.available_templates,
            state="readonly",
        ).grid(row=12, column=0, sticky="ew", padx=12)

        tk.Label(left, text="Document Style", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 9, "bold")).grid(
            row=13, column=0, sticky="w", padx=12, pady=(10, 2)
        )
        ttk.Combobox(
            left,
            textvariable=self.style_var,
            values=[
                "Staff Walkthrough Blue",
                "Executive Sans",
                "Humanist Professional",
                "Editorial Modern",
                "Contemporary Clean",
                "CITL Classic",
            ],
            state="readonly",
        ).grid(row=14, column=0, sticky="ew", padx=12)

        tk.Label(left, text="LLM Model (Ollama)", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 9, "bold")).grid(
            row=15, column=0, sticky="w", padx=12, pady=(10, 2)
        )
        self.model_combo = ttk.Combobox(left, textvariable=self.model_var, values=[], state="readonly")
        self.model_combo.grid(row=16, column=0, sticky="ew", padx=12)
        self._btn(left, "Refresh Models", self._populate_models).grid(row=17, column=0, sticky="ew", padx=12, pady=(8, 4))

        toolbox = self._panel(left, alt=True)
        toolbox.grid(row=18, column=0, sticky="ew", padx=12, pady=(12, 12))
        toolbox.columnconfigure(0, weight=1)
        tk.Label(
            toolbox,
            text="Integrated Tools",
            bg=COLORS["card_alt"],
            fg=COLORS["accent"],
            font=(FONT, 10, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 6))
        self._btn(toolbox, "Launch Screen Recorder", self.on_launch_screen_recorder).grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        self._btn(toolbox, "Launch Video Post Editor", self.on_launch_video_editor).grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        self._btn(toolbox, "Launch Document Composer", self.on_launch_doc_composer).grid(row=3, column=0, sticky="ew", padx=10, pady=(4, 10))

    def _build_right(self, body: tk.PanedWindow) -> None:
        right = self._panel(body, alt=True)
        body.add(right, minsize=740)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        nb = ttk.Notebook(right)
        nb.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.tab_notes = tk.Frame(nb, bg=COLORS["card_alt"])
        self.tab_shots = tk.Frame(nb, bg=COLORS["card_alt"])
        self.tab_video = tk.Frame(nb, bg=COLORS["card_alt"])
        self.tab_publish = tk.Frame(nb, bg=COLORS["card_alt"])
        self.tab_archives = tk.Frame(nb, bg=COLORS["card_alt"])
        nb.add(self.tab_notes, text="1) Manuscript")
        nb.add(self.tab_shots, text="2) Screenshots")
        nb.add(self.tab_video, text="3) Video")
        nb.add(self.tab_publish, text="4) Publish")
        nb.add(self.tab_archives, text="5) Archives / OneNote")

        self._build_notes_tab()
        self._build_screenshots_tab()
        self._build_video_tab()
        self._build_publish_tab()
        self._build_archives_tab()

    def _build_notes_tab(self) -> None:
        self.tab_notes.configure(bg="#f3f4f6")
        self.tab_notes.rowconfigure(2, weight=1)
        self.tab_notes.columnconfigure(0, weight=1)

        # Toolbar 1: typography + paragraph controls.
        bar1 = tk.Frame(self.tab_notes, bg="#eef0f3")
        bar1.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        for c in range(15):
            bar1.columnconfigure(c, weight=0)
        for c in (9, 10, 11, 12, 13, 14):
            bar1.columnconfigure(c, weight=1)

        tk.Label(bar1, text="Style", bg="#eef0f3", fg="#4a5568", font=(FONT, 9, "bold")).grid(row=0, column=0, padx=(8, 4), pady=6)
        ttk.Combobox(
            bar1,
            textvariable=self.editor_style_var,
            values=["Body", "Heading 1", "Heading 2", "Heading 3", "Quote", "Code"],
            state="readonly",
            width=12,
        ).grid(row=0, column=1, padx=4, pady=6)
        self._btn(bar1, "Apply", self.on_apply_block_style).grid(row=0, column=2, padx=4, pady=6, sticky="ew")

        tk.Label(bar1, text="Font", bg="#eef0f3", fg="#4a5568", font=(FONT, 9, "bold")).grid(row=0, column=3, padx=(8, 4), pady=6)
        ttk.Combobox(
            bar1,
            textvariable=self.editor_font_var,
            values=["Georgia", "Times New Roman", "Garamond", "Palatino Linotype", "Avenir Next", "Helvetica", "Arial"],
            state="readonly",
            width=16,
        ).grid(row=0, column=4, padx=4, pady=6)
        ttk.Combobox(
            bar1,
            textvariable=self.editor_size_var,
            values=["11", "12", "13", "14", "16", "18", "22", "28", "34"],
            state="readonly",
            width=5,
        ).grid(row=0, column=5, padx=4, pady=6)
        self._btn(bar1, "Set", self.on_apply_body_font).grid(row=0, column=6, padx=4, pady=6, sticky="ew")

        self._btn(bar1, "B", lambda: self._toggle_inline_tag("bold")).grid(row=0, column=7, padx=3, pady=6)
        self._btn(bar1, "I", lambda: self._toggle_inline_tag("italic")).grid(row=0, column=8, padx=3, pady=6)
        self._btn(bar1, "U", lambda: self._toggle_inline_tag("underline")).grid(row=0, column=9, padx=3, pady=6, sticky="ew")
        self._btn(bar1, "Redact", self.on_redact_selection).grid(row=0, column=10, padx=3, pady=6, sticky="ew")
        self._btn(bar1, "Clear Format", self.on_clear_selection_format).grid(row=0, column=11, padx=3, pady=6, sticky="ew")
        self._btn(bar1, "Left", lambda: self.on_apply_alignment("left")).grid(row=0, column=12, padx=3, pady=6, sticky="ew")
        self._btn(bar1, "Center", lambda: self.on_apply_alignment("center")).grid(row=0, column=13, padx=3, pady=6, sticky="ew")
        self._btn(bar1, "Right", lambda: self.on_apply_alignment("right")).grid(row=0, column=14, padx=(3, 8), pady=6, sticky="ew")

        # Toolbar 2: template + LLM controls.
        bar2 = tk.Frame(self.tab_notes, bg="#eef0f3")
        bar2.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        for c in range(9):
            bar2.columnconfigure(c, weight=1)
        tk.Label(bar2, text="Prompt Addendum", bg="#eef0f3", fg="#4a5568", font=(FONT, 9, "bold")).grid(
            row=0, column=0, padx=(8, 4), pady=6, sticky="w"
        )
        ttk.Entry(bar2, textvariable=self.prompt_addendum_var).grid(row=0, column=1, columnspan=3, padx=4, pady=6, sticky="ew")
        self._btn(bar2, "Insert Template Outline", self.on_insert_template_outline).grid(row=0, column=4, padx=4, pady=6, sticky="ew")
        self._btn(bar2, "Auto-Structure", self.on_auto_structure_notes).grid(row=0, column=5, padx=4, pady=6, sticky="ew")
        self._btn(bar2, "LLM Format", self.on_auto_format_with_llm, accent=True).grid(row=0, column=6, padx=4, pady=6, sticky="ew")
        self._btn(bar2, "Save Notes", self.on_save_notes_only).grid(row=0, column=7, padx=4, pady=6, sticky="ew")
        self._btn(bar2, "Save Snapshot", self.on_save_article_snapshot).grid(row=0, column=8, padx=(4, 8), pady=6, sticky="ew")

        # Substack-like centered page canvas.
        page_host = tk.Frame(self.tab_notes, bg="#f3f4f6")
        page_host.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        page_host.rowconfigure(0, weight=1)
        page_host.columnconfigure(0, weight=1)
        page = tk.Frame(
            page_host,
            bg="#ffffff",
            highlightthickness=1,
            highlightbackground="#d8dde6",
            padx=32,
            pady=24,
        )
        page.place(relx=0.5, rely=0.0, relheight=1.0, relwidth=0.72, anchor="n")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)

        self.notes_text = scrolledtext.ScrolledText(
            page,
            wrap="word",
            bg="#ffffff",
            fg="#1f2937",
            insertbackground="#111827",
            relief="flat",
            bd=0,
            font=("Georgia", 13),
            padx=6,
            pady=6,
            spacing1=4,
            spacing2=2,
            spacing3=8,
        )
        self.notes_text.grid(row=0, column=0, sticky="nsew")
        self._configure_editor_tags()
        self._build_notes_context_menu()
        self.notes_text.bind("<Button-3>", self._show_notes_context_menu)
        self.notes_text.bind("<Control-Button-1>", self._show_notes_context_menu)
        self.notes_text.insert(
            "1.0",
            "# Start Writing\n\n"
            "This blank article mode uses serif-first publishing defaults.\n"
            "Use the toolbar for headings, paragraph styling, redaction, and LLM refinement.\n",
        )
        self.notes_text.tag_add("body", "1.0", "end-1c")

    def _build_screenshots_tab(self) -> None:
        self.tab_shots.rowconfigure(1, weight=1)
        self.tab_shots.columnconfigure(0, weight=1)
        actions = tk.Frame(self.tab_shots, bg=COLORS["card_alt"])
        actions.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        for c in range(6):
            actions.columnconfigure(c, weight=1)
        self._btn(actions, "Import Screenshot Files", self.on_import_screenshots, accent=True).grid(row=0, column=0, padx=4, sticky="ew")
        self._btn(actions, "Import Clipboard Path", self.on_import_clipboard_path).grid(row=0, column=1, padx=4, sticky="ew")
        self._btn(actions, "Reindex Numbering", self.on_reindex_screenshots).grid(row=0, column=2, padx=4, sticky="ew")
        self._btn(actions, "Open Screenshot Folder", self.on_open_screenshot_folder).grid(row=0, column=3, padx=4, sticky="ew")
        self._btn(actions, "Insert Placeholder", self.on_insert_selected_screenshot_placeholder).grid(row=0, column=4, padx=4, sticky="ew")
        self._btn(actions, "Refresh List", self.refresh_screenshot_list).grid(row=0, column=5, padx=4, sticky="ew")

        self.screenshot_list = tk.Listbox(
            self.tab_shots,
            bg="#0f1d33",
            fg=COLORS["text"],
            selectbackground=COLORS["accent_hi"],
            relief="flat",
            bd=0,
            font=("Consolas", 10),
        )
        self.screenshot_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.screenshot_list.bind("<Double-Button-1>", lambda _e: self.on_insert_selected_screenshot_placeholder())
        self._build_screenshot_context_menu()
        self.screenshot_list.bind("<Button-3>", self._show_screenshot_context_menu)

    def _build_video_tab(self) -> None:
        self.tab_video.columnconfigure(0, weight=1)
        tk.Label(
            self.tab_video,
            text=(
                "Record -> Edit -> Export workflow:\n"
                "1) Launch Screen Recorder to capture only the target app window.\n"
                "2) Launch Video Post Editor for text boxes, arrows, circles, underlines, fades.\n"
                "3) Export final tutorial clip for LMS / OneNote / handout linking."
            ),
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            justify="left",
            wraplength=900,
            font=(FONT, 10),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(14, 10))
        controls = tk.Frame(self.tab_video, bg=COLORS["card_alt"])
        controls.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        for c in range(3):
            controls.columnconfigure(c, weight=1)
        self._btn(controls, "Launch Screen Recorder", self.on_launch_screen_recorder, accent=True).grid(row=0, column=0, padx=6, sticky="ew")
        self._btn(controls, "Launch Video Post Editor", self.on_launch_video_editor).grid(row=0, column=1, padx=6, sticky="ew")
        self._btn(controls, "Open Recordings Folder", self.on_open_recordings_folder).grid(row=0, column=2, padx=6, sticky="ew")

    def _build_publish_tab(self) -> None:
        self.tab_publish.columnconfigure(0, weight=1)
        tk.Label(
            self.tab_publish,
            text=(
                "Publishing outputs from the same workspace:\n"
                "- OneNote-ready markdown article\n"
                "- Structured seed for CITL Document Composer\n"
                "- Organized screenshot set and recordings for attachments"
            ),
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            justify="left",
            wraplength=900,
            font=(FONT, 10),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(14, 8))
        controls = tk.Frame(self.tab_publish, bg=COLORS["card_alt"])
        controls.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        for c in range(4):
            controls.columnconfigure(c, weight=1)
        self._btn(controls, "Export OneNote Markdown", self.on_export_markdown, accent=True).grid(row=0, column=0, padx=5, sticky="ew")
        self._btn(controls, "Save Project Manifest", self.on_save_project).grid(row=0, column=1, padx=5, sticky="ew")
        self._btn(controls, "Launch Document Composer", self.on_launch_doc_composer).grid(row=0, column=2, padx=5, sticky="ew")
        self._btn(controls, "Open Exports Folder", self.on_open_exports_folder).grid(row=0, column=3, padx=5, sticky="ew")
        self._btn(self.tab_publish, "Generate CITL Workstudy Flyer Draft", self.on_generate_workstudy_flyer, accent=True).grid(
            row=2, column=0, sticky="ew", padx=12, pady=(4, 10)
        )

    def _build_archives_tab(self) -> None:
        self.tab_archives.rowconfigure(1, weight=1)
        self.tab_archives.columnconfigure(0, weight=1)

        top = tk.Frame(self.tab_archives, bg=COLORS["card_alt"])
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        for c in range(8):
            top.columnconfigure(c, weight=1)
        tk.Label(
            top,
            text="OneNote Source (Read-Only)",
            bg=COLORS["card_alt"],
            fg=COLORS["muted"],
            font=(FONT, 9, "bold"),
        ).grid(row=0, column=0, padx=(0, 6), pady=4, sticky="w")
        ttk.Entry(top, textvariable=self.onenote_source_var).grid(row=0, column=1, columnspan=3, padx=4, pady=4, sticky="ew")
        self._btn(top, "Browse", self.on_pick_onenote_source).grid(row=0, column=4, padx=4, pady=4, sticky="ew")
        self._btn(top, "Sync Read-Only", self.on_sync_onenote_readonly, accent=True).grid(row=0, column=5, padx=4, pady=4, sticky="ew")
        self._btn(top, "Refresh", self.refresh_archive_list).grid(row=0, column=6, padx=4, pady=4, sticky="ew")
        self._btn(top, "Open Mirror", self.on_open_onenote_mirror).grid(row=0, column=7, padx=4, pady=4, sticky="ew")

        tk.Label(
            top,
            textvariable=self.supervisor_status_var,
            bg=COLORS["card_alt"],
            fg="#d6e3f5",
            font=(FONT, 9, "bold"),
        ).grid(row=1, column=0, columnspan=4, padx=(0, 6), pady=(2, 6), sticky="w")
        self._btn(top, "Supervisor Unlock", self.on_request_supervisor_unlock).grid(row=1, column=4, padx=4, pady=(2, 6), sticky="ew")
        self._btn(top, "Lock", self.on_lock_supervisor).grid(row=1, column=5, padx=4, pady=(2, 6), sticky="ew")
        self._btn(top, "Save Snapshot", self.on_save_article_snapshot).grid(row=1, column=6, padx=4, pady=(2, 6), sticky="ew")
        self._btn(top, "Load Selected", self.on_load_selected_archive_to_editor).grid(row=1, column=7, padx=4, pady=(2, 6), sticky="ew")

        main = tk.PanedWindow(self.tab_archives, orient="horizontal", sashrelief="flat", bg=COLORS["card_alt"])
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        left = tk.Frame(main, bg=COLORS["card_alt"])
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        tk.Label(left, text="Past Articles", bg=COLORS["card_alt"], fg=COLORS["accent"], font=(FONT, 10, "bold")).grid(
            row=0, column=0, sticky="w", padx=2, pady=(2, 6)
        )
        self.archive_list = tk.Listbox(
            left,
            bg="#0f1d33",
            fg=COLORS["text"],
            selectbackground=COLORS["accent_hi"],
            relief="flat",
            bd=0,
            font=("Consolas", 9),
        )
        self.archive_list.grid(row=1, column=0, sticky="nsew")
        self.archive_list.bind("<<ListboxSelect>>", lambda _e: self.on_archive_selection_changed())
        self.archive_list.bind("<Double-Button-1>", lambda _e: self.on_load_selected_archive_to_editor())
        self._build_archive_context_menu()
        self.archive_list.bind("<Button-3>", self._show_archive_context_menu)
        main.add(left, minsize=320)

        right = tk.Frame(main, bg=COLORS["card_alt"])
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        tk.Label(right, text="Preview (Read-Only)", bg=COLORS["card_alt"], fg=COLORS["accent"], font=(FONT, 10, "bold")).grid(
            row=0, column=0, sticky="w", padx=2, pady=(2, 6)
        )
        self.archive_preview = scrolledtext.ScrolledText(
            right,
            wrap="word",
            bg="#09101d",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            bd=0,
            font=("Consolas", 10),
        )
        self.archive_preview.grid(row=1, column=0, sticky="nsew")
        self.archive_preview.configure(state="disabled")
        main.add(right, minsize=420)

    def _bind_shortcuts(self) -> None:
        def _cmd(fn):
            def _wrapped(_event=None):
                fn()
                return "break"
            return _wrapped

        self.root.bind_all("<Control-b>", _cmd(lambda: self._toggle_inline_tag("bold")))
        self.root.bind_all("<Control-i>", _cmd(lambda: self._toggle_inline_tag("italic")))
        self.root.bind_all("<Control-u>", _cmd(lambda: self._toggle_inline_tag("underline")))
        self.root.bind_all("<Control-s>", _cmd(self.on_save_notes_only))
        self.root.bind_all("<Control-Shift-S>", _cmd(self.on_save_article_snapshot))
        self.root.bind_all("<Control-l>", _cmd(lambda: self.on_apply_alignment("left")))
        self.root.bind_all("<Control-e>", _cmd(lambda: self.on_apply_alignment("center")))
        self.root.bind_all("<Control-r>", _cmd(lambda: self.on_apply_alignment("right")))

    def _build_notes_context_menu(self) -> None:
        self.notes_menu = tk.Menu(self.root, tearoff=0)
        self.notes_menu.add_command(label="Cut", command=lambda: self.notes_text.event_generate("<<Cut>>"))
        self.notes_menu.add_command(label="Copy", command=lambda: self.notes_text.event_generate("<<Copy>>"))
        self.notes_menu.add_command(label="Paste", command=lambda: self.notes_text.event_generate("<<Paste>>"))
        self.notes_menu.add_separator()
        self.notes_menu.add_command(label="Bold", command=lambda: self._toggle_inline_tag("bold"))
        self.notes_menu.add_command(label="Italic", command=lambda: self._toggle_inline_tag("italic"))
        self.notes_menu.add_command(label="Underline", command=lambda: self._toggle_inline_tag("underline"))
        self.notes_menu.add_command(label="Redact Selection", command=self.on_redact_selection)
        self.notes_menu.add_separator()
        self.notes_menu.add_command(label="Insert Screenshot Placeholder", command=self.on_insert_selected_screenshot_placeholder)
        self.notes_menu.add_command(label="Auto-Structure", command=self.on_auto_structure_notes)
        self.notes_menu.add_command(label="LLM Format", command=self.on_auto_format_with_llm)
        self.notes_menu.add_separator()
        self.notes_menu.add_command(label="Save Notes", command=self.on_save_notes_only)
        self.notes_menu.add_command(label="Save Snapshot", command=self.on_save_article_snapshot)

    def _show_notes_context_menu(self, event) -> str:
        try:
            self.notes_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.notes_menu.grab_release()
        return "break"

    def _build_screenshot_context_menu(self) -> None:
        self.screenshot_menu = tk.Menu(self.root, tearoff=0)
        self.screenshot_menu.add_command(label="Open Screenshot", command=self.on_open_selected_screenshot)
        self.screenshot_menu.add_command(label="Insert Placeholder", command=self.on_insert_selected_screenshot_placeholder)
        self.screenshot_menu.add_separator()
        self.screenshot_menu.add_command(label="Delete Screenshot", command=self.on_delete_selected_screenshot)

    def _show_screenshot_context_menu(self, event) -> str:
        try:
            idx = self.screenshot_list.nearest(event.y)
            if idx >= 0:
                self.screenshot_list.selection_clear(0, "end")
                self.screenshot_list.selection_set(idx)
            self.screenshot_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.screenshot_menu.grab_release()
        return "break"

    def _build_archive_context_menu(self) -> None:
        self.archive_menu = tk.Menu(self.root, tearoff=0)
        self.archive_menu.add_command(label="Preview", command=self.on_archive_selection_changed)
        self.archive_menu.add_command(label="Open File", command=self.on_open_selected_archive_file)
        self.archive_menu.add_command(label="Load to Manuscript", command=self.on_load_selected_archive_to_editor)
        self.archive_menu.add_command(label="Create Editable Draft Copy", command=self.on_create_draft_from_archive)

    def _show_archive_context_menu(self, event) -> str:
        try:
            idx = self.archive_list.nearest(event.y)
            if idx >= 0:
                self.archive_list.selection_clear(0, "end")
                self.archive_list.selection_set(idx)
            self.archive_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.archive_menu.grab_release()
        return "break"

    def _configure_editor_tags(self) -> None:
        t = self.notes_text
        t.tag_configure("body", font=(self.editor_font_var.get(), int(self.editor_size_var.get() or "13")), foreground="#1f2937")
        t.tag_configure("h1", font=("Georgia", 32, "bold"), spacing1=22, spacing3=14, foreground="#111827")
        t.tag_configure("h2", font=("Georgia", 24, "bold"), spacing1=18, spacing3=10, foreground="#1f2937")
        t.tag_configure("h3", font=("Georgia", 18, "bold"), spacing1=14, spacing3=8, foreground="#1f2937")
        t.tag_configure("quote", font=("Georgia", 13, "italic"), lmargin1=28, lmargin2=28, foreground="#4b5563")
        t.tag_configure("code", font=("Consolas", 11), background="#f3f4f6", foreground="#111827")
        t.tag_configure("bold", font=(self.editor_font_var.get(), int(self.editor_size_var.get() or "13"), "bold"))
        t.tag_configure("italic", font=(self.editor_font_var.get(), int(self.editor_size_var.get() or "13"), "italic"))
        t.tag_configure("underline", underline=True)
        t.tag_configure("align_left", justify="left")
        t.tag_configure("align_center", justify="center")
        t.tag_configure("align_right", justify="right")
        t.tag_configure("redacted", foreground="#111111", background="#111111")
        for high in ("h1", "h2", "h3", "quote", "code", "bold", "italic", "underline", "redacted", "align_left", "align_center", "align_right"):
            t.tag_raise(high, "body")

    def _selected_range(self) -> Optional[tuple]:
        t = self.notes_text
        try:
            return t.index("sel.first"), t.index("sel.last")
        except Exception:
            return None

    def _line_range_from_selection(self) -> tuple:
        rng = self._selected_range()
        t = self.notes_text
        if rng is None:
            cur = t.index("insert linestart")
            return cur, t.index("insert lineend")
        return t.index(f"{rng[0]} linestart"), t.index(f"{rng[1]} lineend")

    def _toggle_inline_tag(self, tag: str) -> None:
        rng = self._selected_range()
        if rng is None:
            return
        t = self.notes_text
        start, end = rng
        if tag in t.tag_names("sel.first"):
            t.tag_remove(tag, start, end)
        else:
            t.tag_add(tag, start, end)

    def on_apply_body_font(self) -> None:
        self._configure_editor_tags()
        self.notes_text.tag_add("body", "1.0", "end-1c")

    def on_apply_block_style(self) -> None:
        style = self.editor_style_var.get().strip()
        t = self.notes_text
        start, end = self._line_range_from_selection()
        for block_tag in ("h1", "h2", "h3", "quote", "code"):
            t.tag_remove(block_tag, start, end)
        if style == "Heading 1":
            t.tag_add("h1", start, end)
        elif style == "Heading 2":
            t.tag_add("h2", start, end)
        elif style == "Heading 3":
            t.tag_add("h3", start, end)
        elif style == "Quote":
            t.tag_add("quote", start, end)
        elif style == "Code":
            t.tag_add("code", start, end)
        else:
            t.tag_add("body", start, end)

    def on_apply_alignment(self, align: str) -> None:
        t = self.notes_text
        start, end = self._line_range_from_selection()
        for tag in ("align_left", "align_center", "align_right"):
            t.tag_remove(tag, start, end)
        if align == "center":
            t.tag_add("align_center", start, end)
        elif align == "right":
            t.tag_add("align_right", start, end)
        else:
            t.tag_add("align_left", start, end)

    def on_redact_selection(self) -> None:
        rng = self._selected_range()
        if rng is None:
            self.messagebox_info("No selection", "Select text to redact.")
            return
        self.notes_text.tag_add("redacted", rng[0], rng[1])

    def on_clear_selection_format(self) -> None:
        rng = self._selected_range()
        if rng is None:
            return
        start, end = rng
        for tag in ("h1", "h2", "h3", "quote", "code", "bold", "italic", "underline", "redacted", "align_left", "align_center", "align_right"):
            self.notes_text.tag_remove(tag, start, end)
        self.notes_text.tag_add("body", start, end)

    def _template_sections(self, template_name: str) -> List[str]:
        if not template_name or template_name == "Blank Article":
            return []
        out: List[str] = []
        for sec in (get_sections(template_name) or []):
            if not isinstance(sec, dict):
                continue
            title = str(sec.get("title") or "").strip()
            if title:
                out.append(title)
        return out

    def _build_template_outline(self, template_name: str) -> str:
        if template_name == "Blank Article":
            return (
                "# Title\n\n"
                "## Subtitle\n\n"
                "Lead paragraph.\n\n"
                "## Section 1\n\n"
                "Body text.\n\n"
                "## Section 2\n\n"
                "Body text.\n"
            )
        sections = self._template_sections(template_name)
        lines: List[str] = [f"# {self.project_title_var.get().strip() or template_name}", ""]
        for title in sections:
            lines.append(f"## {title}")
            lines.append("")
            lines.append("Write section content...")
            lines.append("")
        if not sections:
            lines.extend(["## Overview", "", "Write section content...", ""])
        return "\n".join(lines).strip() + "\n"

    def on_insert_template_outline(self) -> None:
        tpl = self.template_var.get().strip()
        outline = self._build_template_outline(tpl)
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", outline)
        self.notes_text.tag_add("body", "1.0", "end-1c")

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _workspace_path(self) -> Optional[Path]:
        raw = self.workspace_var.get().strip()
        if not raw:
            return None
        return Path(raw).expanduser()

    def _screenshot_dir(self) -> Optional[Path]:
        ws = self._workspace_path()
        if not ws:
            return None
        return ws / "screenshots"

    def _exports_dir(self) -> Optional[Path]:
        ws = self._workspace_path()
        if not ws:
            return None
        return ws / "exports"

    def _notes_path(self) -> Optional[Path]:
        ws = self._workspace_path()
        if not ws:
            return None
        return ws / "notes.md"

    def _articles_dir(self) -> Optional[Path]:
        ws = self._workspace_path()
        if not ws:
            return None
        return ws / "articles"

    def _article_meta_path(self) -> Optional[Path]:
        d = self._articles_dir()
        if not d:
            return None
        return d / ARTICLE_META_NAME

    def _onenote_mirror_dir(self) -> Optional[Path]:
        ws = self._workspace_path()
        if not ws:
            return None
        return ws / "third_party" / READONLY_SYNC_DIR_NAME

    def _populate_models(self) -> None:
        try:
            models = list(get_ollama_models() or [])
            best = str(get_best_model() or "").strip()
        except Exception:
            models = []
            best = ""
        if best and best not in models:
            models.insert(0, best)
        if not models:
            models = ["(no local Ollama models detected)"]
        self.model_combo.configure(values=models)
        if best:
            self.model_var.set(best)
        elif models:
            self.model_var.set(models[0])

    def on_create_workspace(self) -> None:
        title = self.project_title_var.get().strip() or "CITL Walkthrough"
        slug = _slugify(title)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ws = WORKSPACES_DIR / f"{slug}_{ts}"
        try:
            (ws / "screenshots").mkdir(parents=True, exist_ok=True)
            (ws / "exports").mkdir(parents=True, exist_ok=True)
            (ws / "articles").mkdir(parents=True, exist_ok=True)
            (ws / "third_party").mkdir(parents=True, exist_ok=True)
            self.workspace_var.set(str(ws))
            self._set_status(f"Workspace created: {ws}")
            self._append_log(f"[WORKSPACE] created {ws}\n")
            self.on_save_project()
            self.refresh_archive_list()
        except Exception as exc:
            self.messagebox_error("Workspace error", str(exc))

    def on_load_workspace(self) -> None:
        picked = filedialog.askdirectory(
            title="Select tutorial workspace",
            initialdir=str(WORKSPACES_DIR),
            mustexist=True,
        )
        if not picked:
            return
        ws = Path(picked).expanduser()
        self.workspace_var.set(str(ws))
        self._append_log(f"[WORKSPACE] loaded {ws}\n")
        self._set_status(f"Workspace loaded: {ws}")
        self._load_project_manifest()
        self._load_notes_file()
        self.refresh_screenshot_list()
        self.refresh_archive_list()

    def on_open_workspace(self) -> None:
        ws = self._workspace_path()
        if not ws:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        ws.mkdir(parents=True, exist_ok=True)
        _open_in_file_manager(ws)

    def on_open_screenshot_folder(self) -> None:
        d = self._screenshot_dir()
        if not d:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        d.mkdir(parents=True, exist_ok=True)
        _open_in_file_manager(d)

    def on_open_exports_folder(self) -> None:
        d = self._exports_dir()
        if not d:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        d.mkdir(parents=True, exist_ok=True)
        _open_in_file_manager(d)

    def on_open_recordings_folder(self) -> None:
        rec = REPO / "recordings"
        rec.mkdir(parents=True, exist_ok=True)
        _open_in_file_manager(rec)

    def on_save_notes_only(self) -> None:
        p = self._notes_path()
        if not p:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.notes_text.get("1.0", "end").strip() + "\n", encoding="utf-8")
        self._append_log(f"[NOTES] saved {p}\n")
        self._set_status("Notes saved")

    def on_save_project(self) -> None:
        ws = self._workspace_path()
        if not ws:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "screenshots").mkdir(parents=True, exist_ok=True)
        (ws / "exports").mkdir(parents=True, exist_ok=True)
        (ws / "articles").mkdir(parents=True, exist_ok=True)
        (ws / "third_party").mkdir(parents=True, exist_ok=True)
        payload = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "saved_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "project_title": self.project_title_var.get().strip(),
            "app_name": self.app_name_var.get().strip(),
            "author": self.author_var.get().strip(),
            "audience": self.audience_var.get().strip(),
            "template": self.template_var.get().strip(),
            "doc_style": self.style_var.get().strip(),
            "model": self.model_var.get().strip(),
        }
        try:
            (ws / "project.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.on_save_notes_only()
            self.refresh_screenshot_list()
            self.refresh_archive_list()
            self._append_log(f"[PROJECT] saved {ws / 'project.json'}\n")
            self._set_status("Project saved")
        except Exception as exc:
            self.messagebox_error("Save failed", str(exc))

    def _load_project_manifest(self) -> None:
        ws = self._workspace_path()
        if not ws:
            return
        path = ws / "project.json"
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            self.project_title_var.set(str(raw.get("project_title") or self.project_title_var.get()))
            self.app_name_var.set(str(raw.get("app_name") or self.app_name_var.get()))
            self.author_var.set(str(raw.get("author") or self.author_var.get()))
            self.audience_var.set(str(raw.get("audience") or self.audience_var.get()))
            self.template_var.set(str(raw.get("template") or self.template_var.get()))
            self.style_var.set(str(raw.get("doc_style") or self.style_var.get()))
            model = str(raw.get("model") or "").strip()
            if model:
                self.model_var.set(model)
        except Exception:
            pass

    def _load_notes_file(self) -> None:
        p = self._notes_path()
        if not p or not p.exists():
            return
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            self.notes_text.delete("1.0", "end")
            self.notes_text.insert("1.0", text)
            self.notes_text.tag_add("body", "1.0", "end-1c")
            self._append_log(f"[NOTES] loaded {p}\n")
        except Exception:
            pass

    def refresh_screenshot_list(self) -> None:
        self.screenshot_list.delete(0, "end")
        d = self._screenshot_dir()
        if not d or not d.exists():
            return
        files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        files.sort(key=lambda p: p.name.lower())
        for p in files:
            self.screenshot_list.insert("end", p.name)
        self._set_status(f"Screenshots: {len(files)}")

    def on_import_screenshots(self) -> None:
        d = self._screenshot_dir()
        if not d:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        d.mkdir(parents=True, exist_ok=True)
        picked = filedialog.askopenfilenames(
            title="Select screenshots",
            initialdir=str(d),
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"), ("All files", "*.*")],
        )
        if not picked:
            return
        existing = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        n = len(existing)
        copied = 0
        for raw in picked:
            src = Path(raw)
            if not src.exists() or src.suffix.lower() not in IMAGE_EXTS:
                continue
            n += 1
            dst = d / f"shot_{n:03d}{src.suffix.lower()}"
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception:
                continue
        self.refresh_screenshot_list()
        self._append_log(f"[SHOTS] imported {copied} file(s)\n")

    def on_import_clipboard_path(self) -> None:
        d = self._screenshot_dir()
        if not d:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        try:
            raw = self.root.clipboard_get().strip()
        except Exception:
            raw = ""
        p = Path(raw.strip("\"'")) if raw else Path("")
        if not raw or not p.exists() or not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            self.messagebox_info(
                "Clipboard import",
                "Clipboard does not currently contain a valid image file path.\n"
                "Tip: copy an image file path, then click this button.",
            )
            return
        d.mkdir(parents=True, exist_ok=True)
        existing = [x for x in d.iterdir() if x.is_file() and x.suffix.lower() in IMAGE_EXTS]
        dst = d / f"shot_{len(existing)+1:03d}{p.suffix.lower()}"
        shutil.copy2(p, dst)
        self.refresh_screenshot_list()
        self._append_log(f"[SHOTS] clipboard path imported: {p.name}\n")

    def on_reindex_screenshots(self) -> None:
        d = self._screenshot_dir()
        if not d or not d.exists():
            self.messagebox_info("No screenshots", "No screenshot folder found.")
            return
        files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        files.sort(key=lambda p: p.name.lower())
        temp_map = []
        for i, src in enumerate(files, start=1):
            tmp = d / f"__tmp_reindex_{i:03d}{src.suffix.lower()}"
            src.rename(tmp)
            temp_map.append(tmp)
        for i, tmp in enumerate(temp_map, start=1):
            tmp.rename(d / f"shot_{i:03d}{tmp.suffix.lower()}")
        self.refresh_screenshot_list()
        self._append_log("[SHOTS] screenshot numbering reindexed\n")

    def _selected_screenshot_path(self) -> Optional[Path]:
        d = self._screenshot_dir()
        if not d or not d.exists():
            return None
        idxs = list(self.screenshot_list.curselection())
        if not idxs:
            return None
        name = str(self.screenshot_list.get(idxs[0])).strip()
        if not name:
            return None
        p = d / name
        return p if p.exists() else None

    def on_insert_screenshot_placeholder(self) -> None:
        idx = self.screenshot_list.size() + 1
        self.notes_text.insert("insert", f"\nSCREENSHOT #{idx}: Capture relevant menu state for this step.\n")

    def on_insert_selected_screenshot_placeholder(self) -> None:
        idxs = list(self.screenshot_list.curselection())
        if idxs:
            idx = idxs[0] + 1
            name = str(self.screenshot_list.get(idxs[0])).strip()
            self.notes_text.insert("insert", f"\nSCREENSHOT #{idx} ({name}): Capture relevant menu state for this step.\n")
            return
        self.on_insert_screenshot_placeholder()

    def on_open_selected_screenshot(self) -> None:
        p = self._selected_screenshot_path()
        if not p:
            self.messagebox_info("No selection", "Select a screenshot first.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception:
            _open_in_file_manager(p.parent)
        self._append_log(f"[SHOTS] opened {p.name}\n")

    def on_delete_selected_screenshot(self) -> None:
        p = self._selected_screenshot_path()
        if not p:
            self.messagebox_info("No selection", "Select a screenshot first.")
            return
        if not messagebox.askyesno("Delete screenshot", f"Delete {p.name} from this workspace?", parent=self.root):
            return
        try:
            p.unlink(missing_ok=False)
            self.refresh_screenshot_list()
            self._append_log(f"[SHOTS] deleted {p.name}\n")
        except Exception as exc:
            self.messagebox_error("Delete failed", str(exc))

    def on_auto_structure_notes(self) -> None:
        raw = self.notes_text.get("1.0", "end").strip()
        if not raw:
            return
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        out: List[str] = []
        step = 0
        for ln in lines:
            if ln.startswith("#"):
                out.append(ln)
                continue
            if re.match(r"^\d+[\).:]\s+", ln):
                out.append(ln)
                continue
            if ln.upper().startswith(("NOTE:", "TIP:", "WARNING:")):
                out.append(ln)
                continue
            step += 1
            out.append(f"{step}. {ln}")
            out.append(f"SCREENSHOT #{step}: Capture evidence for step {step}.")
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", "\n".join(out).strip() + "\n")
        self.notes_text.tag_add("body", "1.0", "end-1c")
        self._append_log("[NOTES] auto-structured into numbered walkthrough format\n")

    def _ollama_generate(self, model: str, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
            }
        ).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", 11434, timeout=240)
        conn.request("POST", "/api/generate", payload, {"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        if resp.status >= 400:
            raise RuntimeError(f"Ollama HTTP {resp.status}: {body[:300]}")
        data = json.loads(body)
        if data.get("error"):
            raise RuntimeError(str(data.get("error")))
        return str(data.get("response") or "").strip()

    def on_auto_format_with_llm(self) -> None:
        raw = self.notes_text.get("1.0", "end").strip()
        if not raw:
            self.messagebox_info("No notes", "Paste draft notes first.")
            return
        model = self.model_var.get().strip()
        if not model or model.startswith("(no local"):
            self.messagebox_info("No model", "No local Ollama model detected.")
            return

        self._set_status("LLM formatting in progress...")
        self._append_log(f"[LLM] formatting notes with model: {model}\n")
        app_name = self.app_name_var.get().strip()
        audience = self.audience_var.get().strip()
        template_name = self.template_var.get().strip() or "Blank Article"
        style_name = self.style_var.get().strip() or "Staff Walkthrough Blue"
        template_sections = self._template_sections(template_name)
        addendum = self.prompt_addendum_var.get().strip()

        req_lines = [
            "- Use numbered steps with explicit menu paths.",
            "- Include NOTE/TIP/WARNING callouts when relevant.",
            "- Insert SCREENSHOT #N placeholders after key steps.",
            "- Keep language concise and operational.",
            "- Use clean publishing prose suitable for technical staff guides.",
            f"- App/system: {app_name}",
            f"- Audience: {audience}",
            f"- Style guide target: {style_name}",
            f"- Template selected: {template_name}",
        ]
        if template_sections:
            req_lines.append("- Keep these section headers in the final output:")
            for sec in template_sections:
                req_lines.append(f"  - {sec}")
        if addendum:
            req_lines.append(f"- Additional editor instructions: {addendum}")

        prompt = (
            "Rewrite the following raw notes into a professional technical walkthrough.\n"
            "Requirements:\n"
            + "\n".join(req_lines)
            + "\n\n"
            "Raw notes:\n"
            f"{raw}\n"
        )

        def worker() -> None:
            try:
                out = self._ollama_generate(model, prompt)
                if not out:
                    raise RuntimeError("Model returned empty output.")
            except Exception as exc:
                self.root.after(0, lambda: self._set_status("LLM formatting failed"))
                self.root.after(0, lambda: self._append_log(f"[LLM][ERR] {exc}\n"))
                self.root.after(0, lambda: self.messagebox_error("LLM formatting failed", str(exc)))
                return

            def done() -> None:
                self.notes_text.delete("1.0", "end")
                self.notes_text.insert("1.0", out + "\n")
                self.notes_text.tag_add("body", "1.0", "end-1c")
                self._set_status("LLM formatting complete")
                self._append_log("[LLM] formatting complete\n")

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _load_article_meta(self) -> Dict[str, dict]:
        p = self._article_meta_path()
        if not p or not p.exists():
            return {}
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return {}

    def _save_article_meta(self, payload: Dict[str, dict]) -> None:
        p = self._article_meta_path()
        if not p:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _selected_archive_record(self) -> Optional[dict]:
        if not hasattr(self, "archive_list"):
            return None
        idxs = list(self.archive_list.curselection())
        if not idxs:
            return None
        i = idxs[0]
        if i < 0 or i >= len(self.archive_paths):
            return None
        p = self.archive_paths[i]
        return self.archive_index.get(str(p))

    def _record_editable(self, rec: dict) -> bool:
        if not rec:
            return False
        if rec.get("source") == "onenote":
            return False
        owner_user = str(rec.get("owner_user") or "").strip().lower()
        return self.supervisor_unlocked or owner_user == self.current_user.lower()

    def _set_file_readonly(self, path: Path) -> None:
        try:
            os.chmod(path, stat.S_IREAD)
        except Exception:
            pass

    def on_pick_onenote_source(self) -> None:
        picked = filedialog.askdirectory(
            title="Select OneNote export/source folder",
            initialdir=self.onenote_source_var.get().strip() or str(REPO),
            mustexist=True,
        )
        if not picked:
            return
        self.onenote_source_var.set(str(Path(picked).expanduser()))

    def on_sync_onenote_readonly(self) -> None:
        ws = self._workspace_path()
        if not ws:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        src = Path(self.onenote_source_var.get().strip().strip("\"'")).expanduser()
        if not src.exists() or not src.is_dir():
            self.messagebox_info("OneNote source missing", "Select a valid OneNote source folder first.")
            return
        mirror = self._onenote_mirror_dir()
        if not mirror:
            return
        try:
            if mirror.exists():
                if ws not in mirror.parents:
                    raise RuntimeError("Refusing to clear sync mirror outside workspace.")
                shutil.rmtree(mirror)
            mirror.mkdir(parents=True, exist_ok=True)
            exts = {".md", ".txt", ".rtf", ".docx", ".pdf", ".html", ".htm"}
            copied = 0
            for p in src.rglob("*"):
                if not p.is_file() or p.suffix.lower() not in exts:
                    continue
                rel = p.relative_to(src)
                dst = mirror / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)
                self._set_file_readonly(dst)
                copied += 1
            self._append_log(f"[ONENOTE] synced read-only mirror: {copied} file(s)\n")
            self._set_status(f"OneNote mirror synced: {copied} file(s)")
            self.refresh_archive_list()
        except Exception as exc:
            self.messagebox_error("OneNote sync failed", str(exc))

    def on_open_onenote_mirror(self) -> None:
        mirror = self._onenote_mirror_dir()
        if not mirror:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        mirror.mkdir(parents=True, exist_ok=True)
        _open_in_file_manager(mirror)

    def on_request_supervisor_unlock(self) -> None:
        pin = os.environ.get("CITL_SUPERVISOR_PIN", "").strip()
        if not pin:
            self.messagebox_info(
                "Supervisor PIN not configured",
                "Set env var CITL_SUPERVISOR_PIN to enable supervisor unlock.",
            )
            return
        entered = simpledialog.askstring("Supervisor Unlock", "Enter supervisor PIN:", show="*", parent=self.root)
        if entered is None:
            return
        if entered.strip() != pin:
            self.messagebox_error("Access denied", "Supervisor PIN is incorrect.")
            return
        self.supervisor_unlocked = True
        self.supervisor_status_var.set("Supervisor mode unlocked: edit rights elevated")
        self._append_log("[ACCESS] supervisor override enabled\n")
        self.refresh_archive_list()

    def on_lock_supervisor(self) -> None:
        self.supervisor_unlocked = False
        self.supervisor_status_var.set("Student mode: edit own articles only")
        self._append_log("[ACCESS] supervisor override disabled\n")
        self.refresh_archive_list()

    def on_save_article_snapshot(self) -> None:
        ws = self._workspace_path()
        ad = self._articles_dir()
        if not ws or not ad:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        ad.mkdir(parents=True, exist_ok=True)
        slug = _slugify(self.project_title_var.get().strip() or "article")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = ad / f"{slug}_{ts}.md"
        out.write_text(self._compose_markdown(), encoding="utf-8")
        meta = self._load_article_meta()
        meta[str(out.name)] = {
            "owner_user": self.current_user,
            "owner_name": self.author_var.get().strip() or self.current_user,
            "title": self.project_title_var.get().strip() or out.stem,
            "source": "local",
            "created_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._save_article_meta(meta)
        self._append_log(f"[ARTICLE] snapshot saved: {out.name}\n")
        self._set_status(f"Saved snapshot: {out.name}")
        self.refresh_archive_list()

    def refresh_archive_list(self) -> None:
        if not hasattr(self, "archive_list"):
            return
        self.archive_list.delete(0, "end")
        self.archive_paths = []
        self.archive_index = {}
        ws = self._workspace_path()
        if not ws:
            return
        meta = self._load_article_meta()
        ad = self._articles_dir()
        if ad and ad.exists():
            for p in sorted(ad.glob("*.md"), key=lambda x: x.name.lower()):
                entry = dict(meta.get(p.name) or {})
                entry.setdefault("source", "local")
                entry.setdefault("owner_user", "")
                entry.setdefault("owner_name", "")
                entry.setdefault("title", p.stem)
                entry["path"] = str(p)
                editable = self._record_editable(entry)
                prefix = "[My]" if editable else "[Locked]"
                row = f"{prefix} {p.name}  owner={entry.get('owner_user') or '-'}"
                self.archive_list.insert("end", row)
                self.archive_paths.append(p)
                self.archive_index[str(p)] = entry
        ed = self._exports_dir()
        if ed and ed.exists():
            for p in sorted(ed.glob("*.md"), key=lambda x: x.name.lower()):
                entry = dict(meta.get(p.name) or {})
                entry.setdefault("source", "local")
                entry.setdefault("owner_user", "")
                entry.setdefault("owner_name", "")
                entry.setdefault("title", p.stem)
                entry["path"] = str(p)
                editable = self._record_editable(entry)
                prefix = "[My]" if editable else "[Locked]"
                row = f"{prefix} {p.name}  owner={entry.get('owner_user') or '-'}"
                self.archive_list.insert("end", row)
                self.archive_paths.append(p)
                self.archive_index[str(p)] = entry
        mirror = self._onenote_mirror_dir()
        if mirror and mirror.exists():
            for p in sorted([x for x in mirror.rglob("*") if x.is_file()], key=lambda x: str(x).lower()):
                rel = p.relative_to(mirror)
                entry = {
                    "source": "onenote",
                    "owner_user": "readonly",
                    "owner_name": "OneNote",
                    "title": p.stem,
                    "path": str(p),
                }
                row = f"[OneNote RO] {rel}"
                self.archive_list.insert("end", row)
                self.archive_paths.append(p)
                self.archive_index[str(p)] = entry
        self._set_status(f"Archive items: {len(self.archive_paths)}")

    def on_archive_selection_changed(self) -> None:
        rec = self._selected_archive_record()
        if not rec:
            return
        p = Path(str(rec.get("path") or ""))
        if not p.exists():
            return
        suffix = p.suffix.lower()
        if suffix not in {".md", ".txt", ".log", ".json", ".csv", ".yaml", ".yml", ".html", ".htm", ".rtf"}:
            preview = f"Preview not available for {p.name} ({suffix}).\nUse 'Open File' to view."
        else:
            try:
                preview = p.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                preview = f"Preview load failed: {exc}"
        header = (
            f"Source: {rec.get('source')}\n"
            f"Owner: {rec.get('owner_user') or '-'}\n"
            f"Editable by current user: {'yes' if self._record_editable(rec) else 'no'}\n"
            f"Path: {p}\n"
            + ("-" * 70)
            + "\n"
        )
        self.archive_preview.configure(state="normal")
        self.archive_preview.delete("1.0", "end")
        self.archive_preview.insert("1.0", header + preview[:20000])
        self.archive_preview.configure(state="disabled")

    def on_open_selected_archive_file(self) -> None:
        rec = self._selected_archive_record()
        if not rec:
            self.messagebox_info("No selection", "Select an archive item first.")
            return
        p = Path(str(rec.get("path") or ""))
        if not p.exists():
            self.messagebox_error("Missing file", f"Archive file not found:\n{p}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception:
            _open_in_file_manager(p.parent)

    def _load_text_into_editor(self, text: str, title_hint: str = "") -> None:
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", text)
        self.notes_text.tag_add("body", "1.0", "end-1c")
        if title_hint:
            self.project_title_var.set(title_hint)
        self._set_status("Loaded article into manuscript editor")

    def on_load_selected_archive_to_editor(self) -> None:
        rec = self._selected_archive_record()
        if not rec:
            self.messagebox_info("No selection", "Select an archive item first.")
            return
        p = Path(str(rec.get("path") or ""))
        if not p.exists():
            self.messagebox_error("Missing file", f"Archive file not found:\n{p}")
            return
        if rec.get("source") == "onenote":
            self.messagebox_info(
                "Read-only archive",
                "OneNote records are read-only. Use 'Create Editable Draft Copy' to start a new student-owned draft.",
            )
            return
        if not self._record_editable(rec):
            self.messagebox_error(
                "Edit not allowed",
                "This article belongs to another user. Supervisor unlock is required to edit it.",
            )
            return
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            self.messagebox_error("Load failed", str(exc))
            return
        self._load_text_into_editor(text, str(rec.get("title") or p.stem))

    def on_create_draft_from_archive(self) -> None:
        rec = self._selected_archive_record()
        if not rec:
            self.messagebox_info("No selection", "Select an archive item first.")
            return
        p = Path(str(rec.get("path") or ""))
        if not p.exists():
            self.messagebox_error("Missing file", f"Archive file not found:\n{p}")
            return
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            self.messagebox_error("Draft creation failed", str(exc))
            return
        title = f"{rec.get('title') or p.stem} - Student Draft"
        self.project_title_var.set(title)
        self._load_text_into_editor(text, title)
        self._append_log(f"[ARTICLE] draft created from archive: {p.name}\n")
        self._set_status("Draft loaded from archive (original remains read-only)")

    def on_generate_workstudy_flyer(self) -> None:
        if not self._workspace_path():
            self.on_create_workspace()
            if not self._workspace_path():
                return
        self.project_title_var.set("Join CITL Workstudy: Build Real LLMOps Experience")
        self.app_name_var.set("CITL Workstudy LLMOps Program")
        self.audience_var.set("College students seeking AI + IT portfolio experience")
        self.template_var.set("Blank Article")
        flyer = build_workstudy_flyer_markdown()
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", flyer)
        self.notes_text.tag_add("body", "1.0", "end-1c")
        self.on_save_notes_only()
        self.on_export_markdown()
        self.on_save_article_snapshot()
        self._append_log("[FLYER] CITL Workstudy flyer draft generated and exported\n")
        self._set_status("CITL Workstudy flyer draft generated")

    def _compose_markdown(self) -> str:
        title = self.project_title_var.get().strip() or "CITL Walkthrough"
        app_name = self.app_name_var.get().strip()
        author = self.author_var.get().strip()
        audience = self.audience_var.get().strip()
        template = self.template_var.get().strip()
        style = self.style_var.get().strip()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        notes = self.notes_text.get("1.0", "end").strip()
        d = self._screenshot_dir()
        shots: List[str] = []
        if d and d.exists():
            shots = [p.name for p in sorted(d.iterdir()) if p.is_file() and p.suffix.lower() in IMAGE_EXTS]

        lines = [
            f"# {title}",
            "",
            f"- App/System: **{app_name or '-'}**",
            f"- Audience: **{audience or '-'}**",
            f"- Author: **{author or '-'}**",
            f"- Template: **{template or '-'}**",
            f"- Style Guide: **{style or '-'}**",
            f"- Generated: **{now}**",
            "",
            "## Walkthrough Content",
            "",
            notes or "_No content yet._",
            "",
            "## Screenshot Index",
            "",
        ]
        if shots:
            for i, name in enumerate(shots, start=1):
                lines.append(f"{i}. `{name}`")
        else:
            lines.append("_No screenshots imported yet._")
        lines.append("")
        return "\n".join(lines)

    def on_export_markdown(self) -> None:
        out_dir = self._exports_dir()
        ws = self._workspace_path()
        if not ws or not out_dir:
            self.messagebox_info("No workspace", "Create or load a workspace first.")
            return
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(self.project_title_var.get().strip())
        out = out_dir / f"{slug}_onenote_article.md"
        out.write_text(self._compose_markdown(), encoding="utf-8")
        meta = self._load_article_meta()
        meta[str(out.name)] = {
            "owner_user": self.current_user,
            "owner_name": self.author_var.get().strip() or self.current_user,
            "title": self.project_title_var.get().strip() or out.stem,
            "source": "local",
            "created_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._save_article_meta(meta)
        self._append_log(f"[EXPORT] markdown -> {out}\n")
        self._set_status(f"Exported: {out.name}")
        self.refresh_archive_list()

    def _launch_python_tool(self, tool_path: Path) -> None:
        if not tool_path.exists():
            raise FileNotFoundError(str(tool_path))
        python_bin = sys.executable
        env = os.environ.copy()
        env["CITL_REPO"] = str(REPO)
        subprocess.Popen(
            [python_bin, str(tool_path)],
            cwd=str(REPO),
            env=env,
        )

    def on_launch_doc_composer(self) -> None:
        self.on_save_project()
        try:
            self._launch_python_tool(TOOLS["doc_composer"])
            self._append_log("[LAUNCH] CITL Document Composer\n")
        except Exception as exc:
            self.messagebox_error("Launch failed", str(exc))

    def on_launch_screen_recorder(self) -> None:
        try:
            self._launch_python_tool(TOOLS["screen_recorder"])
            self._append_log("[LAUNCH] CITL Screen Recorder\n")
        except Exception as exc:
            self.messagebox_error("Launch failed", str(exc))

    def on_launch_video_editor(self) -> None:
        try:
            self._launch_python_tool(TOOLS["video_editor"])
            self._append_log("[LAUNCH] CITL Video Post Editor\n")
        except Exception as exc:
            self.messagebox_error("Launch failed", str(exc))

    def messagebox_info(self, title: str, msg: str) -> None:
        messagebox.showinfo(title, msg, parent=self.root)

    def messagebox_error(self, title: str, msg: str) -> None:
        messagebox.showerror(title, msg, parent=self.root)


def main() -> int:
    try:
        root = tk.Tk()
        TutorialCreatorGUI(root)
        root.mainloop()
        return 0
    except Exception as exc:
        crash = HERE / "citl_technical_writing_tutorial_creator_crash.log"
        with crash.open("w", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        try:
            messagebox.showerror(APP_NAME, f"{exc}\n\nSee:\n{crash}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
