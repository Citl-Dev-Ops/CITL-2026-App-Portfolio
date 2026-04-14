#!/usr/bin/env python3
"""
CITL AV/IT Operations Tool
Room inventory, inspection checklists, patch procedure documentation,
and AV driver triage - portfolio-ready exports for IT staff and workstudy.
"""
from __future__ import annotations
import csv, json, os, subprocess, sys, threading
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:
    sys.exit("tkinter required")

_HERE = Path(__file__).parent
REPO  = _HERE.parent if not getattr(sys, "frozen", False) else Path(sys.executable).parent.parent.parent
EXPORTS_DIR = REPO / "documents" / "av_it_ops"

C = {
    "bg":"#0D1B2A","panel":"#112236","panel_alt":"#162B40","notebk":"#0C1A2C",
    "card_sel":"#1E4060","text":"#D4E4F5","muted":"#7A9BBE","faint":"#3E5A78",
    "accent":"#3A8FD4","gold":"#E89820","btn":"#1A3550","btn_hi":"#235272",
    "btn_acc":"#1A4A7A","btn_gold":"#5A3A00","line":"#1D3050","good":"#1E5C30",
}
_F = "Segoe UI" if sys.platform == "win32" else "Ubuntu"
APP_NAME = "CITL AV/IT Operations"
APP_VERSION = "v1.3"

ROOM_FIELDS = ["Room ID", "Building", "Floor", "Projector Model", "Projector SN",
               "Display Type", "PC Hostname", "PC Model", "Webcam Model",
               "Microphone Type", "Audio Interface", "HDMI Switcher",
               "Zoom Certified", "Last Inspected", "Notes"]

INSPECTION_ITEMS = [
    ("Projector / Display", [
        "Display powers on without error",
        "Correct resolution on all outputs",
        "Remote or control panel functional",
        "Lens clean, no visible damage",
    ]),
    ("Audio System", [
        "Microphone(s) functional in Zoom/Teams",
        "Speaker output clear, no feedback/hum",
        "Audio interface drivers installed + current",
        "Volume controls accessible to instructor",
    ]),
    ("PC & Network", [
        "PC boots to desktop, no errors",
        "Network connection stable (>=100 Mbps)",
        "Windows / macOS updates current",
        "Zoom / Teams installed and updated",
    ]),
    ("Cables & Connectivity", [
        "All HDMI/DisplayPort cables seated",
        "USB hub functional for peripherals",
        "Webcam recognized in device manager",
        "No frayed or damaged cabling",
    ]),
    ("Security & Access", [
        "Login credentials posted / accessible",
        "Screen lock policy active",
        "No unauthorized software installed",
        "Asset tag visible and unobscured",
    ]),
]

PATCH_SEVERITY = ["Critical", "High", "Medium", "Low", "Informational"]
TICKET_TYPES = [
    "Incident",
    "Service Request",
    "Problem",
    "Change",
    "Preventive Maintenance",
]
TICKET_PRIORITIES = ["P1 - Critical", "P2 - High", "P3 - Medium", "P4 - Low"]
TICKET_STATUSES = ["New", "In Progress", "Pending User", "Resolved", "Closed"]
TICKET_COLUMNS = [
    "Ticket ID",
    "Type",
    "Priority",
    "Status",
    "Room",
    "Asset",
    "Assigned To",
    "Opened",
    "Resolved",
    "SLA",
]
TICKET_TEMPLATE_PRESETS = {
    "Display no signal": {
        "Type": "Incident",
        "Priority": "P2 - High",
        "Status": "In Progress",
        "Summary": "Instructor reports projector/display shows no signal from podium PC.",
        "Root Cause": "Loose HDMI cable or input source switched at display endpoint.",
        "Resolution": (
            "1. Validate display input source.\n"
            "2. Reseat HDMI/DP at source and sink.\n"
            "3. Test fallback cable and adapter.\n"
            "4. Confirm expected resolution and refresh.\n"
            "5. Record corrective action."
        ),
    },
    "Zoom camera not detected": {
        "Type": "Incident",
        "Priority": "P2 - High",
        "Status": "In Progress",
        "Summary": "Zoom/Teams cannot detect classroom camera device.",
        "Root Cause": "USB hub path failure or camera driver service not loaded.",
        "Resolution": (
            "1. Check camera in Device Manager.\n"
            "2. Reconnect USB path and power-cycle hub.\n"
            "3. Reinstall/repair camera driver.\n"
            "4. Validate in Zoom and Teams test call.\n"
            "5. Document final firmware/driver version."
        ),
    },
    "Audio feedback/hum": {
        "Type": "Incident",
        "Priority": "P3 - Medium",
        "Status": "In Progress",
        "Summary": "Room reports persistent feedback/hum during hybrid session.",
        "Root Cause": "Gain staging mismatch or duplicate loopback audio routes.",
        "Resolution": (
            "1. Isolate microphone channel producing feedback.\n"
            "2. Reduce gain and disable duplicate monitor path.\n"
            "3. Verify echo-cancellation setting in conferencing app.\n"
            "4. Run spoken-word validation at target volume.\n"
            "5. Capture before/after config values."
        ),
    },
    "Patch compliance overdue": {
        "Type": "Change",
        "Priority": "P2 - High",
        "Status": "New",
        "Summary": "Endpoint patch compliance below baseline for AV classroom fleet.",
        "Root Cause": "Deferred updates and inconsistent maintenance window coverage.",
        "Resolution": (
            "1. Build endpoint list by risk class.\n"
            "2. Test cumulative update on pilot room.\n"
            "3. Schedule staged rollout by building.\n"
            "4. Verify service health and rollback readiness.\n"
            "5. Publish completion metrics."
        ),
    },
}
PATCH_WIZARD_PRESETS = {
    "Windows monthly security rollup": {
        "title": "Monthly security rollup with staged deployment and rollback readiness.",
        "affected": "Windows endpoints in RTC classrooms and instructor podium systems.",
        "steps": (
            "1. Verify endpoint snapshot/restore point.\n"
            "2. Download approved cumulative update package.\n"
            "3. Apply in pilot classroom set.\n"
            "4. Validate AV devices, Zoom, browser playback, and USB peripherals.\n"
            "5. Roll out to production by building wave.\n"
            "6. Record KB number and completion metrics."
        ),
        "rollback": (
            "1. Uninstall update KB if regression confirmed.\n"
            "2. Reboot endpoint and validate classroom baseline.\n"
            "3. Re-enable update hold until vendor advisory is reviewed."
        ),
        "verify": "Confirm patch level, AV signal chain, conferencing tests, and classroom launch checklist.",
        "change": "Reference maintenance window ticket, stakeholder comms, and approval chain.",
    },
    "AV driver/firmware refresh": {
        "title": "Driver or firmware update for projector, camera, or audio endpoint.",
        "affected": "AV endpoints listed in room inventory and related USB interfaces.",
        "steps": (
            "1. Capture current firmware/driver version.\n"
            "2. Export existing device configuration.\n"
            "3. Apply vendor-approved update package.\n"
            "4. Validate signal, audio, and camera path end-to-end.\n"
            "5. Document final versions and room validation evidence."
        ),
        "rollback": (
            "1. Reinstall prior stable driver/firmware.\n"
            "2. Restore exported configuration profile.\n"
            "3. Confirm classroom baseline functionality."
        ),
        "verify": "Run full classroom media test matrix and instructor podium checklist.",
        "change": "Attach vendor advisory, test evidence, and room impact summary.",
    },
}
RTC_CATALOG_EXTS = {".csv", ".json"}
RTC_CATALOG_KEYWORDS = ("room", "rtc", "class", "building", "display", "inventory")
RTC_DEFAULT_SOURCE_ROOT = Path(os.environ.get("CITL_DISPLAY_SOURCE_ROOT", "K:\\"))
DISPLAY_UTILITY_CANDIDATES = (
    REPO / "CITL_Toolkit" / "RUN__CITL__DISPLAY_PROFILES.cmd",
    REPO / "CITL_Toolkit" / "LAUNCH_DisplayProfile_GUI.cmd",
    REPO / "CITL_Toolkit" / "CITL_DisplayProfile_GUI.ps1",
    REPO / "CITL_Toolkit" / "CITL_Launcher.ps1",
    Path("K:/PORTABLE_APPS/CITL/CITL_Toolkit/RUN__CITL__DISPLAY_PROFILES.cmd"),
    Path("K:/PORTABLE_APPS/CITL/CITL_Toolkit/LAUNCH_DisplayProfile_GUI.cmd"),
    Path("K:/PORTABLE_APPS/CITL/CITL_Toolkit/CITL_DisplayProfile_GUI.ps1"),
)

