#!/usr/bin/env python3
"""
Cross-platform CITL app sync utility.

Purpose:
- Detect USB/external copies of CITL repositories with similar layout.
- Sync this repo's app files to the selected target copy.
- Provide a small GUI utility that runs on Ubuntu and Windows.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]
LogFn = Optional[Callable[[str], None]]
APP_SYNC_NAME = "CITL App Sync Utility"
APP_SYNC_VERSION = "v1.9.1"
SYNC_LAUNCHER_WINDOWS = "RUN_APP_SYNC_WINDOWS.cmd"
SYNC_LAUNCHER_UBUNTU = "RUN_APP_SYNC_UBUNTU.sh"
SYNC_DUPLICATE_WINDOWS = "COPY_THIS_USB_TO_NEXT_WINDOWS.cmd"
SYNC_DUPLICATE_UBUNTU = "COPY_THIS_USB_TO_NEXT_UBUNTU.sh"
SYNC_LAUNCHER_README = "OPEN_SYNC_UTILITY_README.txt"
STATE_SCHEMA_VERSION = 1
STATE_FILE_NAME = "citl_app_sync_state.json"
UPDATE_AVAILABLE_EPSILON_SEC = 2.0
MODEL_SYNC_WARN_BYTES = 8 * 1024 * 1024 * 1024  # 8 GiB
BOOTSTRAP_SCHEMA_VERSION = 1
BOOTSTRAP_MANIFEST_NAME = "citl_bootstrap_manifest.json"
BOOTSTRAP_STATE_REL = "bootstrap/citl_bootstrap_state.json"
BOOTSTRAP_CADENCE_STATE_REL = "bootstrap/citl_patch_cadence_state.json"
BOOTSTRAP_PATCH_DIR_REL = "bootstrap/patches"
BOOTSTRAP_ROLLBACK_DIR_REL = "bootstrap/rollback"
BOOTSTRAP_ROLLBACK_MANIFEST_NAME = "citl_bootstrap_rollback_manifest.json"
BOOTSTRAP_WARN_EPSILON_SEC = 2.0
DEFAULT_PATCH_CADENCE_HOURS = 48
USB_MEDIA_CACHE_TTL_SEC = 20.0
DEVICE_PUSH_LOG_NAME = "citl_device_push_log.jsonl"
TERMUX_SHORTCUT_BACKUP_DIR = "termux_shortcut_backups"
TERMUX_SHORTCUT_FILE = "CITL_Latest_Push.sh"
PINNED_APP_NOETIKON = "NOETIKON PRIME"
PINNED_APP_CANIS = "CANIS COSMOS ASTROLOGY"

SYNC_SCOPE_CITL = "citl"
SYNC_SCOPE_HENOSIS = "henosis"
SYNC_TAG_HENOSIS = "henosis_sync"
SYNC_TAG_CITL = "citl_sync"

ACTIVE_SYNC_SCOPE = SYNC_SCOPE_CITL
PHONE_DOWNLOAD_DIR = "/sdcard/Download/CITL"

CITL_REPO_MARKERS: Tuple[str, ...] = (
    "factbook-assistant/factbook_assistant_gui.py",
    "factbook_assistant_gui.py",
    "RUN_FACTBOOK.sh",
    "Run-CITL.ps1",
    "run_citl_factbook_gui_ffmpeg.ps1",
)

HENOSIS_REPO_MARKERS: Tuple[str, ...] = (
    ".henosis_sync",
    "henosis_sync.json",
    "HENOSIS_SYNC.tag",
    "NOETIKON_SYNC.tag",
)

REPO_MARKERS: Tuple[str, ...] = CITL_REPO_MARKERS

CITL_REPO_HINT_KEYWORDS: Tuple[str, ...] = (
    "citl", "factbook", "llmops",
)

HENOSIS_REPO_HINT_KEYWORDS: Tuple[str, ...] = (
    "henosis", "noetikon", "zine", "canis", "studio",
)

REPO_HINT_KEYWORDS: Tuple[str, ...] = CITL_REPO_HINT_KEYWORDS


# ── CITL app registry ─────────────────────────────────────────────────────────
# "Factbook" is the umbrella name for the main desktop LLM utility.
# It encompasses: Study/Library Q&A, Transcription, Translation, TTS, and App Sync.
# Other distinct CITL apps (each may live in their own repo) are listed below it.
CITL_APPS_BASE: Tuple[dict, ...] = (
    {
        # ── UMBRELLA: everything that ships as the "Factbook" desktop app ──────
        "name": "Factbook",
        "description": (
            "Main CITL desktop LLM utility — Study & Library Q&A, "
            "Transcription, Translation, TTS, and corpus management. "
            "All components ship together as 'Factbook'."
        ),
        "icon": "📚",
        "key_files": [
            "factbook-assistant/factbook_assistant_gui.py",
            "factbook-assistant/citl_factbook_query.py",
            "factbook-assistant/citl_auto_index.py",
            "factbook-assistant/citl_text_extract.py",
            "factbook-assistant/citl_translation.py",
            "factbook-assistant/citl_audio_ffmpeg_graceful_v2.py",
            "factbook-assistant/citl_theme.py",
            "factbook-assistant/parsers.py",
            "factbook-assistant/citl_screen_recorder.py",
            "factbook-assistant/citl_video_post_editor.py",
            "factbook-assistant/citl_doc_composer.py",
            "factbook-assistant/citl_doc_theme.py",
            "factbook-assistant/citl_doc_templates.py",
            "factbook-assistant/fonts/doc_composer",
            "RUN_FACTBOOK_WINDOWS.cmd",
            "RUN_FACTBOOK.sh",
            "scripts/windows/run.ps1",
            "Run-CITL.ps1",
            "scripts/windows/run_llmops.ps1",
            "scripts/windows/record_demo.ps1",
            "scripts/windows/sync_doc_composer_fonts.ps1",
        ],
        "version_file": "FACTBOOK_VERSION.txt",
        "launcher_win": "RUN_FACTBOOK_WINDOWS.cmd",
        "launcher_nix": "RUN_FACTBOOK.sh",
        "repo_marker": "factbook-assistant/factbook_assistant_gui.py",
    },
    {
        # ── App Sync ─────────────────────────────────────────────────────────
        "name": "CITL App Sync",
        "description": (
            "Cross-platform USB and phone sync dashboard. "
            "Keeps all CITL app copies aligned across Windows and Ubuntu. "
            "Auto-ports Ubuntu requirements on every sync."
        ),
        "icon": "🔄",
        "key_files": [
            "factbook-assistant/citl_app_sync.py",
            "RUN_APP_SYNC_WINDOWS.cmd",
            "RUN_APP_SYNC_UBUNTU.sh",
            "RUN_APP_SYNC.sh",
            "Run-CITL-App-Sync.ps1",
            "requirements-windows.txt",
            "requirements-linux.txt",
            "scripts/windows/setup.ps1",
            "scripts/linux/setup.sh",
            "SYNC_CITL_APPS_TO_USB_WINDOWS.cmd",
            "SYNC_CITL_APPS_TO_USB_UBUNTU.sh",
            "SYNC_EXES_TO_USB_WINDOWS.cmd",
            "INSTALL_CITL_APPS_PORTABLE.cmd",
            "scripts/windows/sync_usb_apps.ps1",
            "scripts/windows/install_citl_apps_portable.ps1",
            "scripts/windows/build_all_citl_exes.ps1",
            "BUILD_ALL_CITL_EXES_WINDOWS.cmd",
            "OPEN_SYNC_UTILITY_README.txt",
            "bootstrap/patches",
        ],
        "version_file": None,
        "launcher_win": "RUN_APP_SYNC_WINDOWS.cmd",
        "launcher_nix": "RUN_APP_SYNC_UBUNTU.sh",
        "repo_marker": "factbook-assistant/citl_app_sync.py",
    },
    {
        # ── CITL Fixer / USB Repair Cloner ──────────────────────────────────
        "name": "CITL Fixer",
        "description": (
            "Primary repair, restore, and clone utility for CITL deployments. "
            "Runs offline diagnostics, applies self-update patch cadence, and "
            "can clone the latest working payload to replacement USB drives."
        ),
        "icon": "🧯",
        "key_files": [
            "citl_fixer.py",
            "citl_repair_all.py",
            "REPAIR_CITL_APPS.cmd",
            "RUN_CITL_FIXER_WINDOWS.cmd",
            "RUN_CITL_FIXER_UBUNTU.sh",
            "RUN_CITL_USB_REPAIR_CLONER_WINDOWS.cmd",
            "BUILD_CITL_USB_REPAIR_CLONER_WINDOWS.cmd",
            "Run-CITL-App-Sync.ps1",
            "PATCH_CITL_48H_AUTO_WINDOWS.cmd",
            "PATCH_CITL_48H_MANUAL_WINDOWS.cmd",
            "REGISTER_PATCH_CADENCE_TASK_WINDOWS.cmd",
            "UNREGISTER_PATCH_CADENCE_TASK_WINDOWS.cmd",
            "scripts/windows/citl_usb_repair_clone.py",
        ],
        "version_file": None,
        "launcher_win": "RUN_CITL_FIXER_WINDOWS.cmd",
        "launcher_nix": "RUN_CITL_FIXER_UBUNTU.sh",
        "repo_marker": "citl_fixer.py",
    },
    {
        # ── LLM Studio / Bot Maker ───────────────────────────────────────────
        "name": "CITL LLM Studio",
        "description": (
            "Ollama model configuration and bot-building studio. "
            "Create, test, and export custom Modelfiles and chat personas. "
            "Also runs as 'Bot Maker' in the CITL Utilities launcher."
        ),
        "icon": "🤖",
        "key_files": [
            "factbook-assistant/citl_modelfile.py",
            "CITL-LLM-Studio-Kit/app/llm_studio_gui.py",
        ],
        "version_file": None,
        "launcher_win": None,
        "launcher_nix": None,
        "repo_marker": "CITL-LLM-Studio-Kit/app/llm_studio_gui.py",
    },
    {
        # ── Academic Advisor ─────────────────────────────────────────────────
        # FastAPI backend (uvicorn :8000) + React/Vite frontend (:5173)
        # Backed by Ollama qwen2.5:7b — advises on college course schedules,
        # degree audits, and CTCLink/SBCTC data.
        # Repo: C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS\2026 ACADEMIC ADVISOR
        # Override source: set env CITL_ACADEMIC_ADVISOR_REPO=<path> if repo
        # lives at a non-standard location on the target machine.
        "name": "CITL Academic Advisor",
        "description": (
            "AI degree-audit and advising assistant. "
            "FastAPI backend + React UI (Vite), powered by Ollama qwen2.5. "
            "Features academic calendar explorer, program prereq planner, "
            "course catalog browser, and CTCLink/SBCTC transcript audit. "
            "USB-ready: dist/ ships built so no Node.js required on target."
        ),
        "icon": "🎓",
        "key_files": [
            # ── FastAPI backend (all runnable source) ──────────────────────
            "api/__init__.py",
            "api/app.py",
            "api/main.py",
            "api/routes.py",
            "api/planner_core.py",
            "api/baseline_router.py",
            "api/ctclink_scraper.py",
            "api/fetch_ctclink.py",
            "api/fetch_sbctc.py",
            "api/term_code_utils.py",
            "api/Modelfile",
            # ── React / Vite frontend — source ────────────────────────────
            # advisor-ui/src is a directory: all .ts/.tsx/.css files inside
            # are walked and copied, including rtcData.ts and App.tsx.
            "advisor-ui/src",
            "advisor-ui/public",
            "advisor-ui/index.html",
            "advisor-ui/package.json",
            "advisor-ui/package-lock.json",
            "advisor-ui/vite.config.ts",
            "advisor-ui/tsconfig.json",
            "advisor-ui/tsconfig.app.json",
            "advisor-ui/tsconfig.node.json",
            "advisor-ui/eslint.config.js",
            # ── React / Vite frontend — built output ──────────────────────
            # Shipping dist/ means the UI runs from USB without Node.js.
            # Build first on dev machine: cd advisor-ui && npm run build
            "advisor-ui/dist",
            # ── Scripts / launchers ───────────────────────────────────────
            "scripts/Run-CITLAdvisor.ps1",
            "scripts/Install-CITLAdvisor.ps1",
            "scripts/Create-RTCAdvisorModel.ps1",
            "scripts/Pull-OllamaModels.ps1",
            "scripts/Run-UI.ps1",
            # ── Python dependencies ───────────────────────────────────────
            "requirements.txt",
        ],
        "version_file": None,
        "launcher_win": "scripts/Run-CITLAdvisor.ps1",
        "launcher_nix": None,   # no Linux launcher yet
        "repo_marker": "api/app.py",
        "repo_path": r"C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS\2026 ACADEMIC ADVISOR",
        "repo_path_env": "CITL_ACADEMIC_ADVISOR_REPO",
    },
    {
        # ── CITL Toolkit (device/AV management) ──────────────────────────────
        "name": "CITL Toolkit",
        "description": (
            "Classroom AV and device management suite — audio checks, "
            "camera visibility, display profiles, Zoom updater, "
            "and software layer triage. Runs on Windows without install."
        ),
        "icon": "🖥️",
        "key_files": [
            "CITL_Toolkit/CITL_Launcher.ps1",
            "CITL_Toolkit/CITL_DeviceUpdater_GUI.ps1",
            "CITL_Toolkit/CITL_DisplayProfile_GUI.ps1",
        ],
        "version_file": None,
        "launcher_win": "CITL_Toolkit/CITL_Launcher.ps1",
        "launcher_nix": None,
        "repo_marker": "CITL_Toolkit/CITL_Launcher.ps1",
    },
    {
        # ── CITL Technical Writing and Tutorial Creator ──────────────────────
        "name": "CITL Technical Writing and Tutorial Creator",
        "description": (
            "Comprehensive tutorial production hub that combines technical writing, "
            "screenshot organization, LLM-assisted formatting, screen recording, and "
            "video post-editing into one workflow-focused GUI."
        ),
        "icon": "🧭",
        "key_files": [
            "factbook-assistant/citl_technical_writing_tutorial_creator.py",
            "factbook-assistant/citl_screen_recorder.py",
            "factbook-assistant/citl_video_post_editor.py",
            "factbook-assistant/citl_doc_composer.py",
            "factbook-assistant/citl_doc_theme.py",
            "factbook-assistant/citl_doc_templates.py",
            "RUN_TECHNICAL_WRITER_CREATOR_WINDOWS.cmd",
            "RUN_TECHNICAL_WRITER_CREATOR.sh",
            "scripts/windows/run_technical_writer_creator.ps1",
        ],
        "version_file": None,
        "launcher_win": "RUN_TECHNICAL_WRITER_CREATOR_WINDOWS.cmd",
        "launcher_nix": "RUN_TECHNICAL_WRITER_CREATOR.sh",
        "repo_marker": "factbook-assistant/citl_technical_writing_tutorial_creator.py",
    },
    {
        # ── CITL Database LLMOps Builder ─────────────────────────────────────
        "name": "CITL Database LLMOps Builder",
        "description": (
            "Wizard that exports complete runnable custom AI apps with Modelfile, "
            "README, launchers, and corpus packaging for portfolio-ready LLMOps work."
        ),
        "icon": "🛠️",
        "key_files": [
            "factbook-assistant/citl_database_llmops_builder.py",
            "RUN_DATABASE_LLMOPS_BUILDER_WINDOWS.cmd",
            "RUN_DATABASE_LLMOPS_BUILDER.sh",
            "scripts/windows/run_database_llmops_builder.ps1",
        ],
        "version_file": None,
        "launcher_win": "RUN_DATABASE_LLMOPS_BUILDER_WINDOWS.cmd",
        "launcher_nix": "RUN_DATABASE_LLMOPS_BUILDER.sh",
        "repo_marker": "factbook-assistant/citl_database_llmops_builder.py",
    },
    {
        # ── CITL AV IT Operations ────────────────────────────────────────────
        "name": "CITL AV IT Operations",
        "description": (
            "Room inventory, AV inspection checklists, and patch documentation utility "
            "for classroom technology support workflows."
        ),
        "icon": "🖧",
        "key_files": [
            "factbook-assistant/citl_av_it_ops.py",
            "RUN_AV_IT_OPS_WINDOWS.cmd",
            "RUN_AV_IT_OPS.sh",
            "scripts/windows/run_av_it_ops.ps1",
        ],
        "version_file": None,
        "launcher_win": "RUN_AV_IT_OPS_WINDOWS.cmd",
        "launcher_nix": "RUN_AV_IT_OPS.sh",
        "repo_marker": "factbook-assistant/citl_av_it_ops.py",
    },
    {
        # ── CITL Work and Preparedness Launcher ───────────────────────────────
        "name": "CITL Work and Preparedness Launcher",
        "description": (
            "Multi-app work and preparedness launcher for staff/workstudy covering "
            "LLMOps IT Admin, AV IT Operations, E-Learning Technologies, and "
            "Technical Writing, with resource links for SharePoint, Office 365, "
            "and local file databases."
        ),
        "icon": "🧰",
        "key_files": [
            "factbook-assistant/citl_staff_toolkit.py",
            "RUN_WORK_PREPAREDNESS_LAUNCHER_WINDOWS.cmd",
            "RUN_WORK_PREPAREDNESS_LAUNCHER.sh",
            "scripts/windows/run_work_preparedness_launcher.ps1",
            "RUN_STAFF_TOOLKIT_WINDOWS.cmd",
            "RUN_STAFF_TOOLKIT.sh",
            "scripts/windows/run_staff_toolkit.ps1",
            "factbook-assistant/citl_database_llmops_builder.py",
            "factbook-assistant/citl_av_it_ops.py",
            "factbook-assistant/citl_technical_writing_tutorial_creator.py",
        ],
        "version_file": None,
        "launcher_win": "RUN_WORK_PREPAREDNESS_LAUNCHER_WINDOWS.cmd",
        "launcher_nix": "RUN_WORK_PREPAREDNESS_LAUNCHER.sh",
        "repo_marker": "factbook-assistant/citl_staff_toolkit.py",
    },
    {
        # ── CITL LLMOps Presentation Suite ────────────────────────────────────
        "name": "LLMOps Suite",
        "description": (
            "Showcase, installer, and walkthrough for the full CITL app ecosystem. "
            "Explains LLM technology, career readiness, and human-in-the-loop "
            "operations for each app. Maroon + gray theme. "
            "Windows 10/11 and Ubuntu 24.04 LTS."
        ),
        "icon": "🎯",
        "key_files": [
            "factbook-assistant/citl_llmops_suite.py",
            "RUN_LLMOPS_WINDOWS.cmd",
            "RUN_LLMOPS.sh",
            "scripts/windows/run_llmops.ps1",
            "scripts/windows/build_llmops_exe.ps1",
            "scripts/windows/build_all_citl_exes.ps1",
            "BUILD_LLMOPS_EXE_WINDOWS.cmd",
            "BUILD_ALL_CITL_EXES_WINDOWS.cmd",
            "LLMOPS_SUITE_README.txt",
        ],
        "version_file": None,
        "launcher_win": "RUN_LLMOPS_WINDOWS.cmd",
        "launcher_nix": "RUN_LLMOPS.sh",
        "repo_marker": "factbook-assistant/citl_llmops_suite.py",
    },
    {
        # ── CITL Workstation Apps ─────────────────────────────────────────────
        # Windows-only (uses WMI/PowerShell display APIs). No Linux launcher.
        "name": "CITL Workstation Apps",
        "description": (
            "Display port tester, profile save/restore, connection diagnostics, "
            "and quick-fix actions for campus workstations with persistent "
            "display difficulties. No admin required, Windows 10/11."
        ),
        "icon": "🖥️",
        "key_files": [
            "factbook-assistant/citl_workstation_apps.py",
            "RUN_WORKSTATION_APPS_WINDOWS.cmd",
            "scripts/windows/build_all_citl_exes.ps1",
            "SYNC_EXES_TO_USB_WINDOWS.cmd",
            "INSTALL_CITL_APPS_PORTABLE.cmd",
            "scripts/windows/install_citl_apps_portable.ps1",
        ],
        "version_file": None,
        "launcher_win": "RUN_WORKSTATION_APPS_WINDOWS.cmd",
        "launcher_nix": None,
        "repo_marker": "factbook-assistant/citl_workstation_apps.py",
    },
    {
        # ── CITL Field Apps ───────────────────────────────────────────────────
        # Windows-only (uses WMI/PowerShell display APIs). No Linux launcher.
        "name": "CITL Field Apps",
        "description": (
            "Field technician toolkit: room inventory, AV driver check/log/"
            "rollback guide, rapid 25-point inspection checklist, and "
            "per-room display profile saver. No admin required, Windows 10/11."
        ),
        "icon": "🧰",
        "key_files": [
            "factbook-assistant/citl_field_apps.py",
            "RUN_FIELD_APPS_WINDOWS.cmd",
            "scripts/windows/build_all_citl_exes.ps1",
            "SYNC_EXES_TO_USB_WINDOWS.cmd",
            "INSTALL_CITL_APPS_PORTABLE.cmd",
            "scripts/windows/install_citl_apps_portable.ps1",
        ],
        "version_file": None,
        "launcher_win": "RUN_FIELD_APPS_WINDOWS.cmd",
        "launcher_nix": None,
        "repo_marker": "factbook-assistant/citl_field_apps.py",
    },
    {
        # ── CITL Work Ticketing System ────────────────────────────────────────
        "name": "CITL Work Ticketing System",
        "description": (
            "Powerflow ticketing automation GUI with FlowFX compiler, packet diagnostics, "
            "connection preflight, SharePoint CRUD tools, and local ticket DB."
        ),
        "icon": "🎫",
        "key_files": [
            "powerflow_builder/citl_work_ticketing_gui.py",
            "powerflow_builder/ops_assistant.py",
            "powerflow_builder/flowfx_compiler.py",
            "powerflow_builder/flowfx_validator_pack.py",
            "powerflow_builder/README_TICKETING_SYSTEM.md",
            "powerflow_builder/build_ticketing_automation_exe.ps1",
            "RUN_WORK_TICKETING_SYSTEM_WINDOWS.cmd",
            "RUN_WORK_TICKETING_SYSTEM_WINDOWS_EXE.cmd",
            "RUN_WORK_TICKETING_SYSTEM_UBUNTU.sh",
            "scripts/windows/build_all_citl_exes.ps1",
            "SYNC_EXES_TO_USB_WINDOWS.cmd",
            "INSTALL_CITL_APPS_PORTABLE.cmd",
            "scripts/windows/install_citl_apps_portable.ps1",
        ],
        "version_file": None,
        "launcher_win": "RUN_WORK_TICKETING_SYSTEM_WINDOWS.cmd",
        "launcher_nix": "RUN_WORK_TICKETING_SYSTEM_UBUNTU.sh",
        "repo_marker": "powerflow_builder/citl_work_ticketing_gui.py",
    },
    {
        # ── CITL Sync Hub ─────────────────────────────────────────────────────
        "name": "CITL Sync Hub",
        "description": (
            "Comprehensive sync and management hub with maroon RTC GUI. "
            "Tiles: System Scan, First-Time Install, USB->PC, PC->USB, "
            "Git Upload, Git Pull, Fix Shortcuts, App Bundle Status."
        ),
        "icon": "🔄",
        "key_files": [
            "factbook-assistant/citl_sync_hub.py",
            "RUN_SYNC_HUB_WINDOWS.cmd",
            "CITL Sync Hub.spec",
            "scripts/windows/build_all_citl_exes.ps1",
            "SYNC_EXES_TO_USB_WINDOWS.cmd",
            "INSTALL_CITL_APPS_PORTABLE.cmd",
            "scripts/windows/install_citl_apps_portable.ps1",
        ],
        "version_file": None,
        "launcher_win": "RUN_SYNC_HUB_WINDOWS.cmd",
        "launcher_nix": None,
        "repo_marker": "factbook-assistant/citl_sync_hub.py",
    },
    {
        # ── CITL FLEX Troubleshooter ─────────────────────────────────────────
        "name": "CITL FLEX Troubleshooter",
        "description": (
            "FLEX-specific troubleshooting assistant built from the FLEX Team OneNote PDF. "
            "Includes RAG index, Modelfile template, query CLI, and a lightweight GUI. "
            "Packable as a standalone EXE for student portfolio demos."
        ),
        "icon": "🛡️",
        "key_files": [
            "citl_flex_troubleshooter/flex_assistant_gui.py",
            "citl_flex_troubleshooter/query_flex.py",
            "citl_flex_troubleshooter/flex_builder.py",
            "citl_flex_troubleshooter/Modelfile",
            "citl_flex_troubleshooter/flex_embeddings.json",
            "RUN_CITL_FLEX_WINDOWS.cmd",
            "RUN_CITL_FLEX.sh",
            "scripts/windows/build_flex_exe.ps1",
        ],
        "version_file": None,
        "launcher_win": "RUN_CITL_FLEX_WINDOWS.cmd",
        "launcher_nix": "RUN_CITL_FLEX.sh",
        "repo_marker": "citl_flex_troubleshooter/flex_assistant_gui.py",
    },
)

HENOSIS_SYNC_APPS: Tuple[dict, ...] = (
    {
        "name": "NOETIKON PRIME",
        "description": (
            "HENOSIS-tagged NOETIKON PRIME repository sync target for mobile/USB patch flows."
        ),
        "icon": "🜂",
        "key_files": ["README.md", "requirements.txt", "pyproject.toml", "src", "app", "scripts", "launchers"],
        "version_file": None,
        "launcher_win": None,
        "launcher_nix": None,
        "repo_marker": ".henosis_sync",
        "repo_markers": [".henosis_sync", "NOETIKON_SYNC.tag", "README.md"],
        "repo_path_env": "HENOSIS_NOETIKON_PRIME_REPO",
        "sync_tags": [SYNC_TAG_HENOSIS],
    },
    {
        "name": "NOETIKON STUDIO 2",
        "description": (
            "HENOSIS-tagged NOETIKON Studio 2 repository sync target for patch continuation and deployment."
        ),
        "icon": "🜁",
        "key_files": ["README.md", "requirements.txt", "pyproject.toml", "src", "app", "scripts", "launchers"],
        "version_file": None,
        "launcher_win": None,
        "launcher_nix": None,
        "repo_marker": ".henosis_sync",
        "repo_markers": [".henosis_sync", "NOETIKON_SYNC.tag", "README.md"],
        "repo_path_env": "HENOSIS_NOETIKON_STUDIO2_REPO",
        "sync_tags": [SYNC_TAG_HENOSIS],
    },
    {
        "name": "ZINE WRITER",
        "description": (
            "HENOSIS-tagged Zine Writer repository sync target for device-aware patch/update continuity."
        ),
        "icon": "🜃",
        "key_files": ["README.md", "requirements.txt", "pyproject.toml", "src", "app", "scripts", "launchers"],
        "version_file": None,
        "launcher_win": None,
        "launcher_nix": None,
        "repo_marker": ".henosis_sync",
        "repo_markers": [".henosis_sync", "HENOSIS_SYNC.tag", "README.md"],
        "repo_path_env": "HENOSIS_ZINE_WRITER_REPO",
        "sync_tags": [SYNC_TAG_HENOSIS],
    },
    {
        "name": "CANIS COSMOS ASTROLOGY",
        "description": (
            "HENOSIS-tagged CANIS COSMOS ASTROLOGY repository sync target."
        ),
        "icon": "🜄",
        "key_files": ["README.md", "requirements.txt", "pyproject.toml", "src", "app", "scripts", "launchers"],
        "version_file": None,
        "launcher_win": None,
        "launcher_nix": None,
        "repo_marker": ".henosis_sync",
        "repo_markers": [".henosis_sync", "HENOSIS_SYNC.tag", "README.md"],
        "repo_path_env": "HENOSIS_CANIS_COSMOS_REPO",
        "sync_tags": [SYNC_TAG_HENOSIS],
    },
)

CITL_APPS: Tuple[dict, ...] = CITL_APPS_BASE


def _default_sync_scope() -> str:
    env_scope = (os.environ.get("CITL_SYNC_SCOPE", "") or "").strip().lower()
    if env_scope in {SYNC_SCOPE_CITL, SYNC_SCOPE_HENOSIS}:
        return env_scope
    henosis_only = (os.environ.get("HENOSIS_SYNC_ONLY", "") or "").strip().lower()
    if henosis_only in {"1", "true", "yes", "on"}:
        return SYNC_SCOPE_HENOSIS
    return SYNC_SCOPE_CITL


def _scope_label() -> str:
    return "HENOSIS" if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS else "CITL"


def _app_has_tag(app: dict, tag: str) -> bool:
    tags = app.get("sync_tags")
    if not isinstance(tags, (list, tuple, set)):
        return False
    want = str(tag or "").strip().lower()
    if not want:
        return False
    for item in tags:
        if str(item or "").strip().lower() == want:
            return True
    return False


def _apply_sync_scope(scope: str) -> str:
    global ACTIVE_SYNC_SCOPE, CITL_APPS, REPO_MARKERS, REPO_HINT_KEYWORDS
    global APP_SYNC_NAME, DEVICE_PUSH_LOG_NAME, TERMUX_SHORTCUT_FILE, PHONE_DOWNLOAD_DIR
    normalized = (scope or "").strip().lower()
    if normalized not in {SYNC_SCOPE_CITL, SYNC_SCOPE_HENOSIS}:
        normalized = SYNC_SCOPE_CITL

    ACTIVE_SYNC_SCOPE = normalized
    if normalized == SYNC_SCOPE_HENOSIS:
        CITL_APPS = tuple(HENOSIS_SYNC_APPS)
        REPO_MARKERS = HENOSIS_REPO_MARKERS
        REPO_HINT_KEYWORDS = HENOSIS_REPO_HINT_KEYWORDS
        APP_SYNC_NAME = "HENOSIS Sync Utility"
        DEVICE_PUSH_LOG_NAME = "henosis_device_push_log.jsonl"
        TERMUX_SHORTCUT_FILE = "HENOSIS_Latest_Push.sh"
        PHONE_DOWNLOAD_DIR = "/sdcard/Download/HENOSIS"
        return SYNC_SCOPE_HENOSIS

    CITL_APPS = tuple(CITL_APPS_BASE)
    REPO_MARKERS = CITL_REPO_MARKERS
    REPO_HINT_KEYWORDS = CITL_REPO_HINT_KEYWORDS
    APP_SYNC_NAME = "CITL App Sync Utility"
    DEVICE_PUSH_LOG_NAME = "citl_device_push_log.jsonl"
    TERMUX_SHORTCUT_FILE = "CITL_Latest_Push.sh"
    PHONE_DOWNLOAD_DIR = "/sdcard/Download/CITL"
    return SYNC_SCOPE_CITL


_apply_sync_scope(_default_sync_scope())


def _read_version_file(repo: Path, rel_path: Optional[str]) -> str:
    """Return first non-empty line of a version file, or '' if absent."""
    if not rel_path:
        return ""
    try:
        return (repo / rel_path).read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return ""


def _bump_version_file(repo: Path, rel_path: Optional[str]) -> bool:
    """
    Increment the patch/build number in a version file if it contains a
    semantic-ish version string (e.g. 'v2.0', 'v2.0.1', 'CITL FACTBOOK v2.0').
    Returns True on success.
    """
    if not rel_path:
        return False
    vpath = repo / rel_path
    try:
        text = vpath.read_text(encoding="utf-8")
    except Exception:
        return False
    # Match patterns like v2.0 or v2.0.1 anywhere in the text
    m = re.search(r"(v\d+\.\d+)(?:\.(\d+))?", text)
    if not m:
        return False
    old_str = m.group(0)
    major_minor = m.group(1)
    patch = int(m.group(2) or "0") + 1
    new_str = f"{major_minor}.{patch}"
    new_text = text.replace(old_str, new_str, 1)
    # Update the baseline date line if present
    today = datetime.utcnow().strftime("%Y-%m-%d")
    new_text = re.sub(r"Baseline date:\s*\d{4}-\d{2}-\d{2}", f"Baseline date: {today}", new_text)
    try:
        vpath.write_text(new_text, encoding="utf-8")
        return True
    except Exception:
        return False


DEFAULT_EXCLUDES: Tuple[str, ...] = (
    ".git/",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".cache/",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tmp",
    "*.bak",
    "dist/",
    "build/",
    "node_modules/",
    "data/citl/",
    "data/indexes/",
    "models/",
    "ollama/",
    "*.wav",
    "*.mp3",
    "*.mp4",
)


@dataclass(frozen=True)
class SyncTarget:
    path: Path
    score: int
    has_git: bool
    markers: Tuple[str, ...]
    root: Path
    remembered: bool = False


@dataclass
class SyncResult:
    copied: int = 0
    skipped: int = 0
    errors: int = 0
    used_rsync: bool = False
    elapsed_sec: float = 0.0


@dataclass(frozen=True)
class SourceDetection:
    path: Path
    reason: str
    freshness_ts: float


@dataclass
class RepoComparison:
    source_avg_ts: float
    target_avg_ts: float
    source_newer: int
    target_newer: int
    source_only: int
    target_only: int
    common_files: int
    source_file_count: int
    target_file_count: int
    recommendation: str
    summary: str
    newer_source_files: List[str] = None   # files updated on source since last sync
    new_source_files: List[str] = None     # files only on source (not yet synced)

    def __post_init__(self):
        if self.newer_source_files is None:
            self.newer_source_files = []
        if self.new_source_files is None:
            self.new_source_files = []


@dataclass(frozen=True)
class PhoneDevice:
    serial: str
    state: str
    meta: str


@dataclass(frozen=True)
class TargetStatus:
    target: SyncTarget
    freshness_ts: float
    writable: bool
    write_detail: str
    update_available: bool
    root_label: str
    comparison: RepoComparison


@dataclass(frozen=True)
class BootstrapPackage:
    path: Path
    bootstrap_id: str
    created_utc: str
    created_ts: float
    package_size: int
    app_names: Tuple[str, ...]
    app_file_counts: Dict[str, int]
    file_count: int
    payload_bytes: int
    source_repo_label: str
    source_hint: str


@dataclass
class BootstrapInstallPreview:
    total_apps: int
    newer_apps: int
    same_apps: int
    older_apps: int
    classification: str  # all | some | none
    stale: bool
    stale_reason: str


def _freshness_score(values: Iterable[float], sample_limit: int = 250) -> float:
    seq = sorted((float(v) for v in values if v and v > 0), reverse=True)
    if not seq:
        return 0.0
    sample = seq[: min(sample_limit, len(seq))]
    return sum(sample) / float(len(sample))


def _tracked_repo_mtimes(repo: PathLike, excludes: Sequence[str]) -> Dict[str, float]:
    base = Path(repo).expanduser().resolve()
    out: Dict[str, float] = {}
    if not base.exists() or not base.is_dir():
        return out

    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        rel_root = root_path.relative_to(base)
        rel_root_posix = "" if str(rel_root) == "." else rel_root.as_posix()

        kept_dirs: List[str] = []
        for d in dirs:
            rel_dir = "/".join(x for x in (rel_root_posix, d) if x)
            if _is_excluded(rel_dir, excludes, is_dir=True):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for name in files:
            rel_file = "/".join(x for x in (rel_root_posix, name) if x)
            if _is_excluded(rel_file, excludes, is_dir=False):
                continue
            path = root_path / name
            try:
                out[rel_file] = path.stat().st_mtime
            except OSError:
                continue
    return out


def compare_repo_freshness(
    source_repo: PathLike,
    target_repo: PathLike,
    include_data: bool = False,
    include_models: bool = False,
) -> RepoComparison:
    excludes = _build_excludes(include_data=include_data, include_models=include_models)
    source_map = _tracked_repo_mtimes(source_repo, excludes)
    target_map = _tracked_repo_mtimes(target_repo, excludes)

    source_keys = set(source_map)
    target_keys = set(target_map)
    common = source_keys & target_keys

    source_newer = 0
    target_newer = 0
    newer_source_files: List[str] = []
    for rel in common:
        delta = source_map[rel] - target_map[rel]
        if delta > UPDATE_AVAILABLE_EPSILON_SEC:
            source_newer += 1
            newer_source_files.append((source_map[rel], rel))
        elif delta < -UPDATE_AVAILABLE_EPSILON_SEC:
            target_newer += 1

    # Sort newest-first; keep display names only
    newer_source_files.sort(key=lambda x: -x[0])
    newer_source_files = [r for _, r in newer_source_files[:12]]

    source_only_set = source_keys - target_keys
    new_source_files = sorted(source_only_set, key=lambda r: -source_map.get(r, 0))[:12]
    source_only = len(source_only_set)
    target_only = len(target_keys - source_keys)
    source_avg_ts = _freshness_score(source_map.values())
    target_avg_ts = _freshness_score(target_map.values())

    if not source_map or not target_map:
        recommendation = "review"
    elif source_newer == 0 and target_newer == 0 and source_only == 0 and target_only == 0:
        recommendation = "current"
    else:
        source_edge = source_newer + source_only + max(0.0, (source_avg_ts - target_avg_ts) / 43200.0)
        target_edge = target_newer + target_only + max(0.0, (target_avg_ts - source_avg_ts) / 43200.0)
        if source_edge >= max(3.0, target_edge * 1.35):
            recommendation = "push_source_to_target"
        elif target_edge >= max(3.0, source_edge * 1.35):
            recommendation = "pull_target_to_source"
        else:
            recommendation = "review"

    summary = (
        f"source newer files={source_newer}, target newer files={target_newer}, "
        f"source only={source_only}, target only={target_only}, "
        f"source average freshness={_fmt_ts(source_avg_ts)}, "
        f"target average freshness={_fmt_ts(target_avg_ts)}"
    )
    return RepoComparison(
        source_avg_ts=source_avg_ts,
        target_avg_ts=target_avg_ts,
        source_newer=source_newer,
        target_newer=target_newer,
        source_only=source_only,
        target_only=target_only,
        common_files=len(common),
        source_file_count=len(source_map),
        target_file_count=len(target_map),
        recommendation=recommendation,
        summary=summary,
        newer_source_files=newer_source_files,
        new_source_files=new_source_files,
    )


def adb_devices() -> List[PhoneDevice]:
    try:
        proc = subprocess.run(
            ["adb", "devices", "-l"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            check=False,
            timeout=8.0,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []
    rows: List[PhoneDevice] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        serial = parts[0]
        state = parts[1] if len(parts) > 1 else "unknown"
        meta = " ".join(parts[2:]) if len(parts) > 2 else ""
        rows.append(PhoneDevice(serial=serial, state=state, meta=meta))
    return rows


def connected_phone_devices() -> List[PhoneDevice]:
    return [item for item in adb_devices() if item.state == "device"]


def _safe_archive_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (text or "repo").strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "repo"


def create_repo_zip_archive(
    source_repo: PathLike,
    archive_path: PathLike,
    include_data: bool = False,
    include_models: bool = False,
    log_fn: LogFn = None,
) -> Dict[str, object]:
    src = Path(source_repo).expanduser().resolve()
    dst = Path(archive_path).expanduser().resolve()
    excludes = _build_excludes(include_data=include_data, include_models=include_models)
    start = time.time()
    file_count = 0
    byte_count = 0

    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src):
            root_path = Path(root)
            rel_root = root_path.relative_to(src)
            rel_root_posix = "" if str(rel_root) == "." else rel_root.as_posix()

            kept_dirs: List[str] = []
            for d in dirs:
                rel_dir = "/".join(x for x in (rel_root_posix, d) if x)
                if _is_excluded(rel_dir, excludes, is_dir=True):
                    continue
                kept_dirs.append(d)
            dirs[:] = kept_dirs

            for name in files:
                rel_file = "/".join(x for x in (rel_root_posix, name) if x)
                if _is_excluded(rel_file, excludes, is_dir=False):
                    continue
                path = root_path / name
                try:
                    zf.write(path, arcname=rel_file)
                    file_count += 1
                    byte_count += path.stat().st_size
                except OSError as exc:
                    _safe_log(log_fn, f"[PHONE][WARN] skipped {rel_file}: {exc}\n")

    return {
        "archive_path": dst,
        "file_count": file_count,
        "byte_count": byte_count,
        "elapsed_sec": time.time() - start,
    }


def push_repo_archive_to_phone(
    source_repo: PathLike,
    serial: str,
    include_data: bool = False,
    include_models: bool = False,
    log_fn: LogFn = None,
    preserve_termux_shortcuts: bool = True,
    install_termux_shortcut: bool = True,
    record_push_log: bool = True,
) -> Dict[str, object]:
    src = Path(source_repo).expanduser().resolve()
    temp_root = Path(tempfile.mkdtemp(prefix="citl_phone_bundle_"))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"{_safe_archive_name(src.name)}_{stamp}.zip"
    archive_path = temp_root / archive_name
    remote_path = f"/sdcard/Download/{archive_name}"
    backup_ok = False
    backup_note = "Termux shortcut backup not requested."
    backup_path: Optional[Path] = None
    shortcut_ok = False
    shortcut_note = "Termux shortcut update not requested."
    info: Dict[str, object] = {
        "archive_path": archive_path,
        "file_count": 0,
        "byte_count": 0,
        "elapsed_sec": 0.0,
        "remote_path": remote_path,
        "serial": serial,
    }

    try:
        if preserve_termux_shortcuts:
            backup_ok, backup_note, backup_path = _backup_termux_shortcuts(serial, log_fn=log_fn)
            level = "[TERMUX]" if backup_ok else "[TERMUX][WARN]"
            _safe_log(log_fn, f"{level} {backup_note}\n")

        info = create_repo_zip_archive(
            src,
            archive_path,
            include_data=include_data,
            include_models=include_models,
            log_fn=log_fn,
        )
        _safe_log(log_fn, f"[PHONE] pushing {archive_path} to {serial}:{remote_path}\n")
        proc = subprocess.run(
            ["adb", "-s", serial, "push", str(archive_path), remote_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=900.0,
        )
        if proc.stdout:
            _safe_log(log_fn, proc.stdout)
        if proc.returncode != 0:
            raise RuntimeError(f"adb push failed with exit code {proc.returncode}")
        info["remote_path"] = remote_path
        info["serial"] = serial
        if install_termux_shortcut:
            shortcut_ok, shortcut_note = _install_termux_shortcut_for_push(
                serial,
                remote_path,
                log_fn=log_fn,
            )
            level = "[TERMUX]" if shortcut_ok else "[TERMUX][WARN]"
            _safe_log(log_fn, f"{level} {shortcut_note}\n")

        event = {
            "kind": "phone_push",
            "status": "ok",
            "source_repo": str(src),
            "phone_serial": serial,
            "remote_path": remote_path,
            "file_count": int(info.get("file_count") or 0),
            "byte_count": int(info.get("byte_count") or 0),
            "include_data": bool(include_data),
            "include_models": bool(include_models),
            "termux_backup_ok": bool(backup_ok),
            "termux_backup_path": str(backup_path) if backup_path else "",
            "termux_shortcut_ok": bool(shortcut_ok),
            "termux_shortcut_note": shortcut_note,
        }
        if record_push_log:
            _append_device_push_log_entry(event, log_fn=log_fn)
            phone_line = (
                f"{event.get('applied_utc', _utc_now_iso())} "
                f"status=ok serial={serial} repo={src.name} "
                f"remote={remote_path} files={event['file_count']} bytes={event['byte_count']}"
            )
            ok_phone_log, msg_phone_log = _append_phone_push_log(serial, phone_line, log_fn=log_fn)
            if not ok_phone_log:
                _safe_log(log_fn, f"[PHONE-LOG][WARN] {msg_phone_log}\n")

        info["termux_backup_ok"] = backup_ok
        info["termux_backup_path"] = str(backup_path) if backup_path else ""
        info["termux_shortcut_ok"] = shortcut_ok
        info["termux_shortcut_note"] = shortcut_note
        return info
    except Exception as exc:
        if record_push_log:
            error_event = {
                "kind": "phone_push",
                "status": "error",
                "source_repo": str(src),
                "phone_serial": serial,
                "remote_path": remote_path,
                "file_count": int(info.get("file_count") or 0),
                "byte_count": int(info.get("byte_count") or 0),
                "include_data": bool(include_data),
                "include_models": bool(include_models),
                "termux_backup_ok": bool(backup_ok),
                "termux_backup_path": str(backup_path) if backup_path else "",
                "termux_shortcut_ok": bool(shortcut_ok),
                "termux_shortcut_note": shortcut_note,
                "error": str(exc),
            }
            _append_device_push_log_entry(error_event, log_fn=log_fn)
            phone_line = (
                f"{error_event.get('applied_utc', _utc_now_iso())} "
                f"status=error serial={serial} repo={src.name} "
                f"remote={remote_path} error={str(exc)[:180]}"
            )
            _append_phone_push_log(serial, phone_line, log_fn=log_fn)
        raise
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return "unknown"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "unknown"


def _safe_log(log_fn: LogFn, message: str) -> None:
    if log_fn:
        log_fn(message)


def _device_push_log_path() -> Path:
    return _state_dir() / DEVICE_PUSH_LOG_NAME


def _append_device_push_log_entry(entry: Dict[str, object], log_fn: LogFn = None) -> None:
    row = dict(entry or {})
    if not row.get("applied_utc"):
        row["applied_utc"] = _utc_now_iso()
    path = _device_push_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")
    except Exception as e:
        _safe_log(log_fn, f"[PUSH-LOG][WARN] could not write {path}: {e}\n")


def _sh_single_quote(text: str) -> str:
    return "'" + str(text or "").replace("'", "'\"'\"'") + "'"


def _append_phone_push_log(serial: str, line: str, log_fn: LogFn = None) -> Tuple[bool, str]:
    remote_dir = PHONE_DOWNLOAD_DIR
    remote_log = f"{remote_dir}/pushed_apps.log"
    cmd = f"mkdir -p {remote_dir} && printf '%s\\n' {_sh_single_quote(line)} >> {remote_log}"
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, "shell", "sh", "-lc", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=20.0,
        )
    except Exception as e:
        return False, f"adb phone log write failed: {e}"
    if proc.returncode != 0:
        out = (proc.stdout or "").strip()
        return False, f"adb phone log write rc={proc.returncode} {out}"
    _safe_log(log_fn, f"[PHONE-LOG] appended: {remote_log}\n")
    return True, remote_log


def _backup_termux_shortcuts(serial: str, log_fn: LogFn = None) -> Tuple[bool, str, Optional[Path]]:
    backup_root = _state_dir() / TERMUX_SHORTCUT_BACKUP_DIR / _safe_archive_name(serial)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = backup_root / f"termux_shortcuts_{stamp}.tar.gz"
    cmd = [
        "adb",
        "-s",
        serial,
        "exec-out",
        "run-as",
        "com.termux",
        "sh",
        "-lc",
        "cd files/home && if [ -d .shortcuts ] || [ -d .termux ]; then tar -czf - .shortcuts .termux 2>/dev/null; fi; true",
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=45.0,
        )
    except Exception as e:
        return False, f"Termux shortcut backup unavailable: {e}", None
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        return False, f"Termux shortcut backup failed rc={proc.returncode} {err}", None

    payload = proc.stdout or b""
    if len(payload) < 32 or not payload.startswith(b"\x1f\x8b"):
        return False, "No existing Termux shortcuts were detected to back up.", None

    try:
        backup_root.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
    except Exception as e:
        return False, f"Could not save Termux shortcut backup: {e}", None

    _safe_log(log_fn, f"[TERMUX] shortcut backup saved: {out_path}\n")
    return True, f"Saved Termux shortcut backup: {out_path.name}", out_path


def _install_termux_shortcut_for_push(
    serial: str,
    remote_archive_path: str,
    log_fn: LogFn = None,
) -> Tuple[bool, str]:
    archive = str(remote_archive_path or "").strip()
    if not archive:
        return False, "No remote archive path provided for Termux shortcut."
    archive_escaped = archive.replace('"', '\\"')
    script = "\n".join(
        [
            "#!/data/data/com.termux/files/usr/bin/sh",
            "set -eu",
            f'ARCHIVE="{archive_escaped}"',
            f'echo "{_scope_label()} push helper"',
            'echo "Archive: $ARCHIVE"',
            'if [ -f "$ARCHIVE" ]; then',
            '  echo "Archive found. Extract with:"',
            '  echo "  pkg install -y unzip"',
            '  echo "  unzip -o \\"$ARCHIVE\\" -d \\"$HOME/sync_pushes/latest\\""',
            "else",
            '  echo "Archive not found at expected location."',
            "fi",
            "",
        ]
    )
    install_cmd = (
        f"mkdir -p files/home/.shortcuts && "
        f"cat > files/home/.shortcuts/{TERMUX_SHORTCUT_FILE} && "
        f"chmod 700 files/home/.shortcuts/{TERMUX_SHORTCUT_FILE}"
    )
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, "shell", "run-as", "com.termux", "sh", "-lc", install_cmd],
            input=script,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=45.0,
        )
    except Exception as e:
        return False, f"Termux shortcut install unavailable: {e}"
    if proc.returncode != 0:
        out = (proc.stdout or "").strip()
        return False, f"Termux shortcut install failed rc={proc.returncode} {out}"

    tmp_root = Path(tempfile.mkdtemp(prefix="citl_termux_shortcut_"))
    try:
        local_shortcut = tmp_root / TERMUX_SHORTCUT_FILE
        local_shortcut.write_text(script, encoding="utf-8")
        subprocess.run(
            ["adb", "-s", serial, "shell", "mkdir", "-p", PHONE_DOWNLOAD_DIR],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=20.0,
        )
        subprocess.run(
            ["adb", "-s", serial, "push", str(local_shortcut), f"{PHONE_DOWNLOAD_DIR}/{TERMUX_SHORTCUT_FILE}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=45.0,
        )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    _safe_log(log_fn, f"[TERMUX] shortcut updated: ~/.shortcuts/{TERMUX_SHORTCUT_FILE}\n")
    return True, "Termux shortcut updated."


def _fmt_bytes(size: int) -> str:
    try:
        n = float(size)
    except Exception:
        return "unknown size"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while n >= 1024.0 and idx < len(units) - 1:
        n /= 1024.0
        idx += 1
    return f"{n:.1f} {units[idx]}"


def _dir_size_bytes(path: PathLike) -> int:
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        return 0
    total = 0
    for base, _dirs, files in os.walk(root):
        base_path = Path(base)
        for name in files:
            fp = base_path / name
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def candidate_ollama_model_dirs(repo_root: PathLike) -> List[Path]:
    repo = Path(repo_root).expanduser()
    candidates: List[Path] = []
    env_models = (os.environ.get("OLLAMA_MODELS") or "").strip()
    if env_models:
        candidates.append(Path(env_models))
    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE") or str(Path.home())
        localapp = os.environ.get("LOCALAPPDATA") or ""
        candidates.extend(
            [
                Path(userprofile) / ".ollama" / "models",
                Path(localapp) / "Ollama" / "models" if localapp else Path(""),
            ]
        )
    else:
        candidates.append(Path.home() / ".ollama" / "models")

    candidates.extend(
        [
            repo / "ollama" / "models",
            repo / "ollama",
            repo / "models",
        ]
    )

    out: List[Path] = []
    seen: set = set()
    for p in candidates:
        if not str(p):
            continue
        try:
            rp = p.expanduser().resolve()
        except Exception:
            rp = p.expanduser()
        key = str(rp).lower()
        if key in seen:
            continue
        seen.add(key)
        if rp.exists() and rp.is_dir():
            out.append(rp)
    return out


def recommended_ollama_model_target_dir(target_repo: PathLike) -> Path:
    target = Path(target_repo).expanduser()
    try:
        target = target.resolve()
    except Exception:
        pass
    root = _guess_usb_root(target)
    if root != target:
        return root / "CITL_OLLAMA_MODELS"
    return target / "ollama" / "models"


def sync_external_model_store(
    source_models_dir: PathLike,
    target_models_dir: PathLike,
    log_fn: LogFn = None,
) -> Dict[str, object]:
    src = Path(source_models_dir).expanduser().resolve()
    dst = Path(target_models_dir).expanduser().resolve()
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Model source directory not found: {src}")
    if src == dst:
        _safe_log(log_fn, f"[MODEL] source and target are the same path: {src}\n")
        return {
            "copied": 0,
            "skipped": 0,
            "errors": 0,
            "bytes_copied": 0,
            "elapsed_sec": 0.0,
            "source": src,
            "target": dst,
        }

    start = time.time()
    copied = 0
    skipped = 0
    errors = 0
    bytes_copied = 0
    dst.mkdir(parents=True, exist_ok=True)

    _safe_log(log_fn, f"[MODEL] syncing Ollama model store\n")
    _safe_log(log_fn, f"[MODEL] source={src}\n")
    _safe_log(log_fn, f"[MODEL] target={dst}\n")

    for root, _dirs, files in os.walk(src):
        root_path = Path(root)
        rel_root = root_path.relative_to(src)
        out_dir = dst / rel_root
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            sp = root_path / name
            dp = out_dir / name
            try:
                if _needs_copy(sp, dp):
                    shutil.copy2(str(sp), str(dp))
                    copied += 1
                    try:
                        bytes_copied += sp.stat().st_size
                    except OSError:
                        pass
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                _safe_log(log_fn, f"[MODEL][ERR] {sp} -> {dp}: {exc}\n")

    elapsed = time.time() - start
    _safe_log(
        log_fn,
        f"[MODEL][DONE] copied={copied} skipped={skipped} errors={errors} "
        f"bytes_copied={bytes_copied} ({_fmt_bytes(bytes_copied)}) elapsed={elapsed:.1f}s\n",
    )
    return {
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
        "bytes_copied": bytes_copied,
        "elapsed_sec": elapsed,
        "source": src,
        "target": dst,
    }


def _state_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "CITL"


def _state_path() -> Path:
    return _state_dir() / STATE_FILE_NAME


def _load_state() -> Dict[str, object]:
    data: Dict[str, object] = {
        "version": STATE_SCHEMA_VERSION,
        "remembered_targets": {},
        "last_selected_target": "",
    }
    path = _state_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return data
    if not isinstance(raw, dict):
        return data
    remembered = raw.get("remembered_targets")
    if isinstance(remembered, dict):
        data["remembered_targets"] = remembered
    last_selected = raw.get("last_selected_target")
    if isinstance(last_selected, str):
        data["last_selected_target"] = last_selected
    return data


def _save_state(data: Dict[str, object]) -> None:
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_SCHEMA_VERSION,
        "remembered_targets": data.get("remembered_targets") or {},
        "last_selected_target": data.get("last_selected_target") or "",
    }
    _state_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _existing_paths(paths: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    seen: set = set()
    for p in paths:
        try:
            rp = p.expanduser().resolve()
        except Exception:
            rp = p.expanduser()
        key = str(rp)
        if key in seen:
            continue
        seen.add(key)
        try:
            exists = rp.exists()
        except OSError:
            continue
        except Exception:
            continue
        if exists:
            out.append(rp)
    return out


def _is_external_mount_path(path: Path) -> bool:
    low = str(path).lower()
    if os.name == "nt":
        return False
    # WSL-mounted Windows fixed drives (/mnt/c, /mnt/d, ...) are not external media.
    parts = path.parts
    if len(parts) >= 3 and parts[1].lower() == "mnt":
        letter = parts[2].lower()
        if len(letter) == 1 and letter.isalpha():
            return False
    prefixes = ("/media/", "/run/media/", "/mnt/", "/volumes/")
    return any(low.startswith(p) for p in prefixes)


def _matches_repo_name_hints(path: Path) -> bool:
    name = str(path.name or "").strip().lower()
    if not name:
        return False
    return any(h in name for h in REPO_HINT_KEYWORDS)


def _has_repo_marker(path: Path) -> bool:
    if not path.is_dir():
        return False
    for rel in REPO_MARKERS:
        if (path / rel).exists():
            return True
    # In HENOSIS mode, allow git repos whose folder names match HENOSIS hints.
    if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS:
        if (path / ".git").exists() and _matches_repo_name_hints(path):
            return True
    return False


def _normalize_repo_path(raw: str) -> Optional[Path]:
    val = (raw or "").strip().strip("\"'").strip()
    if not val:
        return None
    val = os.path.expandvars(os.path.expanduser(val))
    p = Path(val)
    try:
        return p.resolve()
    except Exception:
        return p


def _extract_run_citl_local_paths(script_path: Path) -> List[Path]:
    out: List[Path] = []
    if not script_path.exists():
        return out
    try:
        text = script_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return out

    # Matches lines such as: local a="$HOME/CITL_FACTBOOK_UBUNTU"
    for match in re.finditer(r'local\s+[a-zA-Z_]\w*\s*=\s*"([^"]+)"', text):
        p = _normalize_repo_path(match.group(1))
        if not p:
            continue
        if _is_external_mount_path(p):
            continue
        out.append(p)
    return _existing_paths(out)


def _candidate_local_repos(default_source: Path) -> List[Path]:
    home = Path.home()
    run_citl = home / ".local" / "bin" / "run-citl"

    seed: List[Path] = []
    seed.extend(_extract_run_citl_local_paths(run_citl))

    # Known local paths.
    seed.extend(
        [
            default_source,
            home / "CITL_FACTBOOK_UBUNTU",
            home / "CITL" / "CITL_FACTBOOK_UBUNTU",
            home / "CITL" / "CITL",
            home / "CITL" / "CITL - Desktop LLM EZ Install Kits",
            home / "HENOSIS",
            home / "Documents" / "HENOSIS",
            home / "Desktop" / "HENOSIS",
            home / "Documents" / "NOETIKON",
            home / "Desktop" / "NOETIKON",
        ]
    )

    # Shallow scan for similarly named repos.
    scan_roots = [home, home / "CITL", home / "HENOSIS", home / "Documents", home / "Desktop"]
    for root in _existing_paths(scan_roots):
        try:
            entries = list(os.scandir(root))
        except Exception:
            continue
        for ent in entries:
            if not ent.is_dir(follow_symlinks=False):
                continue
            name = ent.name.lower()
            if any(h in name for h in REPO_HINT_KEYWORDS):
                seed.append(Path(ent.path))
                # One more level.
                try:
                    sub = list(os.scandir(ent.path))
                except Exception:
                    sub = []
                for s in sub:
                    if s.is_dir(follow_symlinks=False):
                        sname = s.name.lower()
                        if any(h in sname for h in REPO_HINT_KEYWORDS):
                            seed.append(Path(s.path))

    uniq: List[Path] = []
    seen: set = set()
    for p in _existing_paths(seed):
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if _is_external_mount_path(p):
            continue
        if _has_repo_marker(p):
            uniq.append(p)
    return uniq


def _desktop_preferred_repo(candidates: Sequence[Path]) -> Optional[Path]:
    home = Path.home()
    run_citl = home / ".local" / "bin" / "run-citl"
    ordered = _extract_run_citl_local_paths(run_citl)
    cset = {str(p): p for p in candidates}
    for p in ordered:
        hit = cset.get(str(p))
        if hit is not None:
            return hit
    return None


def _repo_commit_timestamp(repo: Path) -> float:
    git_dir = repo / ".git"
    if not git_dir.exists():
        return 0.0
    try:
        p = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%ct"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return 0.0
    if p.returncode != 0:
        return 0.0
    try:
        return float((p.stdout or "").strip() or 0.0)
    except Exception:
        return 0.0


def _repo_file_timestamp(repo: Path) -> float:
    probe = [repo / rel for rel in REPO_MARKERS]
    probe.extend(
        [
            repo / "factbook-assistant" / "citl_app_sync.py",
            repo / "RUN_APP_SYNC_WINDOWS.cmd",
            repo / "RUN_APP_SYNC_UBUNTU.sh",
            repo / "README.md",
        ]
    )
    mts = [p.stat().st_mtime for p in probe if p.exists()]
    if mts:
        return max(mts)
    try:
        return repo.stat().st_mtime
    except Exception:
        return 0.0


def _repo_freshness(repo: Path) -> float:
    return max(_repo_commit_timestamp(repo), _repo_file_timestamp(repo))


def _windows_volume_identity(root: Path) -> Dict[str, str]:
    drive = str(root.drive or root.anchor or root)
    if drive and not drive.endswith("\\"):
        drive += "\\"
    info = {
        "key": f"winroot:{drive.lower()}",
        "root": drive or str(root),
        "label": "",
        "serial_hex": "",
    }
    if not drive:
        return info
    try:
        import ctypes

        volume_name = ctypes.create_unicode_buffer(261)
        fs_name = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint()
        max_component = ctypes.c_uint()
        flags = ctypes.c_uint()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive),
            volume_name,
            len(volume_name),
            ctypes.byref(serial),
            ctypes.byref(max_component),
            ctypes.byref(flags),
            fs_name,
            len(fs_name),
        )
        if ok:
            label = volume_name.value.strip()
            serial_hex = f"{serial.value:08X}" if serial.value else ""
            info["label"] = label
            info["serial_hex"] = serial_hex
            if serial_hex:
                info["key"] = f"winvol:{serial_hex.lower()}"
    except Exception:
        return info
    return info


def _root_identity(root: Path) -> Dict[str, str]:
    try:
        rp = root.expanduser().resolve()
    except Exception:
        rp = root.expanduser()
    if os.name == "nt":
        return _windows_volume_identity(rp)
    return {
        "key": f"path:{str(rp).lower()}",
        "root": str(rp),
        "label": rp.name,
        "serial_hex": "",
    }


def _root_label(root: Path) -> str:
    ident = _root_identity(root)
    parts = [ident.get("root", str(root))]
    label = ident.get("label", "")
    serial_hex = ident.get("serial_hex", "")
    if label:
        parts.append(label)
    if serial_hex:
        parts.append(f"serial {serial_hex}")
    return " | ".join(part for part in parts if part)


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        rp = path.expanduser().resolve()
    except Exception:
        rp = path.expanduser()
    try:
        rr = root.expanduser().resolve()
    except Exception:
        rr = root.expanduser()
    try:
        return rp.relative_to(rr).as_posix()
    except Exception:
        return ""


def _remember_target(target_repo: PathLike, root: Optional[Path] = None) -> None:
    target = Path(target_repo).expanduser()
    try:
        target = target.resolve()
    except Exception:
        pass

    remembered_root = (root or _guess_usb_root(target)).expanduser()
    try:
        remembered_root = remembered_root.resolve()
    except Exception:
        pass

    ident = _root_identity(remembered_root)
    entry = {
        "target_path": str(target),
        "relative_path": _safe_relative_path(target, remembered_root),
        "root": str(remembered_root),
        "label": ident.get("label", ""),
        "serial_hex": ident.get("serial_hex", ""),
        "saved_ts": time.time(),
        "saved_at": _fmt_ts(time.time()),
    }

    state = _load_state()
    remembered = dict(state.get("remembered_targets") or {})
    remembered[ident["key"]] = entry
    state["remembered_targets"] = remembered
    state["last_selected_target"] = str(target)
    _save_state(state)


def _last_selected_target() -> Optional[Path]:
    state = _load_state()
    raw = state.get("last_selected_target")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _normalize_repo_path(raw)


def _candidate_from_path(
    path: PathLike,
    source_name: str,
    root: Optional[Path] = None,
    remembered: bool = False,
) -> Optional[SyncTarget]:
    cand = Path(path).expanduser()
    try:
        cand = cand.resolve()
    except Exception:
        pass
    if not cand.exists() or not cand.is_dir():
        return None

    score, markers, has_git = _score_candidate(cand, source_name)
    min_score = 3 if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS else 5
    if score < min_score:
        return None

    base_root = root or _guess_usb_root(cand)
    return SyncTarget(
        path=cand,
        score=score + (1 if remembered else 0),
        has_git=has_git,
        markers=markers,
        root=base_root,
        remembered=remembered,
    )


def _remembered_target_candidates(roots: Sequence[Path]) -> List[Tuple[Path, Path]]:
    state = _load_state()
    remembered = state.get("remembered_targets")
    if not isinstance(remembered, dict):
        return []

    out: List[Tuple[Path, Path]] = []
    for root in roots:
        ident = _root_identity(root)
        raw = remembered.get(ident["key"])
        if not isinstance(raw, dict):
            continue

        rel = raw.get("relative_path")
        candidate: Optional[Path] = None
        if isinstance(rel, str) and rel.strip():
            candidate = root / Path(rel)
        else:
            raw_path = raw.get("target_path")
            if isinstance(raw_path, str):
                candidate = _normalize_repo_path(raw_path)
        if candidate is None:
            continue

        try:
            candidate = candidate.resolve()
        except Exception:
            pass
        out.append((root, candidate))
    return out


def detect_source_repo(source_arg: str = "auto", default_source: Optional[Path] = None) -> SourceDetection:
    default_repo = (default_source or _default_source()).expanduser().resolve()
    raw = (source_arg or "").strip()
    if raw and raw.lower() not in ("auto", "detect", "local"):
        explicit = _normalize_repo_path(raw)
        if explicit is None or not explicit.exists():
            raise FileNotFoundError(f"Source repo not found: {raw}")
        valid = _has_repo_marker(explicit)
        if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS and not valid:
            valid = ((explicit / ".git").exists() and _matches_repo_name_hints(explicit))
        if not valid:
            scope_word = "HENOSIS" if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS else "CITL"
            raise FileNotFoundError(f"Source path is not a {scope_word} repo: {explicit}")
        ts = max(_repo_commit_timestamp(explicit), _repo_file_timestamp(explicit))
        return SourceDetection(path=explicit, reason="explicit --source", freshness_ts=ts)

    candidates = _candidate_local_repos(default_repo)
    if not candidates:
        if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS and not _has_repo_marker(default_repo):
            raise FileNotFoundError(
                "No HENOSIS source repo auto-detected. "
                "Pass --source <henosis-repo-path> or set HENOSIS_REPO."
            )
        ts = max(_repo_commit_timestamp(default_repo), _repo_file_timestamp(default_repo))
        return SourceDetection(path=default_repo, reason="fallback default source", freshness_ts=ts)

    preferred = _desktop_preferred_repo(candidates)
    if preferred is not None:
        ts = max(_repo_commit_timestamp(preferred), _repo_file_timestamp(preferred))
        return SourceDetection(path=preferred, reason="desktop launcher preferred local repo", freshness_ts=ts)

    ranked: List[Tuple[float, Path]] = []
    for repo in candidates:
        ts = max(_repo_commit_timestamp(repo), _repo_file_timestamp(repo))
        ranked.append((ts, repo))
    ranked.sort(key=lambda x: x[0], reverse=True)
    best_ts, best_repo = ranked[0]
    return SourceDetection(path=best_repo, reason="most recently updated local repo", freshness_ts=best_ts)


def _windows_drive_roots_by_type(allowed_types: Tuple[int, ...]) -> List[Path]:
    roots: List[Path] = []
    try:
        import ctypes
    except Exception:
        return roots

    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not (bitmask & (1 << i)):
            continue
        drive = f"{letter}:\\"
        try:
            dtype = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive))
        except Exception:
            continue
        if dtype not in allowed_types:
            continue
        roots.append(Path(drive))
    return roots


def _windows_drive_roots() -> List[Path]:
    # DRIVE_REMOVABLE=2, DRIVE_FIXED=3
    return _windows_drive_roots_by_type((2, 3))


def _windows_removable_roots() -> List[Path]:
    # DRIVE_REMOVABLE=2
    return _windows_drive_roots_by_type((2,))


def scan_roots() -> List[Path]:
    roots: List[Path] = []
    user = os.environ.get("USER", "").strip()

    if os.name == "nt":
        # Prefer removable media first for responsive USB scanning.
        removable = _windows_removable_roots()
        include_fixed = (os.environ.get("CITL_SYNC_INCLUDE_FIXED_DRIVES", "").strip().lower() in {"1", "true", "yes"})
        if removable:
            roots.extend(removable)
            if include_fixed:
                roots.extend(_windows_drive_roots_by_type((3,)))
        else:
            # Fallback to original behavior when no removable media is present.
            roots.extend(_windows_drive_roots())
    else:
        if user:
            roots.append(Path("/media") / user)
            roots.append(Path("/run/media") / user)
        roots.append(Path("/media"))
        roots.append(Path("/mnt"))
        roots.append(Path("/Volumes"))

    extra = os.environ.get("CITL_SYNC_SCAN_ROOTS", "").strip()
    if extra:
        for raw in extra.split(os.pathsep):
            raw = raw.strip()
            if raw:
                roots.append(Path(raw))
    return _existing_paths(roots)


def _iter_candidate_dirs(root: Path, max_depth: int = 3) -> Iterable[Path]:
    queue: List[Tuple[Path, int]] = [(root, 0)]
    seen: set = set()
    while queue:
        cur, depth = queue.pop(0)
        key = str(cur)
        if key in seen:
            continue
        seen.add(key)

        lower = cur.name.lower()
        if any(h in lower for h in REPO_HINT_KEYWORDS):
            yield cur

        # Common portable layout shortcuts.
        quick = [
            cur / "CITL",
            cur / "CITL_FACTBOOK_UBUNTU",
            cur / "PORTABLE_APPS" / "CITL",
            cur / "HENOSIS",
            cur / "PORTABLE_APPS" / "HENOSIS",
        ]
        for p in quick:
            try:
                if p.is_dir():
                    yield p
            except Exception:
                continue

        if depth >= max_depth:
            continue
        try:
            entries = list(os.scandir(cur))
        except Exception:
            continue

        for ent in entries:
            if not ent.is_dir(follow_symlinks=False):
                continue
            nxt = Path(ent.path)
            name = ent.name.lower()
            if depth == 0 or any(h in name for h in REPO_HINT_KEYWORDS) or "portable" in name:
                queue.append((nxt, depth + 1))
            elif name in ("apps", "repos"):
                queue.append((nxt, depth + 1))


def _score_candidate(path: Path, source_name: str) -> Tuple[int, Tuple[str, ...], bool]:
    hits: List[str] = []
    for rel in REPO_MARKERS:
        if (path / rel).exists():
            hits.append(rel)

    if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_CITL:
        has_gui = any("factbook_assistant_gui.py" in h for h in hits)
        if not has_gui:
            return 0, tuple(), False
    else:
        has_hint_name = _matches_repo_name_hints(path)
        if not hits and not has_hint_name:
            return 0, tuple(), False

    has_git = (path / ".git").exists()
    pname = path.name.lower()
    score = len(hits) * 2
    if has_git:
        score += 2
    if any(h in pname for h in REPO_HINT_KEYWORDS):
        score += 2
    if "factbook" in pname:
        score += 2
    if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS and "noetikon" in pname:
        score += 2
    if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS and "henosis" in pname:
        score += 2
    if source_name and source_name.lower().replace("-", "_") in pname.replace("-", "_"):
        score += 1
    if "portable_apps" in str(path).lower():
        score += 1
    return score, tuple(hits), has_git


def _discover_sync_targets_from_roots(
    source_repo: PathLike,
    roots: Sequence[Path],
    max_depth: int = 3,
) -> List[SyncTarget]:
    src = Path(source_repo).expanduser().resolve()
    src_name = src.name
    best: Dict[str, SyncTarget] = {}
    checked: set = set()

    def maybe_add(item: SyncTarget) -> None:
        key = str(item.path)
        cur = best.get(key)
        if cur is None:
            best[key] = item
            return
        if item.remembered and not cur.remembered:
            best[key] = item
            return
        if item.score > cur.score:
            best[key] = item

    for root in roots:
        for cand in _iter_candidate_dirs(root, max_depth=max_depth):
            try:
                rp = cand.resolve()
            except Exception:
                rp = cand
            key = str(rp)
            if key in checked:
                continue
            checked.add(key)

            if rp == src:
                continue
            if src in rp.parents:
                continue

            score, markers, has_git = _score_candidate(rp, src_name)
            min_score = 3 if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS else 5
            if score < min_score:
                continue

            maybe_add(
                SyncTarget(
                    path=rp,
                    score=score,
                    has_git=has_git,
                    markers=markers,
                    root=root,
                )
            )

    for root, remembered_path in _remembered_target_candidates(roots):
        try:
            rp = remembered_path.resolve()
        except Exception:
            rp = remembered_path
        if rp == src:
            continue
        if src in rp.parents:
            continue
        item = _candidate_from_path(rp, src_name, root=root, remembered=True)
        if item is not None:
            maybe_add(item)

    out = list(best.values())
    out.sort(
        key=lambda t: (
            0 if t.remembered else 1,
            -t.score,
            0 if t.has_git else 1,
            str(t.path).lower(),
        )
    )
    return out


def discover_sync_targets(source_repo: PathLike, max_depth: int = 3) -> List[SyncTarget]:
    src = Path(source_repo).expanduser().resolve()
    roots = scan_roots()
    if os.name == "nt":
        src_drive = (src.drive or src.anchor or "").lower()
        other_roots = [
            root for root in roots if (root.drive or root.anchor or "").lower() != src_drive
        ]
        if other_roots:
            roots = other_roots
    return _discover_sync_targets_from_roots(src, roots, max_depth=max_depth)


def _resolve_candidate_repo_path(raw: str, source_repo: Path) -> Optional[Path]:
    val = (raw or "").strip()
    if not val:
        return None
    val = os.path.expandvars(os.path.expanduser(val))
    p = Path(val)
    if not p.is_absolute():
        p = source_repo / p
    try:
        return p.resolve()
    except Exception:
        return p


def _app_repo_markers(app: dict) -> List[str]:
    markers: List[str] = []
    marker = str(app.get("repo_marker") or "").strip()
    if marker:
        markers.append(marker)
    extra = app.get("repo_markers")
    if isinstance(extra, (list, tuple, set)):
        for item in extra:
            rel = str(item or "").strip()
            if rel:
                markers.append(rel)
    # preserve order, remove duplicates
    out: List[str] = []
    seen: set = set()
    for m in markers:
        if m in seen:
            continue
        seen.add(m)
        out.append(m)
    return out


def _find_scope_repo_candidates_for_app(app: dict, source_repo: Path) -> List[Path]:
    """Heuristic repo discovery for scope-specific apps (especially HENOSIS repos)."""
    name = str(app.get("name") or "").strip().lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", name) if t]
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        tokens = [name] if name else []

    roots: List[Path] = []
    roots.extend([source_repo, source_repo.parent, Path.home(), Path.home() / "Documents", Path.home() / "Desktop"])
    roots.extend(scan_roots())
    dedup_roots = _existing_paths(roots)

    out: List[Path] = []
    seen: set = set()
    for root in dedup_roots:
        try:
            entries = list(os.scandir(root))
        except Exception:
            continue
        for ent in entries:
            if not ent.is_dir(follow_symlinks=False):
                continue
            p = Path(ent.path)
            low = ent.name.lower()
            if not any(tok in low for tok in tokens):
                continue
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def resolve_app_source_root(app: dict, source_repo: PathLike) -> Path:
    """
    Resolve the best source root for an app:
    1) env var override (repo_path_env)
    2) explicit repo_path
    3) fallback to main source repo
    """
    src = Path(source_repo).expanduser()
    try:
        src = src.resolve()
    except Exception:
        pass

    markers = _app_repo_markers(app)
    marker = markers[0] if markers else ""
    env_key = str(app.get("repo_path_env") or "").strip()
    candidates: List[str] = []

    if env_key:
        env_val = (os.environ.get(env_key) or "").strip()
        if env_val:
            candidates.append(env_val)

    repo_path = app.get("repo_path")
    if isinstance(repo_path, str) and repo_path.strip():
        candidates.append(repo_path)

    for raw in candidates:
        p = _resolve_candidate_repo_path(raw, src)
        if p is None or not p.exists():
            continue
        if markers and not any((p / m).exists() for m in markers):
            continue
        return p

    # Scope-aware heuristic fallback (especially for HENOSIS repos connected on USB/mobile sync roots).
    for p in _find_scope_repo_candidates_for_app(app, src):
        if not p.exists():
            continue
        if markers and not any((p / m).exists() for m in markers):
            if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS:
                # For HENOSIS, allow git+name-hint repos even if explicit markers are absent.
                if not ((p / ".git").exists() and _matches_repo_name_hints(p)):
                    continue
            else:
                continue
        return p

    if marker and (src / marker).exists():
        if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS and _app_has_tag(app, SYNC_TAG_HENOSIS):
            if not _matches_repo_name_hints(src):
                # Prevent CITL-source bleed into HENOSIS app slots.
                pass
            else:
                return src
        else:
            return src

    if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS and _app_has_tag(app, SYNC_TAG_HENOSIS):
        app_name = _safe_archive_name(str(app.get("name") or "henosis_app"))
        return src / "__henosis_repo_not_found__" / app_name
    return src


def sync_registered_app_key_files(
    source_repo: PathLike,
    target_repo: PathLike,
    selected_app_names: Optional[Sequence[str]] = None,
    log_fn: LogFn = None,
) -> Dict[str, Dict[str, int]]:
    """
    Sync key_files for every app entry in CITL_APPS.
    This captures files from app-specific repos when repo_path/repo_path_env is set.
    """
    src = Path(source_repo).expanduser().resolve()
    dst = Path(target_repo).expanduser().resolve()
    summary: Dict[str, Dict[str, int]] = {}

    def _copy_one(src_path: Path, dst_path: Path) -> Tuple[int, int]:
        copied = 0
        skipped = 0
        if src_path.is_dir():
            for root, _dirs, files in os.walk(src_path):
                root_path = Path(root)
                rel_root = root_path.relative_to(src_path)
                out_dir = dst_path / rel_root
                out_dir.mkdir(parents=True, exist_ok=True)
                for name in files:
                    s = root_path / name
                    d = out_dir / name
                    if _needs_copy(s, d):
                        shutil.copy2(s, d)
                        copied += 1
                    else:
                        skipped += 1
            return copied, skipped

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if _needs_copy(src_path, dst_path):
            shutil.copy2(src_path, dst_path)
            copied += 1
        else:
            skipped += 1
        return copied, skipped

    wanted: Optional[set] = None
    if selected_app_names is not None:
        wanted = {str(x or "").strip() for x in selected_app_names if str(x or "").strip()}

    for app in CITL_APPS:
        app_name = str(app.get("name") or "Unnamed App")
        if wanted is not None and app_name not in wanted:
            continue
        key_files = app.get("key_files") or []
        if not key_files:
            continue
        app_src = resolve_app_source_root(app, src)
        if "__henosis_repo_not_found__" in str(app_src):
            summary[app_name] = {"copied": 0, "skipped": 0, "missing": len(key_files), "errors": 0}
            _safe_log(log_fn, f"[APP-SYNC][MISS] {app_name}: source repo unresolved for HENOSIS scope\n")
            continue
        copied = 0
        skipped = 0
        missing = 0
        errors = 0

        _safe_log(log_fn, f"[APP-SYNC] {app_name}: source={app_src}\n")
        for rel in key_files:
            src_p = app_src / rel
            dst_p = dst / rel
            if not src_p.exists():
                missing += 1
                _safe_log(log_fn, f"[APP-SYNC][MISS] {app_name}: {src_p}\n")
                continue
            try:
                c, s = _copy_one(src_p, dst_p)
                copied += c
                skipped += s
            except Exception as e:
                errors += 1
                _safe_log(log_fn, f"[APP-SYNC][ERR] {app_name}: {src_p} -> {dst_p} ({e})\n")

        summary[app_name] = {
            "copied": copied,
            "skipped": skipped,
            "missing": missing,
            "errors": errors,
        }
        _safe_log(
            log_fn,
            f"[APP-SYNC] {app_name}: copied={copied} skipped={skipped} missing={missing} errors={errors}\n",
        )

    return summary


def _select_best_usb_target_for_push(
    source_repo: Path,
    include_data: bool = False,
    include_models: bool = False,
) -> Optional[Tuple[SyncTarget, RepoComparison]]:
    src = Path(source_repo).expanduser().resolve()
    targets: List[SyncTarget] = []

    if os.name == "nt":
        removable_roots = _windows_removable_roots()
        src_drive = (src.drive or src.anchor or "").lower()
        removable_roots = [
            root for root in removable_roots if (root.drive or root.anchor or "").lower() != src_drive
        ]
        if removable_roots:
            targets = _discover_sync_targets_from_roots(src, removable_roots, max_depth=3)

    if not targets:
        targets = discover_sync_targets(src)
    if not targets:
        return None

    priority = {
        "push_source_to_target": 0,
        "current": 1,
        "review": 2,
        "pull_target_to_source": 3,
    }
    ranked: List[Tuple[int, int, int, str, SyncTarget, RepoComparison]] = []
    for t in targets:
        comp = compare_repo_freshness(
            src,
            t.path,
            include_data=include_data,
            include_models=include_models,
        )
        ranked.append(
            (
                priority.get(comp.recommendation, 9),
                0 if t.remembered else 1,
                -t.score,
                str(t.path).lower(),
                t,
                comp,
            )
        )
    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    best = ranked[0]
    return best[4], best[5]


def _resolve_phone_serial(phone_arg: str = "auto") -> Tuple[Optional[str], str]:
    devices = connected_phone_devices()
    if not devices:
        return None, "No Android phone detected over ADB."

    raw = (phone_arg or "auto").strip()
    if not raw or raw.lower() in ("auto", "first"):
        dev = devices[0]
        return dev.serial, f"Auto-selected phone: {dev.serial}"

    for dev in devices:
        if dev.serial == raw:
            return dev.serial, f"Using requested phone: {dev.serial}"
    return None, f"Requested phone serial not found: {raw}"


def _push_repo_copy_to_phone(
    repo_path: PathLike,
    phone_arg: str = "auto",
    include_data: bool = False,
    include_models: bool = False,
) -> int:
    serial, note = _resolve_phone_serial(phone_arg)
    if not serial:
        print(f"[PHONE][ERROR] {note}")
        return 1

    repo = Path(repo_path).expanduser().resolve()
    print(f"[PHONE] {note}")
    print(f"[PHONE] exporting repo copy: {repo}")
    try:
        result = push_repo_archive_to_phone(
            repo,
            serial,
            include_data=include_data,
            include_models=include_models,
            log_fn=lambda s: print(s, end=""),
        )
    except Exception as e:
        print(f"[PHONE][ERROR] export failed: {e}")
        return 1

    print(
        f"[PHONE][DONE] files={result['file_count']} bytes={result['byte_count']} "
        f"remote={result['remote_path']} elapsed={result['elapsed_sec']:.1f}s"
    )
    if bool(result.get("termux_backup_ok")):
        print(f"[PHONE][TERMUX] backup saved: {result.get('termux_backup_path')}")
    else:
        print("[PHONE][TERMUX][WARN] no shortcut backup captured before push.")
    shortcut_note = str(result.get("termux_shortcut_note") or "").strip()
    if bool(result.get("termux_shortcut_ok")):
        print(f"[PHONE][TERMUX] shortcut updated. {shortcut_note}")
    elif shortcut_note:
        print(f"[PHONE][TERMUX][WARN] {shortcut_note}")
    return 0


def _run_sync_best_usb(args: argparse.Namespace, source: SourceDetection) -> int:
    print(f"[SOURCE] {source.path} ({source.reason})")
    model_source_arg = (getattr(args, "ollama_model_source", "") or "").strip()
    model_target_arg = (getattr(args, "ollama_model_target", "") or "").strip()
    if bool(args.include_models) and (not model_source_arg or not model_target_arg):
        print(
            "[WARN] --include-models set without both --ollama-model-source and "
            "--ollama-model-target; external Ollama model store copy will be skipped "
            "(repo-local models/ollama folders still sync)."
        )
    explicit_target_arg = (getattr(args, "target_path", "") or "").strip()
    target_path: Optional[Path] = None
    if explicit_target_arg:
        target_path = _normalize_repo_path(explicit_target_arg)
        if target_path is None:
            print(f"[ERROR] Invalid --target-path: {explicit_target_arg}")
            return 2
        try:
            target_path = target_path.resolve()
        except Exception:
            pass
        if not target_path.exists():
            try:
                target_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"[ERROR] Could not create --target-path {target_path}: {e}")
                return 2
        comparison = compare_repo_freshness(
            source.path,
            target_path,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )
        print(f"[TARGET] {target_path} (explicit --target-path)")
    else:
        chosen = _select_best_usb_target_for_push(
            source.path,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )
        if chosen is None:
            print(f"[ERROR] No compatible USB/external {_scope_label()} target was detected.")
            return 2
        target, comparison = chosen
        target_path = target.path
        print(f"[TARGET] {target_path}")

    if target_path is None:
        print("[ERROR] target_path could not be resolved after USB detection. "
              f"Ensure a {_scope_label()} USB is connected or pass --target-path explicitly.")
        return 2
    print(f"[TARGET] recommendation={comparison.recommendation} ({comparison.summary})")
    if comparison.recommendation == "pull_target_to_source":
        print(
            "[WARN] Selected target appears newer than this PC copy; "
            "continuing with PC -> USB push because --sync-best-usb was requested."
        )

    total_errors = 0
    if bool(getattr(args, "full_repo_sync", False)):
        result = sync_repo(
            source.path,
            target_path,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
            model_source_dir=(model_source_arg or None),
            model_target_dir=(model_target_arg or None),
            log_fn=lambda s: print(s, end=""),
        )
        mode = "rsync" if result.used_rsync else "python-copy"
        print(
            f"[DONE] repo-sync mode={mode} copied={result.copied} skipped={result.skipped} "
            f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s"
        )
        total_errors += int(result.errors)
    else:
        install_sync_launchers(target_path, log_fn=lambda s: print(s, end=""))
        print("[DONE] full repo sync skipped (app key-file update mode).")

    if not bool(getattr(args, "no_app_key_sync", False)):
        app_summary = sync_registered_app_key_files(
            source.path,
            target_path,
            log_fn=lambda s: print(s, end=""),
        )
        total_copied = sum(v.get("copied", 0) for v in app_summary.values())
        total_missing = sum(v.get("missing", 0) for v in app_summary.values())
        app_errors = sum(v.get("errors", 0) for v in app_summary.values())
        total_errors += app_errors
        print(
            f"[DONE] app-key-sync apps={len(app_summary)} copied={total_copied} "
            f"missing={total_missing} errors={app_errors}"
        )

    try:
        port_to_ubuntu(target_path, log_fn=lambda s: print(s, end=""))
    except Exception as e:
        total_errors += 1
        print(f"[WARN] Ubuntu port step failed on target: {e}")

    if bool(getattr(args, "push_target_to_phone", False)):
        total_errors += _push_repo_copy_to_phone(
            target_path,
            phone_arg=str(getattr(args, "phone_serial", "auto") or "auto"),
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )

    return 0 if total_errors == 0 else 1


def _path_root_key(path: PathLike) -> str:
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except Exception:
        pass
    if os.name == "nt":
        return (p.drive or p.anchor or str(p)).lower().rstrip("\\/")
    root = _guess_usb_root(p)
    try:
        root = root.resolve()
    except Exception:
        pass
    return str(root).lower().rstrip("/")


def _is_removable_source_repo(path: PathLike) -> bool:
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except Exception:
        pass

    if os.name == "nt":
        drive = (p.drive or p.anchor or "").lower()
        if not drive:
            return False
        removable = {(r.drive or r.anchor or "").lower() for r in _windows_removable_roots()}
        return drive in removable

    return _is_external_mount_path(p)


def _discover_duplicate_targets(source_repo: PathLike) -> List[SyncTarget]:
    src = Path(source_repo).expanduser().resolve()
    if os.name == "nt":
        removable = _windows_removable_roots()
        if removable:
            return _discover_sync_targets_from_roots(src, removable, max_depth=3)
    return discover_sync_targets(src)


def _pick_duplicate_target(
    from_path: Path,
    candidates: Sequence[SyncTarget],
    include_data: bool = False,
    include_models: bool = False,
) -> Optional[Tuple[Path, RepoComparison]]:
    if not candidates:
        return None

    priority = {
        "push_source_to_target": 0,
        "current": 1,
        "review": 2,
        "pull_target_to_source": 3,
    }
    from_root = _path_root_key(from_path)
    ranked: List[Tuple[int, int, int, int, float, str, Path, RepoComparison]] = []
    for t in candidates:
        comp = compare_repo_freshness(
            from_path,
            t.path,
            include_data=include_data,
            include_models=include_models,
        )
        same_root = 1 if _path_root_key(t.path) == from_root else 0
        freshness = _repo_freshness(t.path)
        ranked.append(
            (
                same_root,
                priority.get(comp.recommendation, 9),
                0 if t.remembered else 1,
                -t.score,
                -freshness,
                str(t.path).lower(),
                t.path,
                comp,
            )
        )

    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4], x[5]))
    best = ranked[0]
    return best[6], best[7]


def _run_duplicate_usb(args: argparse.Namespace, source: SourceDetection) -> int:
    """
    Hardened USB duplication function with comprehensive validation and diagnostics.
    
    Validates:
    - Source/destination are different devices
    - Sufficient space on destination
    - Both paths are CITL repositories
    - USB is formatted with appropriate filesystem
    """
    print(f"[SOURCE] {source.path} ({source.reason})")
    
    smoke_test = bool(getattr(args, "smoke_test", False))
    if smoke_test:
        print("[SMOKE-TEST] Running in diagnostic mode - no actual copying")
    
    source_repo = Path(source.path).expanduser().resolve()
    targets = _discover_duplicate_targets(source_repo)
    by_path = {str(t.path): t for t in targets}
    from_arg = (getattr(args, "duplicate_from", "") or "").strip()
    to_arg = (getattr(args, "duplicate_to", "") or "").strip()
    from_path = _normalize_repo_path(from_arg) if from_arg else None
    to_path = _normalize_repo_path(to_arg) if to_arg else None

    # ── VALIDATE SOURCE ───────────────────────────────────────────────────────
    if from_path is not None:
        if from_path != source_repo and str(from_path) not in by_path:
            print(f"[ERROR] --duplicate-from not detected as a target: {from_path}")
            return 2
        if not _has_repo_marker(from_path):
            print(f"[ERROR] --duplicate-from is not a {_scope_label()} repo: {from_path}")
            return 2
        print(f"[VALIDATE] Source explicitly set: {from_path}")
    if to_path and str(to_path) not in by_path:
        print(f"[ERROR] --duplicate-to not detected as a target: {to_path}")
        return 2

    # ── AUTO-DETECT SOURCE ────────────────────────────────────────────────────
    if from_path is None:
        if _is_removable_source_repo(source_repo) and _has_repo_marker(source_repo):
            from_path = source_repo
            print(f"[DUPLICATE] auto-source=this USB ({from_path})")
        else:
            if not targets:
                print(f"[ERROR] No external {_scope_label()} targets were detected for duplication.")
                print(f"[ERROR] Connect a USB drive with {_scope_label()} repo or pass --duplicate-from")
                return 2
            ranked = sorted(targets, key=lambda t: (_repo_freshness(t.path), t.score), reverse=True)
            from_path = ranked[0].path
            print(f"[DUPLICATE] auto-source=best detected target ({from_path})")

    if from_path is None:
        print("[ERROR] Could not determine a duplication source. "
              f"Connect a {_scope_label()} USB or pass --duplicate-from explicitly.")
        return 2

    # Validate source is readable
    try:
        src_commit = (Path(from_path) / ".git" / "HEAD").read_text(encoding="utf-8", errors="ignore")
        print(f"[VALIDATE] Source is readable (git: {src_commit.strip()[:20]}...)")
    except Exception:
        print(f"[WARN] Could not detect git HEAD in source; continuing anyway")

    # ── AUTO-DETECT DESTINATION ──────────────────────────────────────────────
    if to_path is None:
        candidates = [t for t in targets if t.path != from_path]
        if not candidates:
            print("[ERROR] Need at least 2 USB drives for duplication:")
            print(f"[ERROR]   - Source USB (with {_scope_label()} repo)")
            print("[ERROR]   - Destination USB (will be cloned to)")
            print("[ERROR] Connect a second USB drive and try again.")
            return 2
        
        picked = _pick_duplicate_target(
            from_path,
            candidates,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )
        if picked is None:
            print("[ERROR] Could not pick a suitable destination USB.")
            print(f"[ERROR] Found {len(candidates)} candidates but none suitable")
            return 2
        to_path, auto_comp = picked
        print(f"[DUPLICATE] auto-target=next detected target ({to_path})")
    else:
        auto_comp = compare_repo_freshness(
            from_path,
            to_path,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )

    # ── FINAL VALIDATION ──────────────────────────────────────────────────────
    if from_path == to_path:
        print("[ERROR] Source and destination USB paths are the same.")
        print(f"[ERROR] Both resolved to: {from_path}")
        return 2

    if _path_root_key(from_path) == _path_root_key(to_path):
        print("[WARN] Source and destination appear to be on the same drive root; continuing anyway.")

    # Check destination space
    try:
        src_usage = shutil.disk_usage(str(from_path))
        dst_usage = shutil.disk_usage(str(to_path))
        src_needed = src_usage.used
        dst_available = dst_usage.free
        
        print(f"[VALIDATE] Source size: {_fmt_bytes(src_needed)}")
        print(f"[VALIDATE] Dest free:   {_fmt_bytes(dst_available)}")
        
        if src_needed > dst_available:
            print(f"[ERROR] Insufficient space on destination USB")
            print(f"[ERROR]   Source needed: {_fmt_bytes(src_needed)}")
            print(f"[ERROR]   Dest free:     {_fmt_bytes(dst_available)}")
            print(f"[ERROR]   Shortfall:     {_fmt_bytes(src_needed - dst_available)}")
            return 2
        else:
            headroom_mb = (dst_available - src_needed) / (1024*1024)
            print(f"[VALIDATE] Space check OK (headroom: {headroom_mb:.1f} MB)")
    except Exception as e:
        print(f"[WARN] Could not verify space requirements: {e}")

    model_source_arg = (getattr(args, "ollama_model_source", "") or "").strip()
    model_target_arg = (getattr(args, "ollama_model_target", "") or "").strip()
    if bool(args.include_models) and (not model_source_arg or not model_target_arg):
        print(
            "[WARN] --include-models set without both --ollama-model-source and "
            "--ollama-model-target; external Ollama model store copy will be skipped "
            "(repo-local models/ollama folders still sync)."
        )

    print(f"[DUPLICATE] from={from_path}")
    print(f"[DUPLICATE] to={to_path}")
    print(f"[DUPLICATE] recommendation={auto_comp.recommendation} ({auto_comp.summary})")
    print(f"[DUPLICATE] include_data={bool(args.include_data)} include_models={bool(args.include_models)}")

    # ── SMOKE TEST MODE ───────────────────────────────────────────────────────
    if smoke_test:
        print("[SMOKE-TEST] Validation complete - skipping actual sync")
        print("[SMOKE-TEST] To run actual clone, remove --smoke-test flag")
        return 0

    # ── PERFORM SYNC ──────────────────────────────────────────────────────────
    print("[SYNC] Starting actual file copy...")
    
    result = sync_repo(
        from_path,
        to_path,
        include_data=bool(args.include_data),
        include_models=bool(args.include_models),
        model_source_dir=(model_source_arg or None),
        model_target_dir=(model_target_arg or None),
        log_fn=lambda s: print(s, end=""),
    )
    mode = "rsync" if result.used_rsync else "python-copy"
    print(
        f"[DONE] USB duplicate mode={mode} copied={result.copied} skipped={result.skipped} "
        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s"
    )

    if not bool(getattr(args, "no_app_key_sync", False)):
        app_summary = sync_registered_app_key_files(
            source.path,
            to_path,
            log_fn=lambda s: print(s, end=""),
        )
        total_copied = sum(v.get("copied", 0) for v in app_summary.values())
        total_missing = sum(v.get("missing", 0) for v in app_summary.values())
        app_errors = sum(v.get("errors", 0) for v in app_summary.values())
        print(
            f"[DONE] app-key-overlay apps={len(app_summary)} copied={total_copied} "
            f"missing={total_missing} errors={app_errors}"
        )
        total_errors = int(result.errors) + int(app_errors)
    else:
        total_errors = int(result.errors)

    try:
        port_to_ubuntu(to_path, log_fn=lambda s: print(s, end=""))
    except Exception as e:
        total_errors += 1
        print(f"[WARN] Ubuntu port step failed on duplicate target: {e}")

    if bool(getattr(args, "push_target_to_phone", False)):
        total_errors += _push_repo_copy_to_phone(
            to_path,
            phone_arg=str(getattr(args, "phone_serial", "auto") or "auto"),
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )

    if total_errors == 0:
        print("[SUCCESS] USB clone completed without errors!")
        return 0
    else:
        print(f"[WARNING] USB clone completed with {total_errors} error(s)")
        return 1


# ── GitHub / git automation ───────────────────────────────────────────────────

def _git_run(repo: Path, *args: str, timeout: int = 30) -> Tuple[int, str, str]:
    """Run a git command in `repo`. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", "git not found in PATH"
    except subprocess.TimeoutExpired:
        return -1, "", f"git command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def _find_git_root(path: Path) -> Optional[Path]:
    """Walk up from `path` to find the .git directory root."""
    p = path.resolve()
    for candidate in [p] + list(p.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def git_status_for_repo(repo: Path) -> Dict[str, object]:
    """
    Return a status dict for a git repo:
      branch, remote_url, ahead, behind, dirty, last_commit, last_author, error
    """
    root = _find_git_root(repo)
    if root is None:
        return {"error": "Not a git repo", "branch": "—", "ahead": 0, "behind": 0,
                "dirty": False, "last_commit": "", "last_author": "", "remote_url": ""}

    # Branch
    rc, branch, _ = _git_run(root, "rev-parse", "--abbrev-ref", "HEAD")
    branch = branch if rc == 0 else "unknown"

    # Remote URL
    rc, remote_url, _ = _git_run(root, "remote", "get-url", "origin")
    remote_url = remote_url if rc == 0 else ""

    # Fetch (non-blocking remote check — use cached FETCH_HEAD if offline)
    _git_run(root, "fetch", "--quiet", timeout=12)

    # Ahead / behind
    rc, ab, _ = _git_run(root, "rev-list", "--left-right", "--count",
                          f"HEAD...origin/{branch}")
    ahead = behind = 0
    if rc == 0 and ab:
        parts = ab.split()
        if len(parts) == 2:
            try:
                ahead, behind = int(parts[0]), int(parts[1])
            except ValueError:
                pass

    # Dirty working tree
    rc, diff_out, _ = _git_run(root, "status", "--porcelain")
    dirty = bool(diff_out.strip()) if rc == 0 else False

    # Last commit
    rc, log_line, _ = _git_run(root, "log", "-1", "--pretty=%h %s (%an, %ar)")
    last_commit = log_line if rc == 0 else ""
    rc, last_author, _ = _git_run(root, "log", "-1", "--pretty=%an <%ae>")
    last_author = last_author if rc == 0 else ""

    return {
        "root": root,
        "branch": branch,
        "remote_url": remote_url,
        "ahead": ahead,
        "behind": behind,
        "dirty": dirty,
        "last_commit": last_commit,
        "last_author": last_author,
        "error": None,
    }


def git_backup_repo(repo: Path, backup_dir: Optional[Path] = None) -> Path:
    """
    Create a timestamped zip backup of the repo (excluding .git, venv, __pycache__).
    Returns the path to the backup zip.
    """
    root = _find_git_root(repo) or repo.resolve()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", root.name)
    bdir = backup_dir or (root.parent / ".citl_git_backups")
    bdir.mkdir(parents=True, exist_ok=True)
    zip_path = bdir / f"{safe_name}_{ts}.zip"

    skip_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules",
                 "dist", "build", ".pytest_cache", ".mypy_cache"}
    skip_exts = {".pyc", ".pyo", ".log", ".tmp"}

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fname in filenames:
                if any(fname.endswith(e) for e in skip_exts):
                    continue
                full = Path(dirpath) / fname
                try:
                    arcname = full.relative_to(root)
                    zf.write(str(full), str(arcname))
                except Exception:
                    pass

    return zip_path


def git_commit_and_push(
    repo: Path,
    message: str = "",
    log_fn: LogFn = None,
) -> Tuple[bool, str]:
    """
    Stage all changes, commit (if dirty), and push to origin.
    Returns (success, summary_message).
    Raises nothing — all errors are returned in the message.
    """
    root = _find_git_root(repo)
    if root is None:
        return False, "Not a git repo — cannot push."

    status = git_status_for_repo(root)
    if status.get("error"):
        return False, str(status["error"])

    # Backup first
    try:
        bzip = git_backup_repo(root)
        _safe_log(log_fn, f"[GIT] Backup created: {bzip}\n")
    except Exception as e:
        _safe_log(log_fn, f"[GIT] Backup warning: {e}\n")

    branch = status["branch"]
    lines: List[str] = []

    if status["dirty"]:
        commit_msg = message or (
            f"CITL App Sync auto-commit {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
        )
        rc, out, err = _git_run(root, "add", "-A")
        lines.append(f"git add: rc={rc}")
        if err:
            lines.append(err)

        rc, out, err = _git_run(root, "commit", "-m", commit_msg)
        lines.append(f"git commit: rc={rc} — {out or err}")
        if rc != 0:
            return False, "\n".join(lines)
    else:
        lines.append("Working tree clean — no new commit needed.")

    # Refresh remote refs, then determine ahead/behind.
    _git_run(root, "fetch", "--quiet", timeout=20)
    rc_ab, ab, _ = _git_run(root, "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}")
    ahead = behind = 0
    if rc_ab == 0 and ab:
        parts = ab.split()
        if len(parts) == 2:
            try:
                ahead = int(parts[0])
                behind = int(parts[1])
            except ValueError:
                pass

    # If behind/diverged, attempt rebase first so push can succeed.
    if behind > 0:
        lines.append(f"Local branch is behind remote by {behind}; attempting pull --rebase first.")
        rc, out, err = _git_run(root, "pull", "--rebase", "--autostash", "origin", branch, timeout=180)
        lines.append(f"git pull --rebase origin {branch}: rc={rc}")
        if out:
            lines.append(out)
        if err:
            lines.append(err)
        if rc != 0:
            lines.append(
                "Rebase/pull failed before push. Resolve conflicts in this repo, then retry push."
            )
            return False, "\n".join(lines)

        rc_ab, ab, _ = _git_run(root, "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}")
        ahead = behind = 0
        if rc_ab == 0 and ab:
            parts = ab.split()
            if len(parts) == 2:
                try:
                    ahead = int(parts[0])
                    behind = int(parts[1])
                except ValueError:
                    pass

    if not status["dirty"] and ahead == 0:
        lines.append("Already up to date with remote — nothing to push.")
        return True, "\n".join(lines)

    rc, out, err = _git_run(root, "push", "origin", branch, timeout=90)
    lines.append(f"git push origin {branch}: rc={rc}")
    if out:
        lines.append(out)
    if err:
        lines.append(err)
        # Surface auth errors clearly
        if any(k in err.lower() for k in ("authentication", "credential", "permission denied",
                                           "could not read", "403", "401", "token")):
            lines.append(
                "\n[AUTH HELP] Push requires GitHub authentication.\n"
                "Options:\n"
                "  1. Run in terminal: git config --global credential.helper manager\n"
                "  2. Use a Personal Access Token (PAT) as your password.\n"
                "  3. Set up an SSH key: ssh-keygen then add ~/.ssh/id_ed25519.pub to GitHub.\n"
                "  4. Run: gh auth login  (if GitHub CLI is installed)"
            )

    success = rc == 0
    return success, "\n".join(lines)


def git_pull_repo(
    repo: Path,
    log_fn: LogFn = None,
) -> Tuple[bool, str]:
    """
    Backup then pull from origin.
    Returns (success, summary_message).
    """
    root = _find_git_root(repo)
    if root is None:
        return False, "Not a git repo — cannot pull."

    # Backup first
    try:
        bzip = git_backup_repo(root)
        _safe_log(log_fn, f"[GIT] Backup created before pull: {bzip}\n")
    except Exception as e:
        _safe_log(log_fn, f"[GIT] Backup warning: {e}\n")

    status = git_status_for_repo(root)
    branch = status.get("branch", "main")

    rc, out, err = _git_run(root, "pull", "--rebase", "--autostash", "origin", branch, timeout=180)
    lines: List[str] = [f"git pull --rebase origin {branch}: rc={rc}"]
    if out:
        lines.append(out)
    if err:
        lines.append(err)
    if rc != 0:
        lines.append("Pull failed. If there are conflicts, resolve them and run pull again.")

    return rc == 0, "\n".join(lines)


def git_status_all_apps(source_repo: Path) -> Dict[str, Dict]:
    """
    Return git status for every app in CITL_APPS that has a git repo.
    Keys are app names.
    """
    results: Dict[str, Dict] = {}
    for app in CITL_APPS:
        root = resolve_app_source_root(app, source_repo)
        results[app["name"]] = git_status_for_repo(root)
    return results


# ── Ubuntu port automation ────────────────────────────────────────────────────
# Windows-only pip packages that must never appear in requirements-linux.txt
_WINDOWS_ONLY_PKGS: frozenset = frozenset({
    "pywin32", "pypiwin32", "winsound", "comtypes", "pywintypes",
    "winreg", "winshell", "pywinpty", "pyreadline3",
})

# Linux system packages needed for CITL on Ubuntu (auto-installed by setup.sh)
_UBUNTU_APT_DEPS: Tuple[str, ...] = (
    "python3-venv", "python3-tk", "python3-dev",
    "ffmpeg", "libportaudio2", "portaudio19-dev",
    "alsa-utils", "pulseaudio-utils", "build-essential",
    "git", "python3-gi",
)

# Linux-only pip packages to always ensure are in requirements-linux.txt
_LINUX_EXTRA_PKGS: Tuple[str, ...] = ("sounddevice",)


def _parse_requirements(path: Path) -> List[str]:
    """Return non-empty, non-comment lines from a requirements file."""
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def _pkg_name(req_line: str) -> str:
    """Extract the package name from a requirement line (strips version specifiers)."""
    return re.split(r"[>=<!;\[@\s]", req_line.strip())[0].lower().replace("-", "_")


def sync_requirements_linux(repo: Path) -> Tuple[bool, str]:
    """
    Derive requirements-linux.txt from requirements-windows.txt:
      - Strip Windows-only packages
      - Preserve all -r include lines
      - Ensure Linux-extra packages are present
      - Write only if content changed
    Returns (changed: bool, report: str).
    """
    win_req = repo / "requirements-windows.txt"
    lin_req = repo / "requirements-linux.txt"

    if not win_req.exists():
        return False, "requirements-windows.txt not found; skipping Linux requirements sync."

    win_lines = _parse_requirements(win_req)
    existing_linux = _parse_requirements(lin_req)
    existing_names = {_pkg_name(l) for l in existing_linux if not l.startswith("-r")}

    new_lines: List[str] = []
    removed: List[str] = []
    for line in win_lines:
        if line.startswith("-r"):
            # Replace -r requirements-windows.txt with -r requirements-linux.txt if present
            ref = line[2:].strip()
            if "windows" in ref.lower():
                ref = ref.lower().replace("windows", "linux")
            # Only include if the referenced file exists or it's not the windows req itself
            if ref != "requirements-windows.txt":
                new_lines.append(f"-r {ref}")
            continue
        pname = _pkg_name(line)
        if pname in _WINDOWS_ONLY_PKGS:
            removed.append(line)
            continue
        new_lines.append(line)

    added: List[str] = []
    present_names = {_pkg_name(l) for l in new_lines}
    for extra in _LINUX_EXTRA_PKGS:
        if extra.replace("-", "_") not in present_names:
            new_lines.append(extra)
            added.append(extra)

    new_content = "\n".join(new_lines) + "\n"
    old_content = lin_req.read_text(encoding="utf-8") if lin_req.exists() else ""

    if new_content == old_content:
        return False, "requirements-linux.txt already up to date."

    try:
        lin_req.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return False, f"Could not write requirements-linux.txt: {e}"

    parts = []
    if removed:
        parts.append(f"removed Windows-only: {', '.join(removed)}")
    if added:
        parts.append(f"added Linux extras: {', '.join(added)}")
    return True, f"Updated requirements-linux.txt — {'; '.join(parts) if parts else 'content changed'}."


def _render_setup_sh(repo: Path) -> str:
    """
    Generate scripts/linux/setup.sh content that mirrors scripts/windows/setup.ps1
    in terms of which requirements files it installs.
    """
    req_file = "requirements-linux.txt"
    apt_deps = " \\\n      ".join(_UBUNTU_APT_DEPS)
    return f"""#!/usr/bin/env bash
# Auto-generated by CITL App Sync — mirrors scripts/windows/setup.ps1
# Do not edit manually; changes are overwritten on next sync.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/../.." && pwd)"
echo "== CITL Setup (Ubuntu 24.04 LTS / Linux) =="
echo "Repo: $REPO_DIR"

# ── System deps (Ubuntu 24.04 LTS) ────────────────────────────────────────────
if command -v apt-get >/dev/null 2>&1; then
  SUDO=""
  command -v sudo >/dev/null 2>&1 && SUDO="sudo"
  ${{SUDO}} apt-get update -y
  ${{SUDO}} apt-get install -y \\
      {apt_deps}
fi

# ── Python venv ────────────────────────────────────────────────────────────────
cd "$REPO_DIR"
if [[ ! -d ".venv" ]]; then
  echo "Creating venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -U pip wheel setuptools

# ── Python deps ────────────────────────────────────────────────────────────────
if [[ -f "$REPO_DIR/{req_file}" ]]; then
  pip install -r "$REPO_DIR/{req_file}"
elif [[ -f "$REPO_DIR/requirements.txt" ]]; then
  pip install -r "$REPO_DIR/requirements.txt"
else
  echo "WARN: No requirements file found at $REPO_DIR/{req_file}"
fi

# ── Ubuntu port sync (keeps Linux files in step with Windows changes) ──────────
if python -c "import citl_app_sync" 2>/dev/null; then
  python -c "from citl_app_sync import port_to_ubuntu; from pathlib import Path; r=port_to_ubuntu(Path('$REPO_DIR')); [print(k+': '+v) for k,v in r.items()]" || true
fi

echo "Setup complete. Run: scripts/linux/run.sh"
"""


def sync_linux_setup_script(repo: Path) -> Tuple[bool, str]:
    """
    Regenerate scripts/linux/setup.sh to match what Windows setup.ps1 does,
    keeping apt deps and pip requirements in sync.
    """
    target = repo / "scripts" / "linux" / "setup.sh"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"Cannot create scripts/linux/: {e}"

    new_content = _render_setup_sh(repo)
    old_content = target.read_text(encoding="utf-8") if target.exists() else ""

    # Only regenerate if the file is auto-generated (has our marker) or missing
    if old_content and "Auto-generated by CITL App Sync" not in old_content:
        return False, "scripts/linux/setup.sh exists with custom content; skipping auto-regeneration."

    if new_content == old_content:
        return False, "scripts/linux/setup.sh already up to date."

    try:
        target.write_text(new_content, encoding="utf-8")
        # Make executable on non-Windows hosts
        if os.name != "nt":
            target.chmod(0o755)
    except Exception as e:
        return False, f"Could not write scripts/linux/setup.sh: {e}"

    return True, "Regenerated scripts/linux/setup.sh."


def sync_ubuntu_launchers(repo: Path) -> Tuple[bool, str]:
    """
    Ensure all root-level .sh launchers exist and reference correct paths.
    Regenerates any that are missing or have our auto-generated marker.
    """
    launchers = {
        "RUN_FACTBOOK.sh": (
            "#!/usr/bin/env bash\n"
            "# Auto-generated by CITL App Sync\n"
            'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'VENV="$DIR/.venv"\n'
            'if [[ ! -d "$VENV" ]]; then bash "$DIR/scripts/linux/setup.sh"; fi\n'
            'source "$VENV/bin/activate"\n'
            'GUI="$DIR/factbook-assistant/factbook_assistant_gui.py"\n'
            '[[ -f "$GUI" ]] || GUI="$DIR/factbook_assistant_gui.py"\n'
            'exec python "$GUI"\n'
        ),
        "RUN_APP_SYNC.sh": (
            "#!/usr/bin/env bash\n"
            "# Auto-generated by CITL App Sync\n"
            'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'VENV="$DIR/.venv"\n'
            'if [[ ! -d "$VENV" ]]; then bash "$DIR/scripts/linux/setup.sh"; fi\n'
            'source "$VENV/bin/activate"\n'
            'exec python "$DIR/factbook-assistant/citl_app_sync.py" "$@"\n'
        ),
        "RUN_APP_SYNC_UBUNTU.sh": (
            "#!/usr/bin/env bash\n"
            "# Auto-generated by CITL App Sync\n"
            'exec bash "$(dirname "${BASH_SOURCE[0]}")/RUN_APP_SYNC.sh" "$@"\n'
        ),
        "RUN_LLMOPS.sh": (
            "#!/usr/bin/env bash\n"
            "# Auto-generated by CITL App Sync\n"
            'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'VENV="$DIR/.venv"\n'
            'if [[ ! -d "$VENV" ]]; then bash "$DIR/scripts/linux/setup.sh"; fi\n'
            'source "$VENV/bin/activate"\n'
            'SCRIPT1="$DIR/factbook-assistant/citl_llmops_suite.py"\n'
            'SCRIPT2="$DIR/citl_llmops_suite.py"\n'
            'SCRIPT=""\n'
            'if [[ -f "$SCRIPT1" ]]; then SCRIPT="$SCRIPT1"; elif [[ -f "$SCRIPT2" ]]; then SCRIPT="$SCRIPT2"; fi\n'
            'if [[ -z "$SCRIPT" ]]; then echo "ERROR: LLMOps suite not found"; exit 1; fi\n'
            'if command -v python3 >/dev/null 2>&1; then exec python3 "$SCRIPT"; else exec python "$SCRIPT"; fi\n'
        ),
    }

    updated: List[str] = []
    skipped: List[str] = []
    for name, content in launchers.items():
        path = repo / name
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if old and "Auto-generated by CITL App Sync" not in old:
            skipped.append(name)
            continue
        if old == content:
            continue
        try:
            path.write_text(content, encoding="utf-8")
            if os.name != "nt":
                path.chmod(0o755)
            updated.append(name)
        except Exception:
            pass

    msg_parts = []
    if updated:
        msg_parts.append(f"Updated launchers: {', '.join(updated)}")
    if skipped:
        msg_parts.append(f"Skipped (custom content): {', '.join(skipped)}")
    changed = bool(updated)
    return changed, " | ".join(msg_parts) if msg_parts else "Launchers already up to date."


def _slugify_name(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "app").strip().lower()).strip("-")
    return slug or "app"


def _bootstrap_entry_rel(app: dict) -> str:
    rel = str(app.get("repo_marker") or "").strip()
    if rel:
        return rel.replace("\\", "/")
    keys = app.get("key_files") or []
    for item in keys:
        if str(item).strip():
            return str(item).replace("\\", "/")
    return ""


def _render_bootstrap_cmd(entry_rel: str, app_name: str) -> str:
    entry_win = entry_rel.replace("/", "\\")
    ext = Path(entry_rel).suffix.lower()
    base = (
        "@echo off\n"
        "setlocal\n"
        'set "HERE=%~dp0\\..\\.."\n'
        f'set "TARGET=%HERE%\\{entry_win}"\n'
        'if not exist "%TARGET%" (\n'
        f'  echo {app_name}: entry not found: %TARGET%\n'
        "  pause\n"
        "  exit /b 1\n"
        ")\n"
    )
    if ext in (".cmd", ".bat", ".exe"):
        run = '"%TARGET%" %*\n'
    elif ext == ".ps1":
        run = 'powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%" %*\n'
    elif ext == ".py":
        run = (
            'if exist "%HERE%\\.venv\\Scripts\\python.exe" (\n'
            '  "%HERE%\\.venv\\Scripts\\python.exe" "%TARGET%" %*\n'
            ") else (\n"
            "  where py >nul 2>&1\n"
            "  if %ERRORLEVEL%==0 (\n"
            "    py -3 \"%TARGET%\" %*\n"
            "  ) else (\n"
            "    python \"%TARGET%\" %*\n"
            "  )\n"
            ")\n"
        )
    else:
        run = 'powershell -NoProfile -Command "Start-Process \\"%HERE%\\""\n'
    return base + run + "exit /b %ERRORLEVEL%\n"


def _render_bootstrap_sh(entry_rel: str, app_name: str) -> str:
    ext = Path(entry_rel).suffix.lower()
    base = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"\n'
        f'TARGET="$HERE/{entry_rel}"\n'
        'if [[ ! -e "$TARGET" ]]; then\n'
        f'  echo "{app_name}: entry not found: $TARGET"\n'
        "  exit 1\n"
        "fi\n"
    )
    if ext == ".sh":
        run = 'exec bash "$TARGET" "$@"\n'
    elif ext == ".py":
        run = (
            'if [[ -x "$HERE/.venv/bin/python3" ]]; then\n'
            '  exec "$HERE/.venv/bin/python3" "$TARGET" "$@"\n'
            "fi\n"
            'if command -v python3 >/dev/null 2>&1; then exec python3 "$TARGET" "$@"; fi\n'
            'exec python "$TARGET" "$@"\n'
        )
    else:
        run = (
            f'echo "{app_name}: no Ubuntu-native launcher for {entry_rel}"\n'
            "echo \"Use this as a placeholder and run the Windows launcher on Windows hosts.\"\n"
            "exit 2\n"
        )
    return base + run


def sync_device_agnostic_bootstraps(repo: Path) -> Tuple[bool, str]:
    """
    Generate fallback launchers for apps missing an explicit Windows or Ubuntu launcher.
    This keeps USB copies runnable even when app-specific wrappers are absent.
    """
    win_dir = repo / "bootstrap" / "windows"
    nix_dir = repo / "bootstrap" / "linux"
    win_dir.mkdir(parents=True, exist_ok=True)
    nix_dir.mkdir(parents=True, exist_ok=True)

    updated: List[str] = []
    skipped: List[str] = []

    for app in CITL_APPS:
        app_name = str(app.get("name") or "App")
        slug = _slugify_name(app_name)
        entry_rel = _bootstrap_entry_rel(app)
        if not entry_rel:
            skipped.append(f"{app_name}(no-entry)")
            continue

        win_launcher = str(app.get("launcher_win") or "").strip()
        win_missing = not win_launcher or not (repo / win_launcher).exists()
        if win_missing:
            out = win_dir / f"Run-{slug}.cmd"
            content = _render_bootstrap_cmd(entry_rel, app_name)
            old = out.read_text(encoding="utf-8") if out.exists() else ""
            if old != content:
                out.write_text(content, encoding="utf-8")
                updated.append(out.as_posix())

        nix_launcher = str(app.get("launcher_nix") or "").strip()
        nix_missing = not nix_launcher or not (repo / nix_launcher).exists()
        if nix_missing:
            out = nix_dir / f"run-{slug}.sh"
            content = _render_bootstrap_sh(entry_rel, app_name)
            old = out.read_text(encoding="utf-8") if out.exists() else ""
            if old != content:
                out.write_text(content, encoding="utf-8")
                if os.name != "nt":
                    out.chmod(0o755)
                updated.append(out.as_posix())

    readme = repo / "bootstrap" / "README.txt"
    readme_text = (
        "CITL device-agnostic bootstrap launchers\n"
        "======================================\n\n"
        "These fallback scripts are auto-generated by CITL App Sync.\n"
        "They exist for apps that do not yet ship native launchers on both Windows and Ubuntu.\n\n"
        "Windows fallback folder: bootstrap/windows\n"
        "Ubuntu fallback folder:  bootstrap/linux\n"
    )
    old_readme = readme.read_text(encoding="utf-8") if readme.exists() else ""
    if old_readme != readme_text:
        readme.write_text(readme_text, encoding="utf-8")
        updated.append(readme.as_posix())

    if updated:
        return True, f"Generated/updated {len(updated)} bootstrap file(s)."
    if skipped:
        return False, "No bootstrap updates needed."
    return False, "Bootstrap launchers already up to date."


def _utc_now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    iso = text
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        return float(datetime.fromisoformat(iso).timestamp())
    except Exception:
        pass
    try:
        return float(text)
    except Exception:
        return 0.0


def _normalize_rel_path(rel_path: str) -> str:
    rel = str(rel_path or "").replace("\\", "/").strip().strip("/")
    if not rel:
        return ""
    parts = [p for p in rel.split("/") if p and p != "."]
    if not parts:
        return ""
    if any(p == ".." for p in parts):
        return ""
    return "/".join(parts)


def _drive_total_bytes(path: PathLike) -> int:
    try:
        return int(shutil.disk_usage(str(Path(path))).total)
    except Exception:
        return 0


_USB_MEDIA_PROFILE_CACHE: Dict[str, Tuple[float, Dict[str, object]]] = {}


def _windows_drive_filesystem(path: PathLike) -> str:
    if os.name != "nt":
        return ""
    p = Path(path).expanduser()
    drive = (p.drive or p.anchor or "").strip().rstrip("\\/").rstrip(":")
    if not drive:
        return ""
    letter = drive[0].upper()
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-Volume -DriveLetter '{letter}' -ErrorAction SilentlyContinue).FileSystem",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        out = (proc.stdout or "").strip()
        return out.lower()
    except Exception:
        return ""


def usb_media_profile(path: PathLike) -> Dict[str, object]:
    root = Path(path).expanduser()
    try:
        cache_key = str(root.resolve())
    except Exception:
        cache_key = str(root)
    cached = _USB_MEDIA_PROFILE_CACHE.get(cache_key)
    now = time.time()
    if cached and (now - cached[0]) <= USB_MEDIA_CACHE_TTL_SEC:
        return dict(cached[1])
    total = _drive_total_bytes(root)
    fs = _windows_drive_filesystem(root)
    profile = {
        "path": str(root),
        "total_bytes": total,
        "total_human": _fmt_bytes(total),
        "filesystem": fs or "unknown",
    }
    _USB_MEDIA_PROFILE_CACHE[cache_key] = (now, dict(profile))
    return profile


def is_expected_usb_bootstrap_media(path: PathLike) -> Tuple[bool, str]:
    profile = usb_media_profile(path)
    total = int(profile.get("total_bytes") or 0)
    fs = str(profile.get("filesystem") or "").lower()
    min_bytes = 40 * 1024 * 1024 * 1024
    max_bytes = 80 * 1024 * 1024 * 1024
    size_ok = min_bytes <= total <= max_bytes
    if os.name == "nt":
        fs_ok = ("exfat" in fs) or ("fat32" in fs)
    else:
        fs_ok = True
    ok = bool(size_ok and fs_ok)
    reason = (
        f"media={profile.get('path')} fs={profile.get('filesystem')} "
        f"size={profile.get('total_human')} expected_fs=exfat/fat32 expected_size=40-80GB"
    )
    return ok, reason


def _bootstrap_state_path(repo: PathLike) -> Path:
    return Path(repo).expanduser().resolve() / BOOTSTRAP_STATE_REL


def _bootstrap_default_state() -> Dict[str, object]:
    return {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "updated_utc": "",
        "last_applied": {},
        "app_patch_state": {},
        "history": [],
        "rollback_stack": [],
    }


def load_bootstrap_repo_state(repo: PathLike) -> Dict[str, object]:
    state = _bootstrap_default_state()
    path = _bootstrap_state_path(repo)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return state
    if not isinstance(raw, dict):
        return state

    for key in ("last_applied",):
        if isinstance(raw.get(key), dict):
            state[key] = raw.get(key) or {}
    for key in ("app_patch_state",):
        if isinstance(raw.get(key), dict):
            state[key] = raw.get(key) or {}
    for key in ("history", "rollback_stack"):
        if isinstance(raw.get(key), list):
            state[key] = raw.get(key) or []
    if isinstance(raw.get("updated_utc"), str):
        state["updated_utc"] = raw.get("updated_utc") or ""
    return state


def save_bootstrap_repo_state(repo: PathLike, data: Dict[str, object]) -> None:
    path = _bootstrap_state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _bootstrap_default_state()
    if isinstance(data.get("last_applied"), dict):
        payload["last_applied"] = data.get("last_applied") or {}
    if isinstance(data.get("app_patch_state"), dict):
        payload["app_patch_state"] = data.get("app_patch_state") or {}
    if isinstance(data.get("history"), list):
        payload["history"] = list(data.get("history") or [])[-100:]
    if isinstance(data.get("rollback_stack"), list):
        payload["rollback_stack"] = list(data.get("rollback_stack") or [])[-20:]
    payload["updated_utc"] = _utc_now_iso()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _patch_cadence_state_path(repo: PathLike) -> Path:
    return Path(repo).expanduser().resolve() / BOOTSTRAP_CADENCE_STATE_REL


def _default_patch_cadence_state() -> Dict[str, object]:
    return {
        "schema_version": 1,
        "updated_utc": "",
        "last_auto_run_utc": "",
        "last_auto_run_ts": 0.0,
        "last_auto_package_id": "",
        "last_manual_run_utc": "",
        "last_manual_run_ts": 0.0,
        "last_manual_package_id": "",
        "history": [],
    }


def load_patch_cadence_state(repo: PathLike) -> Dict[str, object]:
    state = _default_patch_cadence_state()
    path = _patch_cadence_state_path(repo)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return state
    if not isinstance(raw, dict):
        return state
    for key in (
        "updated_utc",
        "last_auto_run_utc",
        "last_auto_package_id",
        "last_manual_run_utc",
        "last_manual_package_id",
    ):
        if isinstance(raw.get(key), str):
            state[key] = raw.get(key) or ""
    for key in ("last_auto_run_ts", "last_manual_run_ts"):
        try:
            state[key] = float(raw.get(key) or 0.0)
        except Exception:
            state[key] = 0.0
    if isinstance(raw.get("history"), list):
        state["history"] = raw.get("history") or []
    return state


def save_patch_cadence_state(repo: PathLike, data: Dict[str, object]) -> None:
    path = _patch_cadence_state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _default_patch_cadence_state()
    for key in (
        "last_auto_run_utc",
        "last_auto_package_id",
        "last_manual_run_utc",
        "last_manual_package_id",
    ):
        if isinstance(data.get(key), str):
            payload[key] = data.get(key) or ""
    for key in ("last_auto_run_ts", "last_manual_run_ts"):
        try:
            payload[key] = float(data.get(key) or 0.0)
        except Exception:
            payload[key] = 0.0
    if isinstance(data.get("history"), list):
        payload["history"] = list(data.get("history") or [])[-120:]
    payload["updated_utc"] = _utc_now_iso()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _default_cadence_app_names() -> List[str]:
    names: List[str] = []
    for app in CITL_APPS:
        app_name = str(app.get("name") or "").strip()
        if not app_name:
            continue
        if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS:
            if _app_has_tag(app, SYNC_TAG_HENOSIS):
                names.append(app_name)
            continue
        # Prevent HENOSIS apps from bleeding into default CITL cadence runs.
        if _app_has_tag(app, SYNC_TAG_HENOSIS):
            continue
        names.append(app_name)
    return names


def _collect_app_changes_since(
    source_repo: PathLike,
    app_names: Sequence[str],
    since_ts: float,
) -> Dict[str, Dict[str, object]]:
    src = Path(source_repo).expanduser().resolve()
    wanted = {str(n).strip() for n in app_names if str(n).strip()}
    out: Dict[str, Dict[str, object]] = {}
    for app in CITL_APPS:
        app_name = str(app.get("name") or "").strip()
        if not app_name or app_name not in wanted:
            continue
        changed = 0
        newest_ts = 0.0
        sample_paths: List[str] = []
        for rel_path, src_path in _iter_bootstrap_app_files(src, app):
            try:
                ts = float(src_path.stat().st_mtime)
            except Exception:
                continue
            if ts + UPDATE_AVAILABLE_EPSILON_SEC < since_ts:
                continue
            changed += 1
            if ts > newest_ts:
                newest_ts = ts
            if len(sample_paths) < 10:
                sample_paths.append(rel_path)
        if changed > 0:
            out[app_name] = {
                "changed_file_count": changed,
                "newest_ts": newest_ts,
                "newest_utc": _fmt_ts(newest_ts),
                "sample_paths": sample_paths,
            }
    return out


def _iter_bootstrap_app_files(source_repo: Path, app: dict) -> Iterable[Tuple[str, Path]]:
    app_root = resolve_app_source_root(app, source_repo)
    key_files = app.get("key_files") or []
    for rel in key_files:
        rel_raw = str(rel or "").strip()
        if not rel_raw:
            continue
        src_path = app_root / rel_raw
        rel_base = _normalize_rel_path(rel_raw)
        if not rel_base:
            continue
        if not src_path.exists():
            continue
        if src_path.is_file():
            yield rel_base, src_path
            continue
        if src_path.is_dir():
            for child in sorted(src_path.rglob("*")):
                if not child.is_file():
                    continue
                rel_child = child.relative_to(src_path).as_posix()
                rel_path = _normalize_rel_path(f"{rel_base}/{rel_child}")
                if rel_path:
                    yield rel_path, child


def _read_bootstrap_manifest_dict(zip_path: PathLike) -> Optional[Dict[str, object]]:
    path = Path(zip_path).expanduser()
    try:
        with zipfile.ZipFile(path, "r") as zf:
            candidates = [
                BOOTSTRAP_MANIFEST_NAME,
                "manifest.json",
                "bootstrap_manifest.json",
            ]
            name = ""
            for c in candidates:
                if c in zf.namelist():
                    name = c
                    break
            if not name:
                return None
            text = zf.read(name).decode("utf-8", errors="replace")
            raw = json.loads(text)
            if not isinstance(raw, dict):
                return None
            return raw
    except Exception:
        return None


def _package_from_manifest(zip_path: PathLike, source_hint: str = "") -> Optional[BootstrapPackage]:
    path = Path(zip_path).expanduser()
    manifest = _read_bootstrap_manifest_dict(path)
    if manifest is None:
        return None

    bootstrap_id = str(manifest.get("bootstrap_id") or "").strip()
    if not bootstrap_id:
        bootstrap_id = path.stem
    created_utc = str(manifest.get("created_utc") or "").strip()
    created_ts = _parse_ts(created_utc)
    if created_ts <= 0:
        created_ts = _parse_ts(manifest.get("created_epoch"))
    if created_ts <= 0:
        try:
            created_ts = float(path.stat().st_mtime)
        except Exception:
            created_ts = 0.0

    apps_raw = manifest.get("apps") if isinstance(manifest.get("apps"), list) else []
    app_names: List[str] = []
    app_file_counts: Dict[str, int] = {}
    file_count = 0
    for item in apps_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        files = item.get("files")
        if isinstance(files, list):
            count = sum(1 for f in files if isinstance(f, str) and _normalize_rel_path(f))
        else:
            count = int(item.get("file_count") or 0)
        app_names.append(name)
        app_file_counts[name] = count
        file_count += count

    if not app_names:
        flat = manifest.get("app_names")
        if isinstance(flat, list):
            app_names = [str(x).strip() for x in flat if str(x).strip()]
            for name in app_names:
                app_file_counts[name] = 0
        if not app_names:
            return None

    try:
        package_size = int(path.stat().st_size)
    except Exception:
        package_size = 0

    payload_bytes = int(manifest.get("payload_bytes") or 0)
    source_repo_label = str(manifest.get("source_repo") or "").strip() or "unknown"
    source_hint_text = source_hint or str(path.parent)
    return BootstrapPackage(
        path=path.resolve(),
        bootstrap_id=bootstrap_id,
        created_utc=created_utc or _fmt_ts(created_ts),
        created_ts=created_ts,
        package_size=package_size,
        app_names=tuple(app_names),
        app_file_counts=app_file_counts,
        file_count=file_count,
        payload_bytes=payload_bytes,
        source_repo_label=source_repo_label,
        source_hint=source_hint_text,
    )


def discover_bootstrap_packages(search_roots: Sequence[Tuple[str, PathLike]]) -> List[BootstrapPackage]:
    packages: List[BootstrapPackage] = []
    seen: set = set()
    for hint, root_like in search_roots:
        root = Path(root_like).expanduser()
        candidates = [
            root / BOOTSTRAP_PATCH_DIR_REL,
            root / "bootstrap" / "packages",
            root / "bootstrap",
        ]
        for folder in candidates:
            if not folder.exists() or not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.zip")):
                try:
                    key = str(path.resolve())
                except Exception:
                    key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                pkg = _package_from_manifest(path, source_hint=hint)
                if pkg is not None:
                    packages.append(pkg)
    def _sort_key(pkg: BootstrapPackage) -> Tuple[float, float]:
        mtime = 0.0
        try:
            if pkg.path.exists():
                mtime = float(pkg.path.stat().st_mtime)
        except Exception:
            mtime = 0.0
        return (pkg.created_ts, mtime)

    packages.sort(key=_sort_key, reverse=True)
    return packages


def build_bootstrap_package(
    source_repo: PathLike,
    selected_apps: Optional[Sequence[str]] = None,
    tag_prefix: str = "",
    build_reason: str = "",
    log_fn: LogFn = None,
) -> Tuple[bool, str, Optional[BootstrapPackage]]:
    source = Path(source_repo).expanduser().resolve()
    selected = {str(x).strip() for x in (selected_apps or []) if str(x).strip()}
    if not selected:
        selected = {str(app.get("name") or "").strip() for app in CITL_APPS if str(app.get("name") or "").strip()}

    skip_prefixes = (
        _normalize_rel_path(BOOTSTRAP_PATCH_DIR_REL) + "/",
        _normalize_rel_path(BOOTSTRAP_ROLLBACK_DIR_REL) + "/",
    )
    skip_exact = {
        _normalize_rel_path(BOOTSTRAP_STATE_REL),
    }

    app_files: Dict[str, List[str]] = {}
    payload_sources: Dict[str, Path] = {}
    payload_bytes = 0

    for app in CITL_APPS:
        app_name = str(app.get("name") or "").strip()
        if not app_name or app_name not in selected:
            continue
        rels: List[str] = []
        rel_seen: set = set()
        for rel_path, src_path in _iter_bootstrap_app_files(source, app):
            if rel_path in skip_exact or any(rel_path.startswith(prefix) for prefix in skip_prefixes):
                continue
            if rel_path not in payload_sources:
                payload_sources[rel_path] = src_path
                try:
                    payload_bytes += int(src_path.stat().st_size)
                except Exception:
                    pass
            if rel_path not in rel_seen:
                rels.append(rel_path)
                rel_seen.add(rel_path)
        if rels:
            app_files[app_name] = sorted(rels)
            _safe_log(log_fn, f"[BOOTSTRAP][BUILD] {app_name}: {len(rels)} file(s)\n")

    if not payload_sources:
        return False, "No files found for selected apps. Bootstrap package was not created.", None

    created_utc = _utc_now_iso()
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1()
    for rel in sorted(payload_sources):
        digest.update(rel.encode("utf-8", errors="ignore"))
        try:
            digest.update(str(payload_sources[rel].stat().st_size).encode("ascii", errors="ignore"))
        except Exception:
            digest.update(b"0")
    short_hash = digest.hexdigest()[:10]
    tag_raw = str(tag_prefix or "").strip().upper()
    tag_clean = re.sub(r"[^A-Z0-9]+", "", tag_raw)[:8]
    tag_part = f"{tag_clean}-" if tag_clean else ""
    file_tag_part = f"{tag_clean}_" if tag_clean else ""
    bootstrap_id = f"{tag_part}{stamp}-{short_hash}"

    out_dir = source / BOOTSTRAP_PATCH_DIR_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"citl_bootstrap_{file_tag_part}{stamp}_{short_hash[:8]}.zip"

    apps_manifest = []
    for app_name in sorted(app_files.keys()):
        files = app_files[app_name]
        apps_manifest.append(
            {
                "name": app_name,
                "file_count": len(files),
                "files": files,
            }
        )
    manifest = {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "bootstrap_id": bootstrap_id,
        "created_utc": created_utc,
        "created_epoch": _parse_ts(created_utc),
        "generator_app": APP_SYNC_NAME,
        "generator_version": APP_SYNC_VERSION,
        "source_repo": source.name,
        "source_repo_path": str(source),
        "build_reason": str(build_reason or "").strip() or None,
        "patch_tag": tag_clean or None,
        "app_names": sorted(app_files.keys()),
        "apps": apps_manifest,
        "file_count": len(payload_sources),
        "payload_bytes": payload_bytes,
    }

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(payload_sources):
            arc = f"payload/{rel}"
            zf.write(payload_sources[rel], arcname=arc)
        zf.writestr(BOOTSTRAP_MANIFEST_NAME, json.dumps(manifest, indent=2))

    package = _package_from_manifest(out_path, source_hint="local-source")
    if package is None:
        return False, f"Bootstrap package created but manifest parse failed: {out_path}", None
    scripts_ok, scripts_msg, _script_paths = generate_bootstrap_patch_scripts(source, package, log_fn=log_fn)
    msg = (
        f"Created bootstrap package {out_path.name} "
        f"({len(package.app_names)} app(s), {package.file_count} file(s), {_fmt_bytes(package.package_size)}). "
        f"{scripts_msg if scripts_ok else f'Script generation warning: {scripts_msg}'}"
    )
    return True, msg, package


def generate_bootstrap_patch_scripts(
    source_repo: PathLike,
    package: BootstrapPackage,
    log_fn: LogFn = None,
) -> Tuple[bool, str, List[Path]]:
    repo = Path(source_repo).expanduser().resolve()
    out_dir = repo / BOOTSTRAP_PATCH_DIR_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        rel_pkg = package.path.resolve().relative_to(repo).as_posix()
    except Exception:
        rel_pkg = package.path.resolve().as_posix()
    rel_pkg_win = rel_pkg.replace("/", "\\")
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", package.bootstrap_id).strip("_") or "bootstrap"

    ps1_path = out_dir / f"apply_bootstrap_{slug}.ps1"
    bat_path = out_dir / f"apply_bootstrap_{slug}.bat"
    sh_path = out_dir / f"apply_bootstrap_{slug}.sh"

    ps1 = (
        "param(\n"
        "  [switch]$AlsoUsb\n"
        ")\n"
        "$ErrorActionPreference = 'Stop'\n"
        "$Repo = Split-Path -Parent $PSScriptRoot\n"
        "$Repo = Split-Path -Parent $Repo\n"
        "$SyncPy = Join-Path $Repo 'factbook-assistant\\citl_app_sync.py'\n"
        f"$Pkg = Join-Path $Repo '{rel_pkg_win}'\n"
        "if (!(Test-Path -LiteralPath $SyncPy)) { throw \"citl_app_sync.py not found: $SyncPy\" }\n"
        "if (!(Test-Path -LiteralPath $Pkg)) { throw \"bootstrap package not found: $Pkg\" }\n"
        "$args = @('--bootstrap-install-package', $Pkg, '--bootstrap-install-target', 'local')\n"
        "if ($AlsoUsb) { $args += '--bootstrap-install-usb-if-found' }\n"
        "if (Get-Command py -ErrorAction SilentlyContinue) {\n"
        "  & py -3 $SyncPy @args\n"
        "} else {\n"
        "  & python $SyncPy @args\n"
        "}\n"
        "exit $LASTEXITCODE\n"
    )
    bat = (
        "@echo off\n"
        "setlocal\n"
        'set "SCRIPT=%~dp0apply_bootstrap_' + slug + '.ps1"\n'
        "powershell -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT%\" %*\n"
        "exit /b %ERRORLEVEL%\n"
    )
    sh = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'REPO="$(cd "$HERE/../.." && pwd)"\n'
        'SYNC_PY="$REPO/factbook-assistant/citl_app_sync.py"\n'
        f'PKG="$REPO/{rel_pkg}"\n'
        'ARGS=(--bootstrap-install-package "$PKG" --bootstrap-install-target local)\n'
        'if [[ "${1:-}" == "--also-usb" ]]; then\n'
        "  ARGS+=(--bootstrap-install-usb-if-found)\n"
        "  shift\n"
        "fi\n"
        'ARGS+=("$@")\n'
        'if [[ ! -f "$SYNC_PY" ]]; then echo "Missing: $SYNC_PY"; exit 1; fi\n'
        'if [[ ! -f "$PKG" ]]; then echo "Missing: $PKG"; exit 1; fi\n'
        'if [[ -x "$REPO/.venv/bin/python3" ]]; then exec "$REPO/.venv/bin/python3" "$SYNC_PY" "${ARGS[@]}"; fi\n'
        'if command -v python3 >/dev/null 2>&1; then exec python3 "$SYNC_PY" "${ARGS[@]}"; fi\n'
        'exec python "$SYNC_PY" "${ARGS[@]}"\n'
    )

    try:
        ps1_path.write_text(ps1, encoding="utf-8")
        bat_path.write_text(bat, encoding="utf-8")
        sh_path.write_text(sh, encoding="utf-8")
        if os.name != "nt":
            sh_path.chmod(0o755)
        _safe_log(
            log_fn,
            f"[BOOTSTRAP][SCRIPTS] generated: {ps1_path.name}, {bat_path.name}, {sh_path.name}\n",
        )
        return True, "Generated patch scripts (.ps1/.bat/.sh).", [ps1_path, bat_path, sh_path]
    except Exception as exc:
        return False, str(exc), []


def preview_bootstrap_install(
    package: BootstrapPackage,
    dest_repo: PathLike,
    selected_apps: Optional[Sequence[str]] = None,
) -> BootstrapInstallPreview:
    state = load_bootstrap_repo_state(dest_repo)
    app_state = state.get("app_patch_state") if isinstance(state.get("app_patch_state"), dict) else {}
    wanted = {str(x).strip() for x in (selected_apps or []) if str(x).strip()}
    names = [n for n in package.app_names if (not wanted or n in wanted)]
    newer = 0
    same = 0
    older = 0
    for name in names:
        prev = app_state.get(name) if isinstance(app_state, dict) else {}
        prev_ts = 0.0
        if isinstance(prev, dict):
            prev_ts = _parse_ts(prev.get("bootstrap_created_utc"))
            if prev_ts <= 0:
                prev_ts = _parse_ts(prev.get("bootstrap_created_ts"))
        if prev_ts <= 0:
            newer += 1
        elif package.created_ts > (prev_ts + BOOTSTRAP_WARN_EPSILON_SEC):
            newer += 1
        elif package.created_ts + BOOTSTRAP_WARN_EPSILON_SEC < prev_ts:
            older += 1
        else:
            same += 1

    total = len(names)
    if total <= 0 or newer <= 0:
        classification = "none"
    elif newer == total:
        classification = "all"
    else:
        classification = "some"

    stale = False
    stale_reason = ""
    last = state.get("last_applied") if isinstance(state.get("last_applied"), dict) else {}
    last_ts = _parse_ts(last.get("bootstrap_created_utc")) if isinstance(last, dict) else 0.0
    if last_ts > 0 and package.created_ts + BOOTSTRAP_WARN_EPSILON_SEC < last_ts:
        stale = True
        stale_reason = (
            f"Selected package ({_fmt_ts(package.created_ts)}) appears older than last applied "
            f"({_fmt_ts(last_ts)})."
        )
    elif older > 0:
        stale = True
        stale_reason = f"{older} selected app(s) appear older than currently installed patch state."

    return BootstrapInstallPreview(
        total_apps=total,
        newer_apps=newer,
        same_apps=same,
        older_apps=older,
        classification=classification,
        stale=stale,
        stale_reason=stale_reason,
    )


def _manifest_app_files(manifest: Dict[str, object]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    apps = manifest.get("apps")
    if not isinstance(apps, list):
        return out
    for item in apps:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        files = item.get("files")
        if not name or not isinstance(files, list):
            continue
        clean: List[str] = []
        seen: set = set()
        for rel in files:
            rel_norm = _normalize_rel_path(str(rel or ""))
            if not rel_norm or rel_norm in seen:
                continue
            seen.add(rel_norm)
            clean.append(rel_norm)
        out[name] = clean
    return out


def _create_bootstrap_rollback_snapshot(
    repo: Path,
    rel_files: Sequence[str],
    package: BootstrapPackage,
    previous_state: Dict[str, object],
) -> Path:
    rollback_dir = repo / BOOTSTRAP_ROLLBACK_DIR_REL
    rollback_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", package.bootstrap_id)[:60]
    zip_path = rollback_dir / f"rollback_{stamp}_{safe_id}.zip"

    files_manifest: List[Dict[str, object]] = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(set(rel_files)):
            rel_norm = _normalize_rel_path(rel)
            if not rel_norm:
                continue
            dst = repo / rel_norm
            existed = dst.exists() and dst.is_file()
            files_manifest.append(
                {
                    "rel_path": rel_norm,
                    "existed_before": bool(existed),
                }
            )
            if existed:
                zf.write(dst, arcname=f"before/{rel_norm}")
        rollback_manifest = {
            "schema_version": BOOTSTRAP_SCHEMA_VERSION,
            "created_utc": _utc_now_iso(),
            "bootstrap_id": package.bootstrap_id,
            "package_path": str(package.path),
            "files": files_manifest,
            "previous_state": {
                "last_applied": previous_state.get("last_applied") if isinstance(previous_state.get("last_applied"), dict) else {},
                "app_patch_state": previous_state.get("app_patch_state") if isinstance(previous_state.get("app_patch_state"), dict) else {},
            },
        }
        zf.writestr(BOOTSTRAP_ROLLBACK_MANIFEST_NAME, json.dumps(rollback_manifest, indent=2))
    return zip_path


def apply_bootstrap_package_to_repo(
    package: BootstrapPackage,
    dest_repo: PathLike,
    selected_apps: Optional[Sequence[str]] = None,
    log_fn: LogFn = None,
) -> Tuple[bool, str]:
    repo = Path(dest_repo).expanduser().resolve()
    manifest = _read_bootstrap_manifest_dict(package.path)
    if manifest is None:
        return False, f"Manifest not found in package: {package.path}"

    app_files = _manifest_app_files(manifest)
    if not app_files:
        return False, f"Package manifest has no app file list: {package.path}"

    wanted = {str(x).strip() for x in (selected_apps or []) if str(x).strip()}
    chosen_apps = [name for name in app_files.keys() if (not wanted or name in wanted)]
    if not chosen_apps:
        return False, "No selected apps matched this bootstrap package."

    rel_files: List[str] = []
    rel_seen: set = set()
    for app_name in chosen_apps:
        for rel in app_files.get(app_name, []):
            if rel not in rel_seen:
                rel_seen.add(rel)
                rel_files.append(rel)

    state_before = load_bootstrap_repo_state(repo)
    snapshot_zip = _create_bootstrap_rollback_snapshot(repo, rel_files, package, state_before)
    _safe_log(log_fn, f"[BOOTSTRAP][SNAPSHOT] {snapshot_zip}\n")

    copied = 0
    errors = 0
    bytes_written = 0
    with zipfile.ZipFile(package.path, "r") as zf:
        names = set(zf.namelist())
        for rel in rel_files:
            rel_norm = _normalize_rel_path(rel)
            if not rel_norm:
                errors += 1
                _safe_log(log_fn, f"[BOOTSTRAP][ERR] unsafe rel path skipped: {rel}\n")
                continue
            arc = f"payload/{rel_norm}"
            if arc not in names:
                errors += 1
                _safe_log(log_fn, f"[BOOTSTRAP][ERR] missing payload entry: {arc}\n")
                continue
            dst = repo / rel_norm
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(arc, "r") as src_fh, open(dst, "wb") as dst_fh:
                    shutil.copyfileobj(src_fh, dst_fh)
                copied += 1
                try:
                    bytes_written += int(dst.stat().st_size)
                except Exception:
                    pass
            except Exception as exc:
                errors += 1
                _safe_log(log_fn, f"[BOOTSTRAP][ERR] {rel_norm}: {exc}\n")

    state_after = load_bootstrap_repo_state(repo)
    if not isinstance(state_after.get("app_patch_state"), dict):
        state_after["app_patch_state"] = {}
    app_patch_state = state_after.get("app_patch_state") or {}
    applied_utc = _utc_now_iso()
    for app_name in chosen_apps:
        app_patch_state[app_name] = {
            "bootstrap_id": package.bootstrap_id,
            "bootstrap_created_utc": package.created_utc,
            "bootstrap_created_ts": package.created_ts,
            "applied_utc": applied_utc,
            "package_size_bytes": package.package_size,
            "package_path": str(package.path),
            "file_count": len(app_files.get(app_name, [])),
        }
    state_after["app_patch_state"] = app_patch_state

    install_event = {
        "event": "install",
        "applied_utc": applied_utc,
        "bootstrap_id": package.bootstrap_id,
        "bootstrap_created_utc": package.created_utc,
        "package_path": str(package.path),
        "package_size_bytes": package.package_size,
        "apps": chosen_apps,
        "copied_files": copied,
        "errors": errors,
        "bytes_written": bytes_written,
        "rollback_snapshot": str(snapshot_zip),
    }
    state_after["last_applied"] = install_event
    hist = state_after.get("history") if isinstance(state_after.get("history"), list) else []
    hist.append(install_event)
    state_after["history"] = hist[-100:]
    rollback_stack = state_after.get("rollback_stack") if isinstance(state_after.get("rollback_stack"), list) else []
    rollback_stack.append(
        {
            "created_utc": applied_utc,
            "bootstrap_id": package.bootstrap_id,
            "snapshot_path": str(snapshot_zip),
            "apps": chosen_apps,
        }
    )
    state_after["rollback_stack"] = rollback_stack[-20:]
    save_bootstrap_repo_state(repo, state_after)

    msg = (
        f"Installed bootstrap {package.bootstrap_id} to {repo.name}: "
        f"apps={len(chosen_apps)} files={copied} errors={errors} bytes={_fmt_bytes(bytes_written)} "
        f"rollback={snapshot_zip.name}"
    )
    return errors == 0, msg


def rollback_last_bootstrap_on_repo(dest_repo: PathLike, log_fn: LogFn = None) -> Tuple[bool, str]:
    repo = Path(dest_repo).expanduser().resolve()
    state = load_bootstrap_repo_state(repo)
    stack = state.get("rollback_stack") if isinstance(state.get("rollback_stack"), list) else []
    if not stack:
        return False, f"No rollback snapshot is available for {repo}."

    entry = stack[-1]
    snapshot_path_raw = str(entry.get("snapshot_path") or "").strip()
    if not snapshot_path_raw:
        return False, "Rollback entry is missing snapshot path."
    snap_path = Path(snapshot_path_raw).expanduser()
    if not snap_path.is_absolute():
        snap_path = repo / snap_path
    if not snap_path.exists():
        return False, f"Rollback snapshot not found: {snap_path}"

    restored = 0
    removed = 0
    with zipfile.ZipFile(snap_path, "r") as zf:
        if BOOTSTRAP_ROLLBACK_MANIFEST_NAME not in zf.namelist():
            return False, f"Rollback manifest missing in {snap_path.name}."
        manifest = json.loads(zf.read(BOOTSTRAP_ROLLBACK_MANIFEST_NAME).decode("utf-8", errors="replace"))
        files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
        for item in files:
            if not isinstance(item, dict):
                continue
            rel = _normalize_rel_path(str(item.get("rel_path") or ""))
            if not rel:
                continue
            existed_before = bool(item.get("existed_before"))
            dst = repo / rel
            if existed_before:
                arc = f"before/{rel}"
                if arc not in zf.namelist():
                    _safe_log(log_fn, f"[BOOTSTRAP][ROLLBACK][WARN] missing snapshot file {arc}\n")
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(arc, "r") as src_fh, open(dst, "wb") as dst_fh:
                    shutil.copyfileobj(src_fh, dst_fh)
                restored += 1
            else:
                if dst.exists():
                    if dst.is_file():
                        dst.unlink(missing_ok=True)
                        removed += 1
                    elif dst.is_dir():
                        shutil.rmtree(dst, ignore_errors=True)
                        removed += 1

        previous_state = manifest.get("previous_state") if isinstance(manifest.get("previous_state"), dict) else {}
        if isinstance(previous_state.get("app_patch_state"), dict):
            state["app_patch_state"] = previous_state.get("app_patch_state") or {}
        else:
            state["app_patch_state"] = {}
        if isinstance(previous_state.get("last_applied"), dict):
            state["last_applied"] = previous_state.get("last_applied") or {}
        else:
            state["last_applied"] = {}

    stack = state.get("rollback_stack") if isinstance(state.get("rollback_stack"), list) else []
    if stack:
        stack = stack[:-1]
    state["rollback_stack"] = stack
    history = state.get("history") if isinstance(state.get("history"), list) else []
    history.append(
        {
            "event": "rollback",
            "applied_utc": _utc_now_iso(),
            "snapshot_path": str(snap_path),
            "restored_files": restored,
            "removed_files": removed,
            "for_bootstrap_id": str(entry.get("bootstrap_id") or ""),
        }
    )
    state["history"] = history[-100:]
    save_bootstrap_repo_state(repo, state)

    return True, (
        f"Rollback complete for {repo.name}: restored={restored} removed={removed} "
        f"snapshot={snap_path.name}"
    )


# ── Git-based patch detection and packaging ───────────────────────────────────

def detect_git_patches(repo: PathLike, max_count: int = 30) -> List[dict]:
    """
    Return a list of recent git commits from the repo, newest first.
    Each entry: {hash, short_hash, date_iso, subject, files, file_count}
    Returns [] if repo is not a git repo or git is unavailable.
    """
    git_root = _find_git_root(Path(repo).expanduser().resolve())
    if git_root is None:
        return []

    rc, out, _ = _git_run(
        git_root,
        "log",
        f"--max-count={max_count}",
        "--pretty=format:%H|%ai|%s",
        timeout=20,
    )
    if rc != 0 or not out.strip():
        return []

    commits: List[dict] = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        full_hash = parts[0].strip()
        date_iso  = parts[1].strip()
        subject   = parts[2].strip()

        rc2, files_out, _ = _git_run(
            git_root,
            "diff-tree", "--no-commit-id", "-r", "--name-only",
            "--diff-filter=ACMRD",
            full_hash,
            timeout=15,
        )
        files = [f.strip() for f in files_out.splitlines() if f.strip()] if rc2 == 0 else []

        commits.append({
            "hash":       full_hash,
            "short_hash": full_hash[:8],
            "date_iso":   date_iso,
            "subject":    subject,
            "files":      files,
            "file_count": len(files),
        })

    return commits


def build_git_patch_from_commits(
    source_repo: PathLike,
    commit_hashes: Sequence[str],
    log_fn: LogFn = None,
) -> Tuple[bool, str, Optional[BootstrapPackage]]:
    """
    Build a bootstrap-compatible patch ZIP from the files changed in the
    given git commits.  Files are read from the current working tree.
    Also generates apply scripts (.ps1/.bat/.sh) in bootstrap/patches/.

    Returns (ok, message, BootstrapPackage | None).
    """
    source = Path(source_repo).expanduser().resolve()
    git_root = _find_git_root(source) or source
    hashes = [h.strip() for h in commit_hashes if h.strip()]

    if not hashes:
        return False, "No commits provided.", None

    # ── 1. Collect all files changed across the given commits ─────────────────
    changed_files: set = set()
    for commit in hashes:
        rc, out, _ = _git_run(
            git_root,
            "diff-tree", "--no-commit-id", "-r", "--name-only",
            "--diff-filter=ACMRD",
            commit,
            timeout=15,
        )
        if rc == 0:
            for f in out.splitlines():
                rel = _normalize_rel_path(f.strip())
                if rel:
                    changed_files.add(rel)

    if not changed_files:
        return False, "No file changes found in selected commits (they may only contain deletes or merges).", None

    _safe_log(log_fn, f"[GIT-PATCH] {len(changed_files)} changed path(s) across {len(hashes)} commit(s).\n")

    skip_prefixes = (
        _normalize_rel_path(BOOTSTRAP_PATCH_DIR_REL) + "/",
        _normalize_rel_path(BOOTSTRAP_ROLLBACK_DIR_REL) + "/",
    )
    skip_exact = {_normalize_rel_path(BOOTSTRAP_STATE_REL)}

    # ── 2. Match files to scoped apps ─────────────────────────────────────────
    app_files:       Dict[str, List[str]] = {}
    payload_sources: Dict[str, Path]      = {}
    payload_bytes = 0

    for app in CITL_APPS:
        app_name = str(app.get("name") or "").strip()
        if not app_name:
            continue
        app_root = resolve_app_source_root(app, source)
        app_rels: List[str] = []

        key_files = app.get("key_files") or []
        key_norms = [_normalize_rel_path(str(kf or "")) for kf in key_files if _normalize_rel_path(str(kf or ""))]

        for rel in changed_files:
            if rel in skip_exact or any(rel.startswith(p) for p in skip_prefixes):
                continue
            # Is this file part of this app's key_files?
            is_app_file = any(
                rel == kn or rel.startswith(kn + "/")
                for kn in key_norms
            )
            if not is_app_file:
                continue
            # Resolve actual file path
            src_path = (app_root / rel) if (app_root / rel).is_file() else (source / rel)
            if not src_path.is_file():
                continue
            app_rels.append(rel)
            if rel not in payload_sources:
                payload_sources[rel] = src_path
                try:
                    payload_bytes += int(src_path.stat().st_size)
                except Exception:
                    pass

        if app_rels:
            app_files[app_name] = sorted(set(app_rels))
            _safe_log(log_fn, f"[GIT-PATCH]   {app_name}: {len(app_rels)} file(s)\n")

    # ── 3. Capture unmatched changed files under scope-specific "Other" bucket ─
    matched: set = set()
    for rels in app_files.values():
        matched.update(rels)
    unmatched: List[str] = []
    for rel in sorted(changed_files - matched):
        if rel in skip_exact or any(rel.startswith(p) for p in skip_prefixes):
            continue
        src = source / rel
        if src.is_file():
            unmatched.append(rel)
            if rel not in payload_sources:
                payload_sources[rel] = src
                try:
                    payload_bytes += int(src.stat().st_size)
                except Exception:
                    pass
    if unmatched:
        other_label = f"{_scope_label()} Other"
        app_files[other_label] = sorted(unmatched)
        _safe_log(log_fn, f"[GIT-PATCH]   {other_label} (unmatched changed files): {len(unmatched)}\n")

    if not payload_sources:
        return (
            False,
            "None of the changed files exist in the working tree — they may have been deleted. Nothing to package.",
            None,
        )

    # ── 4. Build ZIP ──────────────────────────────────────────────────────────
    created_utc = _utc_now_iso()
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1()
    for h in sorted(hashes):
        digest.update(h.encode("ascii", errors="ignore"))
    short_hash = digest.hexdigest()[:8]
    bootstrap_id = f"git-{stamp}-{short_hash}"

    out_dir = source / BOOTSTRAP_PATCH_DIR_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"citl_gitpatch_{stamp}_{short_hash}.zip"

    apps_manifest = [
        {"name": n, "file_count": len(f), "files": f}
        for n, f in sorted(app_files.items())
    ]
    manifest: Dict[str, object] = {
        "schema_version":    BOOTSTRAP_SCHEMA_VERSION,
        "bootstrap_id":      bootstrap_id,
        "created_utc":       created_utc,
        "created_epoch":     _parse_ts(created_utc),
        "generator_app":     APP_SYNC_NAME,
        "generator_version": APP_SYNC_VERSION,
        "patch_type":        "git",
        "git_commits":       list(hashes),
        "source_repo":       source.name,
        "source_repo_path":  str(source),
        "app_names":         sorted(app_files.keys()),
        "apps":              apps_manifest,
        "file_count":        len(payload_sources),
        "payload_bytes":     payload_bytes,
    }

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(payload_sources):
            zf.write(payload_sources[rel], arcname=f"payload/{rel}")
        zf.writestr(BOOTSTRAP_MANIFEST_NAME, json.dumps(manifest, indent=2))

    package = _package_from_manifest(out_path, source_hint="git-patch")
    if package is None:
        return False, f"Git patch created but manifest parse failed: {out_path}", None

    generate_bootstrap_patch_scripts(source, package, log_fn=log_fn)

    msg = (
        f"Git patch ready: {out_path.name}  "
        f"({len(hashes)} commit(s), {len(app_files)} app(s), "
        f"{len(payload_sources)} file(s), {_fmt_bytes(payload_bytes)})"
    )
    _safe_log(log_fn, f"[GIT-PATCH] {msg}\n")
    return True, msg, package


def port_to_ubuntu(repo: Path, log_fn: LogFn = None) -> Dict[str, str]:
    """
    Run all Ubuntu porting checks on `repo` and return a dict of
    {component: status_message}.  Writes files only when changes are needed.
    """
    results: Dict[str, str] = {}
    checks = [
        ("requirements-linux.txt", sync_requirements_linux),
        ("scripts/linux/setup.sh", sync_linux_setup_script),
        ("Ubuntu launchers", sync_ubuntu_launchers),
        ("Device-agnostic bootstraps", sync_device_agnostic_bootstraps),
    ]
    for label, fn in checks:
        try:
            changed, msg = fn(repo)
            status = f"{'UPDATED' if changed else 'OK'}: {msg}"
        except Exception as e:
            status = f"ERROR: {e}"
        results[label] = status
        _safe_log(log_fn, f"[UBUNTU-PORT] {label}: {status}\n")
    return results


def _build_excludes(include_data: bool, include_models: bool) -> List[str]:
    excludes = list(DEFAULT_EXCLUDES)
    if include_data:
        excludes = [p for p in excludes if not p.startswith("data/")]
    if include_models:
        excludes = [p for p in excludes if p not in ("models/", "ollama/")]
    return excludes


def _is_excluded(rel_posix: str, excludes: Sequence[str], is_dir: bool = False) -> bool:
    rel = rel_posix.strip("/")
    if not rel:
        return False
    for pattern in excludes:
        pat = pattern.strip()
        if not pat:
            continue
        if pat.endswith("/"):
            base = pat[:-1].strip("/")
            if rel == base or rel.startswith(base + "/"):
                return True
            continue
        if fnmatch.fnmatch(rel, pat):
            return True
        if is_dir and fnmatch.fnmatch(rel + "/", pat):
            return True
    return False


def _needs_copy(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    try:
        ss = src.stat()
        ds = dst.stat()
    except Exception:
        return True
    if ss.st_size != ds.st_size:
        return True
    # mtime granularity can differ across filesystems, use 2s tolerance.
    if abs(ss.st_mtime - ds.st_mtime) > 2.0:
        return True
    return False


def _guess_usb_root(target_repo: Path) -> Path:
    target = target_repo.expanduser().resolve()
    if os.name == "nt":
        drive = target.drive or target.anchor
        if drive:
            return Path(drive + "\\")
        return target

    user = os.environ.get("USER", "").strip()
    roots: List[Path] = []
    if user:
        roots.append(Path("/media") / user)
        roots.append(Path("/run/media") / user)
    roots.extend(
        [
            Path("/mnt"),
            Path("/Volumes"),
            Path("/media"),
            Path("/run/media"),
        ]
    )

    for base in roots:
        try:
            if target == base:
                return target
            if base in target.parents:
                rel = target.relative_to(base)
                if rel.parts:
                    return base / rel.parts[0]
        except Exception:
            continue
    return target


def _render_sync_launcher_sh() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""

pick() {
  local p="$1"
  if [ -f "$p/RUN_APP_SYNC.sh" ]; then
    TARGET="$p"
    return 0
  fi
  return 1
}

pick "$ROOT" || true
pick "$ROOT/CITL_FACTBOOK_UBUNTU" || true
pick "$ROOT/CITL" || true
pick "$ROOT/PORTABLE_APPS/CITL" || true

if [ -z "$TARGET" ]; then
  for d in "$ROOT"/*; do
    [ -d "$d" ] || continue
    if pick "$d"; then
      break
    fi
  done
fi

if [ -z "$TARGET" ]; then
  echo "Could not find RUN_APP_SYNC.sh under: $ROOT"
  exit 1
fi

exec bash "$TARGET/RUN_APP_SYNC.sh" "$@"
"""


def _render_duplicate_launcher_sh() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""

pick() {
  local p="$1"
  if [ -f "$p/RUN_APP_SYNC.sh" ]; then
    TARGET="$p"
    return 0
  fi
  return 1
}

pick "$ROOT" || true
pick "$ROOT/CITL_FACTBOOK_UBUNTU" || true
pick "$ROOT/CITL" || true
pick "$ROOT/PORTABLE_APPS/CITL" || true

if [ -z "$TARGET" ]; then
  for d in "$ROOT"/*; do
    [ -d "$d" ] || continue
    if pick "$d"; then
      break
    fi
  done
fi

if [ -z "$TARGET" ]; then
  echo "Could not find RUN_APP_SYNC.sh under: $ROOT"
  exit 1
fi

exec bash "$TARGET/RUN_APP_SYNC.sh" --source "$TARGET" --duplicate-usb --duplicate-from "$TARGET" "$@"
"""


def _render_sync_launcher_cmd() -> str:
    return r"""@echo off
setlocal enableextensions
set "ROOT=%~dp0"
set "TARGET="

if exist "%ROOT%Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%"
if not defined TARGET if exist "%ROOT%CITL_FACTBOOK_UBUNTU\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL_FACTBOOK_UBUNTU\"
if not defined TARGET if exist "%ROOT%CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL\"
if not defined TARGET if exist "%ROOT%PORTABLE_APPS\CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%PORTABLE_APPS\CITL\"

if not defined TARGET (
  for /d %%D in ("%ROOT%*") do (
    if exist "%%~fD\Run-CITL-App-Sync.ps1" (
      set "TARGET=%%~fD\"
      goto :found
    )
  )
)

:found
if not defined TARGET (
  echo Could not find Run-CITL-App-Sync.ps1 under %ROOT%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%Run-CITL-App-Sync.ps1" %*
exit /b %ERRORLEVEL%
"""


def _render_duplicate_launcher_cmd() -> str:
    return r"""@echo off
setlocal enableextensions
set "ROOT=%~dp0"
set "TARGET="

if exist "%ROOT%Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%"
if not defined TARGET if exist "%ROOT%CITL_FACTBOOK_UBUNTU\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL_FACTBOOK_UBUNTU\"
if not defined TARGET if exist "%ROOT%CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL\"
if not defined TARGET if exist "%ROOT%PORTABLE_APPS\CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%PORTABLE_APPS\CITL\"

if not defined TARGET (
  for /d %%D in ("%ROOT%*") do (
    if exist "%%~fD\Run-CITL-App-Sync.ps1" (
      set "TARGET=%%~fD\"
      goto :found
    )
  )
)

:found
if not defined TARGET (
  echo Could not find Run-CITL-App-Sync.ps1 under %ROOT%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%Run-CITL-App-Sync.ps1" --source "%TARGET%" --duplicate-usb --duplicate-from "%TARGET%" %*
exit /b %ERRORLEVEL%
"""


def _render_sync_launcher_readme() -> str:
    return (
        "CITL Sync Utility Launchers\n"
        "===========================\n\n"
        "Ubuntu launcher: RUN_APP_SYNC_UBUNTU.sh\n"
        "Windows launcher: RUN_APP_SYNC_WINDOWS.cmd\n\n"
        "Self-duplicate launchers (USB -> next USB):\n"
        "  Ubuntu: COPY_THIS_USB_TO_NEXT_UBUNTU.sh\n"
        "  Windows: COPY_THIS_USB_TO_NEXT_WINDOWS.cmd\n\n"
        "These launchers search this USB drive for the CITL repo and then open the\n"
        "cross-platform sync utility.\n\n"
        "Default sync behavior is time-considerate: full repo delta copy while excluding\n"
        "large model/data/media folders unless explicitly requested.\n\n"
        "Headless options:\n"
        "  --sync-best-usb                 Auto-pick best USB target and sync PC -> USB\n"
        "  --duplicate-usb                 Duplicate one USB copy to another\n"
        "  --duplicate-from <path>         Source USB path for duplicate mode\n"
        "  --duplicate-to <path>           Destination USB path for duplicate mode\n"
        "  --include-models                Include repo models/ollama folders\n"
        "  --ollama-model-source <path>    Optional external Ollama model source directory\n"
        "  --ollama-model-target <path>    Optional external Ollama model target directory\n"
    )


def _write_launcher(path: Path, text: str, make_executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if make_executable and os.name != "nt":
        try:
            mode = path.stat().st_mode
            path.chmod(mode | 0o111)
        except Exception:
            # FAT/EXFAT mounts may not support chmod semantics.
            pass


def install_sync_launchers(target_repo: PathLike, log_fn: LogFn = None) -> List[Path]:
    target = Path(target_repo).expanduser().resolve()
    usb_root = _guess_usb_root(target)
    locations: List[Path] = [target]

    if os.name == "nt":
        drive = target.drive or target.anchor
        dtype = 0
        if drive:
            if not str(drive).endswith("\\"):
                drive = str(drive) + "\\"
            try:
                import ctypes

                dtype = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(str(drive)))
            except Exception:
                dtype = 0
        if dtype == 2 and usb_root != target:
            locations.insert(0, usb_root)
    else:
        if _is_external_mount_path(target):
            locations = [usb_root]
            if usb_root != target:
                locations.append(target)
        else:
            locations = [target]

    written: List[Path] = []
    for loc in locations:
        sh_path = loc / SYNC_LAUNCHER_UBUNTU
        cmd_path = loc / SYNC_LAUNCHER_WINDOWS
        dup_sh_path = loc / SYNC_DUPLICATE_UBUNTU
        dup_cmd_path = loc / SYNC_DUPLICATE_WINDOWS
        readme_path = loc / SYNC_LAUNCHER_README

        _write_launcher(sh_path, _render_sync_launcher_sh(), make_executable=True)
        _write_launcher(cmd_path, _render_sync_launcher_cmd(), make_executable=False)
        _write_launcher(dup_sh_path, _render_duplicate_launcher_sh(), make_executable=True)
        _write_launcher(dup_cmd_path, _render_duplicate_launcher_cmd(), make_executable=False)
        _write_launcher(readme_path, _render_sync_launcher_readme(), make_executable=False)

        written.extend([sh_path, cmd_path, dup_sh_path, dup_cmd_path, readme_path])
        _safe_log(log_fn, f"[LAUNCHER] wrote {sh_path}\n")
        _safe_log(log_fn, f"[LAUNCHER] wrote {cmd_path}\n")
        _safe_log(log_fn, f"[LAUNCHER] wrote {dup_sh_path}\n")
        _safe_log(log_fn, f"[LAUNCHER] wrote {dup_cmd_path}\n")
        _safe_log(log_fn, f"[LAUNCHER] wrote {readme_path}\n")

    return written


def audit_docs_bundle(source_repo: PathLike, target_repo: PathLike, log_fn: LogFn = None) -> Dict[str, int]:
    src = Path(source_repo).expanduser().resolve()
    dst = Path(target_repo).expanduser().resolve()
    src_docs = src / "docs"
    dst_docs = dst / "docs"

    if not src_docs.is_dir():
        _safe_log(log_fn, "[DOCS] source docs/ missing; audit skipped.\n")
        return {"audited": 0, "missing": 0, "mismatched": 0}

    src_files: List[Path] = []
    for p in src_docs.rglob("*"):
        if p.is_file():
            src_files.append(p)
    src_files.sort(key=lambda p: str(p.relative_to(src_docs)).lower())

    missing: List[str] = []
    mismatched: List[str] = []
    for sf in src_files:
        rel = sf.relative_to(src_docs)
        tf = dst_docs / rel
        rels = rel.as_posix()
        if not tf.exists():
            missing.append(rels)
            continue
        try:
            if sf.stat().st_size != tf.stat().st_size:
                mismatched.append(rels)
        except Exception:
            mismatched.append(rels)

    audited = len(src_files)
    _safe_log(
        log_fn,
        f"[DOCS] audited={audited} missing={len(missing)} mismatched={len(mismatched)}\n",
    )
    if missing:
        for item in missing[:12]:
            _safe_log(log_fn, f"[DOCS][MISSING] {item}\n")
        if len(missing) > 12:
            _safe_log(log_fn, f"[DOCS][MISSING] ... and {len(missing) - 12} more\n")
    if mismatched:
        for item in mismatched[:12]:
            _safe_log(log_fn, f"[DOCS][MISMATCH] {item}\n")
        if len(mismatched) > 12:
            _safe_log(log_fn, f"[DOCS][MISMATCH] ... and {len(mismatched) - 12} more\n")
    return {"audited": audited, "missing": len(missing), "mismatched": len(mismatched)}


def _sync_with_copy(
    source_repo: Path,
    target_repo: Path,
    excludes: Sequence[str],
    log_fn: LogFn,
) -> SyncResult:
    result = SyncResult()
    start = time.time()
    source_repo = source_repo.resolve()
    target_repo.mkdir(parents=True, exist_ok=True)

    scanned = 0
    for root, dirs, files in os.walk(source_repo):
        root_path = Path(root)
        rel_root = root_path.relative_to(source_repo)
        rel_root_posix = "" if str(rel_root) == "." else rel_root.as_posix()

        kept_dirs: List[str] = []
        for d in dirs:
            rel_dir = "/".join(x for x in (rel_root_posix, d) if x)
            if _is_excluded(rel_dir, excludes, is_dir=True):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for f in files:
            scanned += 1
            rel_file = "/".join(x for x in (rel_root_posix, f) if x)
            if _is_excluded(rel_file, excludes, is_dir=False):
                result.skipped += 1
                continue

            src_file = root_path / f
            dst_file = target_repo / rel_file
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                if _needs_copy(src_file, dst_file):
                    shutil.copy2(src_file, dst_file)
                    result.copied += 1
                else:
                    result.skipped += 1
            except Exception as e:
                result.errors += 1
                _safe_log(log_fn, f"[ERROR] {rel_file}: {e}\n")

            if scanned % 300 == 0:
                _safe_log(
                    log_fn,
                    f"[PROGRESS] scanned={scanned} copied={result.copied} skipped={result.skipped} errors={result.errors}\n",
                )

    result.elapsed_sec = time.time() - start
    return result


def _sync_with_rsync(
    source_repo: Path,
    target_repo: Path,
    excludes: Sequence[str],
    log_fn: LogFn,
) -> SyncResult:
    start = time.time()
    cmd: List[str] = ["rsync", "-a", "--human-readable"]
    for pat in excludes:
        cmd.extend(["--exclude", pat])
    cmd.extend([str(source_repo) + "/", str(target_repo) + "/"])

    _safe_log(log_fn, f"[CMD] {' '.join(cmd)}\n")
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    if p.stdout is None:
        raise RuntimeError("rsync subprocess stdout pipe was not created; "
                           "check that stdout=subprocess.PIPE was set.")
    for line in p.stdout:
        if line:
            _safe_log(log_fn, line)
    rc = p.wait()
    if rc != 0:
        raise RuntimeError(f"rsync failed with exit code {rc}")
    return SyncResult(used_rsync=True, elapsed_sec=time.time() - start)


def sync_repo(
    source_repo: PathLike,
    target_repo: PathLike,
    include_data: bool = False,
    include_models: bool = False,
    model_source_dir: Optional[PathLike] = None,
    model_target_dir: Optional[PathLike] = None,
    log_fn: LogFn = None,
) -> SyncResult:
    src = Path(source_repo).expanduser().resolve()
    dst = Path(target_repo).expanduser().resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"Source repo not found: {src}")
    dst.mkdir(parents=True, exist_ok=True)

    excludes = _build_excludes(include_data=include_data, include_models=include_models)
    _safe_log(log_fn, f"[SYNC] source={src}\n")
    _safe_log(log_fn, f"[SYNC] target={dst}\n")
    _safe_log(log_fn, f"[SYNC] exclude_count={len(excludes)}\n")

    result: SyncResult
    if os.name != "nt" and shutil.which("rsync"):
        try:
            result = _sync_with_rsync(src, dst, excludes, log_fn)
        except Exception as e:
            _safe_log(log_fn, f"[WARN] rsync fallback to Python copy: {e}\n")
            result = _sync_with_copy(src, dst, excludes, log_fn)
    else:
        result = _sync_with_copy(src, dst, excludes, log_fn)

    try:
        install_sync_launchers(dst, log_fn=log_fn)
    except Exception as e:
        _safe_log(log_fn, f"[WARN] launcher install failed: {e}\n")
    try:
        audit_docs_bundle(src, dst, log_fn=log_fn)
    except Exception as e:
        _safe_log(log_fn, f"[WARN] docs audit failed: {e}\n")

    # Always port Ubuntu components in BOTH source and destination repos
    # so the USB copy is immediately ready for Ubuntu installation.
    for label, target_repo in (("source", src), ("target", dst)):
        try:
            port_to_ubuntu(target_repo, log_fn=log_fn)
        except Exception as e:
            _safe_log(log_fn, f"[WARN] Ubuntu port ({label}) failed: {e}\n")

    if include_models and model_source_dir and model_target_dir:
        try:
            sync_external_model_store(
                model_source_dir,
                model_target_dir,
                log_fn=log_fn,
            )
        except Exception as e:
            _safe_log(log_fn, f"[WARN] external model sync failed: {e}\n")

    return result


def open_in_file_manager(path: PathLike) -> None:
    p = Path(path).expanduser()
    if os.name == "nt":
        os.startfile(str(p))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
        return
    subprocess.Popen(["xdg-open", str(p)])


class SyncGUI:
    def __init__(self, source_repo: PathLike, source_reason: str = "", source_freshness_ts: float = 0.0):
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext

        self.tk = tk
        self.messagebox = messagebox
        self.scrolledtext = scrolledtext
        self.filedialog = filedialog

        self.colors = {
            "bg": "#07101c",
            "panel": "#101c31",
            "panel_alt": "#162744",
            "card": "#12203a",
            "card_selected": "#264779",
            "border": "#33527f",
            "text": "#f3f8ff",
            "muted": "#9eb4d5",
            "accent": "#60dbff",
            "accent_active": "#8ce7ff",
            "button": "#29466f",
            "button_active": "#3b6297",
            "good": "#84f6a0",
            "warn": "#ffd369",
            "danger": "#ff8b8b",
        }

        self.source_repo = Path(source_repo).expanduser().resolve()
        self.source_reason = (source_reason or "").strip()
        self.source_freshness_ts = float(source_freshness_ts or 0.0)
        self.targets: List[SyncTarget] = []
        self.target_status: Dict[str, TargetStatus] = {}
        self.devices: List[PhoneDevice] = []
        self._busy = False
        self._tile_columns = 0

        self.root = tk.Tk()
        self.root.title(f"{APP_SYNC_NAME} {APP_SYNC_VERSION}")
        self.root.geometry("1440x940")
        self.root.minsize(1080, 760)
        self.root.configure(bg=self.colors["bg"])
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Scrollable outer layout so the full dashboard is reachable on smaller screens.
        self.main_canvas = tk.Canvas(self.root, bg=self.colors["bg"], highlightthickness=0, bd=0)
        self.main_scroll = tk.Scrollbar(self.root, orient="vertical", command=self.main_canvas.yview)
        self.main_canvas.configure(yscrollcommand=self.main_scroll.set)
        self.main_canvas.grid(row=0, column=0, sticky="nsew")
        self.main_scroll.grid(row=0, column=1, sticky="ns")

        self.main_frame = tk.Frame(self.main_canvas, bg=self.colors["bg"])
        self.main_window = self.main_canvas.create_window((0, 0), window=self.main_frame, anchor="nw")
        self.main_frame.bind("<Configure>", self._sync_main_scrollregion)
        self.main_canvas.bind("<Configure>", self._on_main_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_main_mousewheel)
        self.root.bind_all("<Button-4>", self._on_main_mousewheel)
        self.root.bind_all("<Button-5>", self._on_main_mousewheel)

        self.status_var = tk.StringVar(value="Ready.")
        self.target_var = tk.StringVar(value="")
        self.device_var = tk.StringVar(value="")
        self.include_data_var = tk.BooleanVar(value=False)
        self.include_models_var = tk.BooleanVar(value=False)
        self.header_var = tk.StringVar(value=f"{APP_SYNC_NAME} {APP_SYNC_VERSION}")
        self.source_path_var = tk.StringVar(value=str(self.source_repo))
        self.source_meta_var = tk.StringVar(value="")
        self.targets_meta_var = tk.StringVar(value="Targets detected: scanning...")
        self.phone_var = tk.StringVar(value="Phone: scanning for ADB devices...")
        self.guide_var = tk.StringVar(value="Guide: scanning devices and repo copies...")
        self.health_var = tk.StringVar(value="Health: not checked yet.")
        self.detail_title_var = tk.StringVar(value="No target selected")
        self.detail_status_var = tk.StringVar(value="Insert or refresh a USB/external repo to begin.")
        self.detail_reason_var = tk.StringVar(value="No sync recommendation yet.")
        self.detail_path_var = tk.StringVar(value="Select a repo tile on the left.")
        self.detail_root_var = tk.StringVar(value="-")
        self.detail_freshness_var = tk.StringVar(value="-")
        self.detail_compare_var = tk.StringVar(value="-")
        self.detail_write_var = tk.StringVar(value="-")
        self.detail_memory_var = tk.StringVar(value="-")
        self.detail_device_var = tk.StringVar(value="No phone selected")
        self.bootstrap_info_var = tk.StringVar(value="Bootstrap packages: scanning...")
        self.bootstrap_selection_var = tk.StringVar(value="No bootstrap package selected.")
        self.bootstrap_preview_var = tk.StringVar(value="Install preview: select a package and destination.")
        self.bootstrap_packages: List[BootstrapPackage] = []
        self.bootstrap_listbox = None
        self.bootstrap_app_vars: Dict[str, object] = {}
        self.bootstrap_history_box = None
        self.sync_app_vars: Dict[str, object] = {}
        self.sync_app_selection_var = tk.StringVar(value="App inclusion: all apps selected.")
        self.sync_app_health_var = tk.StringVar(value="App status: pending target analysis.")
        self.launch_apps_cache: List[dict] = []
        self.launch_app_listbox = None
        self.launch_selected_var = tk.StringVar(value="Launch app: select an app from the list.")
        self.launch_update_var = tk.StringVar(value="Update status: scanning app readiness...")
        self.diagnostics_window = None
        self.diagnostics_text = None

        # Git-patch detector state
        self.git_commits: List[dict] = []
        self.git_patch_listbox = None
        self.git_patch_status_var = tk.StringVar(value="Git patches: click 'Detect Recent Commits'")

        self._git_statuses: Dict[str, Dict] = {}   # populated by _refresh_git_statuses
        self._git_accounts: List[Dict[str, str]] = []
        self._build_ui()
        self._apply_scope_ui_rules()
        self.refresh_targets()
        # Fetch git statuses in background at startup
        self.root.after(1500, self._refresh_git_statuses)

    def _panel(self, parent, bg: str):
        return self.tk.Frame(
            parent,
            bg=bg,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            bd=0,
        )

    def _make_label(
        self,
        parent,
        *,
        text: str = "",
        textvariable=None,
        bg: Optional[str] = None,
        fg: Optional[str] = None,
        font: Optional[Tuple[str, int, str]] = None,
        wraplength: int = 0,
        anchor: str = "w",
        justify: str = "left",
        padx: int = 0,
        pady: int = 0,
    ):
        return self.tk.Label(
            parent,
            text=text,
            textvariable=textvariable,
            bg=bg or self.colors["panel"],
            fg=fg or self.colors["text"],
            font=font or ("Segoe UI", 11, "normal"),
            wraplength=wraplength,
            anchor=anchor,
            justify=justify,
            padx=padx,
            pady=pady,
        )

    def _make_button(self, parent, text: str, command, *, accent: bool = False, state: str = "normal"):
        bg = self.colors["accent"] if accent else self.colors["button"]
        fg = self.colors["bg"] if accent else self.colors["text"]
        active_bg = self.colors["accent_active"] if accent else self.colors["button_active"]
        btn = self.tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            disabledforeground=self.colors["muted"],
            relief="flat",
            bd=0,
            padx=16,
            pady=14,
            cursor="hand2",
            font=("Segoe UI Semibold", 12),
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            wraplength=220,
            justify="center",
        )
        btn.configure(state=state)
        return btn

    def _sync_main_scrollregion(self, _event=None) -> None:
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _on_main_canvas_configure(self, event) -> None:
        self.main_canvas.itemconfigure(self.main_window, width=event.width)

    def _is_descendant_widget(self, widget, ancestor) -> bool:
        cur = widget
        while cur is not None:
            if cur == ancestor:
                return True
            cur = getattr(cur, "master", None)
        return False

    def _on_main_mousewheel(self, event) -> None:
        # Allow text and entry controls to keep their own native scroll behavior.
        try:
            klass = str(event.widget.winfo_class()).lower()
        except Exception:
            klass = ""
        if klass in ("text", "entry", "spinbox", "listbox"):
            return

        delta_units = 0
        if getattr(event, "num", None) == 4:
            delta_units = -1
        elif getattr(event, "num", None) == 5:
            delta_units = 1
        else:
            delta = int(getattr(event, "delta", 0) or 0)
            if delta != 0:
                delta_units = -1 if delta > 0 else 1

        if delta_units:
            target_canvas = self.main_canvas
            if (
                getattr(self, "tiles_canvas", None) is not None
                and (
                    event.widget == self.tiles_canvas
                    or (
                        getattr(self, "tiles_inner", None) is not None
                        and self._is_descendant_widget(event.widget, self.tiles_inner)
                    )
                )
            ):
                target_canvas = self.tiles_canvas
            target_canvas.yview_scroll(delta_units, "units")

    def _device_label(self, device: PhoneDevice) -> str:
        meta = (device.meta or "").strip()
        return f"{device.serial}  {meta}".strip()

    def _update_source_meta(self) -> None:
        reason = self.source_reason or "manual/default source"
        fresh = _fmt_ts(self.source_freshness_ts)
        self.source_meta_var.set(f"Selection: {reason}\nFreshness: {fresh}")

    def _apply_scope_ui_rules(self) -> None:
        """Hide/disable CITL-specific controls when running in HENOSIS-only mode."""
        if ACTIVE_SYNC_SCOPE != SYNC_SCOPE_HENOSIS:
            return
        try:
            self.guide_var.set(
                "Guide: HENOSIS scope active. Only HENOSIS-tagged repos/apps are shown and patched."
            )
            self.sync_app_selection_var.set("App inclusion: HENOSIS-tagged apps only.")
            self.launch_update_var.set("HENOSIS scope: scope-specific launch shortcuts are hidden.")
            if getattr(self, "launcher_grid", None) is not None:
                self.launcher_grid.grid_remove()
        except Exception:
            pass

    def _target_write_check(self, target: Path) -> Tuple[bool, str]:
        probe = target / ".citl_sync_write_test.tmp"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True, "writable"
        except Exception as e:
            return False, str(e)

    def _recommendation_label(self, comparison: RepoComparison) -> str:
        mapping = {
            "push_source_to_target": "PUSH PC -> USB",
            "pull_target_to_source": "PULL USB -> PC",
            "current": "ALREADY ALIGNED",
            "review": "REVIEW BEFORE SYNC",
        }
        return mapping.get(comparison.recommendation, "REVIEW BEFORE SYNC")

    def _recommendation_color(self, comparison: RepoComparison) -> str:
        if comparison.recommendation == "push_source_to_target":
            return self.colors["good"]
        if comparison.recommendation == "current":
            return self.colors["accent"]
        if comparison.recommendation == "pull_target_to_source":
            return self.colors["warn"]
        return self.colors["danger"]

    def _recommendation_priority(self, comparison: RepoComparison) -> Tuple[int, int, int]:
        order = {
            "push_source_to_target": 0,
            "current": 1,
            "review": 2,
            "pull_target_to_source": 3,
        }
        return (
            order.get(comparison.recommendation, 9),
            -comparison.source_newer + comparison.target_newer,
            -comparison.source_only + comparison.target_only,
        )

    def _app_priority_bucket(self, app: dict) -> int:
        name = str(app.get("name") or "").strip().upper()
        if PINNED_APP_NOETIKON in name:
            return 0
        if PINNED_APP_CANIS in name or (("CANIS COSMOS" in name) and ("ASTROLOGY" in name)):
            return 1
        return 2

    def _app_last_update_ts(self, app: dict) -> float:
        src_root = self._app_source_root(app)
        latest = 0.0
        for rel in (app.get("key_files") or []):
            p = src_root / rel
            if not p.exists():
                continue
            try:
                ts = float(p.stat().st_mtime)
            except Exception:
                continue
            if ts > latest:
                latest = ts
        if latest <= 0 and src_root.exists():
            try:
                latest = float(src_root.stat().st_mtime)
            except Exception:
                latest = 0.0
        return latest

    def _ordered_apps_for_overview(self) -> List[dict]:
        ranked: List[Tuple[int, float, str, dict]] = []
        for app in CITL_APPS:
            ranked.append(
                (
                    self._app_priority_bucket(app),
                    self._app_last_update_ts(app),
                    str(app.get("name") or "").lower(),
                    app,
                )
            )
        ranked.sort(key=lambda x: (x[0], -x[1], x[2]))
        return [item[3] for item in ranked]

    def _app_rank_badge(self, app: dict, order_idx: int) -> Tuple[str, str]:
        bucket = self._app_priority_bucket(app)
        if bucket == 0:
            return "[PIN-1] NOETIKON", self.colors["accent"]
        if bucket == 1:
            return "[PIN-2] CANIS", self.colors["warn"]
        if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS:
            return f"[HEN-{order_idx:02d}]", self.colors["muted"]
        return f"[{order_idx:02d}] RECENT", self.colors["muted"]

    def _build_ui(self) -> None:
        self._update_source_meta()
        page = self.main_frame
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=3)
        page.grid_rowconfigure(7, weight=1)

        header = self.tk.Frame(page, bg=self.colors["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 10))
        header.grid_columnconfigure(0, weight=1)
        self._make_label(
            header,
            textvariable=self.header_var,
            bg=self.colors["bg"],
            font=("Segoe UI Semibold", 24, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self._make_label(
            header,
            text=f"Accessible USB and phone sync dashboard for {_scope_label()} repo copies",
            bg=self.colors["bg"],
            fg=self.colors["muted"],
            font=("Segoe UI", 13, "normal"),
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))


        top = self.tk.Frame(page, bg=self.colors["bg"])
        top.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 12))
        top.grid_columnconfigure(0, weight=3)
        top.grid_columnconfigure(1, weight=4)

        source_card = self._panel(top, self.colors["panel"])
        source_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        source_card.grid_columnconfigure(0, weight=1)
        self._make_label(
            source_card,
            text="Local Source Repo",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))
        self._make_label(
            source_card,
            textvariable=self.source_path_var,
            bg=self.colors["panel"],
            font=("Consolas", 11, "normal"),
            wraplength=560,
        ).grid(row=1, column=0, sticky="w", padx=16)
        self._make_label(
            source_card,
            textvariable=self.source_meta_var,
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            wraplength=560,
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(10, 12))

        options = self.tk.Frame(source_card, bg=self.colors["panel"])
        options.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 16))
        data_cb = self.tk.Checkbutton(
            options,
            text="Include data and indexes",
            variable=self.include_data_var,
            command=self.refresh_targets,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            selectcolor=self.colors["button"],
            activebackground=self.colors["panel"],
            activeforeground=self.colors["text"],
            highlightthickness=0,
            font=("Segoe UI", 11),
        )
        data_cb.grid(row=0, column=0, sticky="w")
        model_cb = self.tk.Checkbutton(
            options,
            text="Include models and ollama",
            variable=self.include_models_var,
            command=self.refresh_targets,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            selectcolor=self.colors["button"],
            activebackground=self.colors["panel"],
            activeforeground=self.colors["text"],
            highlightthickness=0,
            font=("Segoe UI", 11),
        )
        model_cb.grid(row=1, column=0, sticky="w", pady=(8, 0))

        actions_card = self._panel(top, self.colors["panel_alt"])
        actions_card.grid(row=0, column=1, sticky="nsew")
        actions_card.grid_columnconfigure(0, weight=1)
        self._make_label(
            actions_card,
            text="Guided Sync Actions",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))
        self._make_label(
            actions_card,
            textvariable=self.targets_meta_var,
            bg=self.colors["panel_alt"],
            wraplength=720,
            font=("Segoe UI Semibold", 12, "bold"),
        ).grid(row=1, column=0, sticky="w", padx=16)
        self._make_label(
            actions_card,
            textvariable=self.phone_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            wraplength=720,
            font=("Segoe UI", 11, "normal"),
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(6, 0))
        self.guide_label = self._make_label(
            actions_card,
            textvariable=self.guide_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["good"],
            wraplength=720,
            font=("Segoe UI Semibold", 12, "bold"),
        )
        self.guide_label.grid(row=3, column=0, sticky="w", padx=16, pady=(8, 0))
        self._make_label(
            actions_card,
            textvariable=self.health_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            wraplength=720,
            font=("Segoe UI", 11, "normal"),
        ).grid(row=4, column=0, sticky="w", padx=16, pady=(8, 0))

        device_card = self.tk.Frame(actions_card, bg=self.colors["panel_alt"])
        device_card.grid(row=5, column=0, sticky="ew", padx=16, pady=(14, 8))
        device_card.grid_columnconfigure(0, weight=1)
        self._make_label(
            device_card,
            text="Connected Phones",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.device_button_frame = self.tk.Frame(device_card, bg=self.colors["panel_alt"])
        self.device_button_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        action_grid = self.tk.Frame(actions_card, bg=self.colors["panel_alt"])
        action_grid.grid(row=6, column=0, sticky="ew", padx=16, pady=(10, 16))
        for col in range(3):
            action_grid.grid_columnconfigure(col, weight=1)
        self.refresh_btn = self._make_button(action_grid, "1. Refresh USB + Phone", self.refresh_targets)
        self.refresh_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 10))
        self.pick_btn = self._make_button(action_grid, "2. Auto Pick Best Match", self.on_auto_pick_best)
        self.pick_btn.grid(row=0, column=1, sticky="ew", padx=8, pady=(0, 10))
        self.open_source_btn = self._make_button(action_grid, "Open Local Source", self.on_open_source)
        self.open_source_btn.grid(row=0, column=2, sticky="ew", padx=(8, 0), pady=(0, 10))
        self.push_btn = self._make_button(action_grid, "3. Push PC -> USB", self.on_push_to_target, accent=True, state="disabled")
        self.push_btn.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 10))
        self.pull_btn = self._make_button(action_grid, "4. Pull USB -> PC", self.on_pull_from_target, state="disabled")
        self.pull_btn.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 10))
        self.phone_btn = self._make_button(action_grid, "5. Send Selected USB -> Phone", self.on_send_target_to_phone, state="disabled")
        self.phone_btn.grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=(0, 10))
        self.open_target_btn = self._make_button(action_grid, "Open Selected Target", self.on_open_target, state="disabled")
        self.open_target_btn.grid(row=2, column=0, sticky="ew", padx=(0, 8))
        self.remember_btn = self._make_button(action_grid, "Remember Selected Folder", self.on_remember_target, state="disabled")
        self.remember_btn.grid(row=2, column=1, sticky="ew", padx=8)
        self.close_btn = self._make_button(action_grid, "Close", self.root.destroy)
        self.close_btn.grid(row=2, column=2, sticky="ew", padx=(8, 0))
        self.duplicate_btn = self._make_button(
            action_grid,
            "6. Duplicate Selected USB -> Backup USB",
            self.on_duplicate_usb,
            state="disabled",
        )
        self.duplicate_btn.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.push_apps_only_btn = self._make_button(
            action_grid,
            "7. Push Selected Apps Only -> USB",
            self.on_push_selected_apps_only,
            state="disabled",
        )
        self.push_apps_only_btn.grid(row=4, column=0, sticky="ew", padx=(0, 8), pady=(10, 0))
        self.pull_apps_only_btn = self._make_button(
            action_grid,
            "8. Pull Selected Apps Only <- USB",
            self.on_pull_selected_apps_only,
            state="disabled",
        )
        self.pull_apps_only_btn.grid(row=4, column=1, sticky="ew", padx=8, pady=(10, 0))
        self.diagnostics_btn = self._make_button(
            action_grid,
            "Diagnostics Window",
            self.on_open_diagnostics_window,
        )
        self.diagnostics_btn.grid(row=4, column=2, sticky="ew", padx=(8, 0), pady=(10, 0))

        # ── Clone & Sync Panel ────────────────────────────────────────────────
        clone_sync_panel = self.tk.Frame(actions_card, bg=self.colors["panel_alt"])
        clone_sync_panel.grid(row=6, column=0, sticky="ew", padx=16, pady=(10, 10))
        clone_sync_panel.grid_columnconfigure(0, weight=1)
        clone_sync_panel.grid_columnconfigure(1, weight=1)
        clone_sync_panel.grid_columnconfigure(2, weight=1)
        
        self._make_label(
            clone_sync_panel,
            text="Clone & Sync",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 11, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        
        self.clone_usb_btn = self._make_button(
            clone_sync_panel,
            "🔗 Clone USB (GUI)",
            self.on_clone_usb,
            accent=False
        )
        self.clone_usb_btn.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        
        self.git_sync_btn = self._make_button(
            clone_sync_panel,
            "📥 Sync from Git",
            self.on_sync_from_git
        )
        self.git_sync_btn.grid(row=1, column=1, sticky="ew", padx=6)
        
        self.git_push_btn = self._make_button(
            clone_sync_panel,
            "📤 Push to Git",
            self.on_push_to_git
        )
        self.git_push_btn.grid(row=1, column=2, sticky="ew", padx=(6, 0))

        # ── Application Launcher Buttons ──────────────────────────────────────
        launcher_grid = self.tk.Frame(actions_card, bg=self.colors["panel_alt"])
        launcher_grid.grid(row=7, column=0, sticky="ew", padx=16, pady=(10, 16))
        self.launcher_grid = launcher_grid
        launcher_grid.grid_columnconfigure(0, weight=1)
        self._make_label(
            launcher_grid,
            text=f"Launch {_scope_label()} Applications",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 12, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        launcher_btns = self.tk.Frame(launcher_grid, bg=self.colors["panel_alt"])
        launcher_btns.grid(row=1, column=0, sticky="ew")
        launcher_btns.grid_columnconfigure(0, weight=1)
        launcher_btns.grid_columnconfigure(1, weight=1)
        launcher_btns.grid_columnconfigure(2, weight=1)

        self.doc_composer_btn = self._make_button(
            launcher_btns,
            "📝 Document Composer",
            self.on_launch_doc_composer,
            accent=True
        )
        self.doc_composer_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 6))

        self.presentation_btn = self._make_button(
            launcher_btns,
            "📊 Presentation Suite",
            self.on_launch_presentation_suite
        )
        self.presentation_btn.grid(row=0, column=1, sticky="ew", padx=6, pady=(0, 6))

        self.workstation_btn = self._make_button(
            launcher_btns,
            "🔧 Workstation Apps",
            self.on_launch_workstation_apps
        )
        self.workstation_btn.grid(row=0, column=2, sticky="ew", padx=(6, 0), pady=(0, 6))

        self.field_apps_btn = self._make_button(
            launcher_btns,
            "📱 Field Apps",
            self.on_launch_field_apps
        )
        self.field_apps_btn.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        # ── Find & Repair Factbook ────────────────────────────────────────────
        repair_panel = self.tk.Frame(actions_card, bg=self.colors["panel_alt"])
        repair_panel.grid(row=8, column=0, sticky="ew", padx=16, pady=(4, 16))
        self.repair_panel = repair_panel
        repair_panel.grid_columnconfigure(0, weight=1)
        repair_panel.grid_columnconfigure(1, weight=1)
        repair_panel.grid_columnconfigure(2, weight=1)
        self._make_label(
            repair_panel,
            text="Sync Repair Utilities",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 11, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.factbook_repair_btn = self._make_button(
            repair_panel,
            "🔍 Find & Repair Factbook",
            self.on_find_and_repair_factbook,
            accent=True,
        )
        self.factbook_repair_btn.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.factbook_diag_btn = self._make_button(
            repair_panel,
            "🩺 18-Stage Diagnostic",
            self.on_open_factbook_diagnostic,
        )
        self.factbook_diag_btn.grid(row=1, column=1, sticky="ew", padx=6)
        self.exfat_repair_btn = self._make_button(
            repair_panel,
            "💽 exFAT USB Repair",
            self.on_open_exfat_repair_utility,
        )
        self.exfat_repair_btn.grid(row=1, column=2, sticky="ew", padx=(6, 0))

        body = self.tk.Frame(page, bg=self.colors["bg"])
        body.grid(row=3, column=0, sticky="nsew", padx=22, pady=(0, 12))
        body.grid_columnconfigure(0, weight=4)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(0, weight=1)

        tiles_panel = self._panel(body, self.colors["panel"])
        tiles_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        tiles_panel.grid_columnconfigure(0, weight=1)
        tiles_panel.grid_rowconfigure(1, weight=1)
        self._make_label(
            tiles_panel,
            text=f"Detected {_scope_label()} Repo Copies",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        tile_wrap = self.tk.Frame(tiles_panel, bg=self.colors["panel"])
        tile_wrap.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tile_wrap.grid_columnconfigure(0, weight=1)
        tile_wrap.grid_rowconfigure(0, weight=1)

        self.tiles_canvas = self.tk.Canvas(tile_wrap, bg=self.colors["panel"], highlightthickness=0, bd=0)
        tile_scroll = self.tk.Scrollbar(tile_wrap, orient="vertical", command=self.tiles_canvas.yview)
        self.tiles_canvas.configure(yscrollcommand=tile_scroll.set)
        self.tiles_canvas.grid(row=0, column=0, sticky="nsew")
        tile_scroll.grid(row=0, column=1, sticky="ns")

        self.tiles_inner = self.tk.Frame(self.tiles_canvas, bg=self.colors["panel"])
        self.tiles_window = self.tiles_canvas.create_window((0, 0), window=self.tiles_inner, anchor="nw")
        self.tiles_inner.bind(
            "<Configure>",
            lambda _event: self.tiles_canvas.configure(scrollregion=self.tiles_canvas.bbox("all")),
        )
        self.tiles_canvas.bind("<Configure>", self._on_tiles_canvas_configure)

        detail_panel = self._panel(body, self.colors["panel_alt"])
        detail_panel.grid(row=0, column=1, sticky="nsew")
        detail_panel.grid_columnconfigure(0, weight=1)
        self._make_label(
            detail_panel,
            text="Selected Copy Details",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))
        self._make_label(
            detail_panel,
            textvariable=self.detail_title_var,
            bg=self.colors["panel_alt"],
            font=("Segoe UI Semibold", 18, "bold"),
            wraplength=520,
        ).grid(row=1, column=0, sticky="w", padx=16)
        self.detail_status_label = self._make_label(
            detail_panel,
            textvariable=self.detail_status_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 16, "bold"),
            wraplength=520,
        )
        self.detail_status_label.grid(row=2, column=0, sticky="w", padx=16, pady=(8, 2))
        self.detail_reason_label = self._make_label(
            detail_panel,
            textvariable=self.detail_reason_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=("Segoe UI", 11, "normal"),
            wraplength=520,
        )
        self.detail_reason_label.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 12))

        detail_fields = self.tk.Frame(detail_panel, bg=self.colors["panel_alt"])
        detail_fields.grid(row=4, column=0, sticky="ew", padx=16)
        detail_fields.grid_columnconfigure(0, weight=1)
        rows = [
            ("Target Path", self.detail_path_var, ("Consolas", 11, "normal")),
            ("Detected Unit", self.detail_root_var, ("Consolas", 11, "normal")),
            ("Average Comparison", self.detail_compare_var, ("Segoe UI", 11, "normal")),
            ("Target Freshness", self.detail_freshness_var, ("Segoe UI", 11, "normal")),
            ("Access", self.detail_write_var, ("Segoe UI", 11, "normal")),
            ("Memory", self.detail_memory_var, ("Segoe UI", 11, "normal")),
            ("Selected Phone", self.detail_device_var, ("Segoe UI", 11, "normal")),
        ]
        for idx, (title, var, font) in enumerate(rows):
            self._make_label(
                detail_fields,
                text=title,
                bg=self.colors["panel_alt"],
                fg=self.colors["muted"],
                font=("Segoe UI Semibold", 10, "bold"),
            ).grid(row=idx * 2, column=0, sticky="w", pady=(0 if idx == 0 else 10, 2))
            self._make_label(
                detail_fields,
                textvariable=var,
                bg=self.colors["panel_alt"],
                wraplength=520,
                font=font,
            ).grid(row=idx * 2 + 1, column=0, sticky="w")

        # ── GitHub Sync Panel (row 4) ──────────────────────────────────────────
        page.grid_rowconfigure(4, weight=0)
        gh_panel = self._panel(page, self.colors["panel"])
        gh_panel.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 8))
        gh_panel.grid_columnconfigure(0, weight=1)

        gh_header = self.tk.Frame(gh_panel, bg=self.colors["panel"])
        gh_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        gh_header.grid_columnconfigure(0, weight=1)
        self._make_label(
            gh_header,
            text="GitHub Sync",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self.gh_user_var = self.tk.StringVar(value="Detecting git identity...")
        self._make_label(
            gh_header,
            textvariable=self.gh_user_var,
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Consolas", 10),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Git auth status indicator
        self.gh_auth_var = self.tk.StringVar(value="")
        self._make_label(
            gh_header,
            textvariable=self.gh_auth_var,
            bg=self.colors["panel"],
            fg=self.colors["warn"],
            font=("Segoe UI", 9),
        ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        gh_btns = self.tk.Frame(gh_header, bg=self.colors["panel"])
        gh_btns.grid(row=0, column=1, rowspan=3, sticky="e")
        self._make_button(gh_btns, "Refresh Git Status", self._refresh_git_statuses).grid(
            row=0, column=0, padx=(0, 6))
        self._make_button(gh_btns, "Push All Updated", self.on_git_push_all, accent=True).grid(
            row=0, column=1, padx=(0, 6))
        self._make_button(gh_btns, "Pull All Newer", self.on_git_pull_all_newer).grid(
            row=0, column=2, padx=(0, 6))
        self._make_button(gh_btns, "Check Git Auth", self._check_git_auth).grid(
            row=0, column=3, padx=(0, 6))
        self._make_button(gh_btns, "Open GitHub.com", self._open_github_web).grid(
            row=0, column=4)

        self.gh_apps_frame = self.tk.Frame(gh_panel, bg=self.colors["panel"])
        self.gh_apps_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 14))
        self._make_label(
            self.gh_apps_frame,
            text="Click 'Refresh Git Status' to load remote state.",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, sticky="w", padx=8)

        # ── CITL App Overview (row 2) ──────────────────────────────────────────
        page.grid_rowconfigure(2, weight=0)
        apps_panel = self._panel(page, self.colors["panel"])
        apps_panel.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 12))
        apps_panel.grid_columnconfigure(0, weight=1)
        self._make_label(
            apps_panel,
            text=f"{_scope_label()} Apps Overview",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
        self._make_label(
            apps_panel,
            text=(
                "Priority order: NOETIKON PRIME pinned first, CANIS COSMOS ASTROLOGY next, "
                "then all remaining apps by most recent file update."
            ),
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9, "normal"),
            wraplength=1200,
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 8))
        self.apps_frame = self.tk.Frame(apps_panel, bg=self.colors["panel"])
        self.apps_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 14))
        self._render_apps_overview()
        self._ensure_sync_app_vars()

        filter_panel = self.tk.Frame(apps_panel, bg=self.colors["panel_alt"])
        filter_panel.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        filter_panel.grid_columnconfigure(0, weight=1)
        filter_panel.grid_columnconfigure(1, weight=0)
        self._make_label(
            filter_panel,
            text="App Inclusion List for Push/Pull/Duplicate",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        self._make_label(
            filter_panel,
            textvariable=self.sync_app_selection_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9, "normal"),
            wraplength=980,
        ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 6))
        self._make_label(
            filter_panel,
            textvariable=self.sync_app_health_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9, "normal"),
            wraplength=980,
        ).grid(row=2, column=0, sticky="w", padx=10, pady=(0, 6))
        pick_btns = self.tk.Frame(filter_panel, bg=self.colors["panel_alt"])
        pick_btns.grid(row=0, column=1, rowspan=2, sticky="e", padx=8, pady=(4, 4))
        self._make_button(pick_btns, "All", lambda: self._set_sync_app_selection("all")).pack(side="left", padx=4)
        self._make_button(pick_btns, "Core", lambda: self._set_sync_app_selection("core")).pack(side="left", padx=4)
        self._make_button(pick_btns, "Needs Sync", lambda: self._set_sync_app_selection("needs_sync")).pack(side="left", padx=4)
        self._make_button(pick_btns, "None", lambda: self._set_sync_app_selection("none")).pack(side="left", padx=4)

        app_checks = self.tk.Frame(filter_panel, bg=self.colors["panel_alt"])
        app_checks.grid(row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        col_count = 3
        for c in range(col_count):
            app_checks.grid_columnconfigure(c, weight=1)
        for idx, app in enumerate(self._ordered_apps_for_overview()):
            app_name = str(app.get("name") or "").strip()
            var = self.sync_app_vars.get(app_name)
            if var is None:
                continue
            cb = self.tk.Checkbutton(
                app_checks,
                text=app_name,
                variable=var,
                command=self._refresh_sync_app_selection_meta,
                bg=self.colors["panel_alt"],
                fg=self.colors["text"],
                activebackground=self.colors["panel_alt"],
                activeforeground=self.colors["text"],
                selectcolor=self.colors["button"],
                highlightthickness=0,
                font=("Segoe UI", 9, "normal"),
            )
            cb.grid(row=idx // col_count, column=idx % col_count, sticky="w", padx=6, pady=1)

        # ── Bootstrap / Patch Updater (row 5) ────────────────────────────────
        page.grid_rowconfigure(5, weight=0)
        bootstrap_panel = self._panel(page, self.colors["panel_alt"])
        bootstrap_panel.grid(row=5, column=0, sticky="ew", padx=22, pady=(0, 10))
        bootstrap_panel.grid_columnconfigure(0, weight=2)
        bootstrap_panel.grid_columnconfigure(1, weight=2)
        bootstrap_panel.grid_columnconfigure(2, weight=4)
        walkthrough_blue = "#2e75b6"
        self._make_label(
            bootstrap_panel,
            text="Bootstrap / Patch Updater",
            bg=self.colors["panel_alt"],
            fg=walkthrough_blue,
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 6))
        self._make_label(
            bootstrap_panel,
            textvariable=self.bootstrap_info_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            wraplength=1200,
            font=("Segoe UI", 10, "normal"),
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 10))

        launch_frame = self.tk.Frame(bootstrap_panel, bg=self.colors["panel_alt"])
        launch_frame.grid(row=2, column=0, sticky="nsew", padx=(16, 8), pady=(0, 12))
        launch_frame.grid_columnconfigure(0, weight=1)
        launch_frame.grid_rowconfigure(2, weight=1)
        self._make_label(
            launch_frame,
            text="Launch App (Priority + Recent)",
            bg=self.colors["panel_alt"],
            fg=walkthrough_blue,
            font=("Segoe UI Semibold", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))
        self._make_label(
            launch_frame,
            textvariable=self.launch_update_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            wraplength=320,
            font=("Segoe UI", 9, "normal"),
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        launch_list_wrap = self.tk.Frame(launch_frame, bg=self.colors["panel_alt"])
        launch_list_wrap.grid(row=2, column=0, sticky="nsew")
        launch_list_wrap.grid_columnconfigure(0, weight=1)
        launch_list_wrap.grid_rowconfigure(0, weight=1)
        self.launch_app_listbox = self.tk.Listbox(
            launch_list_wrap,
            bg=self.colors["card"],
            fg=self.colors["text"],
            selectbackground=self.colors["button_active"],
            selectforeground=self.colors["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            activestyle="none",
            font=("Consolas", 9, "normal"),
            height=11,
        )
        launch_scroll = self.tk.Scrollbar(launch_list_wrap, orient="vertical", command=self.launch_app_listbox.yview)
        self.launch_app_listbox.configure(yscrollcommand=launch_scroll.set)
        self.launch_app_listbox.grid(row=0, column=0, sticky="nsew")
        launch_scroll.grid(row=0, column=1, sticky="ns")
        self.launch_app_listbox.bind("<<ListboxSelect>>", self._on_launch_app_selection_changed)

        self._make_label(
            launch_frame,
            textvariable=self.launch_selected_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["text"],
            wraplength=320,
            font=("Segoe UI", 9, "normal"),
        ).grid(row=3, column=0, sticky="w", pady=(8, 6))
        launch_actions = self.tk.Frame(launch_frame, bg=self.colors["panel_alt"])
        launch_actions.grid(row=4, column=0, sticky="ew")
        launch_actions.grid_columnconfigure(0, weight=1)
        launch_actions.grid_columnconfigure(1, weight=1)
        launch_actions.grid_columnconfigure(2, weight=1)
        self._make_button(launch_actions, "Launch Local", self.on_launch_selected_local).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        self._make_button(launch_actions, "Launch USB", self.on_launch_selected_usb).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        self._make_button(launch_actions, "Open Repo", self.on_open_selected_repo).grid(
            row=0, column=2, sticky="ew", padx=(4, 0)
        )

        list_frame = self.tk.Frame(bootstrap_panel, bg=self.colors["panel_alt"])
        list_frame.grid(row=2, column=1, sticky="nsew", padx=(8, 8), pady=(0, 12))
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(1, weight=1)
        self._make_label(
            list_frame,
            text="Discovered bootstraps (newest first)",
            bg=self.colors["panel_alt"],
            fg=walkthrough_blue,
            font=("Segoe UI Semibold", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        listbox_wrap = self.tk.Frame(list_frame, bg=self.colors["panel_alt"])
        listbox_wrap.grid(row=1, column=0, sticky="nsew")
        listbox_wrap.grid_columnconfigure(0, weight=1)
        listbox_wrap.grid_rowconfigure(0, weight=1)
        self.bootstrap_listbox = self.tk.Listbox(
            listbox_wrap,
            bg=self.colors["card"],
            fg=self.colors["text"],
            selectbackground=self.colors["button_active"],
            selectforeground=self.colors["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            activestyle="none",
            font=("Consolas", 9, "normal"),
            height=7,
        )
        bootstrap_scroll = self.tk.Scrollbar(listbox_wrap, orient="vertical", command=self.bootstrap_listbox.yview)
        self.bootstrap_listbox.configure(yscrollcommand=bootstrap_scroll.set)
        self.bootstrap_listbox.grid(row=0, column=0, sticky="nsew")
        bootstrap_scroll.grid(row=0, column=1, sticky="ns")
        self.bootstrap_listbox.bind("<<ListboxSelect>>", self._on_bootstrap_selection_changed)

        right_frame = self.tk.Frame(bootstrap_panel, bg=self.colors["panel_alt"])
        right_frame.grid(row=2, column=2, sticky="nsew", padx=(8, 16), pady=(0, 12))
        right_frame.grid_columnconfigure(0, weight=1)
        right_frame.grid_rowconfigure(4, weight=1)
        self._make_label(
            right_frame,
            textvariable=self.bootstrap_selection_var,
            bg=self.colors["panel_alt"],
            wraplength=760,
            font=("Segoe UI Semibold", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self._make_label(
            right_frame,
            textvariable=self.bootstrap_preview_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            wraplength=760,
            font=("Segoe UI", 10, "normal"),
        ).grid(row=1, column=0, sticky="w", pady=(4, 8))

        app_pick = self.tk.Frame(right_frame, bg=self.colors["panel_alt"])
        app_pick.grid(row=2, column=0, sticky="ew")
        app_pick.grid_columnconfigure(0, weight=1)
        self._make_label(
            app_pick,
            text="Selective update apps",
            bg=self.colors["panel_alt"],
            fg=walkthrough_blue,
            font=("Segoe UI Semibold", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        for idx, app in enumerate(self._ordered_apps_for_overview()):
            app_name = str(app.get("name") or "").strip()
            var = self.tk.BooleanVar(value=True)
            self.bootstrap_app_vars[app_name] = var
            cb = self.tk.Checkbutton(
                app_pick,
                text=app_name,
                variable=var,
                command=self._refresh_bootstrap_preview,
                bg=self.colors["panel_alt"],
                fg=self.colors["text"],
                activebackground=self.colors["panel_alt"],
                activeforeground=self.colors["text"],
                selectcolor=self.colors["button"],
                highlightthickness=0,
                font=("Segoe UI", 9, "normal"),
            )
            cb.grid(row=idx + 1, column=0, sticky="w")

        self._make_label(
            right_frame,
            text="Applied Patch Catalog (Local + Selected USB)",
            bg=self.colors["panel_alt"],
            fg=walkthrough_blue,
            font=("Segoe UI Semibold", 10, "bold"),
        ).grid(row=3, column=0, sticky="w", pady=(8, 4))
        self.bootstrap_history_box = self.scrolledtext.ScrolledText(
            right_frame,
            wrap="word",
            height=9,
            state="disabled",
            bg=self.colors["card"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            relief="flat",
            bd=0,
            font=("Consolas", 9),
            padx=8,
            pady=8,
        )
        self.bootstrap_history_box.grid(row=4, column=0, sticky="nsew", pady=(0, 8))

        action_row = self.tk.Frame(bootstrap_panel, bg=self.colors["panel_alt"])
        action_row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 14))
        for col in range(3):
            action_row.grid_columnconfigure(col, weight=1)
        self.bootstrap_refresh_btn = self._make_button(action_row, "Refresh Bootstraps", self.on_refresh_bootstrap_catalog)
        self.bootstrap_refresh_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.bootstrap_build_btn = self._make_button(action_row, "Create Bootstrap from PC Source", self.on_build_bootstrap_from_source)
        self.bootstrap_build_btn.grid(row=0, column=1, sticky="ew", padx=8, pady=(0, 8))
        self.bootstrap_install_usb_btn = self._make_button(
            action_row, "Install Selected -> USB", self.on_install_bootstrap_to_usb, accent=True
        )
        self.bootstrap_install_usb_btn.grid(row=0, column=2, sticky="ew", padx=(8, 0), pady=(0, 8))
        self.bootstrap_install_local_btn = self._make_button(
            action_row, "Install Selected -> Local", self.on_install_bootstrap_to_local
        )
        self.bootstrap_install_local_btn.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.bootstrap_rollback_usb_btn = self._make_button(
            action_row, "Rollback Last on USB", self.on_rollback_bootstrap_usb
        )
        self.bootstrap_rollback_usb_btn.grid(row=1, column=1, sticky="ew", padx=8)
        self.bootstrap_rollback_local_btn = self._make_button(
            action_row, "Rollback Last on Local", self.on_rollback_bootstrap_local
        )
        self.bootstrap_rollback_local_btn.grid(row=1, column=2, sticky="ew", padx=(8, 0))
        self.bootstrap_deploy_latest_btn = self._make_button(
            action_row,
            "Deploy Newest Bootstrap -> Local + USB",
            self.on_deploy_latest_bootstrap_both,
            accent=True,
        )
        self.bootstrap_deploy_latest_btn.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        # ── Quick Patch from Recent Git Commits (row 4) ───────────────────────
        git_outer = self.tk.Frame(bootstrap_panel, bg=self.colors["panel_alt"])
        git_outer.grid(row=4, column=0, columnspan=3, sticky="ew", padx=16, pady=(4, 14))
        git_outer.grid_columnconfigure(0, weight=1)

        git_title_row = self.tk.Frame(git_outer, bg=self.colors["panel_alt"])
        git_title_row.grid(row=0, column=0, sticky="ew")
        self._make_label(
            git_title_row,
            text="Quick Patch from Recent Git Commits",
            bg=self.colors["panel_alt"],
            fg=walkthrough_blue,
            font=("Segoe UI Semibold", 11, "bold"),
        ).pack(side="left")
        self._make_label(
            git_title_row,
            text=" — detect changes, package, deploy to local/USB with one click",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).pack(side="left")

        self._make_label(
            git_outer,
            textvariable=self.git_patch_status_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky="w", pady=(2, 4))

        git_body = self.tk.Frame(git_outer, bg=self.colors["panel_alt"])
        git_body.grid(row=2, column=0, sticky="ew")
        git_body.grid_columnconfigure(0, weight=1)

        # Commit listbox (multi-select)
        listbox_wrap2 = self.tk.Frame(git_body, bg=self.colors["panel_alt"])
        listbox_wrap2.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        listbox_wrap2.grid_columnconfigure(0, weight=1)
        listbox_wrap2.grid_rowconfigure(0, weight=1)
        self.git_patch_listbox = self.tk.Listbox(
            listbox_wrap2,
            bg=self.colors["card"],
            fg=self.colors["text"],
            selectbackground=self.colors["button_active"],
            selectforeground=self.colors["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            activestyle="none",
            font=("Consolas", 9),
            height=6,
            selectmode="multiple",
        )
        git_scroll2 = self.tk.Scrollbar(listbox_wrap2, orient="vertical", command=self.git_patch_listbox.yview)
        self.git_patch_listbox.configure(yscrollcommand=git_scroll2.set)
        self.git_patch_listbox.grid(row=0, column=0, sticky="nsew")
        git_scroll2.grid(row=0, column=1, sticky="ns")

        # Action buttons column
        git_btns = self.tk.Frame(git_body, bg=self.colors["panel_alt"])
        git_btns.grid(row=0, column=1, sticky="ns")
        git_btns.grid_columnconfigure(0, weight=1)
        _gbtn_cfg = {"sticky": "ew", "pady": 2}
        self._make_button(
            git_btns, "Detect Recent Commits", self.on_check_git_patches
        ).grid(row=0, column=0, **_gbtn_cfg)
        self._make_button(
            git_btns, "Package as Patch ZIP", self.on_build_git_patch
        ).grid(row=1, column=0, **_gbtn_cfg)
        self._make_button(
            git_btns, "Package + Apply → USB", self.on_git_patch_apply_usb, accent=True
        ).grid(row=2, column=0, **_gbtn_cfg)
        self._make_button(
            git_btns, "Package + Apply → Local", self.on_git_patch_apply_local
        ).grid(row=3, column=0, **_gbtn_cfg)
        self._make_button(
            git_btns, "Package + Apply → Both", self.on_git_patch_apply_both, accent=True
        ).grid(row=4, column=0, **_gbtn_cfg)
        self._make_label(
            git_btns,
            text="Rollback: use buttons above ↑",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=("Segoe UI", 8),
        ).grid(row=5, column=0, sticky="ew", pady=(8, 0))

        status_bar = self.tk.Label(
            page,
            textvariable=self.status_var,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            anchor="w",
            padx=18,
            pady=10,
            font=("Segoe UI", 11),
        )
        status_bar.grid(row=6, column=0, sticky="ew")

        log_panel = self._panel(page, self.colors["panel"])
        log_panel.grid(row=7, column=0, sticky="nsew", padx=22, pady=(0, 18))
        log_panel.grid_columnconfigure(0, weight=1)
        log_panel.grid_rowconfigure(1, weight=1)
        self._make_label(
            log_panel,
            text="Activity Log",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))
        self.log = self.scrolledtext.ScrolledText(
            log_panel,
            wrap="word",
            state="disabled",
            bg=self.colors["card"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            relief="flat",
            bd=0,
            font=("Consolas", 10),
            padx=12,
            pady=12,
        )
        self.log.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        self._refresh_launch_app_list()
        self._append(f"{APP_SYNC_NAME} {APP_SYNC_VERSION}\n")
        self._append("This dashboard now guides USB discovery, safe sync direction, and optional phone export.\n")
        self._append(f"Phone export now preserves Termux shortcuts and updates a {_scope_label()} shortcut for the latest pushed app.\n")
        self._append(f"[PUSH_LOG] {_device_push_log_path()}\n")
        self._append("Green recommendation means the PC source is newer and pushing to USB is the safe default.\n")
        self._append("Yellow recommendation means the USB copy appears newer and pulling back to the PC may be safer.\n")
        self._append("Red recommendation means both sides differ enough that you should review before syncing.\n")
        self._append(f"[SOURCE] {self.source_reason or 'manual/default source'}: {self.source_repo}\n")
        self._append(f"[SOURCE_FRESHNESS] {_fmt_ts(self.source_freshness_ts)}\n\n")


    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _selected_target(self) -> Optional[Path]:
        raw = self.target_var.get().strip()
        if not raw:
            return None
        return _normalize_repo_path(raw)

    def _selected_status(self) -> Optional[TargetStatus]:
        target = self._selected_target()
        if target is None:
            return None
        return self.target_status.get(str(target))

    def _selected_device(self) -> Optional[PhoneDevice]:
        raw = self.device_var.get().strip()
        if not raw:
            return None
        for device in self.devices:
            if device.serial == raw:
                return device
        return None

    def _build_target_statuses(self, targets: List[SyncTarget]) -> Dict[str, TargetStatus]:
        status: Dict[str, TargetStatus] = {}
        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        for target in targets:
            freshness_ts = _repo_freshness(target.path)
            writable, detail = self._target_write_check(target.path)
            comparison = compare_repo_freshness(
                self.source_repo,
                target.path,
                include_data=include_data,
                include_models=include_models,
            )
            status[str(target.path)] = TargetStatus(
                target=target,
                freshness_ts=freshness_ts,
                writable=writable,
                write_detail=detail,
                update_available=(comparison.recommendation == "push_source_to_target"),
                root_label=_root_label(target.root),
                comparison=comparison,
            )
        return status

    def _pick_preferred_target(self, targets: List[SyncTarget], statuses: Dict[str, TargetStatus]) -> Tuple[Optional[Path], str]:
        current = self._selected_target()
        if current is not None:
            for target in targets:
                if target.path == current:
                    return target.path, "kept current selection"

        last_selected = _last_selected_target()
        if last_selected is not None:
            for target in targets:
                if target.path == last_selected:
                    return target.path, "re-used last selected target"

        ranked: List[Tuple[Tuple[int, int, int], Path, bool]] = []
        for target in targets:
            snap = statuses.get(str(target.path))
            if snap is None:
                continue
            ranked.append((self._recommendation_priority(snap.comparison), target.path, target.remembered))
        if ranked:
            ranked.sort(key=lambda item: (0 if item[2] else 1, item[0], str(item[1]).lower()))
            best = ranked[0][1]
            return best, "selected safest available match"
        return None, ""

    def _mark_target_remembered(self, target_path: Path) -> None:
        updated: List[SyncTarget] = []
        changed = False
        for target in self.targets:
            if target.path == target_path and not target.remembered:
                updated.append(
                    SyncTarget(
                        path=target.path,
                        score=target.score,
                        has_git=target.has_git,
                        markers=target.markers,
                        root=target.root,
                        remembered=True,
                    )
                )
                changed = True
            else:
                updated.append(target)
        if changed:
            self.targets = updated
            self.target_status = self._build_target_statuses(self.targets)

    def _select_target(self, target_path: Path, *, remember: bool = True, log_selection: bool = False) -> None:
        try:
            rp = target_path.expanduser().resolve()
        except Exception:
            rp = target_path.expanduser()
        self.target_var.set(str(rp))
        if remember:
            try:
                _remember_target(rp)
                self._mark_target_remembered(rp)
            except Exception as e:
                self._append(f"[WARN] could not remember target folder: {e}\n")
        self._render_tiles()
        self._update_detail_panel()
        self._update_health_banner(log=log_selection)
        self._render_apps_overview()
        self._refresh_sync_app_selection_meta()
        self._refresh_guidance()
        self._refresh_bootstrap_preview()
        self._update_action_states()
        self._set_status(f"Selected target: {rp}")

    def _select_device(self, serial: str) -> None:
        self.device_var.set(serial)
        self._render_device_buttons()
        self._update_detail_panel()
        self._refresh_guidance()
        self._update_action_states()

    def _update_action_states(self) -> None:
        has_target = self._selected_target() is not None
        has_device = self._selected_device() is not None
        has_bootstrap = self._selected_bootstrap_package() is not None
        has_selected_apps = bool(self._selected_sync_app_names())
        can_duplicate = has_target and len(self.targets) >= 2
        normal = "disabled" if self._busy else "normal"
        self.refresh_btn.configure(state=normal)
        self.pick_btn.configure(state=normal if (self.targets and not self._busy) else "disabled")
        self.push_btn.configure(state=normal if (has_target and not self._busy) else "disabled")
        self.pull_btn.configure(state=normal if (has_target and not self._busy) else "disabled")
        self.phone_btn.configure(state=normal if (has_target and has_device and not self._busy) else "disabled")
        self.open_target_btn.configure(state=normal if (has_target and not self._busy) else "disabled")
        self.remember_btn.configure(state=normal if (has_target and not self._busy) else "disabled")
        self.duplicate_btn.configure(state=normal if (can_duplicate and not self._busy) else "disabled")
        if hasattr(self, "push_apps_only_btn"):
            self.push_apps_only_btn.configure(
                state=normal if (has_target and has_selected_apps and not self._busy) else "disabled"
            )
        if hasattr(self, "pull_apps_only_btn"):
            self.pull_apps_only_btn.configure(
                state=normal if (has_target and has_selected_apps and not self._busy) else "disabled"
            )
        if hasattr(self, "diagnostics_btn"):
            self.diagnostics_btn.configure(state=normal)
        if hasattr(self, "bootstrap_refresh_btn"):
            self.bootstrap_refresh_btn.configure(state=normal)
        if hasattr(self, "bootstrap_build_btn"):
            self.bootstrap_build_btn.configure(state=normal)
        if hasattr(self, "bootstrap_install_usb_btn"):
            self.bootstrap_install_usb_btn.configure(
                state=normal if (has_bootstrap and has_target and not self._busy) else "disabled"
            )
        if hasattr(self, "bootstrap_install_local_btn"):
            self.bootstrap_install_local_btn.configure(
                state=normal if (has_bootstrap and not self._busy) else "disabled"
            )
        if hasattr(self, "bootstrap_rollback_usb_btn"):
            self.bootstrap_rollback_usb_btn.configure(state=normal if (has_target and not self._busy) else "disabled")
        if hasattr(self, "bootstrap_rollback_local_btn"):
            self.bootstrap_rollback_local_btn.configure(state=normal if not self._busy else "disabled")
        if hasattr(self, "bootstrap_deploy_latest_btn"):
            self.bootstrap_deploy_latest_btn.configure(state=normal if (has_target and not self._busy) else "disabled")

    def _bind_tile_select(self, widget, target_path: Path) -> None:
        widget.bind("<Button-1>", lambda _event, p=target_path: self._select_target(p))

    def _on_tiles_canvas_configure(self, event) -> None:
        self.tiles_canvas.itemconfigure(self.tiles_window, width=event.width)
        columns = 1 if event.width < 980 else 2
        if columns != self._tile_columns:
            self._tile_columns = columns
            self._render_tiles()

    def _render_device_buttons(self) -> None:
        for child in self.device_button_frame.winfo_children():
            child.destroy()
        if not self.devices:
            self._make_label(
                self.device_button_frame,
                text="No Android phone detected over ADB. USB sync still works.",
                bg=self.colors["panel_alt"],
                fg=self.colors["muted"],
                wraplength=700,
            ).grid(row=0, column=0, sticky="w")
            return
        selected = self.device_var.get().strip()
        for idx, device in enumerate(self.devices):
            btn = self._make_button(
                self.device_button_frame,
                self._device_label(device),
                lambda s=device.serial: self._select_device(s),
                accent=(device.serial == selected),
            )
            btn.grid(row=idx, column=0, sticky="ew", pady=(0 if idx == 0 else 8, 0))

    def _app_source_root(self, app: dict) -> Path:
        """Return the source root for an app — its own repo_path if set, else the CITL source repo."""
        return resolve_app_source_root(app, self.source_repo)

    def _ensure_sync_app_vars(self) -> None:
        for app in self._ordered_apps_for_overview():
            app_name = str(app.get("name") or "").strip()
            if not app_name:
                continue
            if app_name not in self.sync_app_vars:
                self.sync_app_vars[app_name] = self.tk.BooleanVar(value=True)
        self._refresh_sync_app_selection_meta()

    def _selected_sync_app_names(self) -> List[str]:
        names: List[str] = []
        for app in CITL_APPS:
            app_name = str(app.get("name") or "").strip()
            var = self.sync_app_vars.get(app_name)
            if var is None:
                continue
            try:
                if bool(var.get()):  # type: ignore[union-attr]
                    names.append(app_name)
            except Exception:
                continue
        return names

    def _selected_sync_apps(self) -> List[dict]:
        picked = set(self._selected_sync_app_names())
        return [app for app in CITL_APPS if str(app.get("name") or "").strip() in picked]

    def _set_sync_app_selection(self, mode: str) -> None:
        self._ensure_sync_app_vars()
        mode_norm = (mode or "").strip().lower()
        for app in CITL_APPS:
            app_name = str(app.get("name") or "").strip()
            if not app_name:
                continue
            var = self.sync_app_vars.get(app_name)
            if var is None:
                continue
            choose = True
            if mode_norm == "none":
                choose = False
            elif mode_norm == "core":
                if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS:
                    choose = _app_has_tag(app, SYNC_TAG_HENOSIS)
                else:
                    choose = app_name in {"Factbook", "CITL App Sync", "LLMOps Suite"}
            elif mode_norm == "needs_sync":
                status_text, _ = self._app_usb_comparison(app)
                normalized = status_text.lower()
                choose = (
                    "needs update" in normalized
                    or "not on usb" in normalized
                    or "not in usb" in normalized
                )
            try:
                var.set(bool(choose))  # type: ignore[union-attr]
            except Exception:
                pass
        self._refresh_sync_app_selection_meta()

    def _refresh_sync_app_selection_meta(self) -> None:
        selected = self._selected_sync_app_names()
        total = len(CITL_APPS)
        if not selected:
            text = "App inclusion: none selected. Choose at least one app before push/pull."
        elif len(selected) == total:
            text = f"App inclusion: all {total} apps selected."
        else:
            names = ", ".join(selected[:6])
            if len(selected) > 6:
                names += f", +{len(selected) - 6} more"
            text = f"App inclusion: {len(selected)}/{total} selected -> {names}"
        self.sync_app_selection_var.set(text)

        target = self._selected_target() or (self.targets[0].path if self.targets else None)
        if target is None:
            self.sync_app_health_var.set("App status: select a USB target to compute sync deltas.")
            return

        needs_usb_update = 0
        usb_ahead = 0
        in_sync = 0
        separate_repo_only = 0
        unknown = 0
        for app in CITL_APPS:
            status_text, _ = self._app_usb_comparison(app)
            s = status_text.lower()
            if "needs update" in s or "not on usb" in s:
                needs_usb_update += 1
            elif "ahead" in s:
                usb_ahead += 1
            elif "in sync" in s:
                in_sync += 1
            elif "separate repo" in s:
                separate_repo_only += 1
            else:
                unknown += 1
        self.sync_app_health_var.set(
            "App status: "
            f"{needs_usb_update} need USB update, {usb_ahead} USB-ahead, "
            f"{in_sync} in sync, {separate_repo_only} separate-repo-only, {unknown} other."
        )
        if hasattr(self, "push_apps_only_btn"):
            self._update_action_states()

    def _sync_selected_apps_only(
        self,
        source_repo: Path,
        target_repo: Path,
        selected_app_names: List[str],
        log_fn: LogFn = None,
    ) -> SyncResult:
        start = time.time()
        summary = sync_registered_app_key_files(
            source_repo,
            target_repo,
            selected_app_names=selected_app_names,
            log_fn=log_fn,
        )
        copied = sum(int(v.get("copied", 0)) for v in summary.values())
        skipped = sum(int(v.get("skipped", 0)) for v in summary.values())
        errors = sum(int(v.get("errors", 0)) for v in summary.values())
        try:
            install_sync_launchers(target_repo, log_fn=log_fn)
        except Exception as e:
            errors += 1
            _safe_log(log_fn, f"[APP-SYNC][WARN] launcher refresh failed: {e}\n")
        try:
            port_to_ubuntu(target_repo, log_fn=log_fn)
        except Exception as e:
            _safe_log(log_fn, f"[APP-SYNC][WARN] Ubuntu port refresh failed: {e}\n")
        return SyncResult(
            copied=copied,
            skipped=skipped,
            errors=errors,
            used_rsync=False,
            elapsed_sec=time.time() - start,
        )

    def _run_selected_apps_sync(self, direction: str) -> None:
        direction_norm = (direction or "").strip().lower()
        target = self._selected_target()
        if target is None:
            self.messagebox.showerror("No target", "Select a repo tile first.")
            return
        selected_app_names = self._selected_sync_app_names()
        if not selected_app_names:
            self.messagebox.showinfo("No apps selected", "Select at least one app in the app inclusion list.")
            return

        if direction_norm == "push":
            src_repo = self.source_repo
            dst_repo = target
            title = "Confirm selected app push"
            prompt = (
                f"Push {len(selected_app_names)} selected app(s) from PC -> USB?\n\n"
                f"To:\n{target}\n\n"
                f"Apps:\n- " + "\n- ".join(selected_app_names)
            )
            status_text = "Pushing selected apps to USB..."
            start_log = "[SYNC] starting selected-app PC -> USB push...\n"
            done_label = "Selected-app push complete. Refreshing analysis..."
            log_kind = "usb_push_apps_only"
        elif direction_norm == "pull":
            src_repo = target
            dst_repo = self.source_repo
            title = "Confirm selected app pull"
            prompt = (
                f"Pull {len(selected_app_names)} selected app(s) from USB -> PC?\n\n"
                f"From:\n{target}\n\n"
                f"Apps:\n- " + "\n- ".join(selected_app_names)
            )
            status_text = "Pulling selected apps from USB..."
            start_log = "[SYNC] starting selected-app USB -> PC pull...\n"
            done_label = "Selected-app pull complete. Refreshing analysis..."
            log_kind = "usb_pull_apps_only"
        else:
            self.messagebox.showerror("Invalid direction", f"Unsupported selected-app sync direction: {direction}")
            return

        if not self.messagebox.askyesno(title, prompt):
            return

        if direction_norm == "push":
            try:
                _remember_target(target)
                self._mark_target_remembered(target)
            except Exception as e:
                self._append(f"[WARN] could not persist target memory before selected-app push: {e}\n")

        self._begin_busy(status_text)
        self._append("\n" + start_log)
        self._append(
            f"[APP-FILTER] explicit selected-app sync with {len(selected_app_names)} app(s): "
            + ", ".join(selected_app_names)
            + "\n"
        )

        def worker() -> None:
            try:
                result = self._sync_selected_apps_only(
                    src_repo,
                    dst_repo,
                    selected_app_names,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
            except Exception as e:
                _append_device_push_log_entry(
                    {
                        "kind": log_kind,
                        "status": "error",
                        "source_repo": str(src_repo),
                        "target_path": str(dst_repo),
                        "selected_apps": list(selected_app_names),
                        "error": str(e),
                    },
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda: self._append(f"[ERROR] selected-app sync failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("Selected-app sync failed."))
            else:
                _append_device_push_log_entry(
                    {
                        "kind": log_kind,
                        "status": "ok" if result.errors == 0 else "partial",
                        "source_repo": str(src_repo),
                        "target_path": str(dst_repo),
                        "selected_apps": list(selected_app_names),
                        "copied": int(result.copied),
                        "skipped": int(result.skipped),
                        "errors": int(result.errors),
                        "elapsed_sec": float(result.elapsed_sec),
                    },
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(
                    0,
                    lambda: self._append(
                        f"[DONE] selected-app sync copied={result.copied} skipped={result.skipped} "
                        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s\n"
                    ),
                )
                if direction_norm == "push" and result.errors == 0:
                    bumped = []
                    for app in self._selected_sync_apps():
                        vf = app.get("version_file")
                        if vf and _bump_version_file(self.source_repo, vf):
                            bumped.append(vf)
                    if bumped:
                        self.root.after(
                            0,
                            lambda b=bumped: self._append(
                                f"[VERSION] auto-bumped patch in: {', '.join(b)}\n"
                            ),
                        )
                self.root.after(0, lambda: self._set_status(done_label))
                self.root.after(0, self._render_apps_overview)
                self.root.after(0, self._refresh_sync_app_selection_meta)
            finally:
                self.root.after(0, self._after_sync_action)

        threading.Thread(target=worker, daemon=True).start()

    def on_push_selected_apps_only(self) -> None:
        self._run_selected_apps_sync("push")

    def on_pull_selected_apps_only(self) -> None:
        self._run_selected_apps_sync("pull")

    def _refresh_launch_app_list(self) -> None:
        if self.launch_app_listbox is None:
            return
        selected_name = ""
        selected_app = self._selected_launch_app()
        if selected_app is not None:
            selected_name = str(selected_app.get("name") or "")

        self.launch_apps_cache = self._ordered_apps_for_overview()
        lb = self.launch_app_listbox
        lb.delete(0, "end")
        needs_update = 0
        ready = 0
        for idx, app in enumerate(self.launch_apps_cache, start=1):
            icon = str(app.get("icon") or "APP")
            name = str(app.get("name") or "Unnamed App")
            usb_status, _color = self._app_usb_comparison(app)
            short_status = usb_status.split(" (", 1)[0]
            if len(short_status) > 34:
                short_status = short_status[:34] + "..."
            if "needs update" in usb_status.lower() or "not on usb" in usb_status.lower():
                needs_update += 1
                cue = "!"
            else:
                ready += 1
                cue = " "
            lb.insert("end", f"{idx:02d}. {cue} {icon} | {name} | {short_status}")

        total = len(self.launch_apps_cache)
        self.launch_update_var.set(f"Update status: {needs_update} need update | {ready} ready | total {total}")

        if self.launch_apps_cache:
            pick_idx = 0
            if selected_name:
                for i, app in enumerate(self.launch_apps_cache):
                    if str(app.get("name") or "") == selected_name:
                        pick_idx = i
                        break
            lb.selection_clear(0, "end")
            lb.selection_set(pick_idx)
            lb.activate(pick_idx)
            self._on_launch_app_selection_changed()
        else:
            self.launch_selected_var.set("Launch app: no apps available.")

    def _selected_launch_app(self) -> Optional[dict]:
        if self.launch_app_listbox is None:
            return None
        sel = self.launch_app_listbox.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.launch_apps_cache):
            return None
        return self.launch_apps_cache[idx]

    def _on_launch_app_selection_changed(self, _event=None) -> None:
        app = self._selected_launch_app()
        if app is None:
            self.launch_selected_var.set("Launch app: select an app from the list.")
            return
        usb_status, _color = self._app_usb_comparison(app)
        self.launch_selected_var.set(f"{app.get('icon', 'APP')} {app['name']} | {usb_status}")

    def on_launch_selected_local(self) -> None:
        app = self._selected_launch_app()
        if app is None:
            self.messagebox.showinfo("No app selected", "Select an app from Launch App list first.")
            return
        self.on_launch_app_local(app)

    def on_launch_selected_usb(self) -> None:
        app = self._selected_launch_app()
        if app is None:
            self.messagebox.showinfo("No app selected", "Select an app from Launch App list first.")
            return
        self.on_launch_app_usb(app)

    def on_open_selected_repo(self) -> None:
        app = self._selected_launch_app()
        if app is None:
            self.messagebox.showinfo("No app selected", "Select an app from Launch App list first.")
            return
        self.on_open_app_repo(app)

    def _resolve_app_launcher_path(self, app: dict, repo_root: Path) -> Optional[Path]:
        root = Path(repo_root).expanduser()
        launcher = ""
        if os.name == "nt":
            launcher = str(app.get("launcher_win") or "").strip()
        else:
            launcher = str(app.get("launcher_nix") or "").strip()
        if launcher:
            p = root / launcher
            if p.exists():
                return p
        slug = _slugify_name(app.get("name", "app"))
        if os.name == "nt":
            fallback = root / "bootstrap" / "windows" / f"Run-{slug}.cmd"
        else:
            fallback = root / "bootstrap" / "linux" / f"run-{slug}.sh"
        if fallback.exists():
            return fallback
        return None

    def _launch_app_from_root(self, app: dict, repo_root: Path, origin_label: str) -> None:
        launch_path = self._resolve_app_launcher_path(app, repo_root)
        if launch_path is None:
            self.messagebox.showerror(
                "Launcher not found",
                f"No runnable launcher was found for {app['name']} in:\n{repo_root}",
            )
            return
        try:
            suffix = launch_path.suffix.lower()
            if os.name == "nt":
                if suffix == ".ps1":
                    subprocess.Popen(
                        [
                            "powershell",
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(launch_path),
                        ],
                        cwd=str(repo_root),
                    )
                elif suffix in {".cmd", ".bat"}:
                    subprocess.Popen(["cmd", "/c", str(launch_path)], cwd=str(repo_root))
                else:
                    subprocess.Popen([str(launch_path)], cwd=str(repo_root))
            else:
                if suffix == ".sh":
                    subprocess.Popen(["bash", str(launch_path)], cwd=str(repo_root))
                else:
                    subprocess.Popen([str(launch_path)], cwd=str(repo_root))
            self._append(f"[LAUNCH] {app['name']} from {origin_label}: {launch_path}\n")
        except Exception as e:
            self.messagebox.showerror("Launch failed", f"{app['name']} launch failed:\n{e}")

    def on_launch_app_local(self, app: dict) -> None:
        self._launch_app_from_root(app, self._app_source_root(app), "local source")

    def on_launch_app_usb(self, app: dict) -> None:
        target = self._selected_target()
        if target is None:
            self.messagebox.showinfo("No USB target", "Select a USB target first.")
            return
        self._launch_app_from_root(app, target, "selected USB")

    def on_open_app_repo(self, app: dict) -> None:
        open_in_file_manager(self._app_source_root(app))

    def _collect_diagnostics_report(self) -> str:
        lines: List[str] = []
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{APP_SYNC_NAME} {APP_SYNC_VERSION}")
        lines.append(f"Generated: {now_text}")
        lines.append("")
        lines.append("Source Repository")
        lines.append(f"  path: {self.source_repo}")
        lines.append(f"  reason: {self.source_reason or 'manual/default source'}")
        lines.append(f"  freshness: {_fmt_ts(self.source_freshness_ts)}")
        lines.append("")
        target = self._selected_target()
        lines.append("Selected USB Target")
        lines.append(f"  path: {target if target is not None else '(none selected)'}")
        snap = self._selected_status()
        if snap is not None:
            lines.append(f"  writable: {snap.writable} ({snap.write_detail})")
            lines.append(f"  recommendation: {snap.comparison.recommendation}")
            lines.append(f"  summary: {snap.comparison.summary}")
        lines.append("")
        selected_names = self._selected_sync_app_names()
        lines.append(f"App Inclusion Selection: {len(selected_names)}/{len(CITL_APPS)} selected")
        if selected_names:
            lines.append(f"  {', '.join(selected_names)}")
        lines.append("")
        lines.append("App Matrix (local vs USB vs launch vs git)")
        for app in self._ordered_apps_for_overview():
            app_name = str(app.get("name") or "").strip()
            last_ts = self._app_last_update_ts(app)
            local_root = self._app_source_root(app)
            usb_status, _usb_color = self._app_usb_comparison(app)
            local_launch = self._resolve_app_launcher_path(app, local_root)
            usb_launch = self._resolve_app_launcher_path(app, target) if target is not None else None
            gst = self._git_statuses.get(app_name) or {}
            branch = str(gst.get("branch") or "-")
            ahead = int(gst.get("ahead", 0) or 0)
            behind = int(gst.get("behind", 0) or 0)
            dirty = bool(gst.get("dirty", False))
            lines.append(
                f"- {app_name}"
                f"\n    last_update={_fmt_ts(last_ts)}"
                f"\n    local_repo={local_root}"
                f"\n    usb_status={usb_status}"
                f"\n    launch_local={'yes' if local_launch else 'no'}"
                f"\n    launch_usb={'yes' if usb_launch else 'no'}"
                f"\n    git=branch:{branch} ahead:{ahead} behind:{behind} dirty:{dirty}"
            )
        lines.append("")
        log_path = _device_push_log_path()
        lines.append(f"Device Push Log: {log_path}")
        if log_path.exists():
            try:
                rows = log_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                rows = []
            lines.append(f"  entries: {len(rows)}")
            for row in rows[-8:]:
                lines.append(f"  {row}")
        else:
            lines.append("  entries: 0")
        lines.append("")
        lines.append("Detected Targets")
        for t in self.targets:
            ts = self.target_status.get(str(t.path))
            if ts is None:
                continue
            lines.append(
                f"- {t.path} | writable={ts.writable} | recommendation={ts.comparison.recommendation} "
                f"| remembered={t.remembered}"
            )
        lines.append("")
        lines.append("Connected Phones")
        if self.devices:
            for dev in self.devices:
                lines.append(f"- {dev.serial} {dev.meta}".strip())
        else:
            lines.append("- none")
        return "\n".join(lines).strip() + "\n"

    # ------------------------------------------------------------------
    # Find & Repair Factbook
    # ------------------------------------------------------------------
    def on_find_and_repair_factbook(self) -> None:
        """Open the citl_repair_all GUI — searches for all Factbook installs,
        runs the 18-stage diagnostic on the selected one, and offers one-click
        Fix buttons for every identified problem."""
        import threading, importlib
        HERE = Path(__file__).parent.resolve()
        repair_path = HERE / "citl_repair_all.py"
        if not repair_path.exists():
            self.messagebox.showerror(
                "Repair Tool Not Found",
                f"citl_repair_all.py was not found in:\n{HERE}\n\n"
                "Sync the USB / repo to get the latest scripts.",
            )
            return
        def _launch():
            spec = importlib.util.spec_from_file_location("citl_repair_all", repair_path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run_gui()
        threading.Thread(target=_launch, daemon=True).start()

    def on_open_factbook_diagnostic(self) -> None:
        """Open the 18-stage pipeline diagnostic GUI directly."""
        import threading, importlib
        HERE = Path(__file__).parent.resolve()
        diag_path = HERE / "citl_factbook_diagnostic.py"
        if not diag_path.exists():
            self.messagebox.showerror(
                "Diagnostic Not Found",
                f"citl_factbook_diagnostic.py was not found in:\n{HERE}\n\n"
                "Sync the USB / repo to get the latest scripts.",
            )
            return
        def _launch():
            spec = importlib.util.spec_from_file_location("citl_factbook_diagnostic", diag_path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run_gui()
        threading.Thread(target=_launch, daemon=True).start()

    def on_open_exfat_repair_utility(self) -> None:
        """Launch the Sync Hub exFAT Repair Utility surface."""
        here = Path(__file__).parent.resolve()
        candidates = [
            here / "citl_sync_hub.py",
            here.parent / "citl_sync_hub.py",
        ]
        hub_path = next((p for p in candidates if p.exists()), None)
        if hub_path is None:
            self.messagebox.showerror(
                "Repair Utility Not Found",
                "Could not find citl_sync_hub.py in expected locations.\n"
                "Sync latest CITL utility files first.",
            )
            return
        try:
            subprocess.Popen([sys.executable, str(hub_path)], cwd=str(hub_path.parent))
        except Exception as exc:
            self.messagebox.showerror(
                "Repair Utility Launch Failed",
                f"Unable to launch exFAT repair utility:\n{exc}",
            )

    def on_open_diagnostics_window(self) -> None:
        if self.diagnostics_window is not None and self.diagnostics_window.winfo_exists():
            self.diagnostics_window.lift()
            self._refresh_diagnostics_window()
            return
        win = self.tk.Toplevel(self.root)
        win.title(f"{APP_SYNC_NAME} Diagnostics")
        win.geometry("1120x760")
        win.minsize(860, 560)
        win.configure(bg=self.colors["bg"])
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)
        self.diagnostics_window = win
        head = self.tk.Frame(win, bg=self.colors["panel"])
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        self._make_label(
            head,
            text="Diagnostics Window",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 13, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 2))
        self._make_label(
            head,
            text="Complete local/USB/app/git/phone diagnostic report for support and change control.",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9, "normal"),
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))
        btns = self.tk.Frame(head, bg=self.colors["panel"])
        btns.grid(row=0, column=1, rowspan=2, sticky="e", padx=10)
        self._make_button(btns, "Refresh", self._refresh_diagnostics_window).pack(side="left", padx=4)
        self._make_button(btns, "Copy", self._copy_diagnostics_to_clipboard).pack(side="left", padx=4)
        self._make_button(btns, "Save Report", self._save_diagnostics_report).pack(side="left", padx=4)
        self._make_button(btns, "Close", win.destroy).pack(side="left", padx=4)
        text = self.scrolledtext.ScrolledText(
            win,
            bg=self.colors["card"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            relief="flat",
            bd=0,
            font=("Consolas", 9),
            padx=10,
            pady=10,
        )
        text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.diagnostics_text = text
        self._refresh_diagnostics_window()

    def _refresh_diagnostics_window(self) -> None:
        if self.diagnostics_text is None:
            return
        report = self._collect_diagnostics_report()
        self.diagnostics_text.configure(state="normal")
        self.diagnostics_text.delete("1.0", "end")
        self.diagnostics_text.insert("1.0", report)
        self.diagnostics_text.configure(state="disabled")

    def _copy_diagnostics_to_clipboard(self) -> None:
        report = self._collect_diagnostics_report()
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(report)
            self._set_status("Diagnostics copied to clipboard.")
        except Exception as e:
            self.messagebox.showerror("Clipboard error", str(e))

    def _save_diagnostics_report(self) -> None:
        default_name = f"citl_sync_diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out = self.filedialog.asksaveasfilename(
            title="Save diagnostics report",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not out:
            return
        try:
            Path(out).write_text(self._collect_diagnostics_report(), encoding="utf-8")
        except Exception as e:
            self.messagebox.showerror("Save failed", str(e))
            return
        self._set_status(f"Diagnostics report saved: {out}")

    # ── Bootstrap / patch updater methods ────────────────────────────────────

    def _bootstrap_search_roots(self) -> List[Tuple[str, Path]]:
        roots: List[Tuple[str, Path]] = [("local-source", self.source_repo)]
        selected = self._selected_target()
        if selected is not None:
            roots.append(("selected-usb", selected))
        for target in self.targets:
            if selected is not None and target.path == selected:
                continue
            roots.append((f"usb:{target.path.name or target.path.drive or 'target'}", target.path))
        deduped: List[Tuple[str, Path]] = []
        seen: set = set()
        for hint, path in roots:
            try:
                key = str(path.expanduser().resolve())
            except Exception:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((hint, path))
        return deduped

    def _selected_bootstrap_package(self) -> Optional[BootstrapPackage]:
        if self.bootstrap_listbox is None:
            return None
        try:
            sel = self.bootstrap_listbox.curselection()
        except Exception:
            sel = ()
        if sel:
            idx = int(sel[0])
        elif self.bootstrap_packages:
            idx = 0
        else:
            return None
        if idx < 0 or idx >= len(self.bootstrap_packages):
            return None
        return self.bootstrap_packages[idx]

    def _selected_bootstrap_apps(self, package: Optional[BootstrapPackage] = None) -> List[str]:
        pkg = package or self._selected_bootstrap_package()
        if pkg is None:
            return []
        picked: List[str] = []
        for app_name in pkg.app_names:
            var = self.bootstrap_app_vars.get(app_name)
            if var is None:
                continue
            try:
                if bool(var.get()):  # type: ignore[union-attr]
                    picked.append(app_name)
            except Exception:
                pass
        return picked

    def _render_bootstrap_catalog(self) -> None:
        if self.bootstrap_listbox is None:
            return
        self.bootstrap_listbox.delete(0, "end")
        for pkg in self.bootstrap_packages:
            created = _fmt_ts(pkg.created_ts)
            label = (
                f"{created} | {pkg.bootstrap_id} | size={_fmt_bytes(pkg.package_size)} | "
                f"apps={len(pkg.app_names)} | {pkg.source_hint}"
            )
            self.bootstrap_listbox.insert("end", label)
        if self.bootstrap_packages:
            self.bootstrap_listbox.selection_clear(0, "end")
            self.bootstrap_listbox.selection_set(0)
            self.bootstrap_listbox.activate(0)
        self._refresh_bootstrap_preview()

    def _bootstrap_state_summary_lines(
        self,
        label: str,
        repo: Path,
        package: Optional[BootstrapPackage],
        selected_apps: Sequence[str],
    ) -> List[str]:
        lines: List[str] = [f"{label}: {repo}"]
        state = load_bootstrap_repo_state(repo)
        last = state.get("last_applied") if isinstance(state.get("last_applied"), dict) else {}
        if isinstance(last, dict) and last:
            last_id = str(last.get("bootstrap_id") or "?")
            last_when = str(last.get("applied_utc") or "?")
            last_created = str(last.get("bootstrap_created_utc") or "?")
            lines.append(f"  last applied: {last_id} | applied={last_when} | package_date={last_created}")
        else:
            lines.append("  last applied: none")
        history = state.get("history") if isinstance(state.get("history"), list) else []
        if history:
            lines.append("  recent events:")
            for item in reversed(history[-5:]):
                if not isinstance(item, dict):
                    continue
                ev = str(item.get("event") or "install")
                when = str(item.get("applied_utc") or "?")
                bid = str(item.get("bootstrap_id") or item.get("for_bootstrap_id") or "-")
                apps = item.get("apps")
                if isinstance(apps, list):
                    app_text = ",".join(str(a) for a in apps if str(a).strip())
                else:
                    app_text = ""
                if app_text:
                    lines.append(f"    {when} | {ev} | {bid} | apps={app_text}")
                else:
                    lines.append(f"    {when} | {ev} | {bid}")

        app_state = state.get("app_patch_state") if isinstance(state.get("app_patch_state"), dict) else {}
        if package is None:
            lines.append("  package comparison: select a bootstrap package.")
            return lines

        preview = preview_bootstrap_install(package, repo, selected_apps)
        lines.append(
            f"  package impact: {preview.classification} "
            f"(new={preview.newer_apps}, same={preview.same_apps}, older={preview.older_apps})"
        )
        if preview.stale and preview.stale_reason:
            lines.append(f"  warning: {preview.stale_reason}")

        if selected_apps:
            lines.append("  app status:")
            for app_name in selected_apps:
                entry = app_state.get(app_name) if isinstance(app_state, dict) else {}
                if isinstance(entry, dict) and entry:
                    bid = str(entry.get("bootstrap_id") or "?")
                    when = str(entry.get("applied_utc") or "?")
                    lines.append(f"    {app_name}: {bid} @ {when}")
                else:
                    lines.append(f"    {app_name}: not yet patched")
        return lines

    def _refresh_bootstrap_history_view(
        self,
        package: Optional[BootstrapPackage],
        selected_apps: Sequence[str],
    ) -> None:
        if self.bootstrap_history_box is None:
            return
        lines: List[str] = []
        lines.extend(self._bootstrap_state_summary_lines("LOCAL", self.source_repo, package, selected_apps))
        target = self._selected_target()
        if target is not None:
            lines.append("")
            lines.extend(self._bootstrap_state_summary_lines("USB", target, package, selected_apps))
            ok_media, reason = is_expected_usb_bootstrap_media(target)
            lines.append(f"  media check: {'eligible' if ok_media else 'not-eligible'} | {reason}")
        else:
            lines.append("")
            lines.append("USB: no selected target")

        self.bootstrap_history_box.configure(state="normal")
        self.bootstrap_history_box.delete("1.0", "end")
        self.bootstrap_history_box.insert("1.0", "\n".join(lines).strip() + "\n")
        self.bootstrap_history_box.configure(state="disabled")

    def _refresh_bootstrap_preview(self) -> None:
        pkg = self._selected_bootstrap_package()
        if pkg is None:
            self.bootstrap_selection_var.set("No bootstrap package selected.")
            self.bootstrap_preview_var.set("Install preview: select a package and destination.")
            self._refresh_bootstrap_history_view(None, [])
            return

        # Default app selection follows package content.
        for app in CITL_APPS:
            app_name = str(app.get("name") or "").strip()
            var = self.bootstrap_app_vars.get(app_name)
            if var is None:
                continue
            try:
                if app_name not in pkg.app_names:
                    var.set(False)  # type: ignore[union-attr]
            except Exception:
                pass
        if not self._selected_bootstrap_apps(pkg):
            for app_name in pkg.app_names:
                var = self.bootstrap_app_vars.get(app_name)
                if var is None:
                    continue
                try:
                    var.set(True)  # type: ignore[union-attr]
                except Exception:
                    pass

        selected_apps = self._selected_bootstrap_apps(pkg)
        local_preview = preview_bootstrap_install(pkg, self.source_repo, selected_apps)
        target = self._selected_target()
        usb_preview = preview_bootstrap_install(pkg, target, selected_apps) if target is not None else None

        self.bootstrap_selection_var.set(
            f"Selected: {pkg.bootstrap_id} | created={_fmt_ts(pkg.created_ts)} | "
            f"size={_fmt_bytes(pkg.package_size)} | files={pkg.file_count} | source={pkg.source_repo_label}"
        )
        local_line = (
            f"Local install impact: {local_preview.classification} "
            f"(new={local_preview.newer_apps}, same={local_preview.same_apps}, older={local_preview.older_apps})"
        )
        usb_line = "USB install impact: select a USB target."
        if usb_preview is not None:
            usb_line = (
                f"USB install impact: {usb_preview.classification} "
                f"(new={usb_preview.newer_apps}, same={usb_preview.same_apps}, older={usb_preview.older_apps})"
            )
        warning_lines: List[str] = []
        if local_preview.stale and local_preview.stale_reason:
            warning_lines.append(f"Local warning: {local_preview.stale_reason}")
        if usb_preview is not None and usb_preview.stale and usb_preview.stale_reason:
            warning_lines.append(f"USB warning: {usb_preview.stale_reason}")
        selected_text = ", ".join(selected_apps) if selected_apps else "none"
        warning_text = "\n".join(warning_lines) if warning_lines else "No stale/retractive warning detected."
        self.bootstrap_preview_var.set(
            f"Selected apps: {selected_text}\n{local_line}\n{usb_line}\n{warning_text}"
        )
        self._refresh_bootstrap_history_view(pkg, selected_apps)

    def _on_bootstrap_selection_changed(self, _event=None) -> None:
        pkg = self._selected_bootstrap_package()
        if pkg is not None:
            pkg_names = set(pkg.app_names)
            for app_name, var in self.bootstrap_app_vars.items():
                try:
                    var.set(app_name in pkg_names)  # type: ignore[union-attr]
                except Exception:
                    pass
        self._refresh_bootstrap_preview()
        self._update_action_states()

    def on_refresh_bootstrap_catalog(self) -> None:
        roots = self._bootstrap_search_roots()
        self.bootstrap_packages = discover_bootstrap_packages(roots)
        if self.bootstrap_packages:
            newest = self.bootstrap_packages[0]
            self.bootstrap_info_var.set(
                f"Bootstrap packages found: {len(self.bootstrap_packages)} | "
                f"newest={newest.bootstrap_id} ({_fmt_ts(newest.created_ts)}, {_fmt_bytes(newest.package_size)})."
            )
            self._append(
                f"[BOOTSTRAP] found {len(self.bootstrap_packages)} package(s); newest={newest.bootstrap_id}\n"
            )
        else:
            self.bootstrap_info_var.set(
                "Bootstrap packages found: 0. Create one from local source, then install to local or selected USB."
            )
            self._append("[BOOTSTRAP] no bootstrap packages detected in local/USB repos.\n")
        self._render_bootstrap_catalog()
        self._update_action_states()

    def on_build_bootstrap_from_source(self) -> None:
        selected_apps = [name for name, var in self.bootstrap_app_vars.items() if bool(var.get())]  # type: ignore[union-attr]
        if not selected_apps:
            self.messagebox.showinfo("No apps selected", "Select at least one app for bootstrap package creation.")
            return
        if not self.messagebox.askyesno(
            "Create bootstrap package",
            "Build a new bootstrap patch package from the local source repo using the selected apps?\n\n"
            f"Apps: {', '.join(selected_apps)}",
        ):
            return

        self._begin_busy("Creating bootstrap package from local source...")
        self._append("\n[BOOTSTRAP] building bootstrap package from local source...\n")

        def worker() -> None:
            ok = False
            try:
                ok, msg, package = build_bootstrap_package(
                    self.source_repo,
                    selected_apps=selected_apps,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda m=msg: self._append(f"[BOOTSTRAP] {m}\n"))
                if ok and package is not None:
                    self.root.after(
                        0,
                        lambda p=package: self._append(
                            f"[BOOTSTRAP] package id={p.bootstrap_id} size={_fmt_bytes(p.package_size)}\n"
                        ),
                    )
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[BOOTSTRAP][ERROR] build failed: {e}\n"))
            finally:
                self.root.after(0, self._finish_busy)
                self.root.after(0, self.on_refresh_bootstrap_catalog)
                self.root.after(
                    0,
                    lambda: self._set_status(
                        "Bootstrap package created." if ok else "Bootstrap package creation failed."
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _install_bootstrap_to_repo(self, dest_repo: Path, label: str) -> None:
        pkg = self._selected_bootstrap_package()
        if pkg is None:
            self.messagebox.showinfo("No bootstrap selected", "Select a bootstrap package first.")
            return
        selected_apps = self._selected_bootstrap_apps(pkg)
        if not selected_apps:
            self.messagebox.showinfo("No apps selected", "Select at least one app to install from this package.")
            return

        preview = preview_bootstrap_install(pkg, dest_repo, selected_apps)
        details = (
            f"Destination: {dest_repo}\n"
            f"Package: {pkg.bootstrap_id}\n"
            f"Created: {_fmt_ts(pkg.created_ts)}\n"
            f"Selected apps: {', '.join(selected_apps)}\n\n"
            f"Impact classification: {preview.classification}\n"
            f"Newer apps: {preview.newer_apps}\n"
            f"Same apps: {preview.same_apps}\n"
            f"Older apps: {preview.older_apps}\n"
        )
        if preview.stale and preview.stale_reason:
            details += f"\nWarning: {preview.stale_reason}\n"
        details += "\nA rollback snapshot will be created before files are replaced."
        if not self.messagebox.askyesno(f"Install bootstrap to {label}", details):
            return
        if preview.stale:
            if not self.messagebox.askyesno(
                "Confirm stale/retractive install",
                "This package appears older than current patch state for at least one app.\n\n"
                "Proceed anyway?",
            ):
                return

        self._begin_busy(f"Installing bootstrap to {label}...")
        self._append(f"\n[BOOTSTRAP] installing {pkg.bootstrap_id} -> {label} ({dest_repo})\n")

        def worker() -> None:
            ok = False
            try:
                ok, msg = apply_bootstrap_package_to_repo(
                    pkg,
                    dest_repo,
                    selected_apps=selected_apps,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda m=msg: self._append(f"[BOOTSTRAP] {m}\n"))
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[BOOTSTRAP][ERROR] install failed: {e}\n"))
            finally:
                self.root.after(0, self._finish_busy)
                self.root.after(0, self.refresh_targets)
                self.root.after(
                    0,
                    lambda: self._set_status(
                        f"Bootstrap install complete for {label}." if ok else f"Bootstrap install failed for {label}."
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def on_install_bootstrap_to_usb(self) -> None:
        target = self._selected_target()
        if target is None:
            self.messagebox.showinfo("No target", "Select a USB target repo first.")
            return
        media_ok, media_reason = is_expected_usb_bootstrap_media(target)
        if not media_ok:
            if not self.messagebox.askyesno(
                "USB media warning",
                "Selected USB media does not match expected bootstrap profile "
                "(exfat/fat32 and 40-80GB).\n\n"
                f"{media_reason}\n\n"
                "Install anyway?",
            ):
                return
        self._install_bootstrap_to_repo(target, "USB target")

    def on_install_bootstrap_to_local(self) -> None:
        self._install_bootstrap_to_repo(self.source_repo, "local source")

    def on_deploy_latest_bootstrap_both(self) -> None:
        target = self._selected_target()
        if target is None:
            self.messagebox.showerror("No USB target", "Select a USB target first.")
            return
        if not self.bootstrap_packages:
            self.on_refresh_bootstrap_catalog()
        if not self.bootstrap_packages:
            self.messagebox.showinfo(
                "No bootstraps found",
                "No bootstrap packages were discovered in local or USB catalogs.",
            )
            return

        pkg = self.bootstrap_packages[0]
        selected_apps = self._selected_bootstrap_apps(pkg)
        if not selected_apps:
            selected_apps = list(pkg.app_names)
        local_preview = preview_bootstrap_install(pkg, self.source_repo, selected_apps)
        usb_preview = preview_bootstrap_install(pkg, target, selected_apps)
        details = (
            f"Package: {pkg.bootstrap_id}\n"
            f"Created: {_fmt_ts(pkg.created_ts)}\n"
            f"Apps selected: {len(selected_apps)}\n\n"
            f"Local preview: {local_preview.classification} "
            f"(new={local_preview.newer_apps}, same={local_preview.same_apps}, older={local_preview.older_apps})\n"
            f"USB preview: {usb_preview.classification} "
            f"(new={usb_preview.newer_apps}, same={usb_preview.same_apps}, older={usb_preview.older_apps})\n\n"
            "Deploy newest bootstrap to both Local and selected USB now?"
        )
        if not self.messagebox.askyesno("Deploy newest bootstrap", details):
            return

        self._begin_busy("Deploying newest bootstrap to local and USB...")
        self._append(f"\n[BOOTSTRAP] deploying newest package {pkg.bootstrap_id} -> local + usb\n")

        def worker() -> None:
            overall_ok = True
            targets: List[Tuple[str, Path]] = [("LOCAL", self.source_repo), ("USB", target)]
            for label, dest in targets:
                if label == "USB":
                    media_ok, media_reason = is_expected_usb_bootstrap_media(dest)
                    self.root.after(0, lambda r=media_reason: self._append(f"[BOOTSTRAP][USB-CHECK] {r}\n"))
                    if not media_ok:
                        overall_ok = False
                        self.root.after(0, lambda: self._append("[BOOTSTRAP][WARN] USB deploy skipped: media profile mismatch.\n"))
                        continue
                preview = preview_bootstrap_install(pkg, dest, selected_apps)
                if preview.stale:
                    overall_ok = False
                    self.root.after(
                        0,
                        lambda l=label, s=preview.stale_reason: self._append(
                            f"[BOOTSTRAP][WARN] {l} stale/retractive blocked: {s}\n"
                        ),
                    )
                    continue
                ok, msg = apply_bootstrap_package_to_repo(
                    pkg,
                    dest,
                    selected_apps=selected_apps,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                if not ok:
                    overall_ok = False
                self.root.after(
                    0,
                    lambda l=label, o=ok, m=msg: self._append(
                        f"[BOOTSTRAP] {l} {'OK' if o else 'WARN'} {m}\n"
                    ),
                )

            self.root.after(0, self.on_refresh_bootstrap_catalog)
            self.root.after(0, self._refresh_bootstrap_preview)
            self.root.after(
                0,
                lambda: self._set_status(
                    "Newest bootstrap deployed to local + USB."
                    if overall_ok
                    else "Bootstrap deploy completed with warnings. Review log."
                ),
            )
            self.root.after(0, self._finish_busy)

        threading.Thread(target=worker, daemon=True).start()

    def _rollback_bootstrap_repo(self, dest_repo: Path, label: str) -> None:
        if not self.messagebox.askyesno(
            f"Rollback last bootstrap on {label}",
            f"Rollback the most recent bootstrap install on:\n{dest_repo}\n\n"
            "This restores the previous file snapshot and patch state ledger.",
        ):
            return
        self._begin_busy(f"Rolling back bootstrap on {label}...")
        self._append(f"\n[BOOTSTRAP] rollback requested on {label}: {dest_repo}\n")

        def worker() -> None:
            ok = False
            try:
                ok, msg = rollback_last_bootstrap_on_repo(
                    dest_repo,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda m=msg: self._append(f"[BOOTSTRAP] {m}\n"))
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[BOOTSTRAP][ERROR] rollback failed: {e}\n"))
            finally:
                self.root.after(0, self._finish_busy)
                self.root.after(0, self.refresh_targets)
                self.root.after(
                    0,
                    lambda: self._set_status(
                        f"Bootstrap rollback complete for {label}." if ok else f"Bootstrap rollback failed for {label}."
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def on_rollback_bootstrap_usb(self) -> None:
        target = self._selected_target()
        if target is None:
            self.messagebox.showinfo("No target", "Select a USB target repo first.")
            return
        self._rollback_bootstrap_repo(target, "USB target")

    def on_rollback_bootstrap_local(self) -> None:
        self._rollback_bootstrap_repo(self.source_repo, "local source")

    # ── Git-based patch detector / deployer ───────────────────────────────────

    def on_check_git_patches(self) -> None:
        """Scan the local repo git log and populate the git-patch commit list."""
        self._begin_busy("Scanning git log for recent commits…")
        self._append("\n[GIT-PATCH] Scanning recent commits…\n")

        def worker() -> None:
            try:
                commits = detect_git_patches(self.source_repo, max_count=30)
            except Exception as exc:
                commits = []
                self.root.after(0, lambda: self._append(f"[GIT-PATCH][ERROR] {exc}\n"))

            def update() -> None:
                self.git_commits = commits
                if self.git_patch_listbox is not None:
                    self.git_patch_listbox.delete(0, "end")
                    for c in commits:
                        label = (
                            f"[{c['short_hash']}]  {c['date_iso'][:10]}  "
                            f"{c['subject'][:56]}  ({c['file_count']} file(s))"
                        )
                        self.git_patch_listbox.insert("end", label)
                    if commits:
                        self.git_patch_listbox.selection_clear(0, "end")
                        self.git_patch_listbox.selection_set(0)
                n = len(commits)
                self.git_patch_status_var.set(
                    f"Found {n} commit(s). Select one or more, then choose an action below."
                    if n > 0 else "No git commits found. Is this a git repo with commit history?"
                )
                self._append(f"[GIT-PATCH] {n} commit(s) detected.\n")
                self._finish_busy()
                self._set_status(f"Git patch: {n} commit(s) detected." if n > 0 else "No git commits found.")

            self.root.after(0, update)

        threading.Thread(target=worker, daemon=True).start()

    def _selected_git_commit_hashes(self) -> List[str]:
        """Return hashes for listbox-selected commits (all commits if none selected)."""
        if self.git_patch_listbox is None or not self.git_commits:
            return []
        sel = list(self.git_patch_listbox.curselection())
        if not sel:
            sel = list(range(len(self.git_commits)))
        return [self.git_commits[i]["hash"] for i in sel if i < len(self.git_commits)]

    def on_build_git_patch(self) -> None:
        """Package selected commits as a patch ZIP without applying it."""
        hashes = self._selected_git_commit_hashes()
        if not hashes:
            self.messagebox.showinfo(
                "No commits selected",
                "Click 'Detect Recent Commits' first, then select commits to package.",
            )
            return
        self._begin_busy(f"Packaging {len(hashes)} commit(s) as patch ZIP…")
        self._append(f"\n[GIT-PATCH] packaging {len(hashes)} commit(s)…\n")

        def worker() -> None:
            ok = False
            try:
                ok, msg, pkg = build_git_patch_from_commits(
                    self.source_repo, hashes,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda m=msg: self._append(f"[GIT-PATCH] {m}\n"))
                if ok:
                    self.root.after(0, self.on_refresh_bootstrap_catalog)
            except Exception as exc:
                self.root.after(0, lambda: self._append(f"[GIT-PATCH][ERROR] {exc}\n"))
            finally:
                self.root.after(0, self._finish_busy)
                self.root.after(
                    0,
                    lambda: self._set_status(
                        "Git patch ZIP created — ready to install." if ok else "Git patch creation failed."
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _git_patch_build_and_apply(self, targets: List[str]) -> None:
        """
        Build a git patch from selected commits and apply it to the given targets.
        targets: list of "local" | "usb"
        Creates a rollback snapshot on each target before applying.
        """
        hashes = self._selected_git_commit_hashes()
        if not hashes:
            self.messagebox.showinfo(
                "No commits selected",
                "Click 'Detect Recent Commits' first, then select commits.",
            )
            return
        target_labels = ", ".join(t.upper() for t in targets)
        if not self.messagebox.askyesno(
            "Apply Git Patch",
            f"Build a patch from {len(hashes)} commit(s) and apply to: {target_labels}?\n\n"
            "A rollback snapshot is automatically created on each target before applying.\n"
            "Use 'Rollback Last on USB/Local' to undo if needed.",
        ):
            return
        self._begin_busy(f"Packaging + applying git patch to {target_labels}…")
        self._append(f"\n[GIT-PATCH] build+apply → {target_labels}: {len(hashes)} commit(s)\n")

        def worker() -> None:
            ok = False
            try:
                ok, msg, pkg = build_git_patch_from_commits(
                    self.source_repo, hashes,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda m=msg: self._append(f"[GIT-PATCH] build: {m}\n"))
                if not ok or pkg is None:
                    return

                for target_label in targets:
                    dest_repo: Optional[Path] = None
                    if target_label == "local":
                        dest_repo = self.source_repo
                    elif target_label == "usb":
                        tgt = self._selected_target()
                        if tgt is None:
                            self.root.after(
                                0,
                                lambda: self._append("[GIT-PATCH][WARN] No USB target selected — skipping USB.\n"),
                            )
                            continue
                        dest_repo = tgt.path
                    if dest_repo is None:
                        continue
                    self.root.after(0, lambda lbl=target_label: self._append(f"[GIT-PATCH] applying to {lbl}…\n"))
                    apply_ok, apply_msg = apply_bootstrap_package_to_repo(
                        pkg,
                        dest_repo,
                        log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                    )
                    status_tag = "OK" if apply_ok else "FAIL"
                    self.root.after(
                        0,
                        lambda m=apply_msg, s=status_tag: self._append(f"[GIT-PATCH][{s}] {m}\n"),
                    )
            except Exception as exc:
                self.root.after(0, lambda: self._append(f"[GIT-PATCH][ERROR] {exc}\n"))
                ok = False
            finally:
                self.root.after(0, self._finish_busy)
                self.root.after(0, self.refresh_targets)
                self.root.after(0, self.on_refresh_bootstrap_catalog)
                self.root.after(
                    0,
                    lambda: self._set_status(
                        f"Git patch applied to {target_labels}." if ok else "Git patch failed — check log."
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def on_git_patch_apply_usb(self) -> None:
        self._git_patch_build_and_apply(["usb"])

    def on_git_patch_apply_local(self) -> None:
        self._git_patch_build_and_apply(["local"])

    def on_git_patch_apply_both(self) -> None:
        self._git_patch_build_and_apply(["local", "usb"])

    # ── GitHub sync methods ───────────────────────────────────────────────────

    def _git_repo_root_for_app(self, app: dict) -> Optional[Path]:
        src = self._app_source_root(app)
        return _find_git_root(src)

    def _collect_git_statuses_inline(self) -> Dict[str, Dict]:
        statuses: Dict[str, Dict] = {}
        for app in CITL_APPS:
            try:
                root = self._git_repo_root_for_app(app)
                if root is None:
                    statuses[app["name"]] = {"error": "No git repo found"}
                else:
                    statuses[app["name"]] = git_status_for_repo(root)
            except Exception as exc:
                statuses[app["name"]] = {"error": f"Status failed: {exc}"}
        self._git_statuses = statuses
        return statuses

    def _get_or_refresh_git_status_for_app(self, app: dict) -> Dict:
        st = self._git_statuses.get(app["name"])
        if st:
            return st
        root = self._git_repo_root_for_app(app)
        if root is None:
            st = {"error": "No git repo found"}
        else:
            try:
                st = git_status_for_repo(root)
            except Exception as exc:
                st = {"error": f"Status failed: {exc}"}
        self._git_statuses[app["name"]] = st
        return st

    def _refresh_git_statuses(self) -> None:
        """Fetch git status for all apps in a background thread, then re-render."""
        self._set_status("Fetching git status from GitHub...")
        self._append("\n[GITHUB] Refresh Git Status requested.\n")

        def worker():
            statuses: Dict[str, Dict] = {}
            accounts: List[Dict[str, str]] = []
            user_name, user_email = "", ""

            try:
                rc, u, _ = _git_run(self.source_repo, "config", "user.name")
                if rc == 0:
                    user_name = u
                rc, e, _ = _git_run(self.source_repo, "config", "user.email")
                if rc == 0:
                    user_email = e
            except Exception:
                pass

            try:
                accounts = self._detect_git_accounts()
            except Exception as e:
                self.root.after(0, lambda t=str(e): self._append(f"[GIT][WARN] account scan failed: {t}\n"))

            for app in CITL_APPS:
                self.root.after(0, lambda n=app["name"]: self._append(f"[GITHUB] checking {n}...\n"))
                try:
                    root = self._git_repo_root_for_app(app)
                    if root:
                        statuses[app["name"]] = git_status_for_repo(root)
                    else:
                        statuses[app["name"]] = {"error": "No git repo found"}
                except Exception as e:
                    statuses[app["name"]] = {"error": f"Status failed: {e}"}

            self.root.after(0, lambda: self._apply_git_statuses(statuses, user_name, user_email, accounts))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_git_statuses(
        self,
        statuses: Dict[str, Dict],
        user_name: str,
        user_email: str,
        accounts: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        self._git_statuses = statuses
        self._git_accounts = list(accounts or [])

        if self._git_accounts:
            if len(self._git_accounts) == 1:
                a = self._git_accounts[0]
                self.gh_user_var.set(f"Logged in as: {a['name']} <{a['email']}>")
                self.gh_auth_var.set("")
            else:
                first = self._git_accounts[0]
                self.gh_user_var.set(
                    f"Logged in as: {first['name']} <{first['email']}> (+{len(self._git_accounts) - 1} more)"
                )
                self.gh_auth_var.set(
                    "Multiple Git identities detected. Click 'Check Git Auth' to choose repo-local identity."
                )
        elif user_name:
            self.gh_user_var.set(f"Logged in as: {user_name} <{user_email}>")
            self.gh_auth_var.set("")
        else:
            self.gh_user_var.set("Logged in as: (no git identity detected)")

        self._render_github_panel()
        self._set_status("Git status refreshed.")

    def _render_github_panel(self) -> None:
        """Render one column per CITL app showing git branch, ahead/behind, dirty state."""
        for w in self.gh_apps_frame.winfo_children():
            w.destroy()

        if not self._git_statuses:
            self._make_label(
                self.gh_apps_frame,
                text="Click 'Refresh Git Status' to load.",
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                font=("Segoe UI", 10),
            ).grid(row=0, column=0, sticky="w", padx=8)
            return

        ordered_apps = self._ordered_apps_for_overview()
        cols = len(ordered_apps)
        for c in range(cols):
            self.gh_apps_frame.grid_columnconfigure(c, weight=1, uniform="ghcol")

        for idx, app in enumerate(ordered_apps):
            st = self._git_statuses.get(app["name"]) or {}
            err = st.get("error")
            bg = self.colors["card"]

            frame = self.tk.Frame(
                self.gh_apps_frame,
                bg=bg,
                highlightthickness=1,
                highlightbackground=self.colors["border"],
                padx=12, pady=10,
            )
            frame.grid(row=0, column=idx, sticky="nsew", padx=6, pady=4)
            frame.grid_columnconfigure(0, weight=1)

            # App name
            self._make_label(frame,
                text=f"{app['icon']} {app['name']}",
                bg=bg, fg=self.colors["accent"],
                font=("Segoe UI Semibold", 11, "bold"), wraplength=210,
            ).grid(row=0, column=0, sticky="w")

            if err:
                self._make_label(frame, text=err, bg=bg, fg=self.colors["danger"],
                    font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(4, 0))
                continue

            branch = st.get("branch", "?")
            ahead  = int(st.get("ahead", 0))
            behind = int(st.get("behind", 0))
            dirty  = bool(st.get("dirty", False))
            last   = st.get("last_commit", "")
            remote_url = st.get("remote_url", "")

            # Remote URL (shortened)
            short_url = re.sub(r"https://github\.com/", "github: ", remote_url)
            self._make_label(frame, text=short_url, bg=bg, fg=self.colors["muted"],
                font=("Consolas", 8), wraplength=210,
            ).grid(row=1, column=0, sticky="w", pady=(3, 0))

            # Branch + sync state
            if ahead > 0 and behind == 0:
                sync_text = f"branch:{branch}  AHEAD {ahead}  ← push needed"
                sync_color = self.colors["warn"]
            elif behind > 0 and ahead == 0:
                sync_text = f"branch:{branch}  BEHIND {behind}  ← pull available"
                sync_color = self.colors["accent"]
            elif ahead > 0 and behind > 0:
                sync_text = f"branch:{branch}  DIVERGED +{ahead}/-{behind}  ← review"
                sync_color = self.colors["danger"]
            else:
                sync_text = f"branch:{branch}  Up to date"
                sync_color = self.colors["good"]

            if dirty:
                sync_text += "  [uncommitted changes]"

            self._make_label(frame, text=sync_text, bg=bg, fg=sync_color,
                font=("Segoe UI Semibold", 10, "bold"), wraplength=210,
            ).grid(row=2, column=0, sticky="w", pady=(6, 0))

            # Last commit
            if last:
                self._make_label(frame, text=last, bg=bg, fg=self.colors["muted"],
                    font=("Consolas", 8), wraplength=210,
                ).grid(row=3, column=0, sticky="w", pady=(4, 0))

            # Push / Pull buttons
            btn_row = self.tk.Frame(frame, bg=bg)
            btn_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))

            can_push = dirty or ahead > 0
            can_pull = behind > 0

            push_btn = self.tk.Button(btn_row,
                text="Push to GitHub",
                command=lambda a=app: self._on_git_push_app(a),
                bg=self.colors["warn"] if can_push else self.colors["button"],
                fg=self.colors["bg"] if can_push else self.colors["muted"],
                activebackground=self.colors["accent_active"],
                activeforeground=self.colors["bg"],
                relief="flat", bd=0, padx=8, pady=5,
                cursor="hand2", font=("Segoe UI Semibold", 10),
            )
            push_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            btn_row.grid_columnconfigure(0, weight=1)

            pull_btn = self.tk.Button(btn_row,
                text="Pull from GitHub",
                command=lambda a=app: self._on_git_pull_app(a),
                bg=self.colors["accent"] if can_pull else self.colors["button"],
                fg=self.colors["bg"] if can_pull else self.colors["muted"],
                activebackground=self.colors["accent_active"],
                activeforeground=self.colors["bg"],
                relief="flat", bd=0, padx=8, pady=5,
                cursor="hand2", font=("Segoe UI Semibold", 10),
            )
            pull_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))
            btn_row.grid_columnconfigure(1, weight=1)

    def _detect_git_accounts(self) -> List[Dict[str, str]]:
        """
        Scan the device for git identities already configured.
        Returns a list of dicts: [{name, email, source}, ...]
        Sources checked (in order): local repo config, global config, gh CLI, SSH config.
        Deduplicates by email when possible.
        """
        accounts: List[Dict[str, str]] = []
        seen_keys: set = set()

        def _add(name: str, email: str, source: str) -> None:
            e = (email or "").strip().lower()
            n = (name or "").strip()
            if not n and not e:
                return
            if not e and n:
                e = f"{n.lower()}@users.noreply.github.com"
            key = e or f"{source}:{n.lower()}"
            if key in seen_keys:
                return
            seen_keys.add(key)
            accounts.append({"name": n or e.split("@")[0], "email": e, "source": source})

        def _owner_from_remote(remote_url: str) -> str:
            raw = (remote_url or "").strip()
            if not raw:
                return ""
            m = re.search(r"github\.com[:/]+([^/]+)/", raw, re.IGNORECASE)
            if m:
                return m.group(1).strip()
            return ""

        # 1. Repo-local config (highest priority)
        rc, n, _ = _git_run(self.source_repo, "config", "--local", "user.name")
        rc2, e, _ = _git_run(self.source_repo, "config", "--local", "user.email")
        if rc == 0 and rc2 == 0 and e.strip():
            _add(n, e, "repo-local")

        # 1b. Repo-local config from all app repos (can differ per app/repo)
        for app in CITL_APPS:
            root = self._git_repo_root_for_app(app)
            if not root:
                continue
            rc, n, _ = _git_run(root, "config", "--local", "user.name")
            rc2, e, _ = _git_run(root, "config", "--local", "user.email")
            if rc == 0 and rc2 == 0 and (n.strip() or e.strip()):
                _add(n, e, f"repo-local:{app['name']}")
            rc3, remote_url, _ = _git_run(root, "remote", "get-url", "origin")
            if rc3 == 0 and remote_url.strip():
                owner = _owner_from_remote(remote_url)
                if owner:
                    _add(owner, f"{owner}@users.noreply.github.com", f"origin-owner:{app['name']}")

        # 2. Global git config
        rc, n, _ = _git_run(self.source_repo, "config", "--global", "user.name")
        rc2, e, _ = _git_run(self.source_repo, "config", "--global", "user.email")
        if rc == 0 and rc2 == 0 and e.strip():
            _add(n, e, "git-global")

        # 3. GitHub CLI identities
        try:
            result = subprocess.run(
                ["gh", "auth", "status", "-h", "github.com"],
                capture_output=True, text=True, timeout=6,
            )
            combined = (result.stdout or "") + (result.stderr or "")
            for m in re.finditer(r"Logged in to github\.com.*?as\s+([^\s]+)", combined, re.IGNORECASE):
                gh_user = m.group(1).strip()
                _add(gh_user, f"{gh_user}@users.noreply.github.com", "gh-cli")
            for m in re.finditer(r"github\.com\s+account\s+([^\s]+)", combined, re.IGNORECASE):
                gh_user = m.group(1).strip()
                _add(gh_user, f"{gh_user}@users.noreply.github.com", "gh-cli")
        except Exception:
            pass

        # 4. Windows Credential Manager entries for github.com
        if os.name == "nt":
            try:
                cred = subprocess.run(
                    ["cmdkey", "/list"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                ctext = (cred.stdout or "") + (cred.stderr or "")
                for m in re.finditer(r"git:https://([^@\s]+)@github\.com", ctext, re.IGNORECASE):
                    user = m.group(1).strip()
                    _add(user, f"{user}@users.noreply.github.com", "win-credential-manager")
            except Exception:
                pass

        # 5. Multiple identities in SSH config (~/.ssh/config  Host github-*)
        ssh_conf = Path.home() / ".ssh" / "config"
        if ssh_conf.exists():
            try:
                txt = ssh_conf.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r"Host\s+(github[^\n]+)", txt, re.IGNORECASE):
                    host_alias = m.group(1).strip()
                    if host_alias.lower() != "github.com":
                        # Extract identity comment if present
                        block_start = m.start()
                        block = txt[block_start:block_start + 300]
                        id_m = re.search(r"IdentityFile\s+(\S+)", block, re.IGNORECASE)
                        if id_m:
                            key_path = Path(id_m.group(1).replace("~", str(Path.home())))
                            pub = key_path.with_suffix(".pub")
                            if pub.exists():
                                pub_text = pub.read_text(encoding="utf-8", errors="ignore").strip()
                                comment = pub_text.split()[-1] if pub_text.split() else ""
                                if "@" in comment:
                                    _add(host_alias, comment, f"ssh-config({host_alias})")
            except Exception:
                pass

        # 6. SSH public key comments often include account email.
        ssh_dir = Path.home() / ".ssh"
        if ssh_dir.exists():
            try:
                for pub in ssh_dir.glob("*.pub"):
                    try:
                        text = pub.read_text(encoding="utf-8", errors="ignore").strip()
                    except Exception:
                        continue
                    parts = text.split()
                    if not parts:
                        continue
                    comment = parts[-1]
                    if "@" in comment:
                        _add(pub.stem, comment, f"ssh-key:{pub.name}")
            except Exception:
                pass

        return accounts

    def _check_git_auth(self) -> None:
        """Detect all git accounts on this device; if multiple, offer account selection."""
        self._set_status("Detecting git accounts...")
        self._append("\n[GITHUB] Check Git Auth requested.\n")

        def worker():
            accounts = self._detect_git_accounts()

            if not accounts:
                self.root.after(0, lambda: (
                    self.gh_auth_var.set("No git account detected on this device"),
                    self._set_status("No git identity found."),
                    self._append("\n[GIT] No git user.name/email configured on this device.\n"
                                 "Run: git config --global user.name 'Your Name'\n"
                                 "     git config --global user.email 'you@example.com'\n"),
                ))
                return

            if len(accounts) == 1:
                a = accounts[0]
                label = f"{a['name']} <{a['email']}> [{a['source']}]"
                self.root.after(0, lambda: (
                    self.gh_user_var.set(f"Account: {label}"),
                    self.gh_auth_var.set(""),
                    self._set_status(f"Using: {label}"),
                    self._append(f"\n[GIT] Active account: {label}\n"),
                ))
            else:
                # Multiple accounts — let user pick
                self.root.after(0, lambda: self._prompt_account_selection(accounts))

        threading.Thread(target=worker, daemon=True).start()

    def _prompt_account_selection(self, accounts: List[Dict[str, str]]) -> None:
        """Show a simple dialog to pick which git identity to use for this repo."""
        import tkinter as _tk

        dlg = _tk.Toplevel(self.root)
        dlg.title("Select GitHub Account")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(bg=self.colors["bg"])

        _tk.Label(dlg, text="Multiple git accounts detected.\nSelect which to use for this repo:",
                  bg=self.colors["bg"], fg=self.colors["text"],
                  font=("Segoe UI", 11), justify="left").pack(padx=20, pady=(16, 8))

        choice_var = _tk.StringVar()
        options = [f"{a['name']} <{a['email']}> [{a['source']}]" for a in accounts]
        choice_var.set(options[0])

        for opt in options:
            _tk.Radiobutton(
                dlg, text=opt, variable=choice_var, value=opt,
                bg=self.colors["bg"], fg=self.colors["text"],
                selectcolor=self.colors["card"],
                activebackground=self.colors["bg"],
                font=("Segoe UI", 10),
            ).pack(anchor="w", padx=24, pady=2)

        def _apply_identity(name: str, email: str, chosen_label: str) -> None:
            # Write repo-local config across all detected app repos so Push/Pull uses
            # the selected identity consistently.
            roots: Dict[str, Path] = {}
            src_root = _find_git_root(self.source_repo)
            if src_root:
                roots[str(src_root)] = src_root
            for app in CITL_APPS:
                r = self._git_repo_root_for_app(app)
                if r:
                    roots[str(r)] = r
            for r in roots.values():
                _git_run(r, "config", "--local", "user.name", name)
                _git_run(r, "config", "--local", "user.email", email)
            self.gh_user_var.set(f"Account: {chosen_label}")
            self.gh_auth_var.set("")
            self._set_status(f"Account set to: {name} <{email}> across {len(roots)} repo(s)")
            self._append(
                f"\n[GIT] Account set (repo-local across {len(roots)} repos): {chosen_label}\n"
            )
            dlg.destroy()

        def _apply():
            chosen = choice_var.get()
            idx = options.index(chosen)
            a = accounts[idx]
            _apply_identity(a["name"], a["email"], chosen)

        def _manual():
            from tkinter import simpledialog

            name = simpledialog.askstring("Manual Git Name", "Enter git user.name:", parent=dlg)
            if name is None:
                return
            name = name.strip()
            if not name:
                self.messagebox.showerror("Invalid name", "git user.name cannot be blank.", parent=dlg)
                return

            email = simpledialog.askstring("Manual Git Email", "Enter git user.email:", parent=dlg)
            if email is None:
                return
            email = email.strip().lower()
            if "@" not in email:
                self.messagebox.showerror("Invalid email", "Enter a valid email address.", parent=dlg)
                return

            label = f"{name} <{email}> [manual]"
            _apply_identity(name, email, label)

        btn_row = _tk.Frame(dlg, bg=self.colors["bg"])
        btn_row.pack(pady=(12, 16))
        self._make_button(btn_row, "Use This Account", _apply, accent=True).pack(side="left", padx=8)
        self._make_button(btn_row, "Use Manual...", _manual).pack(side="left", padx=8)
        self._make_button(btn_row, "Cancel", dlg.destroy).pack(side="left")

    def _open_github_web(self) -> None:
        """Open the GitHub remote URL in the default browser."""
        rc, url, _ = _git_run(self.source_repo, "remote", "get-url", "origin")
        if rc == 0 and url:
            web_url = url.strip()
            if web_url.startswith("git@"):
                # Convert SSH to HTTPS
                web_url = re.sub(r"^git@github\.com:", "https://github.com/", web_url)
                web_url = re.sub(r"\.git$", "", web_url)
            elif web_url.endswith(".git"):
                web_url = web_url[:-4]
            import webbrowser
            webbrowser.open(web_url)
        else:
            self.messagebox.showinfo("No remote", "No 'origin' remote URL configured for this repo.")

    def _on_git_push_app(self, app: dict) -> None:
        root = self._git_repo_root_for_app(app)
        if root is None:
            self.messagebox.showerror("No git repo", f"{app['name']}: no git repo found.")
            return
        self._begin_busy(f"Pushing {app['name']} to GitHub...")
        self._append(f"\n[GITHUB] Pushing {app['name']} ({root})...\n")

        def worker():
            ok, msg = git_commit_and_push(
                root,
                log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
            )
            self.root.after(0, lambda: self._append(
                f"[GITHUB] {'OK' if ok else 'FAILED'}: {msg}\n"
            ))
            self.root.after(0, lambda: self._set_status(
                f"{app['name']} push {'complete' if ok else 'failed'}."
            ))
            self.root.after(0, self._refresh_git_statuses)
            self.root.after(0, self._end_busy)

        threading.Thread(target=worker, daemon=True).start()

    def _on_git_pull_app(self, app: dict) -> None:
        root = self._git_repo_root_for_app(app)
        if root is None:
            self.messagebox.showerror("No git repo", f"{app['name']}: no git repo found.")
            return
        st = self._get_or_refresh_git_status_for_app(app)
        if int(st.get("behind", 0)) == 0 and not self.messagebox.askyesno(
            "Confirm pull",
            f"{app['name']} is not behind the remote.\nPull anyway?"
        ):
            return
        self._begin_busy(f"Pulling {app['name']} from GitHub...")
        self._append(f"\n[GITHUB] Pulling {app['name']} ({root})...\n")

        def worker():
            ok, msg = git_pull_repo(
                root,
                log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
            )
            self.root.after(0, lambda: self._append(
                f"[GITHUB] {'OK' if ok else 'FAILED'}: {msg}\n"
            ))
            self.root.after(0, lambda: self._set_status(
                f"{app['name']} pull {'complete' if ok else 'failed'}."
            ))
            self.root.after(0, self._refresh_git_statuses)
            self.root.after(0, self._end_busy)

        threading.Thread(target=worker, daemon=True).start()

    def on_git_push_all(self) -> None:
        """Push all apps that are dirty or ahead of remote."""
        self._append("\n[GITHUB] Push All Updated requested.\n")
        statuses = dict(self._git_statuses or {})
        if not statuses:
            self._append("[GITHUB] No cached status yet. Refreshing now...\n")
            self._refresh_git_statuses()
            self.messagebox.showinfo(
                "Git status refreshing",
                "Git status is being refreshed now. Click 'Push All Updated' again in a moment."
            )
            return
        to_push = [
            app for app in CITL_APPS
            if (statuses.get(app["name"]) or {}).get("dirty")
            or int((statuses.get(app["name"]) or {}).get("ahead", 0)) > 0
        ]
        if not to_push:
            self.messagebox.showinfo(
                "Nothing to push",
                "All repos are up to date with GitHub. No push needed."
            )
            return

        names = "\n".join(f"  • {a['name']}" for a in to_push)
        if not self.messagebox.askyesno(
            "Push All",
            f"Push {len(to_push)} repo(s) to GitHub?\n\n{names}\n\n"
            "A backup zip will be created for each before pushing."
        ):
            return

        self._begin_busy(f"Pushing {len(to_push)} repos to GitHub...")

        def worker():
            for app in to_push:
                root = self._git_repo_root_for_app(app)
                if root is None:
                    self.root.after(0, lambda n=app["name"]: self._append(
                        f"[GITHUB] Skipping {n}: no git repo\n"
                    ))
                    continue
                self.root.after(0, lambda n=app["name"]: self._append(
                    f"\n[GITHUB] Pushing {n}...\n"
                ))
                ok, msg = git_commit_and_push(
                    root,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda n=app["name"], o=ok, m=msg: self._append(
                    f"[GITHUB] {n}: {'OK' if o else 'FAILED'} — {m}\n"
                ))

            self.root.after(0, self._refresh_git_statuses)
            self.root.after(0, self._end_busy)
            self.root.after(0, lambda: self._set_status("Push all complete."))

        threading.Thread(target=worker, daemon=True).start()

    def on_git_pull_all_newer(self) -> None:
        """Pull all apps where remote has newer commits."""
        self._append("\n[GITHUB] Pull All Newer requested.\n")
        statuses = dict(self._git_statuses or {})
        if not statuses:
            self._append("[GITHUB] No cached status yet. Refreshing now...\n")
            self._refresh_git_statuses()
            self.messagebox.showinfo(
                "Git status refreshing",
                "Git status is being refreshed now. Click 'Pull All Newer' again in a moment."
            )
            return
        to_pull = [
            app for app in CITL_APPS
            if int((statuses.get(app["name"]) or {}).get("behind", 0)) > 0
        ]
        if not to_pull:
            self.messagebox.showinfo(
                "Already up to date",
                "No repos are behind their remote. Nothing to pull."
            )
            return

        names = "\n".join(f"  • {a['name']}" for a in to_pull)
        if not self.messagebox.askyesno(
            "Pull All Newer",
            f"Pull {len(to_pull)} repo(s) that are behind GitHub?\n\n{names}\n\n"
            "A backup zip will be created for each before pulling."
        ):
            return

        self._begin_busy(f"Pulling {len(to_pull)} repos from GitHub...")

        def worker():
            for app in to_pull:
                root = self._git_repo_root_for_app(app)
                if root is None:
                    continue
                self.root.after(0, lambda n=app["name"]: self._append(
                    f"\n[GITHUB] Pulling {n}...\n"
                ))
                ok, msg = git_pull_repo(
                    root,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda n=app["name"], o=ok, m=msg: self._append(
                    f"[GITHUB] {n}: {'OK' if o else 'FAILED'} — {m}\n"
                ))

            self.root.after(0, self._refresh_git_statuses)
            self.root.after(0, self._end_busy)
            self.root.after(0, lambda: self._set_status("Pull all newer complete."))

        threading.Thread(target=worker, daemon=True).start()

    def _app_usb_comparison(self, app: dict) -> Tuple[str, str]:
        """
        Compare key app files between source repo and primary USB target.
        Returns (status_text, color).
        """
        target = self._selected_target() or (self.targets[0].path if self.targets else None)
        src_root = self._app_source_root(app)

        if target is None:
            return "No USB target detected", self.colors["muted"]

        # Apps with their own separate repo that isn't synced to USB yet
        if src_root != self.source_repo and not (target / app.get("repo_marker", "NOMATCH")).exists():
            return f"Separate repo — not in USB copy ({src_root.name})", self.colors["muted"]

        key_files = app.get("key_files") or []
        newer_on_pc = 0
        newer_on_usb = 0
        missing_on_usb = 0
        for rel in key_files:
            src_p = src_root / rel
            dst_p = target / rel
            if not src_p.exists():
                continue
            if not dst_p.exists():
                missing_on_usb += 1
                continue
            try:
                delta = src_p.stat().st_mtime - dst_p.stat().st_mtime
                if delta > UPDATE_AVAILABLE_EPSILON_SEC:
                    newer_on_pc += 1
                elif delta < -UPDATE_AVAILABLE_EPSILON_SEC:
                    newer_on_usb += 1
            except Exception:
                pass

        if missing_on_usb > 0 or newer_on_pc > 0:
            parts = []
            if newer_on_pc:
                parts.append(f"{newer_on_pc} file(s) newer on PC")
            if missing_on_usb:
                parts.append(f"{missing_on_usb} file(s) not on USB")
            return f"USB needs update: {', '.join(parts)}", self.colors["warn"]
        if newer_on_usb > 0:
            return f"USB is ahead ({newer_on_usb} file(s))", self.colors["accent"]
        if key_files:
            return "USB in sync", self.colors["good"]
        return "No key files tracked", self.colors["muted"]

    def _on_sync_app_files(self, app: dict) -> None:
        """Sync only the key files for a specific app to the primary USB target."""
        target = self._selected_target() or (self.targets[0].path if self.targets else None)
        if target is None:
            self.messagebox.showinfo("No Target", "No USB target detected. Refresh first.")
            return

        key_files = app.get("key_files") or []
        if not key_files:
            self.messagebox.showinfo("Nothing to sync", f"{app['name']} has no tracked key files.")
            return

        app_name = app["name"]
        src_root = self._app_source_root(app)
        self._append(f"\n[APP-SYNC] Syncing {app_name} from {src_root.name} to {target}\n")

        def worker() -> None:
            copied = 0
            errors = 0
            for rel in key_files:
                src_p = src_root / rel
                dst_p = target / rel
                if not src_p.exists():
                    continue
                try:
                    if src_p.is_dir():
                        local_copied = 0
                        for child in src_p.rglob("*"):
                            if not child.is_file():
                                continue
                            rel_child = child.relative_to(src_p)
                            dst_child = dst_p / rel_child
                            dst_child.parent.mkdir(parents=True, exist_ok=True)
                            if _needs_copy(child, dst_child):
                                shutil.copy2(str(child), str(dst_child))
                                local_copied += 1
                        if local_copied:
                            copied += local_copied
                            self.root.after(
                                0,
                                lambda r=rel, n=local_copied: self._append(
                                    f"  copied: {r} ({n} files)\n"
                                ),
                            )
                    else:
                        dst_p.parent.mkdir(parents=True, exist_ok=True)
                        if _needs_copy(src_p, dst_p):
                            shutil.copy2(str(src_p), str(dst_p))
                            copied += 1
                            self.root.after(0, lambda r=rel: self._append(f"  copied: {r}\n"))
                except Exception as e:
                    errors += 1
                    self.root.after(0, lambda r=rel, ex=e: self._append(f"  error: {r} — {ex}\n"))

            # Also run Ubuntu port on target after app-level sync
            try:
                port_to_ubuntu(target)
            except Exception:
                pass

            self.root.after(0, lambda: self._append(
                f"[APP-SYNC] {app_name} done — copied={copied} errors={errors}\n"
            ))
            self.root.after(0, self._render_apps_overview)
            self.root.after(0, self._refresh_sync_app_selection_meta)

        threading.Thread(target=worker, daemon=True).start()

    def _on_pull_app_files(self, app: dict) -> None:
        """Pull only the key files for a specific app from selected USB target to local source."""
        target = self._selected_target() or (self.targets[0].path if self.targets else None)
        if target is None:
            self.messagebox.showinfo("No Target", "No USB target detected. Refresh first.")
            return

        key_files = app.get("key_files") or []
        if not key_files:
            self.messagebox.showinfo("Nothing to pull", f"{app['name']} has no tracked key files.")
            return

        app_name = str(app.get("name") or "App")
        dst_root = self._app_source_root(app)
        if not self.messagebox.askyesno(
            "Confirm app pull",
            f"Pull USB -> PC for {app_name}?\n\nFrom:\n{target}\n\nTo:\n{dst_root}",
        ):
            return

        self._append(f"\n[APP-PULL] Pulling {app_name} from {target} to {dst_root}\n")

        def worker() -> None:
            copied = 0
            skipped = 0
            missing = 0
            errors = 0
            for rel in key_files:
                src_p = target / rel
                dst_p = dst_root / rel
                if not src_p.exists():
                    missing += 1
                    continue
                try:
                    if src_p.is_dir():
                        local_copied = 0
                        local_skipped = 0
                        for child in src_p.rglob("*"):
                            if not child.is_file():
                                continue
                            rel_child = child.relative_to(src_p)
                            dst_child = dst_p / rel_child
                            dst_child.parent.mkdir(parents=True, exist_ok=True)
                            if _needs_copy(child, dst_child):
                                shutil.copy2(str(child), str(dst_child))
                                local_copied += 1
                            else:
                                local_skipped += 1
                        copied += local_copied
                        skipped += local_skipped
                        if local_copied:
                            self.root.after(
                                0,
                                lambda r=rel, n=local_copied: self._append(
                                    f"  pulled: {r} ({n} files)\n"
                                ),
                            )
                    else:
                        dst_p.parent.mkdir(parents=True, exist_ok=True)
                        if _needs_copy(src_p, dst_p):
                            shutil.copy2(str(src_p), str(dst_p))
                            copied += 1
                            self.root.after(0, lambda r=rel: self._append(f"  pulled: {r}\n"))
                        else:
                            skipped += 1
                except Exception as e:
                    errors += 1
                    self.root.after(0, lambda r=rel, ex=e: self._append(f"  error: {r} — {ex}\n"))

            self.root.after(
                0,
                lambda: self._append(
                    f"[APP-PULL] {app_name} done — copied={copied} skipped={skipped} "
                    f"missing={missing} errors={errors}\n"
                ),
            )
            self.root.after(0, self._render_apps_overview)
            self.root.after(0, self._refresh_sync_app_selection_meta)

        threading.Thread(target=worker, daemon=True).start()

    def _render_apps_overview(self) -> None:
        """Render app cards with pinned priority and most-recently-updated ordering."""
        for w in self.apps_frame.winfo_children():
            w.destroy()

        ordered_apps = self._ordered_apps_for_overview()
        total = max(len(ordered_apps), 1)
        cols = 1 if total <= 2 else (2 if total <= 6 else 3)
        for col in range(cols):
            self.apps_frame.grid_columnconfigure(col, weight=1, uniform="apptile")
        now_ts = time.time()

        for idx, app in enumerate(ordered_apps, start=1):
            usb_status, usb_color = self._app_usb_comparison(app)
            needs_sync = "needs update" in usb_status or "not on USB" in usb_status
            bucket = self._app_priority_bucket(app)
            badge_text, badge_color = self._app_rank_badge(app, idx)
            last_ts = self._app_last_update_ts(app)
            age_days: Optional[float]
            if last_ts > 0:
                age_days = max(0.0, (now_ts - last_ts) / 86400.0)
                freshness_text = f"Last update: {_fmt_ts(last_ts)} ({age_days:.1f} days ago)"
            else:
                age_days = None
                freshness_text = "Last update: unknown"

            card_bg = self.colors["card"]
            cue_color = self.colors["border"]
            if bucket == 0:
                card_bg = "#1a3552"
                cue_color = self.colors["accent"]
            elif bucket == 1:
                card_bg = "#2f314f"
                cue_color = self.colors["warn"]
            elif needs_sync:
                card_bg = "#2a2a3b"
                cue_color = self.colors["warn"]
            elif age_days is not None and age_days <= 7.0:
                card_bg = "#1a3a2b"
                cue_color = self.colors["good"]

            border_color = cue_color if (needs_sync or bucket < 2) else self.colors["border"]
            card = self.tk.Frame(
                self.apps_frame,
                bg=card_bg,
                highlightthickness=2 if (needs_sync or bucket < 2) else 1,
                highlightbackground=border_color,
                bd=0,
                padx=14,
                pady=12,
            )
            row = (idx - 1) // cols
            col = (idx - 1) % cols
            card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
            card.grid_columnconfigure(0, weight=1)

            cue = self.tk.Frame(card, bg=cue_color, height=5, bd=0)
            cue.grid(row=0, column=0, sticky="ew", pady=(0, 8))

            # Icon + name
            self._make_label(
                card,
                text=f"{app['icon']}  {app['name']}",
                bg=card_bg,
                fg=self.colors["accent"],
                font=("Segoe UI Semibold", 12, "bold"),
                wraplength=250,
            ).grid(row=1, column=0, sticky="w")

            marker = "[!]" if needs_sync else ("[+]" if bucket < 2 else "[=]")
            self._make_label(
                card,
                text=f"{marker} {badge_text}",
                bg=card_bg,
                fg=badge_color,
                font=("Consolas", 9, "bold"),
                wraplength=250,
            ).grid(row=2, column=0, sticky="w", pady=(4, 0))

            # Description
            self._make_label(
                card,
                text=app["description"],
                bg=card_bg,
                fg=self.colors["muted"],
                font=("Segoe UI", 9, "normal"),
                wraplength=250,
            ).grid(row=3, column=0, sticky="w", pady=(4, 0))

            # Version (source)
            src_root = self._app_source_root(app)
            ver = _read_version_file(src_root, app.get("version_file"))
            ver_text = f"v{ver}" if ver else "—"
            repo_label = f"  [{src_root.name}]" if src_root != self.source_repo else ""
            self._make_label(
                card,
                text=f"PC version: {ver_text}{repo_label}",
                bg=card_bg,
                fg=self.colors["text"],
                font=("Consolas", 10, "normal"),
            ).grid(row=4, column=0, sticky="w", pady=(8, 0))

            freshness_color = self.colors["muted"]
            if age_days is not None:
                if age_days <= 7.0:
                    freshness_color = self.colors["good"]
                elif age_days <= 30.0:
                    freshness_color = self.colors["accent"]
                else:
                    freshness_color = self.colors["warn"]
            self._make_label(
                card,
                text=freshness_text,
                bg=card_bg,
                fg=freshness_color,
                font=("Consolas", 9, "normal"),
                wraplength=250,
            ).grid(row=5, column=0, sticky="w", pady=(2, 0))

            # Key files with mtime
            key_files = app.get("key_files") or []
            file_lines = []
            for rel in key_files[:3]:
                p = src_root / rel
                if p.exists():
                    try:
                        mtime = _fmt_ts(p.stat().st_mtime)
                    except Exception:
                        mtime = "?"
                    file_lines.append(f"  {Path(rel).name}  {mtime}")
                else:
                    file_lines.append(f"  {Path(rel).name}  [not in source]")
            if file_lines:
                self._make_label(
                    card,
                    text="\n".join(file_lines),
                    bg=card_bg,
                    fg=self.colors["muted"],
                    font=("Consolas", 9, "normal"),
                    wraplength=260,
                ).grid(row=6, column=0, sticky="w", pady=(4, 0))

            # USB sync status
            status_prefix = "[SYNC]" if needs_sync else ("[AHEAD]" if "ahead" in usb_status.lower() else "[OK]")
            self._make_label(
                card,
                text=f"{status_prefix} {usb_status}",
                bg=card_bg,
                fg=usb_color,
                font=("Segoe UI Semibold", 10, "bold"),
                wraplength=250,
            ).grid(row=7, column=0, sticky="w", pady=(8, 0))

            # Platform readiness (check against the app's own source root)
            slug = _slugify_name(app.get("name", "app"))
            fallback_win = src_root / "bootstrap" / "windows" / f"Run-{slug}.cmd"
            fallback_nix = src_root / "bootstrap" / "linux" / f"run-{slug}.sh"

            win_ok = None
            nix_ok = None
            parts = []
            if app.get("launcher_win"):
                win_ok = (src_root / app["launcher_win"]).exists() or fallback_win.exists()
                parts.append(f"Win {'OK' if win_ok else '!'}")
            else:
                win_ok = fallback_win.exists()
                parts.append(f"Win {'OK' if win_ok else '!'} (bootstrap)")
            if app.get("launcher_nix"):
                nix_ok = (src_root / app["launcher_nix"]).exists() or fallback_nix.exists()
                parts.append(f"Ubuntu {'OK' if nix_ok else '!'}")
            else:
                nix_ok = fallback_nix.exists()
                parts.append(f"Ubuntu {'OK' if nix_ok else '!'} (bootstrap)")
            if parts:
                all_ok = all(x for x in [win_ok, nix_ok] if x is not None)
                self._make_label(
                    card,
                    text="  ".join(parts),
                    bg=card_bg,
                    fg=self.colors["good"] if all_ok else self.colors["warn"],
                    font=("Segoe UI", 9, "normal"),
                ).grid(row=8, column=0, sticky="w", pady=(2, 0))

            # Per-app push/pull actions for tracked key files
            if key_files:
                sync_actions = self.tk.Frame(card, bg=card_bg)
                sync_actions.grid(row=9, column=0, sticky="ew", pady=(10, 0))
                sync_actions.grid_columnconfigure(0, weight=1)
                sync_actions.grid_columnconfigure(1, weight=1)

                btn_text = "Push App -> USB" if needs_sync else "Re-push App -> USB"
                btn_color = self.colors["warn"] if needs_sync else self.colors["button"]
                btn_fg = self.colors["bg"] if needs_sync else self.colors["text"]
                push_btn = self.tk.Button(
                    sync_actions,
                    text=btn_text,
                    command=lambda a=app: self._on_sync_app_files(a),
                    bg=btn_color,
                    fg=btn_fg,
                    activebackground=self.colors["accent_active"],
                    activeforeground=self.colors["bg"],
                    relief="flat",
                    bd=0,
                    padx=8,
                    pady=5,
                    cursor="hand2",
                    font=("Segoe UI Semibold", 9),
                    wraplength=160,
                )
                push_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

                pull_btn = self.tk.Button(
                    sync_actions,
                    text="Pull App <- USB",
                    command=lambda a=app: self._on_pull_app_files(a),
                    bg=self.colors["button"],
                    fg=self.colors["text"],
                    activebackground=self.colors["button_active"],
                    activeforeground=self.colors["text"],
                    relief="flat",
                    bd=0,
                    padx=8,
                    pady=5,
                    cursor="hand2",
                    font=("Segoe UI Semibold", 9),
                    wraplength=160,
                )
                pull_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

            usb_target_for_launch = self._selected_target() or (self.targets[0].path if self.targets else None)
            can_launch_local = self._resolve_app_launcher_path(app, src_root) is not None
            can_launch_usb = (
                usb_target_for_launch is not None
                and self._resolve_app_launcher_path(app, usb_target_for_launch) is not None
            )
            git_root = self._git_repo_root_for_app(app)

            app_actions = self.tk.Frame(card, bg=card_bg)
            app_actions.grid(row=10, column=0, sticky="ew", pady=(8, 0))
            for c in range(3):
                app_actions.grid_columnconfigure(c, weight=1)

            launch_local_btn = self.tk.Button(
                app_actions,
                text="Launch Local",
                command=lambda a=app: self.on_launch_app_local(a),
                bg=self.colors["button"],
                fg=self.colors["text"],
                activebackground=self.colors["button_active"],
                activeforeground=self.colors["text"],
                relief="flat",
                bd=0,
                padx=6,
                pady=4,
                cursor="hand2",
                font=("Segoe UI", 9),
                state="normal" if can_launch_local else "disabled",
            )
            launch_local_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

            launch_usb_btn = self.tk.Button(
                app_actions,
                text="Launch USB",
                command=lambda a=app: self.on_launch_app_usb(a),
                bg=self.colors["button"],
                fg=self.colors["text"],
                activebackground=self.colors["button_active"],
                activeforeground=self.colors["text"],
                relief="flat",
                bd=0,
                padx=6,
                pady=4,
                cursor="hand2",
                font=("Segoe UI", 9),
                state="normal" if can_launch_usb else "disabled",
            )
            launch_usb_btn.grid(row=0, column=1, sticky="ew", padx=4)

            open_repo_btn = self.tk.Button(
                app_actions,
                text="Open Repo",
                command=lambda a=app: self.on_open_app_repo(a),
                bg=self.colors["button"],
                fg=self.colors["text"],
                activebackground=self.colors["button_active"],
                activeforeground=self.colors["text"],
                relief="flat",
                bd=0,
                padx=6,
                pady=4,
                cursor="hand2",
                font=("Segoe UI", 9),
            )
            open_repo_btn.grid(row=0, column=2, sticky="ew", padx=(4, 0))

            git_actions = self.tk.Frame(card, bg=card_bg)
            git_actions.grid(row=11, column=0, sticky="ew", pady=(6, 0))
            git_actions.grid_columnconfigure(0, weight=1)
            git_actions.grid_columnconfigure(1, weight=1)
            git_push_btn = self.tk.Button(
                git_actions,
                text="Git Push",
                command=lambda a=app: self._on_git_push_app(a),
                bg=self.colors["warn"] if git_root is not None else self.colors["button"],
                fg=self.colors["bg"] if git_root is not None else self.colors["muted"],
                activebackground=self.colors["accent_active"],
                activeforeground=self.colors["bg"],
                relief="flat",
                bd=0,
                padx=6,
                pady=4,
                cursor="hand2",
                font=("Segoe UI", 9),
                state="normal" if git_root is not None else "disabled",
            )
            git_push_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            git_pull_btn = self.tk.Button(
                git_actions,
                text="Git Pull",
                command=lambda a=app: self._on_git_pull_app(a),
                bg=self.colors["accent"] if git_root is not None else self.colors["button"],
                fg=self.colors["bg"] if git_root is not None else self.colors["muted"],
                activebackground=self.colors["accent_active"],
                activeforeground=self.colors["bg"],
                relief="flat",
                bd=0,
                padx=6,
                pady=4,
                cursor="hand2",
                font=("Segoe UI", 9),
                state="normal" if git_root is not None else "disabled",
            )
            git_pull_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self._refresh_launch_app_list()

    def _render_tiles(self) -> None:
        for child in self.tiles_inner.winfo_children():
            child.destroy()

        if not self.targets:
            self._make_label(
                self.tiles_inner,
                text=f"No compatible external repo was detected yet. Insert a known USB or external {_scope_label()} copy and click Refresh USB + Phone.",
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                wraplength=860,
            ).grid(row=0, column=0, sticky="w", padx=14, pady=14)
            return

        cols = max(self._tile_columns, 1)
        for col in range(cols):
            self.tiles_inner.grid_columnconfigure(col, weight=1, uniform="tile")

        selected = str(self._selected_target() or "")
        for idx, target in enumerate(self.targets):
            snap = self.target_status.get(str(target.path))
            if snap is None:
                continue
            is_selected = selected == str(target.path)
            card_bg = self.colors["card_selected"] if is_selected else self.colors["card"]
            border = self.colors["accent"] if is_selected else self.colors["border"]
            rec_label = self._recommendation_label(snap.comparison)
            rec_color = self._recommendation_color(snap.comparison)
            memory_text = "LAST KNOWN FOLDER" if target.remembered else "NEW DETECTION"
            memory_color = self.colors["warn"] if target.remembered else self.colors["muted"]
            writable_text = "Writable" if snap.writable else "Read-only / blocked"
            writable_color = self.colors["good"] if snap.writable else self.colors["danger"]

            card = self.tk.Frame(
                self.tiles_inner,
                bg=card_bg,
                highlightthickness=2 if is_selected else 1,
                highlightbackground=border,
                highlightcolor=self.colors["accent"],
                bd=0,
                cursor="hand2",
                padx=14,
                pady=14,
            )
            row = idx // cols
            col = idx % cols
            card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)

            title = self._make_label(
                card,
                text=target.path.name or str(target.path),
                bg=card_bg,
                font=("Segoe UI Semibold", 14, "bold"),
                wraplength=420,
            )
            title.grid(row=0, column=0, sticky="w")
            status = self._make_label(
                card,
                text=rec_label,
                bg=card_bg,
                fg=rec_color,
                font=("Segoe UI Semibold", 11, "bold"),
            )
            status.grid(row=0, column=1, sticky="e")
            path_label = self._make_label(
                card,
                text=str(target.path),
                bg=card_bg,
                fg=self.colors["text"],
                font=("Consolas", 10, "normal"),
                wraplength=500,
            )
            path_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 4))
            root_label = self._make_label(
                card,
                text=f"Unit: {snap.root_label}",
                bg=card_bg,
                fg=self.colors["muted"],
                font=("Segoe UI", 10, "normal"),
                wraplength=500,
            )
            root_label.grid(row=2, column=0, columnspan=2, sticky="w")
            # Changed-files summary
            changed_lines = []
            if snap.comparison.newer_source_files:
                changed_lines.append("Updated: " + ", ".join(
                    Path(f).name for f in snap.comparison.newer_source_files[:5]
                ))
            if snap.comparison.new_source_files:
                changed_lines.append("New: " + ", ".join(
                    Path(f).name for f in snap.comparison.new_source_files[:3]
                ))
            if not changed_lines:
                changed_lines.append(
                    f"Newer on source: {snap.comparison.source_newer}  "
                    f"Newer on target: {snap.comparison.target_newer}  "
                    f"Source only: {snap.comparison.source_only}"
                )
            compare_label = self._make_label(
                card,
                text="\n".join(changed_lines),
                bg=card_bg,
                fg=self.colors["warn"] if snap.comparison.newer_source_files or snap.comparison.new_source_files else self.colors["muted"],
                font=("Segoe UI", 10, "normal"),
                wraplength=500,
            )
            compare_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
            avg_label = self._make_label(
                card,
                text=(
                    f"Average freshness: PC {_fmt_ts(snap.comparison.source_avg_ts)} | "
                    f"copy {_fmt_ts(snap.comparison.target_avg_ts)}"
                ),
                bg=card_bg,
                fg=self.colors["muted"],
                font=("Segoe UI", 10, "normal"),
                wraplength=500,
            )
            avg_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
            footer_left = self._make_label(
                card,
                text=memory_text,
                bg=card_bg,
                fg=memory_color,
                font=("Segoe UI Semibold", 10, "bold"),
            )
            footer_left.grid(row=5, column=0, sticky="w", pady=(12, 0))
            footer_right = self._make_label(
                card,
                text=writable_text,
                bg=card_bg,
                fg=writable_color,
                font=("Segoe UI Semibold", 10, "bold"),
            )
            footer_right.grid(row=5, column=1, sticky="e", pady=(12, 0))

            for widget in (card, title, status, path_label, root_label, compare_label, avg_label, footer_left, footer_right):
                self._bind_tile_select(widget, target.path)


    def _update_detail_panel(self) -> None:
        snap = self._selected_status()
        device = self._selected_device()
        self.detail_device_var.set(self._device_label(device) if device else "No phone selected")
        if snap is None:
            self.detail_title_var.set("No target selected")
            self.detail_status_var.set("Insert or refresh a USB or external repo to begin.")
            self.detail_status_label.configure(fg=self.colors["muted"])
            self.detail_reason_var.set("The utility will auto-pick the safest match once compatible copies are found.")
            self.detail_path_var.set("Select a repo tile on the left.")
            self.detail_root_var.set("-")
            self.detail_freshness_var.set("-")
            self.detail_compare_var.set("-")
            self.detail_write_var.set("-")
            self.detail_memory_var.set("-")
            self._update_action_states()
            return

        target = snap.target
        comparison = snap.comparison
        status_text = self._recommendation_label(comparison)
        status_color = self._recommendation_color(comparison)
        write_text = "Writable" if snap.writable else f"Not writable: {snap.write_detail}"
        memory_text = "Remembered for this detected unit" if target.remembered else "Seen in current scan only"

        self.detail_title_var.set(target.path.name or str(target.path))
        self.detail_status_var.set(status_text)
        self.detail_status_label.configure(fg=status_color)
        self.detail_reason_var.set(comparison.summary)
        self.detail_path_var.set(str(target.path))
        self.detail_root_var.set(snap.root_label)
        self.detail_freshness_var.set(_fmt_ts(snap.freshness_ts))
        self.detail_compare_var.set(
            f"PC newer files {comparison.source_newer}; copy newer files {comparison.target_newer}; "
            f"PC-only files {comparison.source_only}; copy-only files {comparison.target_only}; "
            f"shared tracked files {comparison.common_files}"
        )
        self.detail_write_var.set(write_text)
        self.detail_memory_var.set(memory_text)
        self._update_action_states()

    def _refresh_guidance(self) -> None:
        snap = self._selected_status()
        if snap is None:
            self.guide_var.set("Guide: click Refresh USB + Phone to auto-find repo copies and any connected Android device.")
            self.guide_label.configure(fg=self.colors["muted"])
            return
        comparison = snap.comparison
        if comparison.recommendation == "push_source_to_target":
            self.guide_var.set("Guide: the local PC copy looks newer on average. Push PC -> USB is the safe default.")
        elif comparison.recommendation == "pull_target_to_source":
            self.guide_var.set("Guide: the selected USB copy looks newer on average. Pull USB -> PC before pushing anything else.")
        elif comparison.recommendation == "current":
            self.guide_var.set("Guide: the selected copy appears aligned. No repo sync is needed unless you want a fresh export to phone.")
        else:
            self.guide_var.set("Guide: both sides have differences. Review the counts before pushing or pulling so you do not overwrite newer work.")
        if len(self.targets) >= 2:
            self.guide_var.set(self.guide_var.get() + " You can also duplicate the selected USB to another backup USB.")
        self.guide_label.configure(fg=self._recommendation_color(comparison))

    def _update_health_banner(self, *, log: bool = False) -> None:
        source_ok = _has_repo_marker(self.source_repo)
        snap = self._selected_status()
        device = self._selected_device()
        parts: List[str] = []
        parts.append("source=ok" if source_ok else "source=missing-markers")
        if snap is None:
            parts.append("target=not-selected")
            ok = source_ok
        else:
            parts.append(f"target={'writable' if snap.writable else 'not-writable'}")
            parts.append(f"recommendation={snap.comparison.recommendation}")
            ok = source_ok and snap.writable
        parts.append(f"targets_detected={len(self.targets)}")
        parts.append(f"phones_detected={len(self.devices)}")
        if device is not None:
            parts.append(f"selected_phone={device.serial}")
        msg = ("Health PASS: " if ok else "Health WARN: ") + ", ".join(parts)
        self.health_var.set(msg)
        if log:
            self._append(f"[HEALTH] {msg}\n")

    def refresh_targets(self) -> None:
        self._set_status("Scanning USB targets and ADB phones...")
        self._append("\n[SCAN] discovering candidate repo targets and phones...\n")

        def worker() -> None:
            # Always run Ubuntu port checks on source repo at scan time
            if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_CITL:
                try:
                    ubuntu_results = port_to_ubuntu(
                        self.source_repo,
                        log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                    )
                    any_updated = any("UPDATED" in v for v in ubuntu_results.values())
                    if any_updated:
                        self.root.after(0, self._render_apps_overview)
                except Exception as e:
                    self.root.after(0, lambda: self._append(f"[WARN] Ubuntu port check: {e}\n"))

            try:
                targets = discover_sync_targets(self.source_repo)
                devices = connected_phone_devices()
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[ERROR] scan failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("Scan failed."))
                return
            self.root.after(0, lambda: self._apply_refresh(targets, devices))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_refresh(self, targets: List[SyncTarget], devices: List[PhoneDevice]) -> None:
        self.targets = targets
        self.devices = devices
        self.target_status = self._build_target_statuses(targets)
        preferred, reason = self._pick_preferred_target(targets, self.target_status)
        if devices:
            if self.device_var.get().strip() not in {item.serial for item in devices}:
                self.device_var.set(devices[0].serial)
            self.phone_var.set(f"Phone ready: {len(devices)} device(s) over ADB. Selected: {self._device_label(self._selected_device() or devices[0])}")
        else:
            self.device_var.set("")
            self.phone_var.set("Phone: no Android device detected over ADB. USB sync is still available.")

        updates = sum(1 for item in self.target_status.values() if item.comparison.recommendation == "push_source_to_target")
        pulls = sum(1 for item in self.target_status.values() if item.comparison.recommendation == "pull_target_to_source")
        reviews = sum(1 for item in self.target_status.values() if item.comparison.recommendation == "review")
        remembered = sum(1 for target in targets if target.remembered)
        if targets:
            self.targets_meta_var.set(
                f"Targets found: {len(targets)} | safe pushes: {updates} | safer pulls: {pulls} | review first: {reviews} | remembered folders: {remembered}"
            )
            self._append(
                f"[SCAN] found {len(targets)} target(s); push-safe={updates}; pull-safer={pulls}; review-first={reviews}; remembered={remembered}\n"
            )
            if preferred is not None:
                self.target_var.set(str(preferred))
                self._append(f"[SCAN] {reason}: {preferred}\n")
                self._set_status(f"Found {len(targets)} candidate target(s).")
            else:
                self.target_var.set("")
                self._set_status("Found targets, but no default selection was available.")
        else:
            self.target_var.set("")
            self.targets_meta_var.set("Targets found: 0")
            self._append(f"[SCAN] no compatible external {_scope_label()} repo found.\n")
            self._set_status("No target found. Insert or mount a repo copy and click Refresh USB + Phone.")

        self._render_device_buttons()
        self._render_tiles()
        self._render_apps_overview()
        self._update_detail_panel()
        self._update_health_banner(log=True)
        self._refresh_guidance()
        self._refresh_sync_app_selection_meta()
        self.on_refresh_bootstrap_catalog()
        self._update_action_states()

    def on_open_source(self) -> None:
        try:
            open_in_file_manager(self.source_repo)
        except Exception as e:
            self.messagebox.showerror("Open failed", str(e))

    def on_open_target(self) -> None:
        target = self._selected_target()
        if not target:
            self.messagebox.showinfo("No target", "Select a repo tile first.")
            return
        try:
            _remember_target(target)
            self._mark_target_remembered(target)
            open_in_file_manager(target)
            self._update_detail_panel()
            self._render_tiles()
        except Exception as e:
            self.messagebox.showerror("Open failed", str(e))

    def on_launch_doc_composer(self) -> None:
        """Launch CITL Document Composer from USB or portable installation."""
        self._launch_citl_app("CITL Document Composer", "citl_doc_composer.py", is_python=True)

    def on_launch_presentation_suite(self) -> None:
        """Launch CITL LLMOps Presentation Suite from USB or portable installation."""
        self._launch_citl_app("CITL LLMOps Presentation Suite", "CITL LLMOps Presentation Suite.exe")

    def on_launch_workstation_apps(self) -> None:
        """Launch CITL Workstation Apps from USB or portable installation."""
        self._launch_citl_app("CITL Workstation Apps", "CITL Workstation Apps.exe")

    def on_launch_field_apps(self) -> None:
        """Launch CITL Field Apps from USB or portable installation."""
        self._launch_citl_app("CITL Field Apps", "CITL Field Apps.exe")

    def on_clone_usb(self) -> None:
        """Launch the USB clone GUI for duplicating USB drives."""
        try:
            import subprocess
            gui_path = Path(__file__).parent / "citl_usb_clone_gui.py"
            if not gui_path.exists():
                self.messagebox.showerror(
                    "Not found",
                    f"Clone GUI not found at:\n{gui_path}\n\n"
                    f"Run from the main {_scope_label()} repo directory."
                )
                return
            
            # Launch GUI in separate process
            python_exe = sys.executable
            subprocess.Popen([python_exe, str(gui_path)])
            self._append("[CLONE] Launched USB clone GUI in separate window\n")
        except Exception as e:
            self.messagebox.showerror("Clone failed", f"Could not launch clone GUI:\n{e}")

    def on_sync_from_git(self) -> None:
        """Pull latest changes from GitHub to current device."""
        try:
            source_repo = self.source_repo
            if not source_repo:
                self.messagebox.showerror("No source", "Source repo not detected")
                return
            
            # Check if git repo exists
            git_marker = Path(source_repo) / ".git"
            if not git_marker.exists():
                self.messagebox.showwarning(
                    "Not a git repo",
                    f"Source path is not a git repository:\n{source_repo}\n\n"
                    "Cannot sync from GitHub."
                )
                return
            
            if not self.messagebox.askyesno(
                "Confirm Git Sync",
                f"Pull latest changes from GitHub to:\n{source_repo}\n\n"
                "This will update your working files."
            ):
                return
            
            self._append("\n[GIT-SYNC] Starting git pull from GitHub...\n")
            self._set_status("Syncing from GitHub...")
            
            # Run git pull
            rc, stdout, stderr = _git_run(Path(source_repo), "pull", "origin", "main")
            
            if rc == 0:
                self._append(f"[GIT-SYNC] Pull successful:\n{stdout}\n")
                self._set_status("Git sync complete - files updated from GitHub")
                self.messagebox.showinfo("Success", "Latest changes pulled from GitHub")
                
                # Refresh UI to show any changes
                self.refresh_targets()
            else:
                error_msg = stderr or stdout or f"git pull failed with code {rc}"
                self._append(f"[GIT-SYNC][ERROR] {error_msg}\n")
                self._set_status("Git sync failed")
                self.messagebox.showerror("Git sync failed", error_msg)
        
        except Exception as e:
            self._append(f"[GIT-SYNC][ERROR] {e}\n")
            self.messagebox.showerror("Git sync error", str(e))

    def on_push_to_git(self) -> None:
        """Push current device's changes to GitHub."""
        try:
            source_repo = self.source_repo
            if not source_repo:
                self.messagebox.showerror("No source", "Source repo not detected")
                return
            
            # Check if git repo exists
            git_marker = Path(source_repo) / ".git"
            if not git_marker.exists():
                self.messagebox.showwarning(
                    "Not a git repo",
                    f"Source path is not a git repository:\n{source_repo}\n\n"
                    "Cannot push to GitHub."
                )
                return
            
            # Check for uncommitted changes
            self._append("\n[GIT-PUSH] Checking for uncommitted changes...\n")
            rc, stdout, stderr = _git_run(Path(source_repo), "status", "--porcelain")
            
            if stdout:
                # Has changes - ask to commit first
                if not self.messagebox.askyesno(
                    "Uncommitted changes",
                    "You have uncommitted changes in this repo.\n\n"
                    "Commit and push them to GitHub?\n\n"
                    "Changes will be committed with message:\n"
                    "'Fleet update from field device'"
                ):
                    return
                
                # Stage changes
                self._append("[GIT-PUSH] Staging changes...\n")
                rc_add, _, err_add = _git_run(Path(source_repo), "add", "-A")
                if rc_add != 0:
                    self._append(f"[GIT-PUSH][ERROR] Failed to stage: {err_add}\n")
                    self.messagebox.showerror("Commit failed", f"Could not stage changes:\n{err_add}")
                    return
                
                # Commit
                self._append("[GIT-PUSH] Committing changes...\n")
                rc_commit, _, err_commit = _git_run(
                    Path(source_repo),
                    "commit",
                    "-m",
                    f"Fleet update from {socket.gethostname()} - {datetime.utcnow().isoformat()}"
                )
                if rc_commit != 0:
                    self._append(f"[GIT-PUSH][ERROR] Commit failed: {err_commit}\n")
                    self.messagebox.showerror("Commit failed", err_commit)
                    return
                
                self._append("[GIT-PUSH] Commit successful\n")
            else:
                self._append("[GIT-PUSH] No uncommitted changes\n")
            
            # Push to GitHub
            if not self.messagebox.askyesno(
                "Confirm Push",
                f"Push changes to GitHub from:\n{source_repo}\n\n"
                "This will update the remote repository."
            ):
                return
            
            self._append("[GIT-PUSH] Pushing to GitHub...\n")
            self._set_status("Pushing to GitHub...")
            
            rc_push, stdout, stderr = _git_run(Path(source_repo), "push", "origin", "main")
            
            if rc_push == 0:
                self._append(f"[GIT-PUSH] Push successful:\n{stdout}\n")
                self._set_status("Push to GitHub complete")
                self.messagebox.showinfo("Success", "Changes pushed to GitHub")
            else:
                error_msg = stderr or stdout or f"git push failed with code {rc_push}"
                self._append(f"[GIT-PUSH][ERROR] {error_msg}\n")
                self._set_status("Git push failed")
                self.messagebox.showerror("Push failed", error_msg)
        
        except Exception as e:
            self._append(f"[GIT-PUSH][ERROR] {e}\n")
            self.messagebox.showerror("Push error", str(e))

        """Detect USB root containing CITL applications."""
        if hasattr(self, '_usb_root') and self._usb_root:
            return self._usb_root

        # Check if we have a selected target that's on a USB drive
        target = self._selected_target()
        if target:
            # Check if target is on a removable drive
            try:
                import ctypes
                if sys.platform == "win32":
                    # Check if drive is removable
                    drive = str(target)[:3]  # e.g., "F:\"
                    drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
                    if drive_type == 2:  # DRIVE_REMOVABLE
                        return Path(drive)
            except:
                pass

        # Fallback: scan common USB drive letters
        if sys.platform == "win32":
            for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
                drive = Path(f"{letter}:\\")
                if drive.exists():
                    # Check for CITL folders
                    if any((drive / folder).exists() for folder, _, _ in APP_BUNDLES):
                        return drive

        return None

    def _launch_citl_app(self, app_name: str, exe_name: str, is_python: bool = False) -> None:
        """Launch a CITL application from USB drive or portable installation."""
        import subprocess
        import os

        # First try to find on USB drive
        usb_root = self._detect_usb_root()
        if usb_root:
            if is_python:
                # For Python scripts, look in factbook-assistant folder
                exe_path = usb_root / "factbook-assistant" / exe_name
            else:
                # For executables, find the right numbered folder
                for folder_name, _, bundle_exe in APP_BUNDLES:
                    if bundle_exe == exe_name:
                        exe_path = usb_root / folder_name / exe_name
                        break
                else:
                    exe_path = usb_root / exe_name

            if exe_path.exists():
                try:
                    if is_python:
                        # Launch Python script
                        python_cmd = sys.executable
                        subprocess.Popen([python_cmd, str(exe_path)])
                    else:
                        # Launch executable
                        if sys.platform == "win32":
                            os.startfile(str(exe_path))
                        else:
                            subprocess.Popen(["xdg-open", str(exe_path)])
                    self._append(f"[LAUNCH] Started {app_name} from USB: {exe_path}\n")
                    return
                except Exception as e:
                    self._append(f"[LAUNCH_ERROR] Failed to start {app_name} from USB: {e}\n")

        # Try portable installation
        if is_python:
            portable_paths = [
                Path.home() / "CITL Apps" / "factbook-assistant" / exe_name,
                Path.home() / "Desktop" / "CITL Apps" / "factbook-assistant" / exe_name,
                Path.home() / "Documents" / "CITL Apps" / "factbook-assistant" / exe_name,
            ]
        else:
            portable_paths = [
                Path.home() / "CITL Apps" / exe_name,
                Path.home() / "Desktop" / "CITL Apps" / exe_name,
                Path.home() / "Documents" / "CITL Apps" / exe_name,
            ]

        for exe_path in portable_paths:
            if exe_path.exists():
                try:
                    if is_python:
                        python_cmd = sys.executable
                        subprocess.Popen([python_cmd, str(exe_path)])
                    else:
                        if sys.platform == "win32":
                            os.startfile(str(exe_path))
                        else:
                            subprocess.Popen(["xdg-open", str(exe_path)])
                    self._append(f"[LAUNCH] Started {app_name} from portable: {exe_path}\n")
                    return
                except Exception as e:
                    self._append(f"[LAUNCH_ERROR] Failed to start {app_name} from portable: {e}\n")

        # If not found, show error
        self.messagebox.showerror(
            "Application Not Found",
            f"{app_name} was not found on USB drive or in portable installation.\n\n"
            f"Searched for: {exe_name}\n\n"
            f"Try running INSTALL_CITL_APPS_PORTABLE.cmd first."
        )

    def on_remember_target(self) -> None:
        target = self._selected_target()
        if not target:
            self.messagebox.showinfo("No target", "Select a repo tile first.")
            return
        try:
            _remember_target(target)
            self._mark_target_remembered(target)
        except Exception as e:
            self.messagebox.showerror("Remember failed", str(e))
            return
        self._append(f"[STATE] remembered target folder for auto-detection: {target}\n")
        self._update_detail_panel()
        self._render_tiles()
        self._set_status(f"Remembered target folder: {target}")

    def on_auto_pick_best(self) -> None:
        if not self.targets:
            self.messagebox.showinfo("No targets", "Refresh first so the utility can find USB copies.")
            return
        preferred, reason = self._pick_preferred_target(self.targets, self.target_status)
        if preferred is None:
            self.messagebox.showinfo("No recommendation", "No safe default target was available.")
            return
        self._select_target(preferred, log_selection=True)
        self._append(f"[GUIDE] auto-picked best target: {preferred} ({reason})\n")

    def on_health_check(self) -> None:
        self._update_health_banner(log=True)
        self._refresh_guidance()
        self._set_status("Health check complete.")


    def _choose_duplicate_destination(self, source_target: Path) -> Optional[Tuple[Path, RepoComparison]]:
        candidates = [t for t in self.targets if t.path != source_target]
        if not candidates:
            return None
        picked = _pick_duplicate_target(
            source_target,
            candidates,
            include_data=bool(self.include_data_var.get()),
            include_models=bool(self.include_models_var.get()),
        )
        if picked is None:
            return None
        dest_target, comparison = picked
        self._append(f"[DUPLICATE] auto-picked destination: {dest_target}\n")
        return dest_target, comparison

    def _prepare_model_sync_plan(
        self,
        op_label: str,
        source_repo_for_models: Path,
        target_repo_for_models: Path,
    ) -> Optional[Tuple[bool, Optional[Path], Optional[Path]]]:
        include_models = bool(self.include_models_var.get())
        if not include_models:
            return (False, None, None)

        model_candidates = candidate_ollama_model_dirs(source_repo_for_models)
        default_source = model_candidates[0] if model_candidates else None
        default_target = recommended_ollama_model_target_dir(target_repo_for_models)

        detected_size = _dir_size_bytes(default_source) if default_source else 0
        size_msg = _fmt_bytes(detected_size) if detected_size > 0 else "unknown"
        warn = (
            f"{op_label} requested model sync.\n\n"
            "Model files can be very large (often 8 GB to 100+ GB).\n"
            "Please make sure you already pulled required models first, for example:\n"
            "  ollama pull qwen2.5:7b\n"
            "  ollama pull nomic-embed-text\n\n"
            "Continue with model transfer setup now?"
        )
        if not self.messagebox.askyesno("Model Sync Preflight", warn):
            if self.messagebox.askyesno(
                "Skip model files?",
                "Continue this sync WITHOUT copying model files?",
            ):
                return (False, None, None)
            return None

        source_dir: Optional[Path] = None
        if default_source:
            source_prompt = (
                "Use detected model source directory?\n\n"
                f"{default_source}\n\n"
                f"Approximate size: {size_msg}\n"
            )
            if detected_size >= MODEL_SYNC_WARN_BYTES:
                source_prompt += "\nWarning: this is a large transfer."
            if self.messagebox.askyesno("Model Source Directory", source_prompt):
                source_dir = default_source

        if source_dir is None:
            picked = self.filedialog.askdirectory(
                title="Select Ollama model source directory",
                initialdir=str(source_repo_for_models),
                mustexist=True,
            )
            if not picked:
                return None
            source_dir = Path(picked).expanduser()

        if not source_dir.exists() or not source_dir.is_dir():
            self.messagebox.showerror("Invalid model source", f"Directory not found:\n{source_dir}")
            return None

        target_choice = self.messagebox.askyesnocancel(
            "Model Target Directory",
            "Choose destination for model storage.\n\n"
            f"Recommended (keeps models out of repo and easier to manage size):\n{default_target}\n\n"
            "Yes = use recommended path\n"
            "No = pick a custom path\n"
            "Cancel = stop this sync",
        )
        if target_choice is None:
            return None
        if target_choice:
            target_dir = default_target
        else:
            picked_target = self.filedialog.askdirectory(
                title="Select destination model directory",
                initialdir=str(_guess_usb_root(target_repo_for_models)),
                mustexist=False,
            )
            if not picked_target:
                return None
            target_dir = Path(picked_target).expanduser()

        self._append(
            f"[MODEL] external model copy enabled\n"
            f"[MODEL] source={source_dir} ({_fmt_bytes(_dir_size_bytes(source_dir))})\n"
            f"[MODEL] target={target_dir}\n"
        )
        return (True, source_dir, target_dir)

    def _sync_app_key_overlay(
        self,
        target_repo: Path,
        selected_app_names: Optional[Sequence[str]] = None,
    ) -> Tuple[int, int, int]:
        summary = sync_registered_app_key_files(
            self.source_repo,
            target_repo,
            selected_app_names=selected_app_names,
            log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
        )
        total_copied = sum(v.get("copied", 0) for v in summary.values())
        total_missing = sum(v.get("missing", 0) for v in summary.values())
        total_errors = sum(v.get("errors", 0) for v in summary.values())
        self.root.after(
            0,
            lambda: self._append(
                f"[APP-SYNC][OVERLAY] apps={len(summary)} copied={total_copied} "
                f"missing={total_missing} errors={total_errors}\n"
            ),
        )
        return total_copied, total_missing, total_errors

    def _confirm_sync_direction(self, mode: str, snap: TargetStatus) -> bool:
        comparison = snap.comparison
        if mode == "push":
            title = "Confirm PC -> USB sync"
            if comparison.recommendation == "pull_target_to_source":
                return self.messagebox.askyesno(
                    title,
                    "Warning: this USB copy looks newer on average than the PC source.\n\n"
                    f"{comparison.summary}\n\n"
                    "Pushing now may overwrite newer USB work. Continue anyway?",
                )
            if comparison.recommendation == "review":
                return self.messagebox.askyesno(
                    title,
                    "Warning: both sides have mixed newer components.\n\n"
                    f"{comparison.summary}\n\n"
                    "Continue with PC -> USB push anyway?",
                )
            return self.messagebox.askyesno(
                title,
                f"Push the local PC source to this USB copy?\n\n{comparison.summary}",
            )

        title = "Confirm USB -> PC sync"
        if comparison.recommendation == "push_source_to_target":
            return self.messagebox.askyesno(
                title,
                "Warning: the PC source looks newer on average than the selected USB copy.\n\n"
                f"{comparison.summary}\n\n"
                "Pulling now may overwrite newer PC work. Continue anyway?",
            )
        if comparison.recommendation == "review":
            return self.messagebox.askyesno(
                title,
                "Warning: both sides have mixed newer components.\n\n"
                f"{comparison.summary}\n\n"
                "Continue with USB -> PC pull anyway?",
            )
        return self.messagebox.askyesno(
            title,
            f"Pull the selected USB copy back into the local PC source?\n\n{comparison.summary}",
        )

    def _begin_busy(self, label: str) -> None:
        self._busy = True
        self._set_status(label)
        self._update_action_states()

    def _finish_busy(self) -> None:
        self._busy = False
        self._update_action_states()

    # Alias used by GitHub worker threads
    _end_busy = _finish_busy

    def on_push_to_target(self) -> None:
        target = self._selected_target()
        snap = self._selected_status()
        if not target or snap is None:
            self.messagebox.showerror("No target", "Select a repo tile first.")
            return
        if not self._confirm_sync_direction("push", snap):
            return
        selected_app_names = self._selected_sync_app_names()
        if not selected_app_names:
            self.messagebox.showinfo("No apps selected", "Select at least one app in the app inclusion list.")
            return
        app_filtered = len(selected_app_names) < len(CITL_APPS)

        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        if app_filtered:
            include_models_effective = False
            model_source_dir = None
            model_target_dir = None
        else:
            model_plan = self._prepare_model_sync_plan(
                "PC -> USB push",
                self.source_repo,
                target,
            )
            if model_plan is None:
                return
            include_models_effective, model_source_dir, model_target_dir = model_plan
        try:
            _remember_target(target)
            self._mark_target_remembered(target)
        except Exception as e:
            self._append(f"[WARN] could not persist target memory before push: {e}\n")
        if app_filtered and (include_data or include_models):
            self._append("[APP-FILTER] include_data/include_models apply only to full-repo sync and are ignored in app-only mode.\n")

        self._begin_busy("Syncing PC source to selected USB copy...")
        self._append("\n[SYNC] starting PC -> USB push...\n")

        def worker() -> None:
            try:
                if app_filtered:
                    self.root.after(
                        0,
                        lambda n=selected_app_names: self._append(
                            f"[APP-FILTER] push limited to {len(n)} app(s): {', '.join(n)}\n"
                        ),
                    )
                    result = self._sync_selected_apps_only(
                        self.source_repo,
                        target,
                        selected_app_names,
                        log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                    )
                else:
                    result = sync_repo(
                        self.source_repo,
                        target,
                        include_data=include_data,
                        include_models=include_models_effective,
                        model_source_dir=model_source_dir,
                        model_target_dir=model_target_dir,
                        log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                    )
            except Exception as e:
                _append_device_push_log_entry(
                    {
                        "kind": "usb_push",
                        "status": "error",
                        "source_repo": str(self.source_repo),
                        "target_path": str(target),
                        "include_data": bool(include_data),
                        "include_models": bool(include_models_effective),
                        "error": str(e),
                    },
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda: self._append(f"[ERROR] push failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("PC -> USB push failed."))
            else:
                mode = "rsync" if result.used_rsync else "python-copy"
                _append_device_push_log_entry(
                    {
                        "kind": "usb_push",
                        "status": "ok" if result.errors == 0 else "partial",
                        "source_repo": str(self.source_repo),
                        "target_path": str(target),
                        "include_data": bool(include_data),
                        "include_models": bool(include_models_effective),
                        "copied": int(result.copied),
                        "skipped": int(result.skipped),
                        "errors": int(result.errors),
                        "elapsed_sec": float(result.elapsed_sec),
                    },
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(
                    0,
                    lambda: self._append(
                        f"[DONE] PC -> USB mode={mode} copied={result.copied} skipped={result.skipped} "
                        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s\n"
                    ),
                )
                # Auto-bump version numbers in source repo after successful push
                if result.errors == 0:
                    if not app_filtered:
                        self._sync_app_key_overlay(target, selected_app_names=selected_app_names)
                    bumped = []
                    apps_for_bump = self._selected_sync_apps() if app_filtered else list(CITL_APPS)
                    for app in apps_for_bump:
                        vf = app.get("version_file")
                        if vf and _bump_version_file(self.source_repo, vf):
                            bumped.append(vf)
                    if bumped:
                        self.root.after(0, lambda b=bumped: self._append(
                            f"[VERSION] auto-bumped patch in: {', '.join(b)}\n"
                        ))
                        self.root.after(0, self._render_apps_overview)
                self.root.after(0, lambda: self._set_status("PC -> USB push complete. Refreshing analysis..."))
            finally:
                self.root.after(0, self._after_sync_action)

        threading.Thread(target=worker, daemon=True).start()

    def on_pull_from_target(self) -> None:
        target = self._selected_target()
        snap = self._selected_status()
        if not target or snap is None:
            self.messagebox.showerror("No target", "Select a repo tile first.")
            return
        if not self._confirm_sync_direction("pull", snap):
            return
        selected_app_names = self._selected_sync_app_names()
        if not selected_app_names:
            self.messagebox.showinfo("No apps selected", "Select at least one app in the app inclusion list.")
            return
        app_filtered = len(selected_app_names) < len(CITL_APPS)

        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        if app_filtered:
            include_models_effective = False
            model_source_dir = None
            model_target_dir = None
        else:
            model_plan = self._prepare_model_sync_plan(
                "USB -> PC pull",
                target,
                self.source_repo,
            )
            if model_plan is None:
                return
            include_models_effective, model_source_dir, model_target_dir = model_plan
        if app_filtered and (include_data or include_models):
            self._append("[APP-FILTER] include_data/include_models apply only to full-repo sync and are ignored in app-only mode.\n")
        self._begin_busy("Syncing selected USB copy back to local PC source...")
        self._append("\n[SYNC] starting USB -> PC pull...\n")

        def worker() -> None:
            try:
                if app_filtered:
                    self.root.after(
                        0,
                        lambda n=selected_app_names: self._append(
                            f"[APP-FILTER] pull limited to {len(n)} app(s): {', '.join(n)}\n"
                        ),
                    )
                    result = self._sync_selected_apps_only(
                        target,
                        self.source_repo,
                        selected_app_names,
                        log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                    )
                else:
                    result = sync_repo(
                        target,
                        self.source_repo,
                        include_data=include_data,
                        include_models=include_models_effective,
                        model_source_dir=model_source_dir,
                        model_target_dir=model_target_dir,
                        log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                    )
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[ERROR] pull failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("USB -> PC pull failed."))
            else:
                mode = "rsync" if result.used_rsync else "python-copy"
                self.root.after(
                    0,
                    lambda: self._append(
                        f"[DONE] USB -> PC mode={mode} copied={result.copied} skipped={result.skipped} "
                        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s\n"
                    ),
                )
                self.root.after(0, lambda: self._set_status("USB -> PC pull complete. Refreshing analysis..."))
            finally:
                self.root.after(0, self._after_sync_action)

        threading.Thread(target=worker, daemon=True).start()

    def on_duplicate_usb(self) -> None:
        self._append("\n[SYNC] duplicate button pressed.\n")
        source_target = self._selected_target()
        if source_target is None:
            self.messagebox.showerror("No target", "Select the USB copy you want to duplicate from.")
            return
        selected_app_names = self._selected_sync_app_names()
        if not selected_app_names:
            self.messagebox.showinfo("No apps selected", "Select at least one app in the app inclusion list.")
            return
        app_filtered = len(selected_app_names) < len(CITL_APPS)
        picked = self._choose_duplicate_destination(source_target)
        if picked is None:
            self.messagebox.showerror(
                "No destination",
                f"No backup USB destination was detected. Connect another {_scope_label()} USB and refresh.",
            )
            return
        dest_target, comparison = picked
        if source_target == dest_target:
            self.messagebox.showerror("Invalid destination", "Source and destination USB paths are the same.")
            return

        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        if not self.messagebox.askyesno(
            "Confirm USB duplication",
            "Duplicate selected USB copy to backup USB?\n\n"
            f"From:\n{source_target}\n\n"
            f"To:\n{dest_target}\n\n"
            f"{comparison.summary}",
        ):
            return

        if app_filtered:
            include_models_effective = False
            model_source_dir = None
            model_target_dir = None
            if include_data or include_models:
                self._append("[APP-FILTER] include_data/include_models apply only to full-repo sync and are ignored in app-only mode.\n")
        else:
            model_plan = self._prepare_model_sync_plan(
                "USB -> USB duplicate",
                source_target,
                dest_target,
            )
            if model_plan is None:
                return
            include_models_effective, model_source_dir, model_target_dir = model_plan

        self._begin_busy("Duplicating selected USB copy to backup USB...")
        self._append("\n[SYNC] starting USB -> USB duplicate...\n")

        def worker() -> None:
            try:
                if app_filtered:
                    self.root.after(
                        0,
                        lambda n=selected_app_names: self._append(
                            f"[APP-FILTER] duplicate limited to {len(n)} app(s): {', '.join(n)}\n"
                        ),
                    )
                    result = self._sync_selected_apps_only(
                        source_target,
                        dest_target,
                        selected_app_names,
                        log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                    )
                else:
                    result = sync_repo(
                        source_target,
                        dest_target,
                        include_data=include_data,
                        include_models=include_models_effective,
                        model_source_dir=model_source_dir,
                        model_target_dir=model_target_dir,
                        log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                    )
            except Exception as e:
                _append_device_push_log_entry(
                    {
                        "kind": "usb_duplicate",
                        "status": "error",
                        "source_repo": str(source_target),
                        "target_path": str(dest_target),
                        "include_data": bool(include_data),
                        "include_models": bool(include_models_effective),
                        "error": str(e),
                    },
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda: self._append(f"[ERROR] duplicate failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("USB duplicate failed."))
            else:
                mode = "rsync" if result.used_rsync else "python-copy"
                _append_device_push_log_entry(
                    {
                        "kind": "usb_duplicate",
                        "status": "ok" if result.errors == 0 else "partial",
                        "source_repo": str(source_target),
                        "target_path": str(dest_target),
                        "include_data": bool(include_data),
                        "include_models": bool(include_models_effective),
                        "copied": int(result.copied),
                        "skipped": int(result.skipped),
                        "errors": int(result.errors),
                        "elapsed_sec": float(result.elapsed_sec),
                    },
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(
                    0,
                    lambda: self._append(
                        f"[DONE] USB duplicate mode={mode} copied={result.copied} skipped={result.skipped} "
                        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s\n"
                    ),
                )
                if result.errors == 0:
                    if not app_filtered:
                        self._sync_app_key_overlay(dest_target, selected_app_names=selected_app_names)
                self.root.after(0, lambda: self._set_status("USB duplicate complete. Refreshing analysis..."))
            finally:
                self.root.after(0, self._after_sync_action)

        threading.Thread(target=worker, daemon=True).start()

    def on_send_target_to_phone(self) -> None:
        target = self._selected_target()
        device = self._selected_device()
        if target is None:
            self.messagebox.showerror("No target", "Select the USB copy you want to send to the phone.")
            return
        if device is None:
            self.messagebox.showerror("No phone", "No Android phone is selected. Connect one over ADB first.")
            return

        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        if not self.messagebox.askyesno(
            "Confirm USB -> phone export",
            "Create a ZIP bundle from the selected repo copy and push it to the phone's Downloads folder?\n"
            f"Termux shortcuts will be preserved (backup) and a fresh {_scope_label()} launch shortcut will be written.\n\n"
            f"Selected copy:\n{target}\n\n"
            f"Phone:\n{self._device_label(device)}\n\n"
            f"Include data/indexes: {'yes' if include_data else 'no'}\n"
            f"Include models/ollama: {'yes' if include_models else 'no'}\n",
        ):
            return

        self._begin_busy("Building ZIP and sending selected copy to phone...")
        self._append("\n[PHONE] starting USB -> phone export...\n")

        def worker() -> None:
            try:
                result = push_repo_archive_to_phone(
                    target,
                    device.serial,
                    include_data=include_data,
                    include_models=include_models,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[ERROR] phone export failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("USB -> phone export failed."))
            else:
                self.root.after(
                    0,
                    lambda: self._append(
                        f"[DONE] phone export files={result['file_count']} bytes={result['byte_count']} "
                        f"elapsed={result['elapsed_sec']:.1f}s remote={result['remote_path']} serial={result['serial']}\n"
                    ),
                )
                if bool(result.get("termux_backup_ok")):
                    self.root.after(
                        0,
                        lambda: self._append(
                            f"[TERMUX] shortcut backup saved: {result.get('termux_backup_path')}\n"
                        ),
                    )
                else:
                    self.root.after(
                        0,
                        lambda: self._append("[TERMUX][WARN] no existing shortcuts were captured before push.\n"),
                    )
                shortcut_note = str(result.get("termux_shortcut_note") or "").strip()
                if bool(result.get("termux_shortcut_ok")):
                    self.root.after(0, lambda: self._append("[TERMUX] shortcut updated for latest pushed app.\n"))
                elif shortcut_note:
                    self.root.after(0, lambda n=shortcut_note: self._append(f"[TERMUX][WARN] {n}\n"))
                self.root.after(0, lambda: self._set_status("USB -> phone export complete."))
            finally:
                self.root.after(0, self._after_phone_action)

        threading.Thread(target=worker, daemon=True).start()

    def _after_sync_action(self) -> None:
        self._finish_busy()
        self.refresh_targets()

    def _after_phone_action(self) -> None:
        self._finish_busy()
        self.refresh_targets()

    def on_sync(self) -> None:
        self.on_push_to_target()

    def run(self) -> None:
        self.root.mainloop()


def launch_sync_gui(source_repo: PathLike, source_reason: str = "", source_freshness_ts: float = 0.0) -> None:
    gui = SyncGUI(
        source_repo=source_repo,
        source_reason=source_reason,
        source_freshness_ts=source_freshness_ts,
    )
    gui.run()


def _print_detect_json(source: SourceDetection) -> int:
    targets = discover_sync_targets(source.path)
    target_rows: List[dict] = []
    for t in targets:
        freshness_ts = _repo_freshness(t.path)
        comparison = compare_repo_freshness(source.path, t.path)
        target_rows.append(
            {
                "path": str(t.path),
                "score": t.score,
                "has_git": t.has_git,
                "markers": list(t.markers),
                "root": str(t.root),
                "root_label": _root_label(t.root),
                "remembered": t.remembered,
                "freshness_ts": freshness_ts,
                "freshness_local": _fmt_ts(freshness_ts),
                "comparison": {
                    "recommendation": comparison.recommendation,
                    "summary": comparison.summary,
                    "source_newer": comparison.source_newer,
                    "target_newer": comparison.target_newer,
                    "source_only": comparison.source_only,
                    "target_only": comparison.target_only,
                },
            }
        )
    payload = {
        "app": {
            "name": APP_SYNC_NAME,
            "version": APP_SYNC_VERSION,
        },
        "source": {
            "path": str(source.path),
            "reason": source.reason,
            "freshness_ts": source.freshness_ts,
            "freshness_local": _fmt_ts(source.freshness_ts),
        },
        "targets": target_rows,
        "phones": [
            {
                "serial": item.serial,
                "state": item.state,
                "meta": item.meta,
            }
            for item in connected_phone_devices()
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


def _parse_bootstrap_apps(raw: str) -> List[str]:
    out: List[str] = []
    for part in (raw or "").split(","):
        name = part.strip()
        if name:
            out.append(name)
    return out


def _resolve_bootstrap_target(source: SourceDetection, target_raw: str) -> Optional[Path]:
    text = (target_raw or "local").strip().lower()
    if text in ("", "local", "pc", "source"):
        return source.path
    if text in ("best-usb", "usb", "auto-usb"):
        picked = _select_best_usb_target_for_push(source.path)
        if picked is None:
            return None
        return picked[0].path
    return _normalize_repo_path(target_raw)


def _resolve_bootstrap_package_path(source: SourceDetection, raw: str) -> Optional[Path]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.lower() in ("latest", "newest", "auto"):
        found = discover_bootstrap_packages([("local-source", source.path)])
        return found[0].path if found else None
    p = _normalize_repo_path(text)
    if p is None:
        return None
    return p


def _copy_bootstrap_assets_to_repo(
    source_repo: PathLike,
    package: BootstrapPackage,
    dest_repo: PathLike,
    log_fn: LogFn = None,
) -> Tuple[bool, str]:
    src_repo = Path(source_repo).expanduser().resolve()
    dst_repo = Path(dest_repo).expanduser().resolve()
    dst_dir = dst_repo / BOOTSTRAP_PATCH_DIR_REL
    dst_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    errors = 0

    try:
        dst_pkg = dst_dir / package.path.name
        if _needs_copy(package.path, dst_pkg):
            shutil.copy2(package.path, dst_pkg)
            copied += 1
        else:
            skipped += 1
    except Exception as e:
        errors += 1
        _safe_log(log_fn, f"[PATCH-ASSET][ERR] package copy failed: {e}\n")

    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", package.bootstrap_id).strip("_") or "bootstrap"
    src_patch_dir = src_repo / BOOTSTRAP_PATCH_DIR_REL
    for ext in ("ps1", "bat", "sh"):
        src_script = src_patch_dir / f"apply_bootstrap_{slug}.{ext}"
        if not src_script.is_file():
            continue
        try:
            dst_script = dst_dir / src_script.name
            if _needs_copy(src_script, dst_script):
                shutil.copy2(src_script, dst_script)
                copied += 1
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            _safe_log(log_fn, f"[PATCH-ASSET][ERR] script copy failed ({src_script.name}): {e}\n")

    msg = f"copied={copied} skipped={skipped} errors={errors} dest={dst_dir}"
    return errors == 0, msg


def _run_patch_cadence(args: argparse.Namespace, source: SourceDetection) -> int:
    cadence_hours = max(1, int(getattr(args, "patch_cadence_hours", DEFAULT_PATCH_CADENCE_HOURS) or DEFAULT_PATCH_CADENCE_HOURS))
    cadence_window_sec = float(cadence_hours) * 3600.0
    now_ts = time.time()
    since_ts = now_ts - cadence_window_sec
    manual_mode = bool(getattr(args, "manual_patch", False))
    force_mode = bool(getattr(args, "force_patch", False))
    target_mode = str(getattr(args, "patch_apply_target", "both") or "both").strip().lower()
    if target_mode not in {"none", "local", "usb", "both"}:
        print(f"[ERROR] invalid --patch-apply-target: {target_mode}")
        return 2

    raw_apps = _parse_bootstrap_apps(str(getattr(args, "patch_apps", "") or ""))
    selected_apps = raw_apps if raw_apps else _default_cadence_app_names()
    if not selected_apps:
        print("[ERROR] No apps selected for patch cadence run.")
        return 2

    state = load_patch_cadence_state(source.path)
    last_auto_ts = float(state.get("last_auto_run_ts") or 0.0)
    if (not manual_mode) and (not force_mode) and last_auto_ts > 0:
        elapsed = now_ts - last_auto_ts
        if elapsed + UPDATE_AVAILABLE_EPSILON_SEC < cadence_window_sec:
            wait_sec = max(0.0, cadence_window_sec - elapsed)
            print(
                f"[PATCH-CADENCE] skipped: last auto run {_fmt_ts(last_auto_ts)}; "
                f"next auto window in {int(wait_sec // 3600)}h {int((wait_sec % 3600) // 60)}m."
            )
            return 0

    changes = _collect_app_changes_since(source.path, selected_apps, since_ts)
    changed_apps = sorted(changes.keys())
    if (not changed_apps) and (not force_mode):
        print(
            f"[PATCH-CADENCE] no app key-file changes detected in last {cadence_hours}h "
            f"across {len(selected_apps)} selected app(s)."
        )
        return 0

    build_apps = changed_apps if changed_apps else list(selected_apps)
    tag_prefix = "M" if manual_mode else "A"
    reason = f"{'manual' if manual_mode else 'auto'}_{cadence_hours}h"

    print(f"[PATCH-CADENCE] source={source.path}")
    print(f"[PATCH-CADENCE] mode={'manual' if manual_mode else 'auto'} cadence={cadence_hours}h apps={len(build_apps)}")
    if changed_apps:
        for app_name in changed_apps:
            item = changes.get(app_name) or {}
            print(
                f"[PATCH-CADENCE]   {app_name}: changed={item.get('changed_file_count', 0)} "
                f"newest={item.get('newest_utc', '-')}"
            )
    elif force_mode:
        print("[PATCH-CADENCE] force mode active: packaging selected apps even without recent file changes.")

    ok_build, msg_build, package = build_bootstrap_package(
        source.path,
        selected_apps=build_apps,
        tag_prefix=tag_prefix,
        build_reason=reason,
        log_fn=lambda s: print(s, end=""),
    )
    print(f"[PATCH-CADENCE] {'OK' if ok_build else 'FAIL'} {msg_build}")
    if (not ok_build) or package is None:
        return 4

    history = list(state.get("history") or []) if isinstance(state.get("history"), list) else []
    history.append(
        {
            "ran_utc": _utc_now_iso(),
            "manual": manual_mode,
            "cadence_hours": cadence_hours,
            "package_id": package.bootstrap_id,
            "package_path": str(package.path),
            "changed_apps": changed_apps,
            "selected_apps": build_apps,
            "target_mode": target_mode,
        }
    )
    state["history"] = history[-120:]
    if manual_mode:
        state["last_manual_run_utc"] = _utc_now_iso()
        state["last_manual_run_ts"] = now_ts
        state["last_manual_package_id"] = package.bootstrap_id
    else:
        state["last_auto_run_utc"] = _utc_now_iso()
        state["last_auto_run_ts"] = now_ts
        state["last_auto_package_id"] = package.bootstrap_id
    save_patch_cadence_state(source.path, state)

    total_errors = 0
    if target_mode in {"local", "both"}:
        ok_local, msg_local = apply_bootstrap_package_to_repo(
            package,
            source.path,
            selected_apps=build_apps,
            log_fn=lambda s: print(s, end=""),
        )
        print(f"[PATCH-CADENCE][LOCAL] {'OK' if ok_local else 'WARN'} {msg_local}")
        if not ok_local:
            total_errors += 1

    if target_mode in {"usb", "both"}:
        usb_target = _resolve_bootstrap_target(source, "best-usb")
        if usb_target is None:
            print("[PATCH-CADENCE][USB][WARN] No USB target detected.")
            total_errors += 1
        else:
            ok_usb, msg_usb = apply_bootstrap_package_to_repo(
                package,
                usb_target,
                selected_apps=build_apps,
                log_fn=lambda s: print(s, end=""),
            )
            print(f"[PATCH-CADENCE][USB] {'OK' if ok_usb else 'WARN'} {msg_usb}")
            if not ok_usb:
                total_errors += 1
            ok_assets, msg_assets = _copy_bootstrap_assets_to_repo(
                source.path,
                package,
                usb_target,
                log_fn=lambda s: print(s, end=""),
            )
            print(f"[PATCH-CADENCE][USB-ASSETS] {'OK' if ok_assets else 'WARN'} {msg_assets}")
            if not ok_assets:
                total_errors += 1

    return 0 if total_errors == 0 else 1


def _run_bootstrap_install(args: argparse.Namespace, source: SourceDetection) -> int:
    pkg_path = _resolve_bootstrap_package_path(source, args.bootstrap_install_package)
    if pkg_path is None or not pkg_path.exists():
        print(f"[ERROR] Bootstrap package not found: {args.bootstrap_install_package}")
        return 2
    package = _package_from_manifest(pkg_path, source_hint="headless")
    if package is None:
        print(f"[ERROR] Invalid bootstrap package manifest: {pkg_path}")
        return 2

    apps = _parse_bootstrap_apps(getattr(args, "bootstrap_apps", "") or "")
    target = _resolve_bootstrap_target(source, getattr(args, "bootstrap_install_target", "local") or "local")
    if target is None:
        print("[ERROR] Bootstrap target could not be resolved.")
        return 2
    if not target.exists():
        print(f"[ERROR] Bootstrap target does not exist: {target}")
        return 2

    preview = preview_bootstrap_install(package, target, apps)
    print(
        f"[BOOTSTRAP][PREVIEW] target={target} classification={preview.classification} "
        f"new={preview.newer_apps} same={preview.same_apps} older={preview.older_apps}"
    )
    if preview.stale and not bool(getattr(args, "allow_retractive_bootstrap", False)):
        print(f"[ERROR] stale/retractive bootstrap blocked: {preview.stale_reason}")
        print("        Re-run with --allow-retractive-bootstrap to override.")
        return 3

    ok, msg = apply_bootstrap_package_to_repo(
        package,
        target,
        selected_apps=apps,
        log_fn=lambda s: print(s, end=""),
    )
    print(f"[BOOTSTRAP] {'OK' if ok else 'WARN'} {msg}")
    rc = 0 if ok else 4

    if bool(getattr(args, "bootstrap_install_usb_if_found", False)):
        usb_targets = discover_sync_targets(source.path)
        pushed = 0
        for item in usb_targets:
            usb_path = item.path
            try:
                if usb_path.resolve() == target.resolve():
                    continue
            except Exception:
                if str(usb_path) == str(target):
                    continue
            media_ok, media_reason = is_expected_usb_bootstrap_media(usb_path)
            print(f"[BOOTSTRAP][USB-CHECK] {media_reason} -> {'OK' if media_ok else 'SKIP'}")
            if not media_ok:
                continue
            usb_preview = preview_bootstrap_install(package, usb_path, apps)
            if usb_preview.stale and not bool(getattr(args, "allow_retractive_bootstrap", False)):
                print(f"[BOOTSTRAP][USB-SKIP] stale/retractive blocked for {usb_path}: {usb_preview.stale_reason}")
                continue
            ok_usb, msg_usb = apply_bootstrap_package_to_repo(
                package,
                usb_path,
                selected_apps=apps,
                log_fn=lambda s: print(s, end=""),
            )
            print(f"[BOOTSTRAP][USB] {'OK' if ok_usb else 'WARN'} {msg_usb}")
            if ok_usb:
                pushed += 1
            else:
                rc = 4
        print(f"[BOOTSTRAP][USB] applied to {pushed} eligible USB repo(s).")

    return rc


def _run_bootstrap_rollback(args: argparse.Namespace, source: SourceDetection) -> int:
    target = _resolve_bootstrap_target(source, getattr(args, "bootstrap_rollback_target", "local") or "local")
    if target is None:
        print("[ERROR] Rollback target could not be resolved.")
        return 2
    ok, msg = rollback_last_bootstrap_on_repo(target, log_fn=lambda s: print(s, end=""))
    print(f"[BOOTSTRAP][ROLLBACK] {'OK' if ok else 'WARN'} {msg}")
    return 0 if ok else 4


def _run_headless_sync(args: argparse.Namespace, source: SourceDetection) -> int:
    print(f"[SOURCE] {source.path} ({source.reason})")
    model_source_arg = (getattr(args, "ollama_model_source", "") or "").strip()
    model_target_arg = (getattr(args, "ollama_model_target", "") or "").strip()
    if bool(args.include_models) and (not model_source_arg or not model_target_arg):
        print(
            "[WARN] --include-models set without both --ollama-model-source and "
            "--ollama-model-target; external Ollama model store copy will be skipped "
            "(repo-local models/ollama folders still sync)."
        )
    result = sync_repo(
        source.path,
        args.sync,
        include_data=bool(args.include_data),
        include_models=bool(args.include_models),
        model_source_dir=(model_source_arg or None),
        model_target_dir=(model_target_arg or None),
        log_fn=lambda s: print(s, end=""),
    )
    mode = "rsync" if result.used_rsync else "python-copy"
    print(
        f"[DONE] mode={mode} copied={result.copied} skipped={result.skipped} "
        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s"
    )
    return 0


def _default_source() -> Path:
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller EXE.  Honour CITL_REPO env if set; otherwise
        # walk up 3 levels from EXE: dist/AppName/App.exe -> CITL/
        env_keys = ["CITL_REPO"]
        if ACTIVE_SYNC_SCOPE == SYNC_SCOPE_HENOSIS:
            env_keys = ["HENOSIS_REPO", "CITL_REPO"]
        env_repo = ""
        for key in env_keys:
            raw = (os.environ.get(key) or "").strip()
            if raw:
                env_repo = raw
                break
        if env_repo and Path(env_repo).is_dir():
            return Path(env_repo)
        return Path(sys.executable).parent.parent.parent
    return Path(__file__).resolve().parent.parent


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Cross-platform app sync utility (CITL/HENOSIS scope)")
    ap.add_argument(
        "--sync-scope",
        default=_default_sync_scope(),
        choices=[SYNC_SCOPE_CITL, SYNC_SCOPE_HENOSIS],
        help="Sync scope profile: citl | henosis",
    )
    ap.add_argument("--version", action="store_true", help="Print sync utility version and exit")
    ap.add_argument(
        "--source",
        default="auto",
        help="Source repo path or 'auto' (desktop local repo first, else most recently updated local repo)",
    )
    ap.add_argument("--detect-json", action="store_true", help="Print detected targets as JSON and exit")
    ap.add_argument("--sync", default="", help="Sync source repo to this target path (headless)")
    ap.add_argument(
        "--sync-best-usb",
        action="store_true",
        help="Auto-detect the best USB target and push PC app files to it (headless)",
    )
    ap.add_argument(
        "--target-path",
        default="",
        help="Explicit target repo path for --sync-best-usb (bypasses auto target selection)",
    )
    ap.add_argument(
        "--duplicate-usb",
        action="store_true",
        help="Duplicate one USB scoped repo copy to another USB target (headless)",
    )
    ap.add_argument("--duplicate-from", default="", help="Source USB repo path for --duplicate-usb")
    ap.add_argument("--duplicate-to", default="", help="Destination USB repo path for --duplicate-usb")
    ap.add_argument(
        "--smoke-test",
        action="store_true",
        help="With --duplicate-usb, validate configuration without copying (diagnostic mode)",
    )
    ap.add_argument("--include-data", action="store_true", help="Include data/ and index folders in sync")
    ap.add_argument("--include-models", action="store_true", help="Include models/ and ollama/ in sync")
    ap.add_argument("--ollama-model-source", default="", help="Optional external Ollama model source directory")
    ap.add_argument("--ollama-model-target", default="", help="Optional external Ollama model target directory")
    ap.add_argument(
        "--no-app-key-sync",
        action="store_true",
        help="With --sync-best-usb, skip per-app key-file sync pass",
    )
    ap.add_argument(
        "--full-repo-sync",
        action="store_true",
        help="With --sync-best-usb, also perform full repo copy (slower)",
    )
    ap.add_argument(
        "--push-target-to-phone",
        action="store_true",
        help="After sync/duplicate, zip selected target and push it to phone Downloads via ADB",
    )
    ap.add_argument(
        "--phone-serial",
        default="auto",
        help="ADB phone serial to use with --push-target-to-phone (default: auto)",
    )
    ap.add_argument(
        "--bootstrap-install-package",
        default="",
        help="Install a bootstrap package ZIP path, or 'latest' for newest package in source repo",
    )
    ap.add_argument(
        "--bootstrap-install-target",
        default="local",
        help="Bootstrap install target: local | best-usb | <explicit path>",
    )
    ap.add_argument(
        "--bootstrap-install-usb-if-found",
        action="store_true",
        help="With --bootstrap-install-package, also apply to eligible USB repo copies (exfat/fat32 and ~40-80GB)",
    )
    ap.add_argument(
        "--bootstrap-apps",
        default="",
        help="Comma-separated app names to selectively apply from bootstrap package",
    )
    ap.add_argument(
        "--allow-retractive-bootstrap",
        action="store_true",
        help="Allow applying stale/retractive bootstrap packages",
    )
    ap.add_argument(
        "--bootstrap-rollback-target",
        default="",
        help="Rollback last bootstrap on target: local | best-usb | <explicit path>",
    )
    ap.add_argument(
        "--patch-cadence",
        action="store_true",
        help="Build a cadence patch from recently changed app files (48h default) and optionally apply to local/USB.",
    )
    ap.add_argument(
        "--patch-cadence-hours",
        type=int,
        default=DEFAULT_PATCH_CADENCE_HOURS,
        help="Change window for --patch-cadence in hours (default: 48).",
    )
    ap.add_argument(
        "--manual-patch",
        action="store_true",
        help="With --patch-cadence, mark package tag prefix as 'M' (manual).",
    )
    ap.add_argument(
        "--force-patch",
        action="store_true",
        help="With --patch-cadence, package selected apps even when no recent changes were detected.",
    )
    ap.add_argument(
        "--patch-apply-target",
        default="both",
        help="With --patch-cadence: none | local | usb | both (default: both).",
    )
    ap.add_argument(
        "--patch-apps",
        default="",
        help="Comma-separated app names for --patch-cadence (default: all CITL-scope apps).",
    )
    args = ap.parse_args(argv)
    _apply_sync_scope(getattr(args, "sync_scope", _default_sync_scope()))

    if args.version:
        print(f"{APP_SYNC_NAME} {APP_SYNC_VERSION}")
        return 0

    try:
        source = detect_source_repo(args.source, default_source=_default_source())
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return 2
    except Exception as e:
        print(f"[ERROR] source detection failed: {e}")
        return 2

    if args.bootstrap_install_package:
        return _run_bootstrap_install(args, source)
    if args.bootstrap_rollback_target:
        return _run_bootstrap_rollback(args, source)
    if args.patch_cadence:
        return _run_patch_cadence(args, source)
    if args.detect_json:
        return _print_detect_json(source)
    if args.duplicate_usb:
        return _run_duplicate_usb(args, source)
    if args.sync_best_usb:
        return _run_sync_best_usb(args, source)
    if args.sync:
        return _run_headless_sync(args, source)

    launch_sync_gui(source.path, source.reason, source.freshness_ts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



