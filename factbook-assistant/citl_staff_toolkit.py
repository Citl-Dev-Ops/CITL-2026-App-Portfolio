#!/usr/bin/env python3
"""
CITL Work and Preparedness Launcher  v2.0
==========================================
Day-to-day operational launcher for CITL staff and workstudy.
Four professional tracks, O365/SharePoint SSO sign-in, GitHub
portfolio onboarding, and repo-age detection.
"""
from __future__ import annotations
import json, os, subprocess, sys, threading, time, webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, simpledialog, ttk
except ImportError:
    sys.exit("tkinter required")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
REPO  = (_HERE.parent if not getattr(sys, "frozen", False)
         else Path(sys.executable).parent.parent.parent)

CONFIG_PATH = REPO / "factbook-assistant" / "staff_toolkit_config.json"
MATERIAL_PATHS = [
    ("Tutorial Projects",  REPO / "tutorial_projects"),
    ("Recordings",         REPO / "recordings"),
    ("Doc Composer Fonts", REPO / "factbook-assistant" / "fonts" / "doc_composer"),
    ("Factbook Data",      REPO / "factbook-assistant" / "data"),
    ("Bootstrap Patches",  REPO / "bootstrap" / "patches"),
]
REPO_SCAN_ROOTS = [
    Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop",
    Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Documents",
    Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Downloads",
    Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop" / "CITL Apps",
]
REPO_MARKER = "factbook-assistant/citl_app_sync.py"

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
C = {
    "bg":"#0A1A24","panel":"#102733","panel_alt":"#163645","notebk":"#0A1E2A",
    "card":"#123247","card_sel":"#1B4962","card_hover":"#18445E",
    "text":"#D6ECFA","muted":"#8AB3C8","faint":"#4A7086",
    "accent":"#48A9D6","gold":"#F2A33B","gold_dim":"#A86E1A",
    "btn":"#194258","btn_hi":"#24617E","btn_acc":"#1D5F86",
    "t1":"#1A4575","t2":"#1A4A30","t3":"#4A2A10","t4":"#3A1A45",
    "line":"#214960","good":"#1A5C2A","warn":"#6A3A00","err":"#5C1A1A",
}
_F = "Segoe UI" if sys.platform == "win32" else "Ubuntu"
APP_NAME    = "CITL Work and Preparedness Launcher"
APP_VERSION = "v2.0"
SUBTITLE    = "Staff Operations, Portfolio, and Account Hub"

# ---------------------------------------------------------------------------
# O365 institution profile
# ---------------------------------------------------------------------------
O365_TENANT_DOMAINS = {
    "whatcom.edu":   {"name": "Whatcom Community College",  "tenant": "whatcom.edu"},
    "skagit.edu":    {"name": "Skagit Valley College",       "tenant": "skagit.edu"},
    "bellevuecollege.edu": {"name": "Bellevue College",      "tenant": "bellevuecollege.edu"},
}
GITHUB_PORTFOLIO_STEPS = [
    ("1. Sign in to GitHub",
     "Go to github.com and sign in or create a free account.\n"
     "Use your personal email (not school email) so you keep this portfolio after graduation."),
    ("2. Create your portfolio repository",
     "Click the + icon (top right) -> 'New repository'.\n"
     "Name it exactly: YOUR-USERNAME.github.io\n"
     "Set it to Public. Check 'Add a README file'. Click 'Create repository'."),
    ("3. Enable GitHub Pages",
     "In your new repo, click Settings -> Pages.\n"
     "Under 'Branch', select 'main' and click Save.\n"
     "Your site will be live at: https://YOUR-USERNAME.github.io"),
    ("4. Add your first project",
     "Click 'Add file' -> 'Create new file'.\n"
     "Name it index.html and paste in a simple HTML intro page.\n"
     "Commit directly to main."),
    ("5. Pin repositories to your profile",
     "Go to your GitHub profile page.\n"
     "Click 'Customize your pins' and select your best 6 repos.\n"
     "Employers see these first when they visit your profile."),
    ("6. Add your portfolio link to your resume",
     "Copy https://YOUR-USERNAME.github.io\n"
     "Add it to your resume header alongside LinkedIn.\n"
     "Update it after every CITL project you complete."),
]

