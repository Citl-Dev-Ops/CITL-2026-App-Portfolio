#!/usr/bin/env python3
"""
CITL LLMOps Presentation Suite  v1.1
======================================
Showcase, installer, and walkthrough for the full CITL app ecosystem.
Includes Ollama + system capability panel with model cookbook.

Color scheme : maroon + charcoal gray
Compatible   : Windows 10/11,  Ubuntu 24.04 LTS
"""
from __future__ import annotations

import http.client
import json as _json
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    print("tkinter not available  install python3-tk (Ubuntu) or use bundled Python (Windows).")
    sys.exit(1)

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

#  Identity 
SUITE_NAME    = "CITL LLMOps Presentation Suite"
SUITE_VERSION = "v1.2"
SUITE_TAGLINE = "Student showcase    AI career readiness    Human-in-the-loop LLMOps"

#  Paths 
_HERE = Path(__file__).parent   # factbook-assistant/
if getattr(sys, "frozen", False):
    # Running as a PyInstaller EXE.  Honour CITL_REPO env if set; otherwise
    # walk up 3 levels from the EXE: dist/AppName/App.exe -> CITL/
    _env_repo = os.environ.get("CITL_REPO", "").strip()
    REPO = Path(_env_repo) if (_env_repo and Path(_env_repo).is_dir()) else Path(sys.executable).parent.parent.parent
else:
    REPO = _HERE.parent         # CITL/

# Suppress console windows on Windows subprocess calls
_NO_WIN = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
RECORDINGS_DIR = REPO / "recordings"
RECORDER_SIGNAL_PATH = RECORDINGS_DIR / "citl_recorder_target_signal.json"

#  Colors 
C: Dict[str, str] = {
    "bg":         "#140a0a",
    "panel":      "#1e0f0f",
    "panel_alt":  "#271414",
    "card":       "#221010",
    "card_sel":   "#521c1c",
    "border":     "#6b2c2c",
    "sep":        "#3d1c1c",
    "text":       "#f5eeee",
    "muted":      "#c4a0a0",
    "faint":      "#8a7070",
    "accent":     "#d84444",
    "accent_hi":  "#f06060",
    "btn":        "#4a1a1a",
    "btn_hi":     "#6e2525",
    "btn_accent": "#7a1e1e",
    "good":       "#84f6a0",
    "warn":       "#ffd369",
    "danger":     "#ff8b8b",
    "tag":        "#321515",
    "notebk":     "#180c0c",
}

_F = "Segoe UI" if sys.platform == "win32" else "Ubuntu"

RECORDER_WINDOW_HINTS: Dict[str, str] = {
    "factbook": "CITL Desktop LLM Assistant",
    "screen_recorder": "CITL Screen Recorder",
    "doc_composer": "CITL Document Composer",
    "technical_writer_creator": "CITL Technical Writing and Tutorial Creator",
    "database_llmops_builder": "DATABASE LLMOps Builder",
    "av_it_ops": "CITL AV/IT Operations",
    "staff_toolkit": "CITL Work and Preparedness Launcher",
}

# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
# Drive / path discovery
# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

def _windows_scan_roots() -> List[Path]:
    roots: List[Path] = []
    if sys.platform != "win32":
        return roots
    try:
        import ctypes
    except Exception:
        return roots
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        if not (bitmask & (1 << i)):
            continue
        drive = f"{letter}:\\"
        try:
            dtype = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive))
        except Exception:
            continue
        # 2=removable, 3=fixed. Skip network/cd/unready to avoid long startup stalls.
        if dtype in (2, 3):
            roots.append(Path(drive))
    return roots


def _scan_drives(folder_hints: List[str], key_rel: str) -> Optional[Path]:
    """
    Scan all drive letters (DZ) for any folder whose name matches one of
    folder_hints and that contains key_rel inside it.
    Handles USB drives that may appear on different letters on different machines.
    """
    roots: List[Path]
    if sys.platform == "win32":
        roots = _windows_scan_roots()
    else:
        roots = []
    for root in roots:
        if not root.exists():
            continue
        # Direct child of drive root
        for hint in folder_hints:
            candidate = root / hint
            if (candidate / key_rel).exists():
                return candidate
        # One level deep (e.g. D:\00 CITL APPS 2026\CITL-LLM-Studio-Kit)
        try:
            for sub in root.iterdir():
                if not sub.is_dir():
                    continue
                for hint in folder_hints:
                    candidate = sub / hint
                    if (candidate / key_rel).exists():
                        return candidate
        except PermissionError:
            continue
    return None


def _find_llm_studio() -> Optional[Path]:
    key = "app/llm_studio_gui.py"
    # Fixed known paths first (fast)
    fixed = [
        Path(r"K:\CITL-LLM-Studio-Kit"),
        Path(r"D:\00 CITL APPS 2026\CITL-LLM-Studio-Kit"),
        Path(r"D:\CITL-LLM-Studio-Kit"),
    ]
    for p in fixed:
        if (p / "app" / "llm_studio_gui.py").exists():
            return p
    hints = ["CITL-LLM-Studio-Kit", "CITL LLM Studio Kit", "LLM-Studio-Kit"]
    return _scan_drives(hints, key)


def _find_advisor() -> Optional[Path]:
    key = "api/app.py"
    fixed = [
        Path(r"C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS\2026 ACADEMIC ADVISOR"),
        Path(r"C:\Users\Doc_M\AI-Training-Hub"),  # fallback if misnamed
    ]
    for p in fixed:
        if (p / "api" / "app.py").exists():
            return p
    hints = [
        "2026 ACADEMIC ADVISOR",
        "rtc-academic-advisor",
        "academic-advisor",
        "ACADEMIC ADVISOR",
        "CITLAdvisor",
    ]
    # Also check Linux home
    for nm in hints:
        p = Path.home() / nm
        if (p / "api" / "app.py").exists():
            return p
    return _scan_drives(hints, key)


def _find_ai_hub() -> Optional[Path]:
    fixed = [
        Path(r"C:\Users\Doc_M\AI-Training-Hub"),
        Path.home() / "AI-Training-Hub",
    ]
    for p in fixed:
        if (p / "app" / "hub.py").exists():
            return p
    hints = ["AI-Training-Hub", "AI Training Hub", "AITrainingHub"]
    return _scan_drives(hints, "app/hub.py")


# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
# System / Ollama probes
# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

def _check_ollama(host: str = "localhost", port: int = 11434) -> dict:
    result: dict = {"running": False, "version": "", "models": []}
    try:
        conn = http.client.HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/api/version")
        r = conn.getresponse()
        if r.status == 200:
            result["running"] = True
            result["version"] = _json.loads(r.read()).get("version", "")
        conn.close()
    except Exception:
        return result
    try:
        conn2 = http.client.HTTPConnection(host, port, timeout=2)
        conn2.request("GET", "/api/tags")
        r2 = conn2.getresponse()
        if r2.status == 200:
            mdata = _json.loads(r2.read())
            result["models"] = [m["name"] for m in mdata.get("models", [])]
        conn2.close()
    except Exception:
        pass
    return result


def _nvidia_smi(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["nvidia-smi"] + list(args), timeout=4,
            stderr=subprocess.DEVNULL, **_NO_WIN
        ).decode().strip()
    except Exception:
        return ""


def _get_gpu_info() -> Tuple[str, Optional[float]]:
    """Returns (gpu_name, vram_gb) or ('Unknown', None)."""
    name = _nvidia_smi("--query-gpu=name", "--format=csv,noheader")
    vram_str = _nvidia_smi("--query-gpu=memory.total",
                           "--format=csv,noheader,nounits")
    if name and vram_str:
        try:
            return name.splitlines()[0], float(vram_str.splitlines()[0]) / 1024
        except ValueError:
            pass
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-WmiObject Win32_VideoController | Select-Object -First 1 Name,AdapterRAM | ConvertTo-Json"],
                timeout=6, stderr=subprocess.DEVNULL, **_NO_WIN
            ).decode()
            data = _json.loads(out)
            nm  = data.get("Name", "Unknown")
            ram = data.get("AdapterRAM") or 0
            return nm, (int(ram) / (1024 ** 3)) if ram else None
        except Exception:
            pass
    return "Unknown GPU", None


def _get_ram_gb() -> Optional[float]:
    if _HAS_PSUTIL:
        return _psutil.virtual_memory().total / (1024 ** 3)
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-WmiObject Win32_ComputerSystem).TotalPhysicalMemory"],
                timeout=6, stderr=subprocess.DEVNULL, **_NO_WIN
            ).decode().strip()
            return int(out) / (1024 ** 3)
        except Exception:
            pass
    return None


def _get_cpu_info() -> str:
    if _HAS_PSUTIL:
        cores = _psutil.cpu_count(logical=False)
        threads = _psutil.cpu_count(logical=True)
        pct = _psutil.cpu_percent(interval=0.3)
        return f"{platform.processor() or 'CPU'}    {cores}c/{threads}t    {pct:.0f}% load"
    return platform.processor() or "Unknown CPU"


# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
# Model cookbook
# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