RTC_FIELD_MAP = {
    "room id": "Room ID",
    "room number": "Room ID",
    "room no": "Room ID",
    "room name": "Room ID",
    "roomid": "Room ID",
    "room": "Room ID",
    "classroom": "Room ID",
    "building": "Building",
    "building name": "Building",
    "bldg": "Building",
    "campus building": "Building",
    "floor": "Floor",
    "level": "Floor",
    "story": "Floor",
    "projector model": "Projector Model",
    "projector": "Projector Model",
    "projector serial": "Projector SN",
    "projector sn": "Projector SN",
    "projector serial number": "Projector SN",
    "display type": "Display Type",
    "display": "Display Type",
    "pc hostname": "PC Hostname",
    "computer name": "PC Hostname",
    "hostname": "PC Hostname",
    "pc model": "PC Model",
    "computer model": "PC Model",
    "webcam": "Webcam Model",
    "webcam model": "Webcam Model",
    "microphone": "Microphone Type",
    "microphone type": "Microphone Type",
    "audio interface": "Audio Interface",
    "hdmi switcher": "HDMI Switcher",
    "zoom certified": "Zoom Certified",
    "last inspected": "Last Inspected",
    "notes": "Notes",
}


def _norm_key(raw: str) -> str:
    return " ".join(str(raw or "").strip().lower().replace("_", " ").split())


def _iter_catalog_files(root: Path, max_depth: int = 6) -> Iterable[Path]:
    queue: List[Tuple[Path, int]] = [(root, 0)]
    seen: set = set()
    while queue:
        cur, depth = queue.pop(0)
        key = str(cur).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            entries = list(os.scandir(cur))
        except Exception:
            continue
        for e in entries:
            p = Path(e.path)
            name_l = e.name.lower()
            if e.is_file(follow_symlinks=False):
                if p.suffix.lower() in RTC_CATALOG_EXTS and any(k in name_l for k in RTC_CATALOG_KEYWORDS):
                    yield p
            elif e.is_dir(follow_symlinks=False) and depth < max_depth:
                if depth == 0 or any(k in name_l for k in ("citl", "rtc", "display", "room", "inventory", "toolkit", "portable")):
                    queue.append((p, depth + 1))


def _canonical_room_record(raw: Dict[str, str]) -> Optional[dict]:
    record = {k: "" for k in ROOM_FIELDS}
    normalized_raw: Dict[str, str] = {}
    for key, val in raw.items():
        nkey = _norm_key(key)
        normalized_raw[nkey] = str(val or "").strip()
        mapped = RTC_FIELD_MAP.get(nkey)
        if mapped:
            record[mapped] = str(val or "").strip()
    rid = record.get("Room ID", "").strip()
    if not rid:
        for raw_key in ("room number", "room no", "room name", "classroom", "name", "location"):
            val = normalized_raw.get(raw_key, "").strip()
            if val:
                rid = val
                break
    if not record.get("Building", "").strip():
        for raw_key in ("building name", "bldg", "campus building"):
            val = normalized_raw.get(raw_key, "").strip()
            if val:
                record["Building"] = val
                break
    if not record.get("Floor", "").strip():
        for raw_key in ("level", "story"):
            val = normalized_raw.get(raw_key, "").strip()
            if val:
                record["Floor"] = val
                break
    if not rid:
        bldg = record.get("Building", "").strip()
        loc = normalized_raw.get("location", "").strip()
        if bldg and loc:
            rid = f"{bldg}-{loc}"
    record["Room ID"] = rid.strip()
    if not rid:
        return None
    if not record.get("Last Inspected"):
        record["Last Inspected"] = str(date.today())
    return record