# ---------------------------------------------------------------------------
# Track definitions
# ---------------------------------------------------------------------------
TRACKS = [
    {
        "id":    "llmops",
        "title": "LLMOps IT Admin",
        "icon":  "LLM",
        "color": "#1A4575",
        "tag":   "AI  Automation  Portfolio Bots",
        "desc": (
            "Build, configure, and deploy custom AI applications using local LLMs. "
            "Design Modelfiles, create specialized chatbots, and export working Python "
            "apps as portfolio artifacts that demonstrate LLMOps readiness to employers."
        ),
        "outcomes": [
            "Custom AI application (Python + Modelfile)",
            "Trained system prompt and persona configuration",
            "Deployment documentation and README",
            "CLI/GUI bot demo for portfolio",
        ],
        "tools": [
            ("DATABASE LLMOps Builder",  "factbook-assistant/citl_database_llmops_builder.py",
             "Wizard to configure and export a complete AI application"),
            ("LLMOps Presentation Suite","factbook-assistant/citl_llmops_suite.py",
             "Full CITL LLMOps training and presentation environment"),
            ("LLM Studio / Bot Maker",   "CITL-LLM-Studio-Kit/app/llm_studio_gui.py",
             "Create and test custom Modelfiles and chat personas"),
            ("Factbook Assistant",       "factbook-assistant/factbook_assistant_gui.py",
             "Reference Q&A assistant  --  demonstrates a production RAG system"),
            ("App Sync + Patch Updater", "factbook-assistant/citl_app_sync.py",
             "Bootstrap, patch, and deploy CITL apps  --  demonstrates software maintenance"),
        ],
    },
    {
        "id":    "avit",
        "title": "AV/IT Operations",
        "icon":  "AVIT",
        "color": "#1A4A30",
        "tag":   "Inventory  Inspection  Patch Docs  Field Tech",
        "desc": (
            "Manage classroom and lab AV equipment, run room inspections, document "
            "patches and security fixes, and build AV driver triage tools. "
            "Produce inspection reports and patch procedures employers expect from IT staff."
        ),
        "outcomes": [
            "Room inventory spreadsheet (CSV/report)",
            "AV inspection checklist with pass/fail log",
            "Patch procedure documentation",
            "AV driver triage bot (via DATABASE LLMOps Builder)",
        ],
        "tools": [
            ("AV/IT Operations Tool",    "factbook-assistant/citl_av_it_ops.py",
             "Room inventory, AV inspection checklists, patch procedure docs"),
            ("Workstation Apps",         "factbook-assistant/citl_workstation_apps.py",
             "Display port tester, profile save/restore, diagnostics for campus workstations"),
            ("Field Apps",               "factbook-assistant/citl_field_apps.py",
             "Field tech toolkit: room inventory, driver check/rollback, checklist"),
            ("Display Profiles Utility", "CITL_Toolkit/CITL_DisplayProfile_GUI.ps1",
             "RTC classroom display profiles and room display state utility"),
            ("CITL Toolkit",             "CITL_Toolkit/CITL_Launcher.ps1",
             "Device management, display profiles, Zoom updater (PowerShell)"),
            ("Doc Composer",             "factbook-assistant/citl_doc_composer.py",
             "Create AV procedure manuals and technical documentation"),
        ],
    },
    {
        "id":    "elearn",
        "title": "E-Learning Technologies",
        "icon":  "LMS",
        "color": "#4A2A10",
        "tag":   "Canvas LMS  Office 365  SharePoint  HTML/CSS",
        "desc": (
            "Create Canvas LMS content, build MS Office automation flows, design "
            "HTML/CSS page templates, and deploy AI assistants for LMS support. "
            "Demonstrates digital pedagogy and office automation skills for education IT roles."
        ),
        "outcomes": [
            "Canvas page HTML/CSS template",
            "Office/SharePoint automation flow document",
            "LMS integration guide",
            "Custom course assistant bot",
        ],
        "tools": [
            ("Doc Composer",             "factbook-assistant/citl_doc_composer.py",
             "Create Canvas content, Office flow docs, and HTML/CSS templates"),
            ("Technical Writer Creator", "factbook-assistant/citl_technical_writing_tutorial_creator.py",
             "Generate step-by-step integration guides for Canvas and Office"),
            ("DATABASE LLMOps Builder",  "factbook-assistant/citl_database_llmops_builder.py",
             "Build a Canvas LMS assistant or Office automation advisor bot"),
            ("Factbook Assistant",       "factbook-assistant/factbook_assistant_gui.py",
             "Load Canvas syllabi or policy docs as a searchable knowledge base"),
        ],
    },
    {
        "id":    "techwrite",
        "title": "Technical Writing and Instruction",
        "icon":  "WRITE",
        "color": "#3A1A45",
        "tag":   "Tutorials  Docs  Screen Recording  Portfolio",
        "desc": (
            "Produce professional tutorials, how-to guides, and instructional materials "
            "using the full CITL documentation and recording suite. Build portfolios that "
            "demonstrate pedagogical and technical communication skills."
        ),
        "outcomes": [
            "Step-by-step tutorial (DOCX/PDF)",
            "Screen recording with narration",
            "Visual walkthrough with screenshots",
            "Published instructional document",
        ],
        "tools": [
            ("Technical Writer Creator", "factbook-assistant/citl_technical_writing_tutorial_creator.py",
             "Full tutorial production: writing, screenshots, LLM-assisted formatting"),
            ("Doc Composer",             "factbook-assistant/citl_doc_composer.py",
             "Advanced word processor with built-in snipping and PDF export"),
            ("LLMOps Presentation Suite","factbook-assistant/citl_llmops_suite.py",
             "Use as a content generator and presentation tool for tutorials"),
        ],
    },
]

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
_DEFAULT_CONFIG: Dict = {
    "sharepoint_url":   "",
    "office365_url":    "https://www.office.com",
    "local_db_path":    str(REPO / "data"),
    "o365_domain":      "",
    "o365_email":       "",
    "o365_display_name":"",
    "github_username":  "",
    "github_portfolio": "",
}

def _load_config() -> Dict:
    cfg = dict(_DEFAULT_CONFIG)
    for p in (CONFIG_PATH,
              REPO / "factbook-assistant" / "staff_toolkit_links.json"):
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    cfg.update({k: v for k, v in raw.items() if k in cfg})
                break
            except Exception:
                pass
    return cfg