MODEL_COOKBOOK: List[dict] = [
    {
        "tier": "Micro  (4 GB VRAM or CPU-only)",
        "color": "warn",
        "models": ["llama3.2:1b", "tinyllama:1b", "phi3:mini", "moondream2"],
        "best_for": [
            "Basic student Q&A and quick lookups",
            "Simple chatbot demos on lab machines",
            "Fast responses when GPU is shared",
        ],
        "avoid_for": "Long document synthesis, complex reasoning, multilingual output",
    },
    {
        "tier": "Standard  (48 GB VRAM)",
        "color": "good",
        "models": ["llama3.2:3b", "gemma2:2b", "qwen2.5:3b", "mistral:7b-q4"],
        "best_for": [
            "Student Q&A with citation support (Factbook RAG)",
            "Classroom summarization and note-taking",
            "Basic translation and paraphrasing",
        ],
        "avoid_for": "Complex multi-step reasoning, very long documents",
    },
    {
        "tier": "Research  (816 GB VRAM)",
        "color": "good",
        "models": ["llama3.1:8b", "mistral:7b", "qwen2.5:7b", "gemma2:9b",
                   "olmo2:7b AllenAI", "tulu3:8b AllenAI"],
        "best_for": [
            "Full Factbook research synthesis with long context",
            "Multilingual Q&A (qwen2.5 excels here)",
            "Academic Advisor degree audit reasoning",
            "AllenAI OLMo / Tulu  open-weights, ideal for education transparency",
        ],
        "avoid_for": "Real-time responses on shared GPU; use quantized (q4/q5) variants",
    },
    {
        "tier": "Institutional / Archival  (1624 GB VRAM)",
        "color": "accent",
        "models": ["qwen2.5:14b", "mistral:12b", "llama3.1:13b", "gemma2:27b-q4"],
        "best_for": [
            "Institutional knowledge base and document archiving",
            "Cross-course curriculum analysis",
            "Long-context document comparison and synthesis",
            "Department-level AI advising systems",
        ],
        "avoid_for": "Single-machine student demos  resource intensive",
    },
    {
        "tier": "Multimodal Vision+Text  (any VRAM 6 GB)",
        "color": "accent_hi",
        "models": ["llava:7b", "llava:13b", "llava-phi3", "gemma3", "moondream2"],
        "best_for": [
            "Image-based exam questions and diagram analysis",
            "Classroom photo descriptions for accessibility",
            "Lab equipment identification and troubleshooting",
            "Slide deck and whiteboard OCR + explanation",
        ],
        "avoid_for": "Audio/video  multimodal means image+text only (not speech)",
    },
    {
        "tier": "Embedding / Retrieval  (CPU-friendly)",
        "color": "muted",
        "models": ["nomic-embed-text", "mxbai-embed-large", "snowflake-arctic-embed"],
        "best_for": [
            "Factbook semantic search (the RAG 'find' step)",
            "Academic Advisor document similarity",
            "Building searchable knowledge bases",
            "NOT for generating text  for finding relevant passages",
        ],
        "avoid_for": "Direct conversation or generation  these are embeddings only",
    },
]

ALLENAI_MODELS: List[dict] = [
    {
        "name": "olmo2:7b",
        "full": "AllenAI OLMo 2 (7B)",
        "pull": "ollama pull olmo2:7b",
        "why": (
            "Fully open weights  training data, code, and checkpoints all public. "
            "Ideal for education transparency: students can inspect exactly what the model learned."
        ),
    },
    {
        "name": "tulu3:8b",
        "full": "AllenAI Tulu 3 (8B)",
        "pull": "ollama pull tulu3",
        "why": (
            "Instruction-tuned on OLMo. Strong at following multi-step directions, "
            "format compliance, and Q&A  great for advising and research workflows."
        ),
    },
]


# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
# App definitions
# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