class AVITOps:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"{APP_NAME}  {APP_VERSION}")
        root.configure(bg=C["bg"])
        root.minsize(1000, 660)
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

        self.rooms: List[dict] = []
        self.rtc_rooms: List[dict] = []
        self.rtc_source_path: Optional[Path] = None
        self.rtc_buildings: List[str] = []
        self.rtc_rooms_by_building: Dict[str, List[dict]] = {}
        self.tickets: List[dict] = []
        self.inspection_vars: dict = {}   # {category: {item: BooleanVar}}
        self.status_var = tk.StringVar(value="Ready")
        self.rtc_status_var = tk.StringVar(value="RTC catalog: not loaded")
        self.rtc_source_var = tk.StringVar(value=f"Source: {RTC_DEFAULT_SOURCE_ROOT}")
        self.student_name_var = tk.StringVar(value=os.environ.get("CITL_STUDENT_NAME", "").strip())
        self.portfolio_project_var = tk.StringVar(value="CITL_AV_IT_Portfolio_Project")
        self.role_focus_var = tk.StringVar(value="AV/IT Operations Workstudy")
        self.artifact_prefix_var = tk.StringVar(value="citl_avit")
        self.inv_building_var = tk.StringVar(value="")
        self.inv_room_var = tk.StringVar(value="")

        self._build_ui()
        self.root.after(250, self._auto_load_rtc_catalog)

    #  UI 

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg=C["panel"]); hdr.pack(fill="x")
        tk.Frame(hdr, bg=C["gold"], height=3).pack(fill="x")
        hi = tk.Frame(hdr, bg=C["panel"]); hi.pack(fill="x", padx=14, pady=8)
        tk.Label(hi, text=APP_NAME, font=(_F,15,"bold"), bg=C["panel"], fg=C["text"]).pack(side="left")
        tk.Label(hi, text=APP_VERSION, font=(_F,9,"bold"), bg=C["panel"], fg=C["gold"]).pack(side="left",padx=6)
        tk.Label(hi, text="Room inventory - AV inspection - Patch procedures",
                 font=(_F,9,"italic"), bg=C["panel"], fg=C["muted"]).pack(side="right")

        status_row = tk.Frame(self.root, bg=C["panel_alt"])
        status_row.pack(fill="x")
        tk.Label(status_row, textvariable=self.status_var, font=(_F,9),
                 bg=C["panel_alt"], fg=C["accent"], anchor="w", padx=12, pady=4).pack(side="left", fill="x", expand=True)
        tk.Label(status_row, textvariable=self.rtc_status_var, font=(_F,8,"bold"),
                 bg=C["panel_alt"], fg=C["gold"], anchor="e", padx=12, pady=4).pack(side="right")

        meta = tk.Frame(self.root, bg=C["panel"])
        meta.pack(fill="x")
        tk.Label(meta, text="Student:", font=(_F, 9), bg=C["panel"], fg=C["muted"]).grid(row=0, column=0, padx=(10, 4), pady=6, sticky="w")
        tk.Entry(meta, textvariable=self.student_name_var, font=(_F, 9), bg=C["notebk"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", width=20).grid(row=0, column=1, padx=(0, 10), pady=6, sticky="w")
        tk.Label(meta, text="Project:", font=(_F, 9), bg=C["panel"], fg=C["muted"]).grid(row=0, column=2, padx=(0, 4), pady=6, sticky="w")
        tk.Entry(meta, textvariable=self.portfolio_project_var, font=(_F, 9), bg=C["notebk"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", width=30).grid(row=0, column=3, padx=(0, 10), pady=6, sticky="w")
        tk.Label(meta, text="Role focus:", font=(_F, 9), bg=C["panel"], fg=C["muted"]).grid(row=0, column=4, padx=(0, 4), pady=6, sticky="w")
        tk.Entry(meta, textvariable=self.role_focus_var, font=(_F, 9), bg=C["notebk"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", width=24).grid(row=0, column=5, padx=(0, 10), pady=6, sticky="w")
        tk.Label(meta, text="Artifact prefix:", font=(_F, 9), bg=C["panel"], fg=C["muted"]).grid(row=0, column=6, padx=(0, 4), pady=6, sticky="w")
        tk.Entry(meta, textvariable=self.artifact_prefix_var, font=(_F, 9), bg=C["notebk"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", width=18).grid(row=0, column=7, padx=(0, 10), pady=6, sticky="w")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        self._build_inventory_tab(nb)
        self._build_inspection_tab(nb)
        self._build_patch_tab(nb)
        self._build_ticketing_tab(nb)
        self._build_log_tab(nb)

    #  Tab 1: Room Inventory 

    def _build_inventory_tab(self, nb):
        frame = tk.Frame(nb, bg=C["bg"]); nb.add(frame, text="  Room Inventory  ")
        frame.columnconfigure(0, weight=1); frame.rowconfigure(3, weight=1)

        toolbar = tk.Frame(frame, bg=C["panel"]); toolbar.grid(row=0,column=0,sticky="ew",pady=(0,4))
        for text, cmd in [("+ Add Room", self._add_room_dialog),
                          ("Load RTC Catalog (K:)", self._load_rtc_catalog_from_default_root),
                          ("Select RTC Root...", self._pick_rtc_root_and_load),
                          ("Import RTC Catalog File", self._import_rtc_catalog_file),
                          ("Import RTC -> Inventory", self._import_all_rtc_rooms_to_inventory),
                          ("Launch Display Utility", self._launch_display_utility),
                          ("Import CSV", self._import_inventory_csv),
                          ("Export CSV", self._export_inventory_csv),
                          ("Export Report", self._export_inventory_report)]:
            self._btn(toolbar, text, C["btn_acc"] if text.startswith("+") else C["btn"], cmd).pack(
                side="left", padx=4, pady=6)

        pick = tk.Frame(frame, bg=C["panel_alt"])
        pick.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        pick.columnconfigure(5, weight=1)
        tk.Label(pick, text="Building:", bg=C["panel_alt"], fg=C["muted"], font=(_F, 9)).grid(row=0, column=0, padx=(10, 4), pady=6, sticky="w")
        self.inv_building_combo = ttk.Combobox(pick, textvariable=self.inv_building_var, state="readonly", width=22, values=[])
        self.inv_building_combo.grid(row=0, column=1, padx=(0, 10), pady=6, sticky="w")
        self.inv_building_combo.bind("<<ComboboxSelected>>", self._on_inventory_building_changed)
        tk.Label(pick, text="Room:", bg=C["panel_alt"], fg=C["muted"], font=(_F, 9)).grid(row=0, column=2, padx=(0, 4), pady=6, sticky="w")
        self.inv_room_combo = ttk.Combobox(pick, textvariable=self.inv_room_var, state="readonly", width=22, values=[])
        self.inv_room_combo.grid(row=0, column=3, padx=(0, 10), pady=6, sticky="w")
        self._btn(pick, "Add Selected RTC Room", C["btn_acc"], self._add_selected_rtc_room).grid(row=0, column=4, padx=(0, 10), pady=6, sticky="w")
        self._btn(pick, "Use in Inspection", C["btn"], self._use_selected_rtc_room_for_inspection).grid(row=0, column=5, padx=(0, 10), pady=6, sticky="w")

        src = tk.Frame(frame, bg=C["panel_alt"])
        src.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        tk.Label(src, textvariable=self.rtc_source_var, font=(_F, 8, "bold"),
                 bg=C["panel_alt"], fg=C["gold"], anchor="w",
                 padx=10, pady=4).pack(fill="x")

        cols = ("Room ID","Building","Floor","PC Hostname","Projector Model","Last Inspected","Notes")
        wrap = tk.Frame(frame, bg=C["bg"]); wrap.grid(row=3,column=0,sticky="nsew")
        wrap.columnconfigure(0,weight=1); wrap.rowconfigure(0,weight=1)
        self.inv_tree = ttk.Treeview(wrap, columns=cols, show="headings", height=18)
        for col in cols:
            self.inv_tree.heading(col, text=col)
            self.inv_tree.column(col, width=130, stretch=True)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.inv_tree.yview)
        xsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.inv_tree.xview)
        self.inv_tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.inv_tree.grid(row=0,column=0,sticky="nsew"); ysb.grid(row=0,column=1,sticky="ns")
        xsb.grid(row=1,column=0,sticky="ew")
        self.inv_tree.bind("<Double-1>", self._edit_room_dialog)

    def _add_room_dialog(self, prefill: Optional[dict] = None):
        win = tk.Toplevel(self.root); win.title("Room Record"); win.configure(bg=C["bg"])
        win.grab_set()
        vars_: dict = {}
        for i, field in enumerate(ROOM_FIELDS):
            tk.Label(win, text=field+":", font=(_F,9), bg=C["bg"], fg=C["muted"],
                     anchor="e", width=18).grid(row=i,column=0,padx=(10,4),pady=2,sticky="e")
            v = tk.StringVar(value=(prefill or {}).get(field,""))
            tk.Entry(win, textvariable=v, font=(_F,9), bg=C["notebk"], fg=C["text"],
                     insertbackground=C["text"], relief="flat", width=36).grid(
                row=i,column=1,padx=(0,10),pady=2,sticky="ew")
            vars_[field] = v

        def save():
            record = {f: vars_[f].get() for f in ROOM_FIELDS}
            record.setdefault("Last Inspected", str(date.today()))
            # Replace existing if same Room ID
            rid = record["Room ID"].strip()
            for j, r in enumerate(self.rooms):
                if r.get("Room ID","").strip() == rid:
                    self.rooms[j] = record
                    self._refresh_inv_tree(); win.destroy(); return
            self.rooms.append(record)
            self._refresh_inv_tree(); win.destroy()
            self.status_var.set(f"Room {rid} saved.")

        tk.Button(win, text="Save", font=(_F,10), bg=C["btn_acc"], fg=C["text"],
                  relief="flat", padx=16, pady=6, command=save).grid(
            row=len(ROOM_FIELDS),column=0,columnspan=2,pady=10)

    def _edit_room_dialog(self, event=None):
        sel = self.inv_tree.selection()
        if not sel: return
        rid = self.inv_tree.item(sel[0])["values"][0]
        record = next((r for r in self.rooms if r.get("Room ID","") == rid), None)
        if record:
            self._add_room_dialog(prefill=record)

    def _refresh_inv_tree(self):
        self.inv_tree.delete(*self.inv_tree.get_children())
        self.rooms.sort(key=lambda r: (str(r.get("Building") or ""), str(r.get("Room ID") or "")))
        for r in self.rooms:
            vals = tuple(r.get(c,"") for c in ("Room ID","Building","Floor","PC Hostname",
                                                "Projector Model","Last Inspected","Notes"))
            self.inv_tree.insert("","end",values=vals)

    def _merge_room_into_inventory(self, room: dict) -> str:
        rid = str(room.get("Room ID") or "").strip()
        if not rid:
            return "skipped"
        for idx, current in enumerate(self.rooms):
            if str(current.get("Room ID") or "").strip() == rid:
                self.rooms[idx] = dict(room)
                return "updated"
        self.rooms.append(dict(room))
        return "added"

    def _import_all_rtc_rooms_to_inventory(self):
        if not self.rtc_rooms:
            messagebox.showinfo(APP_NAME, "No RTC catalog is loaded yet.")
            return
        added = 0
        updated = 0
        for room in self.rtc_rooms:
            outcome = self._merge_room_into_inventory(room)
            if outcome == "added":
                added += 1
            elif outcome == "updated":
                updated += 1
        self._refresh_inv_tree()
        self.status_var.set(
            f"RTC imported to inventory: {added} added, {updated} updated ({len(self.rtc_rooms)} total from catalog)"
        )

    def _find_display_utility(self) -> Optional[Path]:
        for p in DISPLAY_UTILITY_CANDIDATES:
            if p.exists():
                return p
        return None

    def _launch_display_utility(self):
        tool = self._find_display_utility()
        if tool is None:
            messagebox.showwarning(
                APP_NAME,
                "CITL Display Utility was not found.\n"
                "Expected in CITL_Toolkit (DisplayProfile GUI)."
            )
            return
        try:
            ext = tool.suffix.lower()
            if ext == ".ps1":
                subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tool)])
            elif ext in (".cmd", ".bat"):
                subprocess.Popen(["cmd", "/c", str(tool)], cwd=str(tool.parent))
            else:
                subprocess.Popen([str(tool)], cwd=str(tool.parent))
            self.status_var.set(f"Launched Display Utility: {tool.name}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not launch Display Utility:\n{exc}")

    def _load_rooms_from_catalog_file(self, path: Path) -> List[dict]:
        rooms: List[dict] = []
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rec = _canonical_room_record({str(k): str(v or "") for k, v in row.items()})
                    if rec is not None:
                        rooms.append(rec)
            return rooms

        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                seq = payload
            elif isinstance(payload, dict):
                for key in ("rooms", "inventory", "items", "data"):
                    if isinstance(payload.get(key), list):
                        seq = payload[key]
                        break
                else:
                    seq = []
            else:
                seq = []
            for obj in seq:
                if isinstance(obj, dict):
                    rec = _canonical_room_record({str(k): str(v or "") for k, v in obj.items()})
                    if rec is not None:
                        rooms.append(rec)
            return rooms
        return rooms

    def _index_rtc_rooms(self):
        by_building: Dict[str, List[dict]] = {}
        for room in self.rtc_rooms:
            b = str(room.get("Building") or "").strip() or "Unspecified"
            by_building.setdefault(b, []).append(room)
        for b in by_building.keys():
            by_building[b].sort(key=lambda r: str(r.get("Room ID") or ""))
        self.rtc_rooms_by_building = by_building
        self.rtc_buildings = sorted(by_building.keys())

    def _refresh_rtc_selectors(self):
        self._index_rtc_rooms()
        buildings = self.rtc_buildings
        self.inv_building_combo["values"] = buildings
        self.insp_building_combo["values"] = buildings
        if buildings:
            if self.inv_building_var.get() not in buildings:
                self.inv_building_var.set(buildings[0])
            if self.insp_building_var.get() not in buildings:
                self.insp_building_var.set(buildings[0])
        self._on_inventory_building_changed()
        self._on_inspection_building_changed()

    def _on_inventory_building_changed(self, _event=None):
        building = self.inv_building_var.get().strip()
        rooms = self.rtc_rooms_by_building.get(building, [])
        values = [str(r.get("Room ID") or "").strip() for r in rooms if str(r.get("Room ID") or "").strip()]
        self.inv_room_combo["values"] = values
        if values:
            self.inv_room_var.set(values[0])
        else:
            self.inv_room_var.set("")

    def _on_inspection_building_changed(self, _event=None):
        building = self.insp_building_var.get().strip()
        rooms = self.rtc_rooms_by_building.get(building, [])
        values = [str(r.get("Room ID") or "").strip() for r in rooms if str(r.get("Room ID") or "").strip()]
        self.insp_room_combo["values"] = values
        if values and self.insp_room_var.get().strip() not in values:
            self.insp_room_var.set(values[0])

    def _selected_rtc_room(self) -> Optional[dict]:
        building = self.inv_building_var.get().strip()
        rid = self.inv_room_var.get().strip()
        if not building or not rid:
            return None
        for r in self.rtc_rooms_by_building.get(building, []):
            if str(r.get("Room ID") or "").strip() == rid:
                return dict(r)
        return None

    def _add_selected_rtc_room(self):
        rec = self._selected_rtc_room()
        if rec is None:
            messagebox.showinfo(APP_NAME, "Select a building and room from the RTC catalog first.")
            return
        self._add_room_dialog(prefill=rec)

    def _use_selected_rtc_room_for_inspection(self):
        rec = self._selected_rtc_room()
        if rec is None:
            messagebox.showinfo(APP_NAME, "Select a building and room from the RTC catalog first.")
            return
        self.insp_building_var.set(str(rec.get("Building") or ""))
        self._on_inspection_building_changed()
        self.insp_room_var.set(str(rec.get("Room ID") or ""))
        self.status_var.set(f"Inspection target set from RTC catalog: {self.insp_room_var.get().strip()}")

    def _auto_load_rtc_catalog(self):
        root = RTC_DEFAULT_SOURCE_ROOT
        self.rtc_source_var.set(f"Source: {root}")
        if root.exists():
            self._load_rtc_catalog_from_root(root, quiet=True)
        else:
            self.rtc_status_var.set("RTC catalog: K: not mounted")

    def _load_rtc_catalog_from_default_root(self):
        root = RTC_DEFAULT_SOURCE_ROOT
        if not root.exists():
            messagebox.showwarning(
                APP_NAME,
                f"Default RTC source root was not found:\n{root}\n\n"
                "Mount K: and retry, or use 'Import RTC Catalog File'."
            )
            return
        self._load_rtc_catalog_from_root(root, quiet=False)

    def _pick_rtc_root_and_load(self):
        selected = filedialog.askdirectory(
            title="Select RTC catalog root folder",
            initialdir=str(self.rtc_source_path or RTC_DEFAULT_SOURCE_ROOT),
        )
        if not selected:
            return
        root = Path(selected)
        self._load_rtc_catalog_from_root(root, quiet=False)

    def _load_rtc_catalog_from_root(self, root: Path, quiet: bool = False):
        files = list(_iter_catalog_files(root, max_depth=6))
        rooms: List[dict] = []
        loaded_files = 0
        for p in files:
            try:
                batch = self._load_rooms_from_catalog_file(p)
            except Exception:
                continue
            if batch:
                loaded_files += 1
                rooms.extend(batch)
        if not rooms:
            if not quiet:
                messagebox.showinfo(
                    APP_NAME,
                    f"No RTC room catalog entries were found under:\n{root}\n\n"
                    "Try 'Import RTC Catalog File' to select a specific CSV/JSON."
                )
            self.rtc_status_var.set("RTC catalog: no room records found")
            return
        # Merge into live room inventory by Room ID.
        merged: Dict[str, dict] = {}
        for r in rooms:
            rid = str(r.get("Room ID") or "").strip()
            if rid:
                merged[rid] = r
        self.rtc_rooms = list(merged.values())
        self.rtc_source_path = root
        self.rtc_source_var.set(f"Source: {root}")
        self._refresh_rtc_selectors()
        self.status_var.set(
            f"Loaded RTC catalog from {root} - {len(self.rtc_rooms)} room records ({loaded_files} file(s))"
        )
        self.rtc_status_var.set(
            f"RTC catalog: {len(self.rtc_rooms)} rooms from {root}"
        )

    def _import_rtc_catalog_file(self):
        path = filedialog.askopenfilename(
            title="Import RTC room catalog",
            filetypes=[("Catalog files", "*.csv *.json"), ("CSV", "*.csv"), ("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        p = Path(path)
        try:
            rooms = self._load_rooms_from_catalog_file(p)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Catalog import failed:\n{exc}")
            return
        if not rooms:
            messagebox.showwarning(APP_NAME, "No room records were found in the selected catalog file.")
            return
        merged: Dict[str, dict] = {}
        for r in rooms:
            rid = str(r.get("Room ID") or "").strip()
            if rid:
                merged[rid] = r
        self.rtc_rooms = list(merged.values())
        self.rtc_source_path = p
        self.rtc_source_var.set(f"Source: {p}")
        self._refresh_rtc_selectors()
        self.status_var.set(f"Imported RTC catalog: {p.name} ({len(self.rtc_rooms)} rooms)")
        self.rtc_status_var.set(f"RTC catalog: {len(self.rtc_rooms)} rooms from {p.name}")

    def _import_inventory_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV","*.csv"),("All","*.*")])
        if not path: return
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.rooms.append({k: row.get(k,"") for k in ROOM_FIELDS})
            self._refresh_inv_tree()
            self.status_var.set(f"Imported {len(self.rooms)} room(s) from CSV.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"CSV import failed:\n{exc}")

    def _export_inventory_csv(self):
        prefix = self._artifact_prefix()
        path = filedialog.asksaveasfilename(defaultextension=".csv",
            filetypes=[("CSV","*.csv")], initialdir=str(EXPORTS_DIR),
            initialfile=f"{prefix}_room_inventory_{date.today()}.csv")
        if not path: return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ROOM_FIELDS)
            writer.writeheader(); writer.writerows(self.rooms)
        self.status_var.set(f"Exported: {Path(path).name}")

    def _export_inventory_report(self):
        if not self.rooms:
            messagebox.showinfo(APP_NAME, "No rooms in inventory yet."); return
        prefix = self._artifact_prefix()
        path = filedialog.asksaveasfilename(defaultextension=".txt",
            filetypes=[("Text","*.txt")], initialdir=str(EXPORTS_DIR),
            initialfile=f"{prefix}_room_inventory_report_{date.today()}.txt")
        if not path: return
        lines = self._portfolio_header_lines("Room Inventory Report")
        lines += [f"Generated: {datetime.now():%Y-%m-%d %H:%M}", "="*60, ""]
        for r in self.rooms:
            lines.append(f"Room: {r.get('Room ID','')}  ({r.get('Building','')} Floor {r.get('Floor','')})")
            for f in ROOM_FIELDS[3:]:
                v = r.get(f,"")
                if v: lines.append(f"  {f}: {v}")
            lines.append("")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.status_var.set(f"Report saved: {Path(path).name}")

    #  Tab 2: Room Inspection 

    def _build_inspection_tab(self, nb):
        frame = tk.Frame(nb, bg=C["bg"]); nb.add(frame, text="  AV Inspection  ")
        frame.columnconfigure(0,weight=1); frame.rowconfigure(1,weight=1)

        meta = tk.Frame(frame, bg=C["panel"]); meta.grid(row=0,column=0,sticky="ew",pady=(0,4))
        self.insp_building_var = tk.StringVar(value="")
        self.insp_room_var  = tk.StringVar(value="")
        self.insp_tech_var  = tk.StringVar(value="")
        self.insp_date_var  = tk.StringVar(value=str(date.today()))
        tk.Label(meta, text="Building:", font=(_F,9), bg=C["panel"], fg=C["muted"]).pack(side="left",padx=(10,2),pady=6)
        self.insp_building_combo = ttk.Combobox(meta, textvariable=self.insp_building_var, values=[], state="readonly", width=14, font=(_F, 9))
        self.insp_building_combo.pack(side="left", padx=(0, 10))
        self.insp_building_combo.bind("<<ComboboxSelected>>", self._on_inspection_building_changed)
        tk.Label(meta, text="Room ID:", font=(_F,9), bg=C["panel"], fg=C["muted"]).pack(side="left",padx=(0,2),pady=6)
        self.insp_room_combo = ttk.Combobox(meta, textvariable=self.insp_room_var, values=[], state="readonly", width=16, font=(_F, 9))
        self.insp_room_combo.pack(side="left", padx=(0, 10))
        tk.Label(meta, text="Technician:", font=(_F,9), bg=C["panel"], fg=C["muted"]).pack(side="left",padx=(0,2),pady=6)
        tk.Entry(meta, textvariable=self.insp_tech_var, font=(_F,9), bg=C["notebk"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", width=16).pack(side="left",padx=(0,12))
        tk.Label(meta, text="Date:", font=(_F,9), bg=C["panel"], fg=C["muted"]).pack(side="left",padx=(0,2),pady=6)
        tk.Entry(meta, textvariable=self.insp_date_var, font=(_F,9), bg=C["notebk"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", width=12).pack(side="left",padx=(0,12))
        self._btn(meta, "Launch Display Utility", C["btn"], self._launch_display_utility).pack(side="right", padx=(0, 8))
        self._btn(meta,"Export Inspection Report",C["btn_acc"],self._export_inspection).pack(side="right",padx=10)

        canvas = tk.Canvas(frame, bg=C["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=1,column=0,sticky="nsew"); vsb.grid(row=1,column=1,sticky="ns")
        inner = tk.Frame(canvas, bg=C["bg"])
        cwin = canvas.create_window(0,0,anchor="nw",window=inner)
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin,width=e.width))

        for cat, items in INSPECTION_ITEMS:
            self.inspection_vars[cat] = {}
            tk.Label(inner, text=cat, font=(_F,10,"bold"), bg=C["bg"], fg=C["gold"],
                     anchor="w").pack(fill="x", padx=10, pady=(10,2))
            for item in items:
                var = tk.BooleanVar(value=False)
                self.inspection_vars[cat][item] = var
                tk.Checkbutton(inner, text=item, variable=var, font=(_F,9),
                               bg=C["bg"], fg=C["text"], activebackground=C["bg"],
                               activeforeground=C["text"], selectcolor=C["btn"],
                               highlightthickness=0).pack(anchor="w", padx=24)

        tk.Label(inner, text="Additional Notes:", font=(_F,9), bg=C["bg"],
                 fg=C["muted"]).pack(anchor="w",padx=10,pady=(10,2))
        self.insp_notes = scrolledtext.ScrolledText(inner, height=4, wrap="word",
            font=(_F,9), bg=C["notebk"], fg=C["text"], relief="flat")
        self.insp_notes.pack(fill="x", padx=10, pady=(0,10))

    def _export_inspection(self):
        room  = self.insp_room_var.get().strip() or "Unknown Room"
        tech  = self.insp_tech_var.get().strip() or "CITL Staff"
        dt    = self.insp_date_var.get().strip() or str(date.today())
        notes = self.insp_notes.get("1.0","end-1c").strip()
        prefix = self._artifact_prefix()
        path = filedialog.asksaveasfilename(defaultextension=".txt",
            filetypes=[("Text","*.txt")], initialdir=str(EXPORTS_DIR),
            initialfile=f"{prefix}_inspection_{room}_{dt}.txt")
        if not path: return
        lines = self._portfolio_header_lines("AV Room Inspection Report")
        lines += [f"CITL AV Room Inspection Report",
                 f"Room: {room}  |  Technician: {tech}  |  Date: {dt}", "="*60, ""]
        passed = failed = 0
        for cat, items in INSPECTION_ITEMS:
            lines.append(f"\n[ {cat.upper()} ]")
            for item, var in self.inspection_vars[cat].items():
                ok = var.get()
                lines.append(f"  {'[PASS]' if ok else '[FAIL]'}  {item}")
                if ok: passed += 1
                else:  failed += 1
        lines += ["", f"Summary: {passed} passed, {failed} failed",
                  "", "Notes:", notes or "(none)"]
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.status_var.set(f"Inspection report saved: {Path(path).name}")

    #  Tab 3: Patch Procedure Documentation 

    def _build_patch_tab(self, nb):
        frame = tk.Frame(nb, bg=C["bg"]); nb.add(frame, text="  Patch Procedures  ")
        frame.columnconfigure(0,weight=1); frame.rowconfigure(1,weight=1)

        meta = tk.Frame(frame, bg=C["panel"]); meta.grid(row=0,column=0,sticky="ew",pady=(0,4))
        self.patch_sys_var  = tk.StringVar(value="")
        self.patch_sev_var  = tk.StringVar(value="High")
        self.patch_auth_var = tk.StringVar(value="CITL Staff")
        self.patch_wizard_var = tk.StringVar(value=list(PATCH_WIZARD_PRESETS.keys())[0])
        for lbl, var, extra in [
            ("System/App:", self.patch_sys_var, {}),
            ("Severity:", self.patch_sev_var, {"values": PATCH_SEVERITY}),
            ("Author:", self.patch_auth_var, {}),
        ]:
            tk.Label(meta, text=lbl, font=(_F,9), bg=C["panel"], fg=C["muted"]).pack(side="left",padx=(10,2),pady=6)
            if "values" in extra:
                cb = ttk.Combobox(meta, textvariable=var, values=extra["values"],
                                  state="readonly", width=14, font=(_F,9))
                cb.pack(side="left",padx=(0,12)); cb.current(1)
            else:
                tk.Entry(meta, textvariable=var, font=(_F,9), bg=C["notebk"], fg=C["text"],
                         insertbackground=C["text"], relief="flat", width=18).pack(side="left",padx=(0,12))
        tk.Label(meta, text="Wizard:", font=(_F,9), bg=C["panel"], fg=C["muted"]).pack(side="left", padx=(0,2), pady=6)
        ttk.Combobox(
            meta,
            textvariable=self.patch_wizard_var,
            values=list(PATCH_WIZARD_PRESETS.keys()),
            state="readonly",
            width=28,
            font=(_F, 9),
        ).pack(side="left", padx=(0, 10))
        self._btn(meta, "Apply Wizard", C["btn"], self._apply_patch_wizard).pack(side="left", padx=(0, 8))
        self._btn(meta, "Launch Display Utility", C["btn"], self._launch_display_utility).pack(side="right", padx=(0, 8))
        self._btn(meta,"Export Patch Doc",C["btn_acc"],self._export_patch_doc).pack(side="right",padx=10)

        scroll_frame = tk.Frame(frame, bg=C["bg"]); scroll_frame.grid(row=1,column=0,sticky="nsew")
        scroll_frame.columnconfigure(0,weight=1); scroll_frame.rowconfigure(0,weight=1)

        sections = [
            ("Vulnerability / Issue Description",
             "Describe the vulnerability, bug, or required update being addressed."),
            ("Affected Systems",
             "List all affected hostnames, IP ranges, OS versions, or software versions."),
            ("Patch / Fix Steps",
             "1. Verify current version:\n2. Download patch from:\n3. Test on staging:\n4. Apply to production:\n5. Verify fix:\n6. Document outcome:"),
            ("Rollback Procedure",
             "Steps to revert if the patch causes issues:\n1.\n2.\n3."),
            ("Testing & Verification",
             "Describe how to confirm the patch was successful."),
            ("Change Control Notes",
             "Approvals, ticket numbers, maintenance window, communication sent."),
        ]
        self.patch_boxes: dict = {}
        canvas2 = tk.Canvas(scroll_frame, bg=C["bg"], highlightthickness=0)
        vsb2 = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas2.yview)
        canvas2.configure(yscrollcommand=vsb2.set)
        canvas2.grid(row=0,column=0,sticky="nsew"); vsb2.grid(row=0,column=1,sticky="ns")
        inner2 = tk.Frame(canvas2, bg=C["bg"])
        cwin2 = canvas2.create_window(0,0,anchor="nw",window=inner2)
        inner2.bind("<Configure>", lambda e: canvas2.configure(scrollregion=canvas2.bbox("all")))
        canvas2.bind("<Configure>", lambda e: canvas2.itemconfig(cwin2,width=e.width))
        inner2.columnconfigure(0,weight=1)
        for i, (title, placeholder) in enumerate(sections):
            tk.Label(inner2, text=title, font=(_F,9,"bold"), bg=C["bg"],
                     fg=C["gold"], anchor="w").grid(row=i*2, column=0, sticky="w", padx=10, pady=(8,2))
            box = scrolledtext.ScrolledText(inner2, height=4, wrap="word",
                font=(_F,9), bg=C["notebk"], fg=C["text"], relief="flat")
            box.grid(row=i*2+1, column=0, sticky="ew", padx=10, pady=(0,4))
            box.insert("1.0", placeholder)
            self.patch_boxes[title] = box

    def _export_patch_doc(self):
        system   = self.patch_sys_var.get().strip() or "System"
        severity = self.patch_sev_var.get().strip()
        author   = self.patch_auth_var.get().strip() or "CITL Staff"
        prefix = self._artifact_prefix()
        path = filedialog.asksaveasfilename(defaultextension=".txt",
            filetypes=[("Text","*.txt")], initialdir=str(EXPORTS_DIR),
            initialfile=f"{prefix}_patch_procedure_{system.replace(' ','_')}_{date.today()}.txt")
        if not path: return
        lines = self._portfolio_header_lines("Patch Procedure Document")
        lines += [f"CITL Patch Procedure Document",
                 f"System: {system}  |  Severity: {severity}  |  Author: {author}  |  Date: {date.today()}",
                 "="*70, ""]
        for title, box in self.patch_boxes.items():
            content = box.get("1.0","end-1c").strip()
            lines += [f"\n{title.upper()}", "-"*len(title), content, ""]
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.status_var.set(f"Patch procedure saved: {Path(path).name}")

    def _apply_patch_wizard(self):
        preset_name = self.patch_wizard_var.get().strip()
        preset = PATCH_WIZARD_PRESETS.get(preset_name)
        if not preset:
            return
        if not self.patch_sys_var.get().strip():
            self.patch_sys_var.set("RTC Classroom Endpoints")
        if not self.patch_auth_var.get().strip():
            self.patch_auth_var.set(self.student_name_var.get().strip() or "CITL Staff")
        mapping = {
            "Vulnerability / Issue Description": preset.get("title", ""),
            "Affected Systems": preset.get("affected", ""),
            "Patch / Fix Steps": preset.get("steps", ""),
            "Rollback Procedure": preset.get("rollback", ""),
            "Testing & Verification": preset.get("verify", ""),
            "Change Control Notes": preset.get("change", ""),
        }
        for title, content in mapping.items():
            box = self.patch_boxes.get(title)
            if box is None:
                continue
            box.delete("1.0", "end")
            box.insert("1.0", str(content))
        self.status_var.set(f"Patch wizard applied: {preset_name}")

    #  Tab 4: Ticketing + Portfolio Reporting

    def _build_ticketing_tab(self, nb):
        frame = tk.Frame(nb, bg=C["bg"]); nb.add(frame, text="  Ticketing / Portfolio  ")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        top = tk.Frame(frame, bg=C["panel"])
        top.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.ticket_template_var = tk.StringVar(value=list(TICKET_TEMPLATE_PRESETS.keys())[0])
        self.ticket_id_var = tk.StringVar(value="")
        self.ticket_type_var = tk.StringVar(value=TICKET_TYPES[0])
        self.ticket_priority_var = tk.StringVar(value=TICKET_PRIORITIES[1])
        self.ticket_status_var = tk.StringVar(value=TICKET_STATUSES[0])
        self.ticket_room_var = tk.StringVar(value="")
        self.ticket_asset_var = tk.StringVar(value="")
        self.ticket_assigned_var = tk.StringVar(value=self.student_name_var.get().strip() or "Workstudy")
        self.ticket_sla_var = tk.StringVar(value="")
        self.ticket_opened_var = tk.StringVar(value=str(date.today()))
        self.ticket_resolved_var = tk.StringVar(value="")

        tk.Label(top, text="Template:", font=(_F, 9), bg=C["panel"], fg=C["muted"]).grid(row=0, column=0, padx=(10, 4), pady=6, sticky="w")
        ttk.Combobox(top, textvariable=self.ticket_template_var, values=list(TICKET_TEMPLATE_PRESETS.keys()),
                     state="readonly", width=28, font=(_F, 9)).grid(row=0, column=1, padx=(0, 8), pady=6, sticky="w")
        self._btn(top, "Apply Template", C["btn"], self._apply_ticket_template).grid(row=0, column=2, padx=(0, 12), pady=6, sticky="w")
        self._btn(top, "Launch Display Utility", C["btn"], self._launch_display_utility).grid(row=0, column=3, padx=(0, 8), pady=6, sticky="w")
        self._btn(top, "Build Portfolio Bundle", C["btn_acc"], self._export_portfolio_bundle).grid(row=0, column=4, padx=(0, 8), pady=6, sticky="w")

        form = tk.Frame(frame, bg=C["panel_alt"])
        form.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        for c in range(6):
            form.grid_columnconfigure(c, weight=1 if c % 2 == 1 else 0)

        self._labeled_entry(form, 0, "Ticket ID", self.ticket_id_var, width=18)
        self._labeled_combo(form, 1, "Type", self.ticket_type_var, TICKET_TYPES, width=18)
        self._labeled_combo(form, 2, "Priority", self.ticket_priority_var, TICKET_PRIORITIES, width=18)
        self._labeled_combo(form, 3, "Status", self.ticket_status_var, TICKET_STATUSES, width=16)
        self._labeled_entry(form, 4, "Room", self.ticket_room_var, width=14)
        self._labeled_entry(form, 5, "Asset", self.ticket_asset_var, width=18)
        self._labeled_entry(form, 6, "Assigned To", self.ticket_assigned_var, width=18)
        self._labeled_entry(form, 7, "Opened", self.ticket_opened_var, width=12)
        self._labeled_entry(form, 8, "Resolved", self.ticket_resolved_var, width=12)
        self._labeled_entry(form, 9, "SLA Due", self.ticket_sla_var, width=14)

        text_block = tk.Frame(form, bg=C["panel_alt"])
        text_block.grid(row=2, column=0, columnspan=6, sticky="ew", padx=10, pady=(6, 8))
        text_block.columnconfigure(1, weight=1)
        text_block.columnconfigure(3, weight=1)
        text_block.columnconfigure(5, weight=1)
        tk.Label(text_block, text="Summary", font=(_F, 9, "bold"), bg=C["panel_alt"], fg=C["gold"]).grid(row=0, column=0, sticky="w", padx=(0, 4))
        tk.Label(text_block, text="Root Cause", font=(_F, 9, "bold"), bg=C["panel_alt"], fg=C["gold"]).grid(row=0, column=2, sticky="w", padx=(8, 4))
        tk.Label(text_block, text="Resolution Steps", font=(_F, 9, "bold"), bg=C["panel_alt"], fg=C["gold"]).grid(row=0, column=4, sticky="w", padx=(8, 4))
        self.ticket_summary_box = scrolledtext.ScrolledText(text_block, height=4, wrap="word", font=(_F, 9), bg=C["notebk"], fg=C["text"], relief="flat")
        self.ticket_summary_box.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.ticket_root_box = scrolledtext.ScrolledText(text_block, height=4, wrap="word", font=(_F, 9), bg=C["notebk"], fg=C["text"], relief="flat")
        self.ticket_root_box.grid(row=1, column=2, columnspan=2, sticky="ew", padx=(8, 0))
        self.ticket_resolution_box = scrolledtext.ScrolledText(text_block, height=4, wrap="word", font=(_F, 9), bg=C["notebk"], fg=C["text"], relief="flat")
        self.ticket_resolution_box.grid(row=1, column=4, columnspan=2, sticky="ew", padx=(8, 0))

        btns = tk.Frame(form, bg=C["panel_alt"])
        btns.grid(row=3, column=0, columnspan=6, sticky="ew", padx=10, pady=(0, 8))
        for col in range(7):
            btns.grid_columnconfigure(col, weight=1)
        self._btn(btns, "Add Ticket", C["btn_acc"], self._add_ticket).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._btn(btns, "Update Selected", C["btn"], self._update_ticket).grid(row=0, column=1, sticky="ew", padx=6)
        self._btn(btns, "Mark Resolved", C["btn"], self._mark_ticket_resolved).grid(row=0, column=2, sticky="ew", padx=6)
        self._btn(btns, "Remove", C["btn"], self._remove_ticket).grid(row=0, column=3, sticky="ew", padx=6)
        self._btn(btns, "Clear Form", C["btn"], self._clear_ticket_form).grid(row=0, column=4, sticky="ew", padx=6)
        self._btn(btns, "Export Tickets CSV", C["btn"], self._export_tickets_csv).grid(row=0, column=5, sticky="ew", padx=6)
        self._btn(btns, "Export ITSM Report", C["btn"], self._export_ticket_report).grid(row=0, column=6, sticky="ew", padx=(6, 0))
        self._btn(btns, "Save Ticket DB", C["btn"], self._save_ticket_db).grid(row=1, column=5, sticky="ew", padx=6, pady=(6, 0))
        self._btn(btns, "Load Ticket DB", C["btn"], self._load_ticket_db).grid(row=1, column=6, sticky="ew", padx=(6, 0), pady=(6, 0))

        wrap = tk.Frame(frame, bg=C["bg"])
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.ticket_tree = ttk.Treeview(wrap, columns=TICKET_COLUMNS, show="headings", height=11)
        for col in TICKET_COLUMNS:
            self.ticket_tree.heading(col, text=col)
            self.ticket_tree.column(col, width=110, stretch=True)
        tysb = ttk.Scrollbar(wrap, orient="vertical", command=self.ticket_tree.yview)
        txsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.ticket_tree.xview)
        self.ticket_tree.configure(yscrollcommand=tysb.set, xscrollcommand=txsb.set)
        self.ticket_tree.grid(row=0, column=0, sticky="nsew")
        tysb.grid(row=0, column=1, sticky="ns")
        txsb.grid(row=1, column=0, sticky="ew")
        self.ticket_tree.bind("<<TreeviewSelect>>", self._on_ticket_tree_select)

    def _labeled_entry(self, parent, idx: int, label: str, var: tk.StringVar, width: int = 18):
        row = idx // 5
        col = (idx % 5) * 2
        tk.Label(parent, text=f"{label}:", font=(_F, 9), bg=C["panel_alt"], fg=C["muted"]).grid(
            row=row, column=col, padx=(10 if col == 0 else 6, 4), pady=4, sticky="w"
        )
        tk.Entry(parent, textvariable=var, font=(_F, 9), bg=C["notebk"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", width=width).grid(
            row=row, column=col + 1, padx=(0, 6), pady=4, sticky="w"
        )

    def _labeled_combo(self, parent, idx: int, label: str, var: tk.StringVar, values: List[str], width: int = 18):
        row = idx // 5
        col = (idx % 5) * 2
        tk.Label(parent, text=f"{label}:", font=(_F, 9), bg=C["panel_alt"], fg=C["muted"]).grid(
            row=row, column=col, padx=(10 if col == 0 else 6, 4), pady=4, sticky="w"
        )
        ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=width, font=(_F, 9)).grid(
            row=row, column=col + 1, padx=(0, 6), pady=4, sticky="w"
        )

    def _default_ticket_id(self) -> str:
        return f"CITL-{datetime.now():%Y%m%d-%H%M%S}"

    def _ticket_form_payload(self) -> dict:
        ticket_id = self.ticket_id_var.get().strip() or self._default_ticket_id()
        return {
            "Ticket ID": ticket_id,
            "Type": self.ticket_type_var.get().strip() or TICKET_TYPES[0],
            "Priority": self.ticket_priority_var.get().strip() or TICKET_PRIORITIES[1],
            "Status": self.ticket_status_var.get().strip() or TICKET_STATUSES[0],
            "Room": self.ticket_room_var.get().strip(),
            "Asset": self.ticket_asset_var.get().strip(),
            "Assigned To": self.ticket_assigned_var.get().strip(),
            "Opened": self.ticket_opened_var.get().strip() or str(date.today()),
            "Resolved": self.ticket_resolved_var.get().strip(),
            "SLA": self.ticket_sla_var.get().strip(),
            "Summary": self.ticket_summary_box.get("1.0", "end-1c").strip(),
            "Root Cause": self.ticket_root_box.get("1.0", "end-1c").strip(),
            "Resolution": self.ticket_resolution_box.get("1.0", "end-1c").strip(),
            "Student": self.student_name_var.get().strip(),
            "Project": self.portfolio_project_var.get().strip(),
        }

    def _refresh_ticket_tree(self):
        self.ticket_tree.delete(*self.ticket_tree.get_children())
        self.tickets.sort(key=lambda t: str(t.get("Opened") or ""), reverse=True)
        for t in self.tickets:
            vals = tuple(t.get(c, "") for c in TICKET_COLUMNS)
            self.ticket_tree.insert("", "end", values=vals)

    def _find_ticket_index(self, ticket_id: str) -> Optional[int]:
        for i, t in enumerate(self.tickets):
            if str(t.get("Ticket ID") or "").strip() == ticket_id.strip():
                return i
        return None

    def _add_ticket(self):
        payload = self._ticket_form_payload()
        idx = self._find_ticket_index(payload["Ticket ID"])
        if idx is None:
            self.tickets.append(payload)
            msg = f"Ticket added: {payload['Ticket ID']}"
        else:
            self.tickets[idx] = payload
            msg = f"Ticket updated: {payload['Ticket ID']}"
        self._refresh_ticket_tree()
        self.ticket_id_var.set(payload["Ticket ID"])
        self.status_var.set(msg)

    def _selected_ticket_id(self) -> str:
        sel = self.ticket_tree.selection()
        if not sel:
            return ""
        vals = self.ticket_tree.item(sel[0]).get("values") or []
        if not vals:
            return ""
        return str(vals[0]).strip()

    def _update_ticket(self):
        tid = self._selected_ticket_id() or self.ticket_id_var.get().strip()
        if not tid:
            messagebox.showinfo(APP_NAME, "Select a ticket row first or provide Ticket ID.")
            return
        payload = self._ticket_form_payload()
        payload["Ticket ID"] = tid
        idx = self._find_ticket_index(tid)
        if idx is None:
            self.tickets.append(payload)
            self.status_var.set(f"Ticket created from form: {tid}")
        else:
            self.tickets[idx] = payload
            self.status_var.set(f"Ticket updated: {tid}")
        self._refresh_ticket_tree()

    def _mark_ticket_resolved(self):
        tid = self._selected_ticket_id()
        if not tid:
            messagebox.showinfo(APP_NAME, "Select a ticket to mark resolved.")
            return
        idx = self._find_ticket_index(tid)
        if idx is None:
            return
        self.tickets[idx]["Status"] = "Resolved"
        self.tickets[idx]["Resolved"] = str(date.today())
        self._refresh_ticket_tree()
        self.status_var.set(f"Ticket marked resolved: {tid}")

    def _remove_ticket(self):
        tid = self._selected_ticket_id()
        if not tid:
            return
        idx = self._find_ticket_index(tid)
        if idx is None:
            return
        self.tickets.pop(idx)
        self._refresh_ticket_tree()
        self._clear_ticket_form()
        self.status_var.set(f"Ticket removed: {tid}")

    def _clear_ticket_form(self):
        self.ticket_id_var.set("")
        self.ticket_type_var.set(TICKET_TYPES[0])
        self.ticket_priority_var.set(TICKET_PRIORITIES[1])
        self.ticket_status_var.set(TICKET_STATUSES[0])
        self.ticket_room_var.set("")
        self.ticket_asset_var.set("")
        self.ticket_assigned_var.set(self.student_name_var.get().strip() or "Workstudy")
        self.ticket_sla_var.set("")
        self.ticket_opened_var.set(str(date.today()))
        self.ticket_resolved_var.set("")
        self.ticket_summary_box.delete("1.0", "end")
        self.ticket_root_box.delete("1.0", "end")
        self.ticket_resolution_box.delete("1.0", "end")

    def _on_ticket_tree_select(self, _event=None):
        tid = self._selected_ticket_id()
        if not tid:
            return
        idx = self._find_ticket_index(tid)
        if idx is None:
            return
        t = self.tickets[idx]
        self.ticket_id_var.set(str(t.get("Ticket ID") or ""))
        self.ticket_type_var.set(str(t.get("Type") or TICKET_TYPES[0]))
        self.ticket_priority_var.set(str(t.get("Priority") or TICKET_PRIORITIES[1]))
        self.ticket_status_var.set(str(t.get("Status") or TICKET_STATUSES[0]))
        self.ticket_room_var.set(str(t.get("Room") or ""))
        self.ticket_asset_var.set(str(t.get("Asset") or ""))
        self.ticket_assigned_var.set(str(t.get("Assigned To") or ""))
        self.ticket_opened_var.set(str(t.get("Opened") or ""))
        self.ticket_resolved_var.set(str(t.get("Resolved") or ""))
        self.ticket_sla_var.set(str(t.get("SLA") or ""))
        self.ticket_summary_box.delete("1.0", "end")
        self.ticket_summary_box.insert("1.0", str(t.get("Summary") or ""))
        self.ticket_root_box.delete("1.0", "end")
        self.ticket_root_box.insert("1.0", str(t.get("Root Cause") or ""))
        self.ticket_resolution_box.delete("1.0", "end")
        self.ticket_resolution_box.insert("1.0", str(t.get("Resolution") or ""))

    def _apply_ticket_template(self):
        name = self.ticket_template_var.get().strip()
        preset = TICKET_TEMPLATE_PRESETS.get(name)
        if not preset:
            return
        self.ticket_type_var.set(str(preset.get("Type") or TICKET_TYPES[0]))
        self.ticket_priority_var.set(str(preset.get("Priority") or TICKET_PRIORITIES[1]))
        self.ticket_status_var.set(str(preset.get("Status") or TICKET_STATUSES[0]))
        if not self.ticket_id_var.get().strip():
            self.ticket_id_var.set(self._default_ticket_id())
        if not self.ticket_opened_var.get().strip():
            self.ticket_opened_var.set(str(date.today()))
        self.ticket_summary_box.delete("1.0", "end")
        self.ticket_summary_box.insert("1.0", str(preset.get("Summary") or ""))
        self.ticket_root_box.delete("1.0", "end")
        self.ticket_root_box.insert("1.0", str(preset.get("Root Cause") or ""))
        self.ticket_resolution_box.delete("1.0", "end")
        self.ticket_resolution_box.insert("1.0", str(preset.get("Resolution") or ""))
        self.status_var.set(f"Ticket template applied: {name}")

    def _export_tickets_csv(self):
        prefix = self._artifact_prefix()
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialdir=str(EXPORTS_DIR),
            initialfile=f"{prefix}_itsm_tickets_{date.today()}.csv",
        )
        if not path:
            return
        fieldnames = list(TICKET_COLUMNS) + ["Summary", "Root Cause", "Resolution", "Student", "Project"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.tickets)
        self.status_var.set(f"Ticket CSV saved: {Path(path).name}")

    def _export_ticket_report(self):
        prefix = self._artifact_prefix()
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text", "*.txt")],
            initialdir=str(EXPORTS_DIR),
            initialfile=f"{prefix}_itsm_incident_report_{date.today()}.txt",
        )
        if not path:
            return
        lines = self._portfolio_header_lines("ITSM Incident and Service Report")
        lines += [f"Generated: {datetime.now():%Y-%m-%d %H:%M}", "=" * 72, ""]
        if not self.tickets:
            lines += ["No tickets logged yet."]
        else:
            status_counts: Dict[str, int] = {}
            for t in self.tickets:
                st = str(t.get("Status") or "Unknown")
                status_counts[st] = status_counts.get(st, 0) + 1
            lines.append("Status Summary:")
            for k in sorted(status_counts.keys()):
                lines.append(f"  - {k}: {status_counts[k]}")
            lines.append("")
            lines.append("Ticket Detail Records")
            lines.append("-" * 72)
            for t in self.tickets:
                lines.append(
                    f"Ticket {t.get('Ticket ID','')} | {t.get('Type','')} | {t.get('Priority','')} | {t.get('Status','')}"
                )
                lines.append(
                    f"Room: {t.get('Room','')} | Asset: {t.get('Asset','')} | Assigned: {t.get('Assigned To','')}"
                )
                lines.append(
                    f"Opened: {t.get('Opened','')} | Resolved: {t.get('Resolved','')} | SLA: {t.get('SLA','')}"
                )
                if t.get("Summary"):
                    lines.append(f"Summary: {t.get('Summary')}")
                if t.get("Root Cause"):
                    lines.append(f"Root Cause: {t.get('Root Cause')}")
                if t.get("Resolution"):
                    lines.append(f"Resolution: {t.get('Resolution')}")
                lines.append("")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.status_var.set(f"ITSM report saved: {Path(path).name}")

    def _save_ticket_db(self):
        prefix = self._artifact_prefix()
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=str(EXPORTS_DIR),
            initialfile=f"{prefix}_ticket_db_{date.today()}.json",
        )
        if not path:
            return
        payload = {
            "project": self.portfolio_project_var.get().strip(),
            "student": self.student_name_var.get().strip(),
            "role_focus": self.role_focus_var.get().strip(),
            "artifact_prefix": self.artifact_prefix_var.get().strip(),
            "generated": datetime.now().isoformat(timespec="seconds"),
            "tickets": self.tickets,
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.status_var.set(f"Ticket DB saved: {Path(path).name}")

    def _load_ticket_db(self):
        path = filedialog.askopenfilename(
            title="Load ticket DB",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialdir=str(EXPORTS_DIR),
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not load ticket DB:\n{exc}")
            return
        tickets = payload.get("tickets") if isinstance(payload, dict) else None
        if not isinstance(tickets, list):
            messagebox.showwarning(APP_NAME, "Selected file does not contain a valid ticket list.")
            return
        normalized: List[dict] = []
        for obj in tickets:
            if not isinstance(obj, dict):
                continue
            rec = {k: str(obj.get(k, "")) for k in (list(TICKET_COLUMNS) + ["Summary", "Root Cause", "Resolution", "Student", "Project"])}
            if not rec.get("Ticket ID", "").strip():
                continue
            normalized.append(rec)
        self.tickets = normalized
        if isinstance(payload, dict):
            if payload.get("project"):
                self.portfolio_project_var.set(str(payload.get("project")))
            if payload.get("student"):
                self.student_name_var.set(str(payload.get("student")))
            if payload.get("role_focus"):
                self.role_focus_var.set(str(payload.get("role_focus")))
            if payload.get("artifact_prefix"):
                self.artifact_prefix_var.set(str(payload.get("artifact_prefix")))
        self._refresh_ticket_tree()
        self.status_var.set(f"Ticket DB loaded: {len(self.tickets)} ticket(s)")

    def _export_portfolio_bundle(self):
        prefix = self._artifact_prefix()
        out_dir = EXPORTS_DIR / f"{prefix}_bundle_{date.today()}"
        out_dir.mkdir(parents=True, exist_ok=True)

        inventory_csv = out_dir / f"{prefix}_room_inventory_{date.today()}.csv"
        with inventory_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ROOM_FIELDS)
            writer.writeheader()
            writer.writerows(self.rooms)

        inventory_txt = out_dir / f"{prefix}_inventory_report_{date.today()}.txt"
        inv_lines = self._portfolio_header_lines("Room Inventory Report")
        inv_lines += [f"Generated: {datetime.now():%Y-%m-%d %H:%M}", "=" * 60, ""]
        for r in self.rooms:
            inv_lines.append(f"Room: {r.get('Room ID','')} | Building: {r.get('Building','')} | Floor: {r.get('Floor','')}")
            inv_lines.append(f"PC: {r.get('PC Hostname','')} | Display: {r.get('Display Type','')} | Projector: {r.get('Projector Model','')}")
            inv_lines.append(f"Notes: {r.get('Notes','')}")
            inv_lines.append("")
        inventory_txt.write_text("\n".join(inv_lines), encoding="utf-8")

        tickets_csv = out_dir / f"{prefix}_itsm_tickets_{date.today()}.csv"
        ticket_fields = list(TICKET_COLUMNS) + ["Summary", "Root Cause", "Resolution", "Student", "Project"]
        with tickets_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ticket_fields)
            writer.writeheader()
            writer.writerows(self.tickets)

        ticket_txt = out_dir / f"{prefix}_itsm_report_{date.today()}.txt"
        ticket_lines = self._portfolio_header_lines("ITSM Incident and Service Report")
        ticket_lines += [f"Generated: {datetime.now():%Y-%m-%d %H:%M}", "=" * 72, ""]
        for t in self.tickets:
            ticket_lines.append(
                f"{t.get('Ticket ID','')} | {t.get('Type','')} | {t.get('Priority','')} | {t.get('Status','')} | Room {t.get('Room','')}"
            )
        if not self.tickets:
            ticket_lines.append("No tickets recorded yet.")
        ticket_txt.write_text("\n".join(ticket_lines), encoding="utf-8")

        patch_txt = out_dir / f"{prefix}_patch_procedure_{date.today()}.txt"
        patch_lines = self._portfolio_header_lines("Patch Procedure Report")
        patch_lines += [
            f"System: {self.patch_sys_var.get().strip() or 'System'}",
            f"Severity: {self.patch_sev_var.get().strip()}",
            f"Author: {self.patch_auth_var.get().strip() or 'CITL Staff'}",
            "=" * 70,
            "",
        ]
        for title, box in self.patch_boxes.items():
            patch_lines.append(title)
            patch_lines.append("-" * len(title))
            patch_lines.append(box.get("1.0", "end-1c").strip())
            patch_lines.append("")
        patch_txt.write_text("\n".join(patch_lines), encoding="utf-8")

        summary_md = out_dir / f"{prefix}_portfolio_summary_{date.today()}.md"
        summary_lines = [
            f"# CITL AV/IT Portfolio Artifact Bundle",
            "",
            f"- Project: {self.portfolio_project_var.get().strip() or 'Untitled'}",
            f"- Student: {self.student_name_var.get().strip() or 'Not provided'}",
            f"- Role Focus: {self.role_focus_var.get().strip() or 'AV/IT Operations'}",
            f"- Generated: {datetime.now():%Y-%m-%d %H:%M}",
            "",
            "## Demonstrated Skills",
            "- ITSM-style incident and service ticket lifecycle management",
            "- Classroom AV inventory and endpoint data governance",
            "- Inspection procedure execution with pass/fail evidence",
            "- Change/patch runbook authoring with rollback design",
            "",
            "## Artifact Index",
            f"- `{inventory_csv.name}`",
            f"- `{inventory_txt.name}`",
            f"- `{tickets_csv.name}`",
            f"- `{ticket_txt.name}`",
            f"- `{patch_txt.name}`",
        ]
        summary_md.write_text("\n".join(summary_lines), encoding="utf-8")

        self.status_var.set(f"Portfolio bundle generated: {out_dir}")
        self._log(f"[PORTFOLIO] bundle generated at {out_dir}\n")

    #  Tab 5: Activity Log 

    def _build_log_tab(self, nb):
        frame = tk.Frame(nb, bg=C["bg"]); nb.add(frame, text="  Log  ")
        frame.columnconfigure(0,weight=1); frame.rowconfigure(0,weight=1)
        self.log = scrolledtext.ScrolledText(frame, wrap="word", state="disabled",
            font=("Consolas",9), bg=C["notebk"], fg=C["text"], relief="flat")
        self.log.grid(row=0,column=0,sticky="nsew",padx=6,pady=6)
        self._log(f"{APP_NAME} {APP_VERSION} ready. Date: {date.today()}\n"
                  f"Exports folder: {EXPORTS_DIR}\n")

    def _artifact_prefix(self) -> str:
        raw = self.artifact_prefix_var.get().strip() or self.portfolio_project_var.get().strip() or "citl_avit"
        safe = "".join(ch if (ch.isalnum() or ch in ("-", "_")) else "_" for ch in raw.strip().lower())
        safe = "_".join(part for part in safe.split("_") if part)
        return safe or "citl_avit"

    def _portfolio_header_lines(self, title: str) -> List[str]:
        return [
            f"CITL {title}",
            f"Project: {self.portfolio_project_var.get().strip() or 'Untitled'}",
            f"Student: {self.student_name_var.get().strip() or 'Not provided'}",
            f"Role Focus: {self.role_focus_var.get().strip() or 'AV/IT Operations'}",
        ]

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _btn(self, parent, text, bg, cmd):
        return tk.Button(parent, text=text, font=(_F,9), bg=bg, fg=C["text"],
                         activebackground=C["btn_hi"], relief="flat", bd=0,
                         padx=8, pady=5, cursor="hand2", command=cmd)


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        root.tk.call("tk","scaling",1.25)
    except Exception:
        pass
    root.deiconify()
    AVITOps(root)
    root.mainloop()


if __name__ == "__main__":
    main()