def _save_config(cfg: Dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

def _normalize_url(raw: str) -> str:
    t = str(raw or "").strip()
    if not t:
        return ""
    return t if "://" in t else "https://" + t


# ---------------------------------------------------------------------------
# Repo age scanner
# ---------------------------------------------------------------------------
def _scan_repos() -> List[Tuple[Path, float]]:
    """Return [(repo_path, age_days)] for all CITL repos found in user folders."""
    found = []
    for root in REPO_SCAN_ROOTS:
        if not root.exists():
            continue
        # Check root itself and one level of subdirectories
        candidates = [root] + [p for p in root.iterdir()
                                if p.is_dir() and not p.name.startswith(".")]
        for candidate in candidates:
            marker = candidate / REPO_MARKER.replace("/", os.sep)
            if marker.exists():
                try:
                    mtime = marker.stat().st_mtime
                    age_days = (time.time() - mtime) / 86400
                    found.append((candidate, age_days))
                except Exception:
                    pass
    return found


# ---------------------------------------------------------------------------
# Main GUI
# ---------------------------------------------------------------------------
class StaffToolkit:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"{APP_NAME}  {APP_VERSION}")
        root.configure(bg=C["bg"])
        root.minsize(1120, 700)
        root.geometry("1200x760")

        self._cfg = _load_config()
        self._materials_var  = tk.StringVar(value="Checking materials...")
        self._resource_var   = tk.StringVar(value="Loading accounts...")
        self._active_track   = TRACKS[0]
        self._age_banner_shown = False

        self._build_ui()
        self._show_track(TRACKS[0])

        # Background startup checks
        threading.Thread(target=self._startup_checks, daemon=True).start()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        hdr = tk.Frame(self.root, bg=C["panel"])
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=C["gold"], height=3).pack(fill="x")
        hi = tk.Frame(hdr, bg=C["panel"])
        hi.pack(fill="x", padx=16, pady=8)
        tk.Label(hi, text=APP_NAME, font=(_F, 16, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(side="left")
        tk.Label(hi, text=APP_VERSION, font=(_F, 9, "bold"),
                 bg=C["panel"], fg=C["gold"]).pack(side="left", padx=6)
        tk.Label(hi, text=SUBTITLE, font=(_F, 9, "italic"),
                 bg=C["panel"], fg=C["muted"]).pack(side="right")

        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_sidebar(body)
        self._build_main(body)

        # Age-warning banner (hidden until scan completes)
        self._banner_frame = tk.Frame(self.root, bg=C["warn"], pady=4)
        self._banner_lbl = tk.Label(self._banner_frame, text="",
                                     font=(_F, 9), bg=C["warn"], fg="#FFD080",
                                     anchor="w", padx=14)
        self._banner_lbl.pack(side="left", fill="x", expand=True)
        tk.Button(self._banner_frame, text="Dismiss", font=(_F, 8),
                  bg=C["btn"], fg=C["muted"], relief="flat", padx=6,
                  command=self._banner_frame.pack_forget).pack(side="right", padx=6)

    # ------------------------------------------------------------------ Sidebar
    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg=C["panel"], width=238)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.pack_propagate(False)

        canvas = tk.Canvas(sb, bg=C["panel"], highlightthickness=0)
        vsb = ttk.Scrollbar(sb, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["panel"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        def _section(text):
            tk.Label(inner, text=text, font=(_F, 8, "bold"), bg=C["panel"],
                     fg=C["faint"], anchor="w").pack(fill="x", padx=12, pady=(14, 3))

        def _btn(text, cmd, color=None, fg=None):
            tk.Button(inner, text=f"  {text}", font=(_F, 9),
                      bg=color or C["panel_alt"], fg=fg or C["muted"],
                      relief="flat", bd=0, padx=10, pady=6,
                      anchor="w", cursor="hand2", command=cmd).pack(fill="x", padx=8, pady=1)

        def _div():
            tk.Frame(inner, bg=C["line"], height=1).pack(fill="x", padx=8, pady=8)

        # -- Tracks
        _section("TRACKS")
        self._track_btns: Dict = {}
        for track in TRACKS:
            btn = tk.Button(
                inner, text=f"  {track['icon']}  {track['title']}",
                font=(_F, 10), bg=C["btn"], fg=C["text"],
                activebackground=C["card_sel"], relief="flat", bd=0,
                padx=10, pady=10, anchor="w", cursor="hand2",
                command=lambda t=track: self._show_track(t),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._track_btns[track["id"]] = btn

        _div()

        # -- Quick launch
        _section("QUICK LAUNCH")
        for label, script in [
            ("App Sync",           "factbook-assistant/citl_app_sync.py"),
            ("Doc Composer",       "factbook-assistant/citl_doc_composer.py"),
            ("Workstation Apps",   "factbook-assistant/citl_workstation_apps.py"),
            ("Field Apps",         "factbook-assistant/citl_field_apps.py"),
        ]:
            _btn(f"Launch {label}", lambda s=script: self._launch(s))

        _div()

        # -- Work accounts
        _section("WORK ACCOUNTS")
        self._o365_status_var = tk.StringVar(value=self._o365_status_text())
        _btn("Sign in to Office 365 / SharePoint",
             self._o365_signin_dialog, color=C["btn_acc"], fg=C["text"])
        tk.Label(inner, textvariable=self._o365_status_var, font=(_F, 8),
                 bg=C["panel"], fg=C["muted"], anchor="w",
                 justify="left", wraplength=210).pack(fill="x", padx=14, pady=(0, 4))

        self._gh_status_var = tk.StringVar(value=self._gh_status_text())
        _btn("GitHub Sign-In + Portfolio Setup",
             self._github_dialog, color=C["btn_acc"], fg=C["text"])
        tk.Label(inner, textvariable=self._gh_status_var, font=(_F, 8),
                 bg=C["panel"], fg=C["muted"], anchor="w",
                 justify="left", wraplength=210).pack(fill="x", padx=14, pady=(0, 4))

        _div()

        # -- Work resources
        _section("WORK RESOURCES")
        _btn("Open SharePoint Workspace",  self._open_sharepoint)
        _btn("Open Office 365",            self._open_office365)
        _btn("Open Teams",                 self._open_teams)
        _btn("Open OneDrive",              self._open_onedrive)
        _btn("Open Local Database",        self._open_local_db)
        _btn("Configure Resource URLs",    self._configure_urls_dialog,
             color=C["btn"], fg=C["accent"])
        tk.Label(inner, textvariable=self._resource_var, font=(_F, 8),
                 bg=C["panel"], fg=C["muted"], anchor="w",
                 justify="left", wraplength=210).pack(fill="x", padx=12, pady=(0, 6))

        _div()

        # -- Materials
        _section("MATERIALS READY")
        tk.Label(inner, textvariable=self._materials_var, font=(_F, 8),
                 bg=C["panel"], fg=C["muted"], anchor="w",
                 justify="left", wraplength=210).pack(fill="x", padx=12, pady=(0, 4))
        _btn("Open Tutorial Projects",
             lambda: self._open_path(REPO / "tutorial_projects"))
        _btn("Open Recordings",
             lambda: self._open_path(REPO / "recordings"))
        _btn("Open Doc Fonts",
             lambda: self._open_path(REPO / "factbook-assistant" / "fonts" / "doc_composer"))

        # bottom padding
        tk.Frame(inner, bg=C["panel"], height=20).pack()

    # ------------------------------------------------------------------ Main
    def _build_main(self, parent):
        self._main = tk.Frame(parent, bg=C["bg"])
        self._main.grid(row=0, column=1, sticky="nsew")
        self._main.columnconfigure(0, weight=1)
        self._main.rowconfigure(2, weight=1)

        self._track_title_var = tk.StringVar()
        self._track_tag_var   = tk.StringVar()
        hdr2 = tk.Frame(self._main, bg=C["bg"])
        hdr2.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr2, textvariable=self._track_title_var,
                 font=(_F, 14, "bold"), bg=C["bg"], fg=C["gold"],
                 anchor="w", padx=16).pack(fill="x", pady=(12, 0))
        tk.Label(hdr2, textvariable=self._track_tag_var,
                 font=(_F, 9, "italic"), bg=C["bg"], fg=C["muted"],
                 anchor="w", padx=16).pack(fill="x")

        self._desc_lbl = tk.Label(self._main, text="", font=(_F, 10),
                                   bg=C["bg"], fg=C["text"], anchor="nw",
                                   justify="left", wraplength=680, padx=16, pady=6)
        self._desc_lbl.grid(row=1, column=0, sticky="ew")

        mid = tk.Frame(self._main, bg=C["bg"])
        mid.grid(row=2, column=0, sticky="nsew", padx=10, pady=4)
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)

        tool_outer = tk.Frame(mid, bg=C["panel"])
        tool_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        tool_outer.columnconfigure(0, weight=1)
        tool_outer.rowconfigure(1, weight=1)
        tk.Label(tool_outer, text="TOOLS", font=(_F, 9, "bold"),
                 bg=C["panel"], fg=C["accent"], anchor="w",
                 padx=10).grid(row=0, column=0, sticky="ew", pady=(8, 4))
        tools_canvas = tk.Canvas(tool_outer, bg=C["panel"], highlightthickness=0)
        tools_vsb = ttk.Scrollbar(tool_outer, orient="vertical",
                                   command=tools_canvas.yview)
        tools_canvas.configure(yscrollcommand=tools_vsb.set)
        tools_vsb.grid(row=1, column=1, sticky="ns")
        tools_canvas.grid(row=1, column=0, sticky="nsew")
        self._tools_frame = tk.Frame(tools_canvas, bg=C["panel"])
        self._tools_frame.columnconfigure(0, weight=1)
        tc_win = tools_canvas.create_window((0, 0), window=self._tools_frame, anchor="nw")
        self._tools_frame.bind("<Configure>", lambda e: tools_canvas.configure(
            scrollregion=tools_canvas.bbox("all")))
        tools_canvas.bind("<Configure>",
                          lambda e: tools_canvas.itemconfig(tc_win, width=e.width))

        out_outer = tk.Frame(mid, bg=C["panel"])
        out_outer.grid(row=0, column=1, sticky="nsew")
        out_outer.columnconfigure(0, weight=1)
        tk.Label(out_outer, text="PORTFOLIO OUTCOMES", font=(_F, 9, "bold"),
                 bg=C["panel"], fg=C["gold"], anchor="w",
                 padx=10).grid(row=0, column=0, sticky="ew", pady=(8, 4))
        self._outcomes_frame = tk.Frame(out_outer, bg=C["panel"])
        self._outcomes_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self._outcomes_frame.columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ Track display
    def _show_track(self, track: dict):
        self._active_track = track
        for tid, btn in self._track_btns.items():
            btn.configure(bg=C["card_sel"] if tid == track["id"] else C["btn"])
        self._track_title_var.set(f"{track['icon']}  {track['title']}")
        self._track_tag_var.set(track["tag"])
        self._desc_lbl.configure(text=track["desc"])

        for w in self._tools_frame.winfo_children():
            w.destroy()
        for i, (name, script, desc) in enumerate(track["tools"]):
            card = tk.Frame(self._tools_frame, bg=C["card"],
                            highlightthickness=1, highlightbackground=C["line"])
            card.grid(row=i, column=0, sticky="ew", pady=3, padx=4)
            card.columnconfigure(1, weight=1)
            tk.Label(card, text=track["icon"], font=(_F, 13), bg=track["color"],
                     fg=C["text"], width=4, anchor="center").grid(
                row=0, column=0, rowspan=2, padx=(0, 8), pady=6, sticky="ns")
            tk.Label(card, text=name, font=(_F, 10, "bold"),
                     bg=C["card"], fg=C["text"], anchor="w").grid(
                row=0, column=1, sticky="w", padx=(0, 8), pady=(6, 1))
            tk.Label(card, text=desc, font=(_F, 8), bg=C["card"],
                     fg=C["muted"], anchor="w", wraplength=440).grid(
                row=1, column=1, sticky="w", padx=(0, 8), pady=(0, 4))
            tk.Button(card, text="Launch", font=(_F, 9, "bold"),
                      bg=C["btn_acc"], fg=C["text"], relief="flat", bd=0,
                      padx=12, pady=5, cursor="hand2",
                      command=lambda s=script: self._launch(s)).grid(
                row=0, column=2, rowspan=2, padx=8)

        for w in self._outcomes_frame.winfo_children():
            w.destroy()
        for i, outcome in enumerate(track["outcomes"]):
            tk.Label(self._outcomes_frame, text=f"  -  {outcome}",
                     font=(_F, 9), bg=C["panel"], fg=C["text"],
                     anchor="w", wraplength=290).grid(
                row=i, column=0, sticky="ew", pady=4)

    # ------------------------------------------------------------------ Launch
    def _resolve_script(self, script_rel: str) -> Optional[Path]:
        """Find a tool by: dist exe > repo source > local dir."""
        # 1. Pre-built executable in dist/
        name = Path(script_rel).stem
        dist_exts = [".exe"] if sys.platform == "win32" else []
        for ext in dist_exts:
            exe = REPO / "dist" / name / f"{name}{ext}"
            if exe.exists():
                return exe

        # 2. Source relative to repo root
        full = REPO / script_rel.replace("/", os.sep)
        if full.exists():
            return full

        # 3. Filename in same dir as this script
        local = _HERE / Path(script_rel).name
        if local.exists():
            return local

        return None

    def _launch(self, script_rel: str):
        target = self._resolve_script(script_rel)
        if target is None:
            messagebox.showwarning(
                APP_NAME,
                f"Tool not found:\n  {script_rel}\n\n"
                "It may not be installed yet.\n"
                "Run 'App Sync' or 'BUILD_ALL_CITL_EXES_WINDOWS.cmd' to build it."
            )
            return
        ext = target.suffix.lower()
        try:
            if ext == ".ps1":
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy",
                     "Bypass", "-File", str(target)],
                    cwd=str(target.parent),
                )
            elif ext in (".cmd", ".bat"):
                subprocess.Popen(["cmd", "/c", str(target)],
                                  cwd=str(target.parent))
            elif ext == ".exe":
                if sys.platform == "win32":
                    os.startfile(str(target))  # type: ignore[attr-defined]
                else:
                    subprocess.Popen([str(target)], cwd=str(target.parent))
            elif ext == ".py":
                subprocess.Popen([sys.executable, str(target)], cwd=str(REPO))
            else:
                subprocess.Popen([sys.executable, str(target)], cwd=str(REPO))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Launch failed:\n{exc}")

    def _open_external(self, url: str, label: str = "URL"):
        resolved = _normalize_url(url)
        if not resolved:
            messagebox.showwarning(APP_NAME,
                                   f"{label} is not configured.\n"
                                   "Use 'Configure Resource URLs' or sign in first.")
            return
        try:
            webbrowser.open(resolved)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open browser:\n{exc}")

    def _open_path(self, p: Path):
        p = Path(p).expanduser()
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        if not p.exists():
            messagebox.showwarning(APP_NAME, f"Path not found:\n{p}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open path:\n{exc}")

    # ------------------------------------------------------------------ O365 SSO
    def _o365_status_text(self) -> str:
        email = self._cfg.get("o365_email", "").strip()
        domain = self._cfg.get("o365_domain", "").strip()
        name = self._cfg.get("o365_display_name", "").strip()
        if email:
            return f"Signed in: {name or email}\n{domain}"
        return "Not signed in"

    def _o365_signin_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Office 365 School Sign-In")
        win.configure(bg=C["bg"])
        win.grab_set()
        win.geometry("560x480")
        win.resizable(False, False)

        tk.Frame(win, bg="#0078D4", height=4).pack(fill="x")
        tk.Label(win, text="Microsoft Office 365 - School Sign-In",
                 font=(_F, 13, "bold"), bg=C["bg"], fg=C["text"]).pack(pady=(16, 4))
        tk.Label(win, text="Enter your school (.edu) account to configure SharePoint, Teams, and OneDrive links.",
                 font=(_F, 9), bg=C["bg"], fg=C["muted"],
                 wraplength=500).pack(padx=20)

        tk.Frame(win, bg=C["line"], height=1).pack(fill="x", padx=20, pady=12)

        form = tk.Frame(win, bg=C["bg"])
        form.pack(fill="x", padx=24)
        form.columnconfigure(1, weight=1)

        fields = [
            ("School email address",    "o365_email",        "you@whatcom.edu"),
            ("Display name (optional)", "o365_display_name", "Your Name"),
            ("Institution domain",      "o365_domain",       "whatcom.edu"),
            ("SharePoint site URL",     "sharepoint_url",    "https://yourschool.sharepoint.com/sites/citl"),
        ]
        vars_: Dict[str, tk.StringVar] = {}
        for i, (label, key, placeholder) in enumerate(fields):
            tk.Label(form, text=label + ":", font=(_F, 9), bg=C["bg"],
                     fg=C["muted"], anchor="e", width=22).grid(
                row=i, column=0, padx=(0, 8), pady=6, sticky="e")
            var = tk.StringVar(value=self._cfg.get(key, ""))
            vars_[key] = var
            ent = tk.Entry(form, textvariable=var, font=(_F, 10),
                           bg=C["notebk"], fg=C["text"],
                           insertbackground=C["text"], relief="flat", width=34)
            ent.grid(row=i, column=1, pady=6, sticky="ew")
            if not var.get():
                ent.insert(0, placeholder)
                ent.configure(fg=C["faint"])
                def _clear(e, en=ent, ph=placeholder, v=var):
                    if en.get() == ph:
                        en.delete(0, "end")
                        en.configure(fg=C["text"])
                def _restore(e, en=ent, ph=placeholder, v=var):
                    if not en.get().strip():
                        en.insert(0, ph)
                        en.configure(fg=C["faint"])
                ent.bind("<FocusIn>", _clear)
                ent.bind("<FocusOut>", _restore)

        tk.Frame(win, bg=C["line"], height=1).pack(fill="x", padx=20, pady=10)

        info = tk.Frame(win, bg=C["panel"], padx=16, pady=10)
        info.pack(fill="x", padx=20)
        tk.Label(info, text="After saving, use the buttons below to sign in via your browser.\n"
                 "Your school SSO will handle authentication securely.\n"
                 "This app stores only your email and domain -- never your password.",
                 font=(_F, 8), bg=C["panel"], fg=C["muted"],
                 justify="left").pack(anchor="w")

        btns = tk.Frame(win, bg=C["bg"])
        btns.pack(fill="x", padx=20, pady=(12, 16))

        def _auto_fill_domain(event=None):
            email = vars_["o365_email"].get().strip()
            if "@" in email and not vars_["o365_domain"].get().strip():
                domain = email.split("@", 1)[1]
                if "." in domain:
                    vars_["o365_domain"].set(domain)

        def _save_and_open():
            # Collect values (ignore placeholder text)
            placeholders = {f[2] for f in fields}
            for key, var in vars_.items():
                val = var.get().strip()
                if val not in placeholders:
                    self._cfg[key] = val
            _auto_fill_domain()
            domain = self._cfg.get("o365_domain", "").strip()
            email = self._cfg.get("o365_email", "").strip()
            if domain:
                sp_url = self._cfg.get("sharepoint_url", "").strip()
                if not sp_url or sp_url in placeholders:
                    tenant = domain.split(".")[0]
                    self._cfg["sharepoint_url"] = f"https://{tenant}.sharepoint.com"
                self._cfg["office365_url"] = (
                    f"https://www.office.com?login_hint={email}" if email
                    else "https://www.office.com"
                )
            try:
                _save_config(self._cfg)
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Could not save config:\n{exc}", parent=win)
                return
            self._o365_status_var.set(self._o365_status_text())
            self._refresh_resource_status()
            win.destroy()
            # Open O365 sign-in in browser
            login_url = (
                f"https://login.microsoftonline.com/{domain}/oauth2/v2.0/authorize"
                f"?client_id=4765445b-32c6-49b0-83e6-1d93765276ca"
                f"&response_type=code"
                f"&redirect_uri=https%3A%2F%2Fwww.office.com"
                f"&scope=openid+profile+email"
                f"&login_hint={email}"
                if (domain and email)
                else (
                    f"https://login.microsoftonline.com/{domain}" if domain
                    else "https://www.office.com"
                )
            )
            webbrowser.open(login_url)

        tk.Button(btns, text="Save + Open Sign-In Page",
                  font=(_F, 10, "bold"), bg="#0078D4", fg="white",
                  relief="flat", padx=14, pady=8, cursor="hand2",
                  command=_save_and_open).pack(side="left")
        tk.Button(btns, text="Save Only",
                  font=(_F, 9), bg=C["btn"], fg=C["text"],
                  relief="flat", padx=10, pady=8, cursor="hand2",
                  command=lambda: [
                      [self._cfg.update({k: v.get()}) for k, v in vars_.items()],
                      _save_config(self._cfg),
                      self._o365_status_var.set(self._o365_status_text()),
                      self._refresh_resource_status(),
                      win.destroy()
                  ]).pack(side="left", padx=6)
        tk.Button(btns, text="Cancel",
                  font=(_F, 9), bg=C["btn"], fg=C["muted"],
                  relief="flat", padx=10, pady=8, cursor="hand2",
                  command=win.destroy).pack(side="right")

    # ------------------------------------------------------------------ O365 resource openers
    def _o365_url(self, path: str = "") -> str:
        domain = self._cfg.get("o365_domain", "").strip()
        email  = self._cfg.get("o365_email", "").strip()
        tenant = domain.split(".")[0] if domain else ""
        base   = f"https://{tenant}.sharepoint.com{path}" if tenant else ""
        hint   = f"?login_hint={email}" if email else ""
        return base + hint if base else ""

    def _open_sharepoint(self):
        url = (self._cfg.get("sharepoint_url", "").strip()
               or self._o365_url())
        if not url:
            if messagebox.askyesno(APP_NAME,
                                   "SharePoint URL not configured.\n"
                                   "Open Sign-In dialog to configure it?"):
                self._o365_signin_dialog()
            return
        self._open_external(url, "SharePoint")

    def _open_office365(self):
        email = self._cfg.get("o365_email", "").strip()
        url = (self._cfg.get("office365_url", "").strip()
               or f"https://www.office.com?login_hint={email}" if email
               else "https://www.office.com")
        self._open_external(url, "Office 365")

    def _open_teams(self):
        email = self._cfg.get("o365_email", "").strip()
        url = (f"https://teams.microsoft.com?login_hint={email}"
               if email else "https://teams.microsoft.com")
        self._open_external(url, "Teams")

    def _open_onedrive(self):
        domain = self._cfg.get("o365_domain", "").strip()
        email  = self._cfg.get("o365_email", "").strip()
        tenant = domain.split(".")[0] if domain else ""
        url = (f"https://{tenant}-my.sharepoint.com?login_hint={email}"
               if tenant else "https://onedrive.live.com")
        self._open_external(url, "OneDrive")

    def _open_local_db(self):
        p = Path(self._cfg.get("local_db_path", "") or str(REPO / "data")).expanduser()
        if not p.exists():
            p = REPO / "data"
        self._open_path(p)

    # ------------------------------------------------------------------ GitHub
    def _gh_status_text(self) -> str:
        username = self._cfg.get("github_username", "").strip()
        portfolio = self._cfg.get("github_portfolio", "").strip()
        if username:
            return f"GitHub: @{username}\n{portfolio or 'No portfolio URL saved'}"
        return "Not configured"

    def _github_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("GitHub Sign-In + Portfolio Onboarding")
        win.configure(bg=C["bg"])
        win.grab_set()
        win.geometry("680x600")

        tk.Frame(win, bg="#24292F", height=4).pack(fill="x")
        tk.Label(win, text="GitHub  --  Portfolio Setup Wizard",
                 font=(_F, 13, "bold"), bg=C["bg"], fg=C["text"]).pack(pady=(16, 4))

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=14, pady=8)
        style = ttk.Style(win)
        style.configure("TNotebook", background=C["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=C["btn"], foreground=C["text"],
                        font=(_F, 9), padding=[10, 4])
        style.map("TNotebook.Tab", background=[("selected", "#24292F")])

        # Tab 1: Account
        acct_tab = tk.Frame(nb, bg=C["bg"])
        nb.add(acct_tab, text="  Account  ")
        acct_tab.columnconfigure(1, weight=1)

        tk.Label(acct_tab, text="Save your GitHub account info and open github.com to sign in.",
                 font=(_F, 9), bg=C["bg"], fg=C["muted"],
                 wraplength=560).grid(row=0, column=0, columnspan=3, padx=20, pady=(14, 8), sticky="w")

        gh_user_var = tk.StringVar(value=self._cfg.get("github_username", ""))
        gh_port_var = tk.StringVar(value=self._cfg.get("github_portfolio", ""))

        for i, (label, var, ph) in enumerate([
            ("GitHub username", gh_user_var, "your-username"),
            ("Portfolio URL",   gh_port_var, "https://your-username.github.io"),
        ]):
            tk.Label(acct_tab, text=label + ":", font=(_F, 9), bg=C["bg"],
                     fg=C["muted"], anchor="e", width=18).grid(
                row=i+1, column=0, padx=(20, 8), pady=6, sticky="e")
            tk.Entry(acct_tab, textvariable=var, font=(_F, 10),
                     bg=C["notebk"], fg=C["text"],
                     insertbackground=C["text"], relief="flat",
                     width=40).grid(row=i+1, column=1, pady=6, sticky="ew", padx=(0, 20))

        acct_btns = tk.Frame(acct_tab, bg=C["bg"])
        acct_btns.grid(row=3, column=0, columnspan=3, pady=16, padx=20, sticky="w")

        def _save_gh():
            self._cfg["github_username"] = gh_user_var.get().strip()
            self._cfg["github_portfolio"] = gh_port_var.get().strip()
            if self._cfg["github_username"] and not self._cfg["github_portfolio"]:
                self._cfg["github_portfolio"] = (
                    f"https://{self._cfg['github_username']}.github.io")
                gh_port_var.set(self._cfg["github_portfolio"])
            _save_config(self._cfg)
            self._gh_status_var.set(self._gh_status_text())

        def _open_github():
            _save_gh()
            uname = self._cfg.get("github_username", "").strip()
            url = f"https://github.com/{uname}" if uname else "https://github.com"
            webbrowser.open(url)

        def _open_new_repo():
            uname = self._cfg.get("github_username", "").strip()
            url = (f"https://github.com/new?name={uname}.github.io"
                   if uname else "https://github.com/new")
            webbrowser.open(url)

        tk.Button(acct_btns, text="Save + Open GitHub",
                  font=(_F, 9, "bold"), bg="#24292F", fg="white",
                  relief="flat", padx=12, pady=6, cursor="hand2",
                  command=_open_github).pack(side="left")
        tk.Button(acct_btns, text="Create Portfolio Repo",
                  font=(_F, 9), bg=C["btn_acc"], fg=C["text"],
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  command=_open_new_repo).pack(side="left", padx=6)
        tk.Button(acct_btns, text="Open Portfolio Site",
                  font=(_F, 9), bg=C["btn"], fg=C["muted"],
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  command=lambda: webbrowser.open(
                      gh_port_var.get().strip() or "https://github.com")
                  ).pack(side="left", padx=4)

        # Tab 2: Walkthrough
        walk_tab = tk.Frame(nb, bg=C["bg"])
        nb.add(walk_tab, text="  Portfolio Walkthrough  ")
        tk.Label(walk_tab, text="Step-by-step guide to create your GitHub Pages portfolio.",
                 font=(_F, 9), bg=C["bg"], fg=C["muted"]).pack(anchor="w", padx=16, pady=(12, 4))

        steps_canvas = tk.Canvas(walk_tab, bg=C["bg"], highlightthickness=0)
        steps_vsb = ttk.Scrollbar(walk_tab, orient="vertical", command=steps_canvas.yview)
        steps_canvas.configure(yscrollcommand=steps_vsb.set)
        steps_vsb.pack(side="right", fill="y")
        steps_canvas.pack(fill="both", expand=True)
        steps_inner = tk.Frame(steps_canvas, bg=C["bg"])
        sw = steps_canvas.create_window((0, 0), window=steps_inner, anchor="nw")
        steps_inner.bind("<Configure>", lambda e: steps_canvas.configure(
            scrollregion=steps_canvas.bbox("all")))
        steps_canvas.bind("<Configure>",
                          lambda e: steps_canvas.itemconfig(sw, width=e.width))

        for step_title, step_body in GITHUB_PORTFOLIO_STEPS:
            card = tk.Frame(steps_inner, bg=C["card"],
                            highlightthickness=1, highlightbackground=C["line"])
            card.pack(fill="x", padx=14, pady=4)
            tk.Label(card, text=step_title, font=(_F, 10, "bold"),
                     bg=C["card"], fg=C["gold"], anchor="w",
                     padx=10).pack(fill="x", pady=(8, 2))
            tk.Label(card, text=step_body, font=(_F, 9), bg=C["card"],
                     fg=C["text"], anchor="nw", justify="left",
                     wraplength=580, padx=14).pack(fill="x", pady=(0, 8))

        tk.Button(win, text="Close",
                  font=(_F, 9), bg=C["btn"], fg=C["muted"],
                  relief="flat", padx=12, pady=6, cursor="hand2",
                  command=win.destroy).pack(anchor="e", padx=16, pady=(0, 12))

    # ------------------------------------------------------------------ URL Config
    def _configure_urls_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Configure Resource URLs")
        win.configure(bg=C["bg"])
        win.grab_set()
        win.geometry("580x320")
        win.columnconfigure(1, weight=1)

        fields = [
            ("SharePoint URL",   "sharepoint_url"),
            ("Office 365 URL",   "office365_url"),
            ("Local DB Path",    "local_db_path"),
        ]
        vars_: Dict[str, tk.StringVar] = {}
        for i, (label, key) in enumerate(fields):
            tk.Label(win, text=label + ":", font=(_F, 9), bg=C["bg"],
                     fg=C["muted"], anchor="e", width=16).grid(
                row=i, column=0, padx=(16, 8), pady=8, sticky="e")
            var = tk.StringVar(value=self._cfg.get(key, ""))
            vars_[key] = var
            tk.Entry(win, textvariable=var, font=(_F, 9), bg=C["notebk"],
                     fg=C["text"], insertbackground=C["text"],
                     relief="flat", width=52).grid(
                row=i, column=1, padx=(0, 16), pady=8, sticky="ew")

        btns = tk.Frame(win, bg=C["bg"])
        btns.grid(row=len(fields), column=0, columnspan=2, sticky="ew",
                  padx=16, pady=(8, 16))
        btns.columnconfigure(0, weight=1)

        def _save():
            for key, var in vars_.items():
                val = var.get().strip()
                if key.endswith("_url") and val:
                    val = _normalize_url(val)
                self._cfg[key] = val
            try:
                _save_config(self._cfg)
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Could not save:\n{exc}", parent=win)
                return
            self._refresh_resource_status()
            win.destroy()

        tk.Button(btns, text="Save", font=(_F, 9, "bold"), bg=C["btn_acc"],
                  fg=C["text"], relief="flat", padx=14, pady=6,
                  cursor="hand2", command=_save).pack(side="right")
        tk.Button(btns, text="Cancel", font=(_F, 9), bg=C["btn"],
                  fg=C["text"], relief="flat", padx=12, pady=6,
                  cursor="hand2", command=win.destroy).pack(side="right", padx=(0, 6))

    # ------------------------------------------------------------------ Status helpers
    def _refresh_resource_status(self):
        sp = "OK" if self._cfg.get("sharepoint_url", "").strip() else "not set"
        o365 = "OK" if self._cfg.get("office365_url", "").strip() else "not set"
        gh = f"@{self._cfg['github_username']}" if self._cfg.get("github_username") else "not set"
        self._resource_var.set(
            f"SharePoint: {sp}  |  O365: {o365}\nGitHub: {gh}")

    def _refresh_material_status(self):
        ready = sum(1 for _, p in MATERIAL_PATHS if p.exists())
        total = len(MATERIAL_PATHS)
        if ready == total:
            self._materials_var.set(f"Materials: READY ({ready}/{total})")
        else:
            missing = [lbl for lbl, p in MATERIAL_PATHS if not p.exists()]
            preview = ", ".join(missing[:2])
            if len(missing) > 2:
                preview += f" +{len(missing)-2}"
            self._materials_var.set(
                f"Materials: PARTIAL ({ready}/{total})\nMissing: {preview}")

    # ------------------------------------------------------------------ Startup checks
    def _startup_checks(self):
        self._refresh_material_status()
        self.root.after(0, self._refresh_resource_status)
        # Repo age scan
        repos = _scan_repos()
        stale = [(p, age) for p, age in repos if age > 14]
        if stale:
            msgs = []
            for p, age in stale[:3]:
                msgs.append(f"{p.name}: {int(age)}d old")
            banner = ("Stale CITL repos detected: " + "; ".join(msgs) +
                      "  -- Run App Sync to update.")
            self.root.after(800, lambda: self._show_banner(banner))

    def _show_banner(self, text: str):
        if self._age_banner_shown:
            return
        self._age_banner_shown = True
        self._banner_lbl.configure(text=text)
        self._banner_frame.pack(fill="x", side="bottom", before=self.root.winfo_children()[-1])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    root.withdraw()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except Exception:
        pass
    root.deiconify()
    StaffToolkit(root)
    root.mainloop()


if __name__ == "__main__":
    main()