def _build_apps() -> List[dict]:
    studio  = _find_llm_studio()
    hub     = _find_ai_hub()
    advisor = _find_advisor()

    studio_launcher_win = (studio / "scripts" / "run_citl_llm_studio.ps1") if studio else None
    hub_launcher_win    = (hub / "hub_launcher.py") if hub else None
    hub_exe             = (hub / "Launch AI Training Hub.exe") if hub else None
    advisor_launcher    = (advisor / "scripts" / "Run-CITLAdvisor.ps1") if advisor else None

    return [
        #  1. Factbook 
        {
            "id": "factbook",
            "name": "Factbook",
            "author": "Abdo Mohammad",
            "tagline": "AI Study, Research, Transcription & Translation",
            "icon": "[FACTBOOK]",
            "description": (
                "Factbook is a general-purpose LLM research tool for any text file or document "
                "corpus. Students ask natural-language questions about indexed textbooks, course "
                "materials, or custom knowledge bases, and receive synthesized, cited answers "
                "via a local Ollama LLM  no internet required.\n\n"
                " Transcription (citl_transcribe_lecture.py): Records live audio via "
                "sounddevice, transcribes offline using Whisper (faster-whisper), then "
                "summarizes the lecture with an Ollama LLM. Saves transcripts to Documents.\n\n"
                "Translation (citl_translation.py): Fully offline translation via "
                "Argos Translate. Supports 30+ language pairs (~100 MB per pair, "
                "downloaded once). Zero cloud dependency.\n\n"
                " Text-to-Speech (citl_tts.py): Reads text aloud via pyttsx3  "
                "no internet, no API key, adjustable rate and volume.\n\n"
                " Accessibility Impact: Transcription + Translation + TTS together make "
                "classroom content accessible to students with hearing impairments, language "
                "barriers, or reading difficulties  fully on-premises, FERPA-compliant."
            ),
            "llm_tech": [
                ("Models",        "llama3.2, gemma3, mistral (user-configurable)"),
                ("Provider",      "Ollama  100% local, zero cloud dependency"),
                ("Architecture",  "Hybrid RAG: JSONL keyword index + Ollama embeddings"),
                ("Pipeline",      "Index  Retrieve (kw+embed)  Merge  Synthesize  Cite"),
                ("Transcription", "Whisper (faster-whisper)  runs CPU or GPU, fully offline"),
                ("Translation",   "Argos Translate  offline neural MT, 30+ language pairs"),
                ("TTS",           "pyttsx3  system TTS engine, no API needed"),
                ("Embeddings",    "nomic-embed-text via Ollama /api/embed"),
            ],
            "career_skills": [
                "RAG pipeline design and implementation",
                "Prompt engineering and context window management",
                "Local LLM deployment with Ollama and Modelfiles",
                "Python corpus indexing (JSONL + SQLite)",
                "Audio capture and offline ASR (Whisper / faster-whisper)",
                "Offline neural machine translation (Argos Translate)",
                "Accessible AI tool design (hearing, language, reading barriers)",
                "Cross-platform Python GUI development (tkinter/ttk)",
                "Human-in-the-loop answer validation workflows",
            ],
            "tech_stack": "Python 3.11    Ollama    Whisper    Argos Translate    pyttsx3    SQLite",
            "repo_path":    REPO,
            "launcher_win": REPO / "RUN_FACTBOOK_WINDOWS.cmd",
            "launcher_nix": REPO / "RUN_FACTBOOK.sh",
            "key_file":     REPO / "factbook-assistant" / "factbook_assistant_gui.py",
            "version_file": REPO / "FACTBOOK_VERSION.txt",
            "github_url":   "https://github.com/Citl-Dev-Ops/CITL---Desktop-LLM-EZ-Install-Kits",
        },

        #  2. LLM Studio Kit 
        {
            "id": "llm_studio",
            "name": "LLM Studio Kit",
            "author": "Abdo Mohamed, Wahaj al Obid, Mason Jones",
            "tagline": "Offline LLM Teaching Studio with Model Cookbook",
            "icon": "[STUDIO]",
            "description": (
                "CITL LLM Studio Kit is a Windows offline teaching environment that combines "
                "local LLM chat via Ollama, RAG over instructor documents, classroom audio "
                "transcription, and career-focused prompt templates  all in a dark-mode "
                "Tkinter GUI.\n\n"
                "Key capabilities:\n"
                " Local Ollama chat with automatic health check and startup\n"
                " RAG over .txt documents provided by the instructor\n"
                " Classroom audio capture + offline Whisper transcription\n"
                " Career prompt templates: IT Analyst, LLMOps Automation, "
                "Education Designer, and more\n"
                " JSON blueprint exporter for custom LLM utility interfaces\n"
                " Privacy-preserving audit trail and room-review workflow\n"
                " Portable bundle export for student-made utilities\n\n"
                f"Detected at: {studio or '(not found  insert USB with CITL-LLM-Studio-Kit)'}"
            ),
            "llm_tech": [
                ("Models",        "Any Ollama model (catalog includes AllenAI OLMo, Tulu, Mistral, Qwen, Llama)"),
                ("Provider",      "Ollama local API  automatic health check + service startup"),
                ("RAG",           "Document retrieval over instructor .txt files"),
                ("Transcription", "Classroom audio  Whisper offline ASR  LLM summary"),
                ("Templates",     "6 career templates, 3 deployment templates (Docker/K8s/LLMOps)"),
                ("Audit",         "Privacy-preserving room-review + timestamped session compiler"),
                ("Export",        "Portable bundles to %APPDATA%\\CITL\\llm_studio\\bundles"),
            ],
            "career_skills": [
                "LLM Modelfile authoring and parameter tuning",
                "Ollama model catalog navigation (OLMo, Tulu, Mistral, Qwen, Llama)",
                "RAG system design for classroom document retrieval",
                "Prompt template engineering for IT and education roles",
                "LLMOps automation workflow design",
                "Docker Compose and Kubernetes deployment templates for AI services",
                "AI audit trail and compliance documentation",
                "Portable AI utility development and distribution",
            ],
            "tech_stack": "Python 3.11    tkinter    Ollama    Whisper    PowerShell",
            "repo_path":    studio,
            "launcher_win": studio_launcher_win,
            "launcher_nix": None,
            "key_file":     (studio / "app" / "llm_studio_gui.py") if studio else None,
            "version_file": None,
            "install_win":  (studio / "scripts" / "install_citl_llm_studio_failsafe.ps1") if studio else None,
            "github_url":   None,
        },

        #  3. AI Training Hub 
        {
            "id": "ai_hub",
            "name": "AI Training Hub",
            "author": "CITL Dev Ops",
            "tagline": "Streamlit-Based Bot Builder & LLM Sandbox",
            "icon": "[HUB]",
            "description": (
                "The CITL AI Training Hub is a full Streamlit dashboard for building, "
                "testing, and deploying custom AI bots. It bundles LangChain, LangGraph, "
                "CrewAI, and ChromaDB into a single interface where students can compose "
                "multi-agent pipelines and export them as portable utilities.\n\n"
                "Launch opens a browser tab at http://localhost:8502 automatically.\n\n"
                "Key capabilities:\n"
                " Bot builder with schema editor and runtime testing\n"
                " RAG engine with ChromaDB vector store\n"
                " Multi-agent orchestration (CrewAI, LangGraph, AutoGen)\n"
                " Deployment demo CLI (Docker, cloud, local)\n"
                " Approved model registry with safety guidelines\n"
                " Export engine for student-built utilities\n\n"
                f"Detected at: {hub or '(not found on this machine)'}"
            ),
            "llm_tech": [
                ("Framework",     "Streamlit web dashboard  browser UI, no frontend build step"),
                ("Orchestration", "LangChain, LangGraph, CrewAI, AutoGen  multi-agent pipelines"),
                ("Vector store",  "ChromaDB with sentence-transformers embeddings"),
                ("Models",        "Configurable via approved_models.json  Ollama, OpenAI, Anthropic"),
                ("RAG",           "rag_engine.py  PDF/text ingestion + ChromaDB retrieval"),
                ("Deployment",    "Deployment demo CLI covering Docker Compose and cloud endpoints"),
                ("Port",          "localhost:8502 (configurable via AI_TRAINING_HUB_PORT)"),
            ],
            "career_skills": [
                "Streamlit dashboard and rapid AI prototyping",
                "LangChain / LangGraph multi-agent pipeline design",
                "ChromaDB vector store management",
                "CrewAI and AutoGen multi-agent orchestration",
                "Bot schema design and runtime testing",
                "AI model registry and safety policy enforcement",
                "Docker Compose AI service deployment",
                "RAG pipeline with PDF document ingestion",
            ],
            "tech_stack": "Python 3.11    Streamlit    LangChain    ChromaDB    CrewAI    FastAPI",
            "repo_path":    hub,
            "launcher_win": hub_exe or hub_launcher_win,
            "launcher_nix": (hub / "hub_launcher.py") if hub else None,
            "key_file":     (hub / "app" / "hub.py") if hub else None,
            "version_file": None,
            "github_url":   None,
        },

        #  4. Academic Advisor  LAST (in progress) 
        {
            "id": "academic_advisor",
            "name": "Academic Advisor",
            "author": "Wahaj Al Obid",
            "tagline": "AI Degree Audit & Student Advising  [Coming Soon]",
            "icon": "[ADVISOR]",
            "description": (
                "The CITL Academic Advisor is a full-stack AI advising assistant. It parses "
                "CTCLink/SBCTC class schedule data, audits student transcripts against degree "
                "requirements, and answers natural-language advising questions  all with Ollama "
                "running locally so no student data leaves the institution.\n\n"
                "Students interact via a React 19/Vite web UI; the FastAPI backend handles "
                "document parsing, schedule indexing, and LLM orchestration. "
                "Human-in-the-loop confirmation gates every audit result.\n\n"
                " This app is actively being developed. It will sync automatically from "
                "whichever copy of the repo is found  either the local C: installation or "
                "a USB drive with the repo. Drive letters are detected automatically.\n\n"
                f"Currently detected at: {advisor or '(not found  check USB or local install)'}"
            ),
            "llm_tech": [
                ("Models",       "qwen2.5:7b (primary), Modelfile-configurable"),
                ("Provider",     "Ollama  fully local, on-premises"),
                ("Architecture", "Structured document RAG + CTCLink schedule indexing"),
                ("Pipeline",     "PDF/JSON parse  SQLite index  LLM query  React UI"),
                ("Context",      "Multi-turn advising conversation"),
                ("API layer",    "FastAPI REST + React 19/Vite frontend"),
            ],
            "career_skills": [
                "FastAPI REST backend development",
                "React 19 + TypeScript frontend engineering",
                "LLM Modelfile authoring and orchestration",
                "CTCLink / SBCTC student records parsing",
                "Human-in-the-loop audit workflow design",
                "SQLite + JSON data pipeline construction",
                "Vite build tooling and production deployment",
            ],
            "tech_stack": "Python 3.11    FastAPI    React 19    TypeScript    Vite    Ollama    SQLite",
            "repo_path":    advisor,
            "launcher_win": advisor_launcher,
            "launcher_nix": None,
            "key_file":     (advisor / "api" / "app.py") if advisor else None,
            "version_file": None,
            "github_url":   "https://github.com/Citl-Dev-Ops/rtc-academic-advisor",
        },

        #  6. Screen Recorder 
        {
            "id": "screen_recorder",
            "name": "CITL Screen Recorder",
            "author": "Abdo Mohammad",
            "tagline": "Window-capture demo recorder for CITL apps",
            "icon": "[REC]",
            "description": (
                "GNU/LGPL-licensed screen capture tool for recording demonstration "
                "videos of any CITL application window.\n\n"
                "Built on FFmpeg (LGPL 2.1)  captures only the target CITL app "
                "window, never the full desktop.\n\n"
                "Export formats:\n"
                "   MP4 (H.264/AAC)   universal, best for LMS / presentations\n"
                "   WebM (VP9/Opus)   open standard, excellent quality\n"
                "   MKV (H.264/AAC)   best archive container\n"
                "   AVI (HuffYUV)     lossless, edit-ready master\n"
                "   MOV (H.264)       Apple / Keynote compatible\n"
                "   GIF (animated)    silent short loops for documentation\n\n"
                "Features:\n"
                "   Launch any CITL app and begin recording in one click\n"
                "   Enumerate open CITL windows automatically\n"
                "   Optional DirectShow audio capture (microphone or loopback)\n"
                "   GIF converter from any existing recording\n"
                "   Headless PS1 script for automated recording pipelines\n\n"
                "FFmpeg license: LGPL 2.1    https://ffmpeg.org/legal.html"
            ),
            "llm_tech": [
                ("Tool",    "FFmpeg  (LGPL 2.1)"),
                ("Capture", "gdigrab  Windows GDI screen capture, window-specific"),
                ("Video",   "libx264, libvpx-vp9, huffyuv, gif"),
                ("Audio",   "AAC, Opus, PCM via DirectShow"),
                ("Control", "Python subprocess + tkinter GUI"),
            ],
            "career_skills": [
                "Creating professional software demo recordings",
                "FFmpeg command-line video production",
                "Animated GIF generation for documentation",
                "Lossless-to-lossy export pipelines",
                "Windows GDI screen-capture integration",
            ],
            "tech_stack": "Python 3.11    FFmpeg (LGPL)    gdigrab    tkinter",
            "repo_path":    REPO,
            "launcher_win": REPO / "factbook-assistant" / "citl_screen_recorder.py",
            "launcher_nix": REPO / "factbook-assistant" / "citl_screen_recorder.py",
            "key_file":     REPO / "factbook-assistant" / "citl_screen_recorder.py",
            "version_file": None,
            "github_url":   "",
        },

        #  7. Document Composer 
        {
            "id": "doc_composer",
            "name": "CITL Doc Composer",
            "author": "Abdo Mohammad",
            "tagline": "AI-powered technical manual and tutorial generator",
            "icon": "[DOC]",
            "description": (
                "Generates professionally styled CITL technical documents  manuals, "
                "walkthroughs, tutorials, quick-reference cards, and installation guides.\n\n"
                "Uses the most powerful Ollama model installed on the device (ranked by "
                "parameter count and blob size) to fill every document section from a "
                "single topic prompt.\n\n"
                "Typography:\n"
                "   Body:     Berthold Baskerville  (from CITL reader-pack)\n"
                "   Headings: Cheltenham Bold\n"
                "   Captions: Franklin Gothic Book\n"
                "   Fallback: Georgia (if pack fonts not installed)\n\n"
                "Colors: CITL red-orange (#CC3300) + slate (#334D6E)\n\n"
                "Export: Fully styled .docx with cover page, section headings, "
                "red-orange rule bars, callout boxes (TIP / NOTE / WARNING), "
                "numbered step lists, header, and footer.\n\n"
                "Templates: Technical Manual  App Walkthrough  Training Tutorial  "
                "Quick Reference Card  Installation Guide"
            ),
            "llm_tech": [
                ("Model",    "Best Ollama model auto-detected by param count + blob size"),
                ("API",      "Ollama /api/generate    streaming, local, zero cloud"),
                ("Prompts",  "Per-section professional technical writing prompts"),
                ("Output",   "python-docx    fully styled .docx"),
                ("Fonts",    "Berthold Baskerville + Cheltenham + Franklin Gothic"),
            ],
            "career_skills": [
                "Technical writing and documentation standards",
                "LLM-assisted content generation workflows",
                "python-docx programmatic document creation",
                "CITL brand identity application in print",
                "Prompt engineering for structured long-form output",
            ],
            "tech_stack": "Python 3.11    Ollama    python-docx    tkinter",
            "repo_path":    REPO,
            "launcher_win": REPO / "factbook-assistant" / "citl_doc_composer.py",
            "launcher_nix": REPO / "factbook-assistant" / "citl_doc_composer.py",
            "key_file":     REPO / "factbook-assistant" / "citl_doc_composer.py",
            "version_file": None,
            "github_url":   "",
        },
        {
            "id": "technical_writer_creator",
            "name": "CITL Technical Writing and Tutorial Creator",
            "author": "CITL Team",
            "tagline": "Unified hub for writing, screenshots, recording, and tutorial publishing",
            "icon": "[TUTORIAL]",
            "description": (
                "Comprehensive production workspace that combines technical writing, "
                "screenshot organization, LLM-assisted formatting, screen recording, and "
                "video post-editing in one guided workflow.\n\n"
                "Use it to build professional handouts, step-by-step manuals, tutorial "
                "walkthroughs, and OneNote-ready article drafts from a single project "
                "workspace folder.\n\n"
                "Integrated launch path:\n"
                "   CITL Screen Recorder -> CITL Video Post Editor -> CITL Doc Composer\n\n"
                "Includes screenshot indexing, markdown export, and model-assisted "
                "technical rewrite for raw notes."
            ),
            "llm_tech": [
                ("Model", "Best local Ollama model (user-selectable)"),
                ("LLM task", "Auto-format raw notes into structured walkthroughs"),
                ("Output", "OneNote markdown + Doc Composer seed content"),
                ("Workflow", "Writer -> Screenshot map -> Recording -> Post-edit"),
            ],
            "career_skills": [
                "Technical writing for operational runbooks",
                "Instructional design for software tutorials",
                "LLM-assisted editorial workflows",
                "Screen recording and post-production coordination",
                "Cross-format publishing (markdown/docx/video)",
            ],
            "tech_stack": "Python 3.11    tkinter    Ollama    FFmpeg",
            "repo_path":    REPO,
            "launcher_win": REPO / "factbook-assistant" / "citl_technical_writing_tutorial_creator.py",
            "launcher_nix": REPO / "factbook-assistant" / "citl_technical_writing_tutorial_creator.py",
            "key_file":     REPO / "factbook-assistant" / "citl_technical_writing_tutorial_creator.py",
            "version_file": None,
            "github_url":   "",
        },
        {
            "id": "database_llmops_builder",
            "name": "CITL Database LLMOps Builder",
            "author": "CITL Team",
            "tagline": "Wizard that exports complete runnable custom AI apps",
            "icon": "[BUILDER]",
            "description": (
                "Creates portfolio-ready custom AI applications with a guided wizard that "
                "exports Python app code, Modelfile, README, launchers, and corpus package.\n\n"
                "Use this to rapidly produce specialized assistants for departments, "
                "operations, and project demonstrations."
            ),
            "llm_tech": [
                ("Models", "Ollama local models (user-selected base model)"),
                ("Output", "Generated Python GUI + Modelfile + corpus package"),
                ("Config", "System prompt, context window, temperature"),
                ("Export", "ZIP-ready application bundle for transfer/demo"),
            ],
            "career_skills": [
                "LLMOps configuration and packaging",
                "Prompt and system policy design",
                "App templating and software scaffolding",
                "Technical documentation for deployment handoff",
            ],
            "tech_stack": "Python 3.11    tkinter    Ollama",
            "repo_path":    REPO,
            "launcher_win": REPO / "RUN_DATABASE_LLMOPS_BUILDER_WINDOWS.cmd",
            "launcher_nix": REPO / "RUN_DATABASE_LLMOPS_BUILDER.sh",
            "key_file":     REPO / "factbook-assistant" / "citl_database_llmops_builder.py",
            "version_file": None,
            "github_url":   "",
        },
        {
            "id": "av_it_ops",
            "name": "CITL AV IT Operations",
            "author": "CITL Team",
            "tagline": "Inventory, inspection, and patch documentation workflows",
            "icon": "[AV-IT]",
            "description": (
                "Operational utility for classroom/lab technology support with room inventory, "
                "inspection checklists, and patch procedure documentation exports."
            ),
            "llm_tech": [
                ("Workflow", "Structured checklist and reporting pipeline"),
                ("Exports", "CSV + text reports for audit trails"),
                ("Use case", "AV support operations and maintenance logs"),
            ],
            "career_skills": [
                "IT operations documentation",
                "Asset inventory management",
                "Inspection and compliance reporting",
                "Patch planning and communication",
            ],
            "tech_stack": "Python 3.11    tkinter",
            "repo_path":    REPO,
            "launcher_win": REPO / "RUN_AV_IT_OPS_WINDOWS.cmd",
            "launcher_nix": REPO / "RUN_AV_IT_OPS.sh",
            "key_file":     REPO / "factbook-assistant" / "citl_av_it_ops.py",
            "version_file": None,
            "github_url":   "",
        },
        {
            "id": "staff_toolkit",
            "name": "CITL Work and Preparedness Launcher",
            "author": "CITL Team",
            "tagline": "Multi-app launcher for work readiness and project execution",
            "icon": "[STAFF]",
            "description": (
                "Professional launcher that organizes CITL workflows into four tracks: "
                "LLMOps IT Admin, AV IT Operations, E-Learning Technologies, and "
                "Technical Writing and Instruction.\n\n"
                "Includes quick links for SharePoint, Office 365, and local file "
                "database resources when configured."
            ),
            "llm_tech": [
                ("Tracks", "Role-based launch paths and guided outcomes"),
                ("Coverage", "Links into LLMOps, docs, AV ops, and tutorial tools"),
                ("Output", "Portfolio-oriented task and project pathways"),
            ],
            "career_skills": [
                "Cross-functional technical workflow coordination",
                "Toolchain navigation and deployment readiness",
                "Documentation and project portfolio planning",
                "Human-in-the-loop operational execution",
            ],
            "tech_stack": "Python 3.11    tkinter",
            "repo_path":    REPO,
            "launcher_win": REPO / "RUN_WORK_PREPAREDNESS_LAUNCHER_WINDOWS.cmd",
            "launcher_nix": REPO / "RUN_WORK_PREPAREDNESS_LAUNCHER.sh",
            "key_file":     REPO / "factbook-assistant" / "citl_staff_toolkit.py",
            "version_file": None,
            "github_url":   "",
        },
    ]


# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
# GUI
# aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

class LLMOpsSuite:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.apps = _build_apps()
        self._work_tool_app = next(
            (a for a in self.apps if str(a.get("id") or "").strip().lower() == "staff_toolkit"),
            None,
        )
        self._selected: int = 0        # -1 = system panel
        self._btn_widgets: List[tk.Button] = []
        self._sys_btn: Optional[tk.Button] = None
        self._auto_var   = tk.StringVar(value="watching")
        self._status_var = tk.StringVar(value="Ready.")
        self._watcher_mtime: Dict[str, float] = {}
        self._recorder_autostart_var = tk.BooleanVar(value=False)

        self.root.title(f"{SUITE_NAME}  {SUITE_VERSION}")
        self.root.configure(bg=C["bg"])
        sw = max(1024, self.root.winfo_screenwidth())
        sh = max(768, self.root.winfo_screenheight())
        w = max(980, min(1480, sw - 80))
        h = max(700, min(940, sh - 120))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(980, 680)
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(350, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except Exception:
            pass

        self.root.rowconfigure(2, weight=1)
        self.root.columnconfigure(0, weight=1)

        self._ttk_style()
        self._build_header()
        self._build_selector()
        self._build_body()
        self._build_statusbar()

        self._select_app(0)
        self.root.after(3000, self._start_watcher)

    #  ttk Style 
    def _ttk_style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("Suite.TNotebook", background=C["bg"], borderwidth=0)
        s.configure("Suite.TNotebook.Tab",
                    background=C["panel"], foreground=C["muted"],
                    padding=[18, 8], font=(_F, 10, "bold"), borderwidth=0)
        s.map("Suite.TNotebook.Tab",
              background=[("selected", C["card_sel"]), ("active", C["btn_hi"])],
              foreground=[("selected", C["text"]),     ("active", C["text"])])
        # Scrollbar: configure base TScrollbar only (no custom layout name)
        try:
            s.configure("TScrollbar",
                        background=C["panel"], troughcolor=C["bg"],
                        borderwidth=0, relief="flat")
        except tk.TclError:
            pass

    #  Header 
    def _build_header(self):
        hdr = tk.Frame(self.root, bg=C["panel"])
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(0, weight=1)
        tk.Frame(hdr, bg=C["accent"], height=4).grid(row=0, column=0, columnspan=2, sticky="ew")
        inner = tk.Frame(hdr, bg=C["panel"], padx=24, pady=14)
        inner.grid(row=1, column=0, sticky="ew")
        inner.columnconfigure(0, weight=1)
        tk.Label(inner, text=SUITE_NAME, font=(_F, 22, "bold"),
                 bg=C["panel"], fg=C["text"]).grid(row=0, column=0, sticky="w")
        tk.Label(inner, text=SUITE_TAGLINE, font=(_F, 10),
                 bg=C["panel"], fg=C["muted"]).grid(row=1, column=0, sticky="w")
        right = tk.Frame(inner, bg=C["panel"])
        right.grid(row=0, column=1, rowspan=2, sticky="e")
        tk.Label(right, text=SUITE_VERSION, font=(_F, 11, "bold"),
                 bg=C["panel"], fg=C["accent"]).pack(anchor="e")
        tk.Checkbutton(
            right,
            text="Auto-start Recorder on Launch",
            variable=self._recorder_autostart_var,
            bg=C["panel"],
            fg=C["muted"],
            activebackground=C["panel"],
            activeforeground=C["text"],
            selectcolor=C["panel"],
            font=(_F, 9),
        ).pack(anchor="e", pady=(2, 0))
        tk.Label(right, textvariable=self._auto_var, font=(_F, 9),
                 bg=C["panel"], fg=C["faint"]).pack(anchor="e")

    #  Selector Bar 
    def _build_selector(self):
        bar = tk.Frame(self.root, bg=C["panel_alt"], padx=14, pady=10)
        bar.grid(row=1, column=0, sticky="ew")
        tk.Label(bar, text="APPS:", font=(_F, 9, "bold"),
                 bg=C["panel_alt"], fg=C["faint"]).pack(side="left", padx=(0, 8))
        self._btn_widgets = []
        for i, app in enumerate(self.apps):
            btn = tk.Button(bar,
                text=f"  {app['icon']}  {app['name']}  ",
                font=(_F, 11, "bold"),
                bg=C["btn"], fg=C["muted"],
                activebackground=C["btn_hi"], activeforeground=C["text"],
                relief="flat", bd=0, cursor="hand2", padx=10, pady=7,
                command=lambda idx=i: self._select_app(idx))
            btn.pack(side="left", padx=3)
            self._btn_widgets.append(btn)
        # Separator
        tk.Frame(bar, bg=C["border"], width=2).pack(side="left", fill="y",
                                                     padx=(14, 8), pady=2)
        # System & Models button
        self._sys_btn = tk.Button(bar,
            text="    System & Models  ",
            font=(_F, 11, "bold"),
            bg=C["btn"], fg=C["muted"],
            activebackground=C["btn_hi"], activeforeground=C["text"],
            relief="flat", bd=0, cursor="hand2", padx=10, pady=7,
            command=self._select_system)
        self._sys_btn.pack(side="left", padx=3)
        tk.Frame(self.root, bg=C["border"], height=1).grid(row=1, column=0, sticky="sew")

    #  Body 
    def _build_body(self):
        body = tk.Frame(self.root, bg=C["bg"])
        body.grid(row=2, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, minsize=340)
        body.columnconfigure(1, minsize=1)
        body.columnconfigure(2, weight=1)
        self._body = body
        self._card_frame = tk.Frame(body, bg=C["panel"], width=340)
        self._card_frame.grid(row=0, column=0, sticky="nsew")
        self._card_frame.grid_propagate(False)
        tk.Frame(body, bg=C["border"], width=1).grid(row=0, column=1, sticky="ns")
        self._detail_frame = tk.Frame(body, bg=C["notebk"])
        self._detail_frame.grid(row=0, column=2, sticky="nsew")
        self._detail_frame.rowconfigure(0, weight=1)
        self._detail_frame.columnconfigure(0, weight=1)

    #  Status Bar 
    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C["panel"], padx=16, pady=5)
        bar.grid(row=3, column=0, sticky="ew")
        tk.Frame(bar, bg=C["border"], height=1).pack(side="top", fill="x", pady=(0, 4))
        tk.Label(bar, textvariable=self._status_var, font=(_F, 9),
                 bg=C["panel"], fg=C["muted"], anchor="w").pack(side="left", fill="x", expand=True)
        tk.Button(bar, text="  Open Work Tool", font=(_F, 9, "bold"),
                  bg=C["btn_accent"], fg=C["text"],
                  activebackground=C["btn_hi"], activeforeground=C["text"],
                  relief="flat", cursor="hand2", padx=10, pady=2,
                  command=self._launch_work_tool_direct
                  ).pack(side="right", padx=4)
        tk.Button(bar, text="  Refresh", font=(_F, 9),
                  bg=C["btn"], fg=C["muted"],
                  activebackground=C["btn_hi"], activeforeground=C["text"],
                  relief="flat", cursor="hand2", padx=8, pady=2,
                  command=lambda: threading.Thread(
                      target=self._refresh_status, daemon=True).start()
                  ).pack(side="right", padx=4)

    #  Selection 
    def _select_app(self, idx: int):
        self._selected = idx
        for i, btn in enumerate(self._btn_widgets):
            btn.config(bg=C["card_sel"] if i == idx else C["btn"],
                       fg=C["text"]    if i == idx else C["muted"])
        self._sys_btn.config(bg=C["btn"], fg=C["muted"])
        self._render_card(self.apps[idx])
        self._render_detail(self.apps[idx])

    def _select_system(self):
        self._selected = -1
        for btn in self._btn_widgets:
            btn.config(bg=C["btn"], fg=C["muted"])
        self._sys_btn.config(bg=C["card_sel"], fg=C["text"])
        self._render_system_card()
        self._render_system_detail()

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # App Card + Detail
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

    def _render_card(self, app: dict):
        for w in self._card_frame.winfo_children():
            w.destroy()
        f = self._card_frame
        tk.Frame(f, bg=C["accent"], height=4).pack(fill="x")
        inner = tk.Frame(f, bg=C["panel"], padx=18, pady=18)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text=app["icon"], font=(_F, 30),
                 bg=C["panel"], fg=C["text"]).pack(anchor="w")
        tk.Label(inner, text=app["name"], font=(_F, 16, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(anchor="w")
        tk.Label(inner, text=f"by {app['author']}", font=(_F, 9),
                 bg=C["panel"], fg=C["muted"]).pack(anchor="w")
        tk.Label(inner, text=app["tagline"], font=(_F, 10, "italic"),
                 bg=C["panel"], fg=C["accent"], wraplength=290, justify="left"
                 ).pack(anchor="w", pady=(2, 10))
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x", pady=(0, 10))

        installed = self._is_installed(app)
        badge = tk.Frame(inner, bg=C["tag"], padx=8, pady=4)
        badge.pack(anchor="w", pady=(0, 4))
        tk.Label(badge,
                 text="  Installed" if installed else "  Not Found",
                 font=(_F, 10, "bold"),
                 bg=C["tag"], fg=C["good"] if installed else C["danger"]
                 ).pack()

        ver = self._read_version(app)
        if ver:
            tk.Label(inner, text=f"Version: {ver}", font=(_F, 9),
                     bg=C["panel"], fg=C["muted"]).pack(anchor="w")

        ts = tk.Frame(inner, bg=C["tag"], padx=6, pady=4)
        ts.pack(anchor="w", pady=(8, 12), fill="x")
        tk.Label(ts, text=app["tech_stack"], font=(_F, 8),
                 bg=C["tag"], fg=C["faint"], wraplength=290, justify="left").pack(anchor="w")

        def _btn(label, bg, cmd, enabled=True):
            b = tk.Button(inner, text=label, font=(_F, 10, "bold"),
                          bg=bg, fg=C["text"] if enabled else C["faint"],
                          activebackground=C["btn_hi"], activeforeground=C["text"],
                          relief="flat", cursor="hand2" if enabled else "arrow",
                          pady=7, padx=0,
                          state="normal" if enabled else "disabled",
                          command=cmd)
            b.pack(fill="x", pady=2)

        _btn("  Launch App",          C["btn_accent"],  lambda: self._launch(app),         installed)
        _btn("  Install / Update",     C["btn"],          lambda: self._install_update(app))
        _btn("  Open Folder",          C["btn"],          lambda: self._open_folder(app),    bool(app.get("repo_path")))

    def _render_detail(self, app: dict):
        for w in self._detail_frame.winfo_children():
            w.destroy()
        nb = ttk.Notebook(self._detail_frame, style="Suite.TNotebook")
        nb.pack(fill="both", expand=True)
        t1 = tk.Frame(nb, bg=C["notebk"]); nb.add(t1, text="   About   ")
        t2 = tk.Frame(nb, bg=C["notebk"]); nb.add(t2, text="   LLM Technology   ")
        t3 = tk.Frame(nb, bg=C["notebk"]); nb.add(t3, text="   Career Readiness   ")
        self._tab_about(t1, app)
        self._tab_llm(t2, app)
        self._tab_career(t3, app)

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # System / Ollama Panel
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

    def _render_system_card(self):
        for w in self._card_frame.winfo_children():
            w.destroy()
        f = self._card_frame
        tk.Frame(f, bg=C["accent"], height=4).pack(fill="x")
        inner = tk.Frame(f, bg=C["panel"], padx=18, pady=18)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text="", font=(_F, 30), bg=C["panel"], fg=C["accent"]).pack(anchor="w")
        tk.Label(inner, text="System & Models", font=(_F, 15, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(anchor="w")
        tk.Label(inner, text="GPU  RAM  CPU  Ollama status",
                 font=(_F, 9), bg=C["panel"], fg=C["muted"]).pack(anchor="w", pady=(0, 10))
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x", pady=(0, 12))

        self._sys_labels: Dict[str, tk.StringVar] = {k: tk.StringVar(value="...") for k in
                                                       ["gpu", "vram", "ram", "cpu", "ollama", "models"]}

        rows = [
            ("GPU",    "gpu"),
            ("VRAM",   "vram"),
            ("RAM",    "ram"),
            ("CPU",    "cpu"),
            ("Ollama", "ollama"),
            ("Models", "models"),
        ]
        for label, key in rows:
            row = tk.Frame(inner, bg=C["panel"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{label}:", font=(_F, 9, "bold"),
                     bg=C["panel"], fg=C["muted"], width=8, anchor="e").pack(side="left", padx=(0, 6))
            tk.Label(row, textvariable=self._sys_labels[key], font=(_F, 9),
                     bg=C["panel"], fg=C["text"], wraplength=220, justify="left",
                     anchor="w").pack(side="left")

        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x", pady=10)
        tk.Button(inner, text="  Refresh System Info", font=(_F, 10, "bold"),
                  bg=C["btn"], fg=C["text"],
                  activebackground=C["btn_hi"], activeforeground=C["text"],
                  relief="flat", cursor="hand2", pady=7,
                  command=lambda: threading.Thread(
                      target=self._probe_system, daemon=True).start()
                  ).pack(fill="x", pady=2)

        threading.Thread(target=self._probe_system, daemon=True).start()

    def _probe_system(self):
        gpu_name, vram = _get_gpu_info()
        ram = _get_ram_gb()
        cpu = _get_cpu_info()
        ollama = _check_ollama()

        def upd():
            if not hasattr(self, "_sys_labels"):
                return
            self._sys_labels["gpu"].set(gpu_name)
            self._sys_labels["vram"].set(f"{vram:.1f} GB" if vram else "Not detected")
            self._sys_labels["ram"].set(f"{ram:.1f} GB" if ram else "Unknown")
            self._sys_labels["cpu"].set(cpu)
            if ollama["running"]:
                self._sys_labels["ollama"].set(f"Running  v{ollama['version']}")
            else:
                self._sys_labels["ollama"].set("Not running")
            if ollama["models"]:
                self._sys_labels["models"].set("\n".join(ollama["models"][:8]))
            else:
                self._sys_labels["models"].set("None pulled yet")
        self.root.after(0, upd)

    def _render_system_detail(self):
        for w in self._detail_frame.winfo_children():
            w.destroy()
        nb = ttk.Notebook(self._detail_frame, style="Suite.TNotebook")
        nb.pack(fill="both", expand=True)

        t1 = tk.Frame(nb, bg=C["notebk"]); nb.add(t1, text="   Model Cookbook   ")
        t2 = tk.Frame(nb, bg=C["notebk"]); nb.add(t2, text="   AllenAI Models   ")
        t3 = tk.Frame(nb, bg=C["notebk"]); nb.add(t3, text="   What Are LLMs   ")

        self._tab_cookbook(t1)
        self._tab_allenai(t2)
        self._tab_llm_explainer(t3)

    def _tab_cookbook(self, frame: tk.Frame):
        _, inner = self._scrollable(frame)
        p = tk.Frame(inner, bg=C["notebk"], padx=28, pady=22)
        p.pack(fill="both", expand=True)
        tk.Label(p, text="Model Cookbook - Which Model for Which Purpose",
                 font=(_F, 14, "bold"), bg=C["notebk"], fg=C["accent"]
                 ).pack(anchor="w", pady=(0, 4))
        tk.Label(p,
                 text="Choose based on your available VRAM. When in doubt, start with the "
                      "8 GB tier - it covers most CITL use cases.",
                 font=(_F, 10), bg=C["notebk"], fg=C["muted"],
                 wraplength=740, justify="left").pack(anchor="w", pady=(0, 16))

        for tier in MODEL_COOKBOOK:
            card = tk.Frame(p, bg=C["card"], padx=14, pady=12)
            card.pack(fill="x", pady=6)
            fg_tier = C.get(tier["color"], C["text"])
            tk.Label(card, text=tier["tier"], font=(_F, 11, "bold"),
                     bg=C["card"], fg=fg_tier).pack(anchor="w")
            # Models chips row
            chips = tk.Frame(card, bg=C["card"])
            chips.pack(anchor="w", pady=(4, 6))
            for m in tier["models"]:
                chip = tk.Frame(chips, bg=C["tag"], padx=6, pady=2)
                chip.pack(side="left", padx=(0, 4), pady=2)
                tk.Label(chip, text=m, font=(_F, 8, "bold"),
                         bg=C["tag"], fg=C["accent"]).pack()
            # Best for
            for s in tier["best_for"]:
                row = tk.Frame(card, bg=C["card"])
                row.pack(anchor="w")
                tk.Label(row, text="-", font=(_F, 9), bg=C["card"], fg=C["accent"]
                         ).pack(side="left", padx=(0, 6))
                tk.Label(row, text=s, font=(_F, 10), bg=C["card"], fg=C["text"]
                         ).pack(side="left")
            tk.Label(card, text=f"Avoid for: {tier['avoid_for']}",
                     font=(_F, 9, "italic"), bg=C["card"], fg=C["faint"],
                     wraplength=680, justify="left").pack(anchor="w", pady=(4, 0))

    def _tab_allenai(self, frame: tk.Frame):
        _, inner = self._scrollable(frame)
        p = tk.Frame(inner, bg=C["notebk"], padx=28, pady=22)
        p.pack(fill="both", expand=True)
        tk.Label(p, text="AllenAI Open Models - Best for Education",
                 font=(_F, 14, "bold"), bg=C["notebk"], fg=C["accent"]
                 ).pack(anchor="w", pady=(0, 8))
        tk.Label(p,
                 text="AllenAI (Allen Institute for AI) publishes fully open-weight models "
                      "- training data, code, and checkpoints all public. This makes them "
                      "ideal for education: students can inspect exactly what the model learned "
                      "and why it gives the answers it does.",
                 font=(_F, 10), bg=C["notebk"], fg=C["muted"],
                 wraplength=740, justify="left").pack(anchor="w", pady=(0, 18))

        for m in ALLENAI_MODELS:
            card = tk.Frame(p, bg=C["card"], padx=14, pady=14)
            card.pack(fill="x", pady=6)
            tk.Label(card, text=m["full"], font=(_F, 12, "bold"),
                     bg=C["card"], fg=C["text"]).pack(anchor="w")
            tk.Label(card, text=m["why"], font=(_F, 10),
                     bg=C["card"], fg=C["muted"], wraplength=680, justify="left"
                     ).pack(anchor="w", pady=(4, 8))
            pull_row = tk.Frame(card, bg=C["tag"], padx=10, pady=6)
            pull_row.pack(anchor="w")
            tk.Label(pull_row, text="Pull command:", font=(_F, 9), bg=C["tag"],
                     fg=C["faint"]).pack(side="left", padx=(0, 8))
            tk.Label(pull_row, text=m["pull"], font=("Consolas" if sys.platform == "win32" else "monospace", 10, "bold"),
                     bg=C["tag"], fg=C["accent"]).pack(side="left")
            tk.Button(card, text="  Copy pull command", font=(_F, 9),
                      bg=C["btn"], fg=C["muted"],
                      activebackground=C["btn_hi"], activeforeground=C["text"],
                      relief="flat", cursor="hand2", padx=8, pady=3,
                      command=lambda cmd=m["pull"]: self._copy_to_clipboard(cmd)
                      ).pack(anchor="w", pady=(6, 0))

        tk.Frame(p, bg=C["sep"], height=1).pack(fill="x", pady=18)
        tk.Label(p, text="How to Pull Any Ollama Model", font=(_F, 12, "bold"),
                 bg=C["notebk"], fg=C["warn"]).pack(anchor="w", pady=(0, 8))
        tk.Label(p,
                 text="Open a terminal and run:  ollama pull <model-name>\n"
                      "Example:  ollama pull qwen2.5:7b\n\n"
                      "To see what's installed:  ollama list\n"
                      "To remove a model:        ollama rm <model-name>\n\n"
                      "Models are stored in %USERPROFILE%\\.ollama\\models (Windows) "
                      "or ~/.ollama/models (Linux). Typical size: 4-8 GB per 7B model.",
                 font=("Consolas" if sys.platform == "win32" else "monospace", 10),
                 bg=C["notebk"], fg=C["muted"],
                 wraplength=740, justify="left").pack(anchor="w")

    def _tab_llm_explainer(self, frame: tk.Frame):
        _, inner = self._scrollable(frame)
        p = tk.Frame(inner, bg=C["notebk"], padx=28, pady=22)
        p.pack(fill="both", expand=True)
        tk.Label(p, text="What Are LLMs and How Do They Work",
                 font=(_F, 14, "bold"), bg=C["notebk"], fg=C["accent"]
                 ).pack(anchor="w", pady=(0, 14))

        sections = [
            ("Text-Only LLMs",
             "Text-only LLMs (like Llama, Mistral, OLMo, Qwen) take text as input and "
             "produce text as output. They are trained on massive text corpora and learn "
             "to predict the next token (word piece) given the previous context. "
             "CITL uses these for Q&A, summarization, advising, and translation."),
            ("Multimodal LLMs (Vision + Text)",
             "Multimodal models (like LLaVA, Gemma3, Moondream) accept images AND text "
             "as input. They can describe a photo, read text in an image, analyze a "
             "diagram, or answer questions about a slide. Useful for accessibility "
             "(describe lab equipment, whiteboard content) and visual Q&A."),
            ("Embedding Models  (For Search)",
             "Embedding models (nomic-embed-text, mxbai-embed-large) convert text into "
             "numerical vectors that capture semantic meaning. They do NOT generate text; "
             "instead they power the 'find similar passages' step in RAG. Factbook "
             "uses nomic-embed-text to find the most relevant document chunks before "
             "passing them to the LLM for synthesis."),
            ("Institutional / Archival LLMs",
             "Larger models (14B-70B) with long context windows are used for "
             "institutional knowledge bases - indexing policy documents, multi-year "
             "curriculum archives, or cross-department records. They require more VRAM "
             "(16-24+ GB) but can reason across very long documents. Smaller quantized "
             "versions (q4/q5) reduce memory at some quality cost."),
            ("Human-in-the-Loop: Why It Matters",
             "No CITL application acts autonomously. Every AI-generated answer, audit, "
             "translation, or recommendation requires a human to review and approve before "
             "it is acted upon. This is LLMOps best practice: AI surfaces options and "
             "drafts; humans decide. Students who understand this distinction are ready "
             "for real IT operations roles in any AI-adjacent field."),
        ]
        for title, body in sections:
            tk.Label(p, text=title, font=(_F, 11, "bold"),
                     bg=C["notebk"], fg=C["warn"]).pack(anchor="w", pady=(10, 4))
            tk.Label(p, text=body, font=(_F, 10),
                     bg=C["notebk"], fg=C["text"], wraplength=740, justify="left"
                     ).pack(anchor="w")
            tk.Frame(p, bg=C["sep"], height=1).pack(fill="x", pady=(8, 0))

    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    # Shared tab renderers
    # aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

    def _tab_about(self, frame: tk.Frame, app: dict):
        _, inner = self._scrollable(frame)
        p = tk.Frame(inner, bg=C["notebk"], padx=30, pady=26)
        p.pack(fill="both", expand=True)
        tk.Label(p, text="About This App", font=(_F, 14, "bold"),
                 bg=C["notebk"], fg=C["accent"]).pack(anchor="w", pady=(0, 10))
        tk.Label(p, text=app["description"], font=(_F, 11),
                 bg=C["notebk"], fg=C["text"],
                 wraplength=740, justify="left").pack(anchor="w")
        tk.Frame(p, bg=C["sep"], height=1).pack(fill="x", pady=22)
        tk.Label(p, text="Human-in-the-Loop Principle", font=(_F, 12, "bold"),
                 bg=C["notebk"], fg=C["warn"]).pack(anchor="w", pady=(0, 8))
        tk.Label(p,
                 text="All CITL applications require a human to review and validate every "
                      "AI-generated output before it is acted upon. LLMs assist - they do "
                      "not decide. This prepares students for real-world IT and AI roles "
                      "where accountability, auditability, and explainability matter.",
                 font=(_F, 10), bg=C["notebk"], fg=C["muted"],
                 wraplength=740, justify="left").pack(anchor="w")

    def _tab_llm(self, frame: tk.Frame, app: dict):
        _, inner = self._scrollable(frame)
        p = tk.Frame(inner, bg=C["notebk"], padx=30, pady=26)
        p.pack(fill="both", expand=True)
        tk.Label(p, text="LLM Technology Stack", font=(_F, 14, "bold"),
                 bg=C["notebk"], fg=C["accent"]).pack(anchor="w", pady=(0, 16))
        grid = tk.Frame(p, bg=C["notebk"])
        grid.pack(anchor="w", fill="x")
        grid.columnconfigure(1, weight=1)
        for i, (key, val) in enumerate(app["llm_tech"]):
            row_bg = C["card"] if i % 2 == 0 else C["notebk"]
            row = tk.Frame(grid, bg=row_bg, padx=6, pady=6)
            row.grid(row=i, column=0, columnspan=2, sticky="ew", pady=1)
            row.columnconfigure(1, weight=1)
            tk.Label(row, text=f"{key}:", font=(_F, 10, "bold"),
                     bg=row_bg, fg=C["muted"], width=16, anchor="e"
                     ).grid(row=0, column=0, padx=(0, 14), sticky="ne")
            tk.Label(row, text=val, font=(_F, 10),
                     bg=row_bg, fg=C["text"],
                     wraplength=560, justify="left"
                     ).grid(row=0, column=1, sticky="nw")
        tk.Frame(p, bg=C["sep"], height=1).pack(fill="x", pady=22)
        tk.Label(p, text="Why Ollama for Local AI", font=(_F, 12, "bold"),
                 bg=C["notebk"], fg=C["warn"]).pack(anchor="w", pady=(0, 8))
        tk.Label(p,
                 text="Ollama exposes a REST API at localhost:11434 with /api/generate, "
                      "/api/chat, and /api/embed - the same interface patterns used by "
                      "OpenAI and Anthropic cloud APIs. Students learn real production "
                      "integration skills: streaming responses, token management, context "
                      "sizing, and graceful offline fallback - all transferable to any "
                      "cloud or on-premises AI role.",
                 font=(_F, 10), bg=C["notebk"], fg=C["muted"],
                 wraplength=740, justify="left").pack(anchor="w")

    def _tab_career(self, frame: tk.Frame, app: dict):
        _, inner = self._scrollable(frame)
        p = tk.Frame(inner, bg=C["notebk"], padx=30, pady=26)
        p.pack(fill="both", expand=True)
        tk.Label(p, text="IT Career Readiness Skills", font=(_F, 14, "bold"),
                 bg=C["notebk"], fg=C["accent"]).pack(anchor="w", pady=(0, 6))
        tk.Label(p, text="Working with this app, students develop:", font=(_F, 10),
                 bg=C["notebk"], fg=C["muted"]).pack(anchor="w", pady=(0, 12))
        for skill in app["career_skills"]:
            row = tk.Frame(p, bg=C["notebk"])
            row.pack(anchor="w", fill="x", pady=4)
            tk.Label(row, text="-", font=(_F, 10, "bold"),
                     bg=C["notebk"], fg=C["accent"]).pack(side="left", padx=(0, 10))
            tk.Label(row, text=skill, font=(_F, 11),
                     bg=C["notebk"], fg=C["text"]).pack(side="left")
        tk.Frame(p, bg=C["sep"], height=1).pack(fill="x", pady=22)
        tk.Label(p, text="Why LLMOps", font=(_F, 12, "bold"),
                 bg=C["notebk"], fg=C["warn"]).pack(anchor="w", pady=(0, 8))
        tk.Label(p,
                 text="LLMOps is the emerging discipline of deploying, monitoring, and "
                      "maintaining AI systems in production. IT professionals who understand "
                      "both the technical pipeline (RAG, embeddings, API integration) and "
                      "human oversight requirements (validation, audit trails, explainability) "
                      "are in high demand. CITL apps give students real LLMOps practice: "
                      "local model deployment, RAG tuning, prompt engineering, human "
                      "validation gates, version control, and cross-platform delivery.",
                 font=(_F, 10), bg=C["notebk"], fg=C["muted"],
                 wraplength=740, justify="left").pack(anchor="w")

    #  Scrollable canvas helper (plain ttk.Scrollbar  no custom style name) 
    def _scrollable(self, parent: tk.Frame) -> Tuple:
        canvas = tk.Canvas(parent, bg=C["notebk"], highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["notebk"])
        wid = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        inner.bind("<Configure>",  lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        # Mouse-wheel scroll  bound to canvas only, not all widgets
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
        return canvas, inner

    #  Actions 
    def _launch_work_tool_direct(self):
        app = self._work_tool_app
        if not app:
            messagebox.showwarning(SUITE_NAME, "CITL Work Tool entry is missing from app registry.")
            return
        self._launch(app)

    def _launch(self, app: dict):
        launcher = app.get("launcher_win") if sys.platform == "win32" else app.get("launcher_nix")
        if not launcher or not Path(launcher).exists():
            messagebox.showwarning(SUITE_NAME,
                f"Launcher not found for {app['name']}.\nExpected: {launcher}")
            return
        try:
            p = Path(launcher)
            if sys.platform == "win32":
                if p.suffix.lower() in (".cmd", ".bat", ".exe"):
                    os.startfile(str(p))
                elif p.suffix.lower() == ".ps1":
                    subprocess.Popen(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", str(p)],
                        cwd=str(p.parent), **_NO_WIN)
                elif p.suffix.lower() == ".py":
                    py = _venv_python()
                    subprocess.Popen([py, str(p)], cwd=str(p.parent), **_NO_WIN)
                else:
                    os.startfile(str(p))
            else:
                if p.suffix.lower() == ".py":
                    subprocess.Popen([sys.executable, str(p)], start_new_session=True)
                else:
                    subprocess.Popen(["bash", str(p)], start_new_session=True)
            self._set_status(f"Launched: {app['name']}")
            self._signal_recorder_target(app)
            if bool(self._recorder_autostart_var.get()):
                self._ensure_recorder_running(app)
        except Exception as exc:
            messagebox.showerror(SUITE_NAME, f"Launch failed:\n{exc}")

    def _install_update(self, app: dict):
        # LLM Studio Kit has its own installer
        if app["id"] == "llm_studio" and app.get("install_win"):
            inst = app["install_win"]
            if Path(inst).exists():
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", str(inst)], cwd=str(Path(inst).parent), **_NO_WIN)
                self._set_status("Running LLM Studio installer...")
                return
        # Default: run UPDATE-CITL
        if sys.platform == "win32":
            cmd = REPO / "UPDATE-CITL.cmd"
            if cmd.exists():
                threading.Thread(target=lambda: subprocess.run(
                    ["cmd", "/c", str(cmd)], cwd=str(REPO)), daemon=True).start()
                self._set_status("Running UPDATE-CITL.cmd ...")
            else:
                messagebox.showwarning(SUITE_NAME, "UPDATE-CITL.cmd not found.")
        else:
            sh = REPO / "UPDATE-CITL.sh"
            if sh.exists():
                threading.Thread(target=lambda: subprocess.Popen(
                    ["bash", str(sh)], cwd=str(REPO)), daemon=True).start()
            else:
                messagebox.showwarning(SUITE_NAME, "UPDATE-CITL.sh not found.")

    def _open_folder(self, app: dict):
        rp = app.get("repo_path")
        if not rp or not Path(rp).exists():
            messagebox.showwarning(SUITE_NAME, f"Folder not found:\n{rp}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(rp))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(rp)])
            else:
                subprocess.Popen(["xdg-open", str(rp)])
        except Exception as exc:
            messagebox.showerror(SUITE_NAME, f"Cannot open folder:\n{exc}")

    def _copy_to_clipboard(self, text: str):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._set_status(f"Copied: {text}")
        except Exception:
            pass

    def _signal_recorder_target(self, app: dict):
        """Emit a lightweight hint so an open recorder can retarget to this app."""
        app_id = str(app.get("id") or "").strip()
        title_prefix = RECORDER_WINDOW_HINTS.get(app_id)
        if not title_prefix:
            return
        payload = {
            "ts": time.time(),
            "app_id": app_id,
            "app_name": str(app.get("name") or "").strip(),
            "title_prefix": title_prefix,
        }
        try:
            RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            RECORDER_SIGNAL_PATH.write_text(
                _json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            # Recorder signaling is best-effort and must not block app launch.
            pass

    def _is_recorder_running(self) -> bool:
        tokens = ("citl_screen_recorder.py", "citl_screen_recorder.exe", "citl screen recorder")
        if _HAS_PSUTIL:
            try:
                for proc in _psutil.process_iter(attrs=["name", "cmdline"]):
                    name = str(proc.info.get("name") or "").lower()
                    cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                    if any(tok in name or tok in cmdline for tok in tokens):
                        return True
            except Exception:
                pass
        return False

    def _ensure_recorder_running(self, launched_app: dict):
        """Best-effort auto-launch of recorder when launching any other CITL app."""
        app_id = str(launched_app.get("id") or "").strip().lower()
        if app_id == "screen_recorder":
            return
        if self._is_recorder_running():
            return

        rec_app = next((a for a in self.apps if str(a.get("id") or "") == "screen_recorder"), None)
        if not rec_app:
            return
        launcher = rec_app.get("launcher_win") if sys.platform == "win32" else rec_app.get("launcher_nix")
        if not launcher or not Path(launcher).exists():
            return

        try:
            p = Path(launcher)
            if sys.platform == "win32":
                if p.suffix.lower() in (".cmd", ".bat", ".exe"):
                    os.startfile(str(p))
                elif p.suffix.lower() == ".ps1":
                    subprocess.Popen(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)],
                        cwd=str(p.parent), **_NO_WIN
                    )
                elif p.suffix.lower() == ".py":
                    py = _venv_python()
                    subprocess.Popen([py, str(p)], cwd=str(p.parent), **_NO_WIN)
                else:
                    os.startfile(str(p))
            else:
                if p.suffix.lower() == ".py":
                    subprocess.Popen([sys.executable, str(p)], start_new_session=True)
                else:
                    subprocess.Popen(["bash", str(p)], start_new_session=True)
            self._set_status(f"Launched: {launched_app['name']} (recorder auto-started)")
            self._signal_recorder_target(launched_app)
        except Exception:
            # Auto-start is best-effort; primary app launch already succeeded.
            pass

    #  Helpers 
    def _is_installed(self, app: dict) -> bool:
        kf = app.get("key_file")
        return bool(kf and Path(kf).exists())

    def _read_version(self, app: dict) -> str:
        vf = app.get("version_file")
        if vf and Path(vf).exists():
            try:
                return Path(vf).read_text(encoding="utf-8").strip().splitlines()[0]
            except Exception:
                pass
        return ""

    def _set_status(self, msg: str):
        self.root.after(0, lambda: self._status_var.set(msg))

    def _refresh_status(self):
        installed = sum(1 for a in self.apps if self._is_installed(a))
        self._set_status(f"{installed}/{len(self.apps)} apps detected on this system")

    #  Auto-watcher (30 s poll) 
    def _start_watcher(self):
        threading.Thread(target=self._watch_loop, daemon=True).start()

    def _watch_loop(self):
        while True:
            try:
                changed = False
                state_f = REPO / "citl_app_sync_state.json"
                if state_f.exists():
                    mt = state_f.stat().st_mtime
                    prev = self._watcher_mtime.get("_state", 0.0)
                    if mt != prev:
                        self._watcher_mtime["_state"] = mt
                        if prev:
                            changed = True
                for app in self.apps:
                    kf = app.get("key_file")
                    if kf and Path(kf).exists():
                        mt = Path(kf).stat().st_mtime
                        prev = self._watcher_mtime.get(app["id"], 0.0)
                        if mt != prev:
                            self._watcher_mtime[app["id"]] = mt
                            if prev:
                                changed = True
                if changed:
                    ts = datetime.now().strftime("%H:%M:%S")
                    self.root.after(0, lambda: self._auto_var.set(f"refreshed {ts}"))
                    if self._selected >= 0:
                        self.root.after(0, lambda: self._select_app(self._selected))
            except Exception:
                pass
            time.sleep(30)


#  venv python path 
def _venv_python() -> str:
    venv_py = REPO / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable

def _tk_runtime_help(err: Exception) -> str:
    lines = [
        f"{SUITE_NAME} cannot start because Tk/Tcl runtime is unavailable.",
        f"Python reported: {err}",
        "",
        "Remediation:",
    ]
    if sys.platform == "win32":
        lines.extend(
            [
                "1. Repair/reinstall Python and include Tcl/Tk support.",
                "2. Verify this exists: <Python>\\tcl\\tcl8.6\\init.tcl",
                "3. Or run the packaged CITL executable build.",
            ]
        )
    else:
        lines.extend(
            [
                "1. Install tkinter package (example: sudo apt install python3-tk).",
                "2. Restart the app.",
            ]
        )
    return "\n".join(lines)


#  Entry point 
def main():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        msg = _tk_runtime_help(exc)
        log_path = Path(__file__).parent / "citl_llmops_crash.log"
        try:
            log_path.write_text(msg + "\n\n" + traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        print(msg, file=sys.stderr)
        print(f"Details logged to: {log_path}", file=sys.stderr)
        sys.exit(2)
    # Keep a visible window during startup so users never see a "silent hang".
    root.title(f"{SUITE_NAME} - starting...")
    root.geometry("980x640")
    root.configure(bg=C["bg"])
    try:
        root.update_idletasks()
        root.update()
    except Exception:
        pass
    try:
        LLMOpsSuite(root)
        root.mainloop()
    except Exception as exc:
        err = traceback.format_exc()
        try:
            log_path = Path(__file__).parent / "citl_llmops_crash.log"
            log_path.write_text(f"[{datetime.now()}]\n{err}\n", encoding="utf-8")
        except Exception:
            pass
        try:
            messagebox.showerror(
                "CITL LLMOps Suite  Startup Error",
                f"{exc}\n\nFull trace  factbook-assistant/citl_llmops_crash.log")
        except Exception:
            print(err, file=sys.stderr)
        try:
            root.destroy()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
