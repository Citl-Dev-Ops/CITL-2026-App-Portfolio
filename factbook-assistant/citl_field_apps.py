#!/usr/bin/env python3
"""
CITL Field Apps
Field technician toolkit: room inventory, AV driver check/install/rollback,
rapid inspection checklist, and room-specific display profile save/load.
Non-admin, USB-portable, Windows 10/11.
"""
from __future__ import annotations
import csv, json, os, subprocess, sys, threading
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
except ImportError:
    sys.exit("tkinter required")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
REPO  = _HERE.parent if not getattr(sys, "frozen", False) else Path(sys.executable).parent.parent.parent
DATA_DIR        = REPO / "documents" / "field_apps"
INVENTORY_FILE  = DATA_DIR / "room_inventory.json"
DRIVER_LOG_FILE = DATA_DIR / "driver_log.json"
PROFILES_DIR    = DATA_DIR / "room_display_profiles"
EXPORTS_DIR     = DATA_DIR / "exports"
for _d in (DATA_DIR, PROFILES_DIR, EXPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Theme  (matches CITL suite palette)
# ---------------------------------------------------------------------------
C = {
    "bg":      "#0D1B2A", "panel":   "#112236", "panel_alt": "#162B40",
    "notebk":  "#0C1A2C", "card_sel":"#1E4060",
    "text":    "#D4E4F5", "muted":   "#7A9BBE", "faint":    "#3E5A78",
    "accent":  "#3A8FD4", "gold":    "#E89820",
    "btn":     "#1A3550", "btn_hi":  "#235272",
    "btn_acc": "#1A4A7A", "btn_gold":"#5A3A00",
    "line":    "#1D3050", "good":    "#1E5C30",
    "warn":    "#7A4500", "err":     "#5C1A1A",
}
_F = "Segoe UI" if sys.platform == "win32" else "Ubuntu"
APP_NAME    = "CITL Field Apps"
APP_VERSION = "v1.0"

# ---------------------------------------------------------------------------
# Room inventory schema
# ---------------------------------------------------------------------------
ROOM_FIELDS = [
    ("Room ID",         "e.g. RTC-201"),
    ("Building",        "e.g. RTC"),
    ("Floor",           "e.g. 2"),
    ("Projector Model", "e.g. Epson EB-L200SW"),
    ("Projector SN",    "Serial number"),
    ("Display Type",    "Projector / Flat Panel / LED Wall"),
    ("Display Ports",   "HDMI / DisplayPort / VGA present"),
    ("PC Hostname",     "e.g. RTC201-PC"),
    ("PC Model",        "e.g. Dell OptiPlex 7090"),
    ("Webcam Model",    "e.g. Meeting Owl 3"),
    ("Microphone Type", "e.g. Sennheiser EW-D"),
    ("Audio Interface", "e.g. Focusrite Scarlett"),
    ("HDMI Switcher",   "Brand / model if present"),
    ("Zoom Certified",  "Yes / No"),
    ("Last Inspected",  "YYYY-MM-DD"),
    ("Technician",      "Your name"),
    ("Notes",           "Any issues or remarks"),
]

# ---------------------------------------------------------------------------
# Rapid field checklist
# ---------------------------------------------------------------------------
CHECKLIST_SECTIONS = [
    ("Display & Signal", [
        "Display powers on — no error code",
        "Correct resolution on all outputs (no letterbox/stretch)",
        "All HDMI/DisplayPort cables seated at both ends",
        "Signal detected by display (no 'No Signal' message)",
        "Display profile matches expected layout (extend / duplicate)",
    ]),
    ("Audio", [
        "Microphone functional in Zoom/Teams",
        "Speaker output clear — no feedback or hum",
        "Audio interface/mixer powered and recognised",
        "Volume controls accessible to instructor",
        "HDMI/DP audio endpoint present in Device Manager",
    ]),
    ("PC & Peripherals", [
        "PC boots to desktop without errors",
        "USB hub functional — all peripherals enumerate",
        "Webcam detected in Zoom / Device Manager",
        "Network connection stable (>= 100 Mbps)",
        "Zoom/Teams installed and up to date",
    ]),
    ("Drivers & Updates", [
        "Display adapter driver current (checked in Device Manager)",
        "No yellow-bang devices in Device Manager",
        "Windows update not pending a forced reboot",
        "AV driver versions recorded in Driver Log",
    ]),
    ("Security & Housekeeping", [
        "No unauthorized software or browser extensions visible",
        "Screen lock policy active",
        "Asset tag visible on all major equipment",
        "Login credentials posted or accessible to staff",
        "Room is left in working state for instructor",
    ]),
]

# ---------------------------------------------------------------------------
# Driver PS queries (non-admin)
# ---------------------------------------------------------------------------
PS_DRIVER_SCAN = r"""
Write-Host "=== DISPLAY ADAPTERS ==="
Get-WmiObject Win32_VideoController | Select-Object Name,DriverVersion,Status,InfFilename | ForEach-Object {
    Write-Host "  $($_.Name)"
    Write-Host "    Driver : $($_.DriverVersion)   Status: $($_.Status)"
    Write-Host "    INF    : $($_.InfFilename)"
}
Write-Host ""
Write-Host "=== AUDIO DEVICES ==="
Get-WmiObject Win32_SoundDevice | Select-Object Name,Status | ForEach-Object {
    Write-Host "  [$($_.Status)] $($_.Name)"
}
Write-Host ""
Write-Host "=== USB DEVICES (AV-relevant) ==="
Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object { $_.FriendlyName -match "webcam|camera|owl|zoom|audio|USB.*audio|mic|speakerphone|capture|display|dock" } |
    Select-Object FriendlyName,Status | ForEach-Object {
        Write-Host "  [$($_.Status)] $($_.FriendlyName)"
    }
Write-Host ""
Write-Host "=== PROBLEM DEVICES (non-OK) ==="
Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.Status -ne "OK" } |
    Select-Object FriendlyName,Status,Class | ForEach-Object {
        Write-Host "  [$($_.Status)] $($_.FriendlyName)  (Class: $($_.Class))"
    }
"""

PS_DRIVER_DETAIL = r"""
Write-Host "=== DISPLAY DRIVER DETAIL ==="
Get-WmiObject Win32_VideoController | ForEach-Object {
    $ram = if ($_.AdapterRAM) { [math]::Round($_.AdapterRAM/1MB,0).ToString() + " MB" } else { "N/A" }
    Write-Host ""
    Write-Host "Adapter  : $($_.Name)"
    Write-Host "Driver   : $($_.DriverVersion)"
    Write-Host "Status   : $($_.Status)"
    Write-Host "Mode     : $($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution) @ $($_.CurrentRefreshRate)Hz"
    Write-Host "VRAM     : $ram"
    Write-Host "INF File : $($_.InfFilename)"
    Write-Host "PNP ID   : $($_.PNPDeviceID)"
}
Write-Host ""
Write-Host "=== MONITOR PNP DETAIL ==="
Get-PnpDevice -Class Monitor -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  [$($_.Status)] $($_.FriendlyName)"
    Write-Host "    DeviceID: $($_.DeviceID)"
}
"""

ROLLBACK_GUIDE = """DRIVER ROLLBACK PROCEDURE (No-Admin via Device Manager)
=========================================================

Step 1 — Open Device Manager
  • Right-click Start → Device Manager
    (or: Win+R → devmgmt.msc → Enter)

Step 2 — Locate the problem adapter
  • Expand Display Adapters
  • Right-click the adapter → Properties

Step 3 — Roll back the driver
  • Click the Driver tab
  • Click "Roll Back Driver"
  • If greyed out: no previous driver version is stored.
    You must manually install the prior version from vendor site.

Step 4 — Verify rollback
  • Check Device Manager — no yellow bang
  • Verify display resolution and signal chain

Step 5 — Prevent auto-update re-applying bad driver
  • Search: "Change device installation settings" in Start
  • Set to "No" (prevent automatic updates)
  • Or use Group Policy (admin): Device Installation Settings

VENDOR DRIVER DOWNLOAD LINKS (copy to browser)
  NVIDIA  : nvidia.com/drivers
  AMD     : amd.com/support
  Intel   : intel.com/content/www/us/en/support.html

SAFE DRIVER FALLBACK (no admin — Windows built-in)
  • Device Manager → right-click adapter → Update driver
  • "Browse my computer" → "Let me pick from a list"
  • Choose "Microsoft Basic Display Adapter" as safe baseline
  • This restores basic VGA-mode output for diagnostics.
"""

# ---------------------------------------------------------------------------
# Display profile (per-room, JSON)
# ---------------------------------------------------------------------------
def _ps(script: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except FileNotFoundError:
        return "[powershell not found]"


PS_CAPTURE_PROFILE = r"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
    "$($_.DeviceName)|$($_.Bounds.Width)|$($_.Bounds.Height)|$($_.BitsPerPixel)|$($_.Primary)"
}
"""

def _capture_room_profile(room_id: str) -> Dict:
    screens_raw = _ps(PS_CAPTURE_PROFILE)
    adapter_raw = _ps(r"""
Get-WmiObject Win32_VideoController | ForEach-Object {
    "$($_.Name)|$($_.DriverVersion)|$($_.CurrentHorizontalResolution)|$($_.CurrentVerticalResolution)|$($_.CurrentRefreshRate)"
}
""")
    screens = []
    for line in screens_raw.strip().splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 5:
            screens.append({"device": parts[0], "width": parts[1], "height": parts[2],
                            "bpp": parts[3], "primary": parts[4]})
    adapters = []
    for line in adapter_raw.strip().splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 5:
            adapters.append({"name": parts[0], "driver": parts[1],
                             "width": parts[2], "height": parts[3], "refresh": parts[4]})
    return {
        "room_id":  room_id,
        "captured": datetime.now().isoformat(timespec="seconds"),
        "screens":  screens,
        "adapters": adapters,
    }

def _room_profile_path(room_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in room_id)
    return PROFILES_DIR / f"{safe}.json"

# ---------------------------------------------------------------------------
# Room inventory persistence
# ---------------------------------------------------------------------------
def _load_inventory() -> List[Dict]:
    if INVENTORY_FILE.exists():
        try:
            return json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def _save_inventory(records: List[Dict]):
    INVENTORY_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class FieldApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  {APP_VERSION}")
        self.geometry("1080x740")
        self.configure(bg=C["bg"])
        self._inventory: List[Dict] = _load_inventory()
        self._checklist_vars: Dict = {}
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=C["panel"], pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text=APP_NAME, font=(_F, 16, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(side="left", padx=16)
        tk.Label(hdr, text=APP_VERSION, font=(_F, 10),
                 bg=C["panel"], fg=C["muted"]).pack(side="left")
        tk.Label(hdr, text="Field Technician Toolkit",
                 font=(_F, 10), bg=C["panel"], fg=C["muted"]).pack(side="right", padx=16)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",        background=C["bg"],  borderwidth=0)
        style.configure("TNotebook.Tab",    background=C["btn"], foreground=C["text"],
                        padding=[12, 5],    font=(_F, 10, "bold"))
        style.map("TNotebook.Tab",          background=[("selected", C["accent"])])
        style.configure("TFrame",           background=C["bg"])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        self._tab_inventory(nb)
        self._tab_driver(nb)
        self._tab_checklist(nb)
        self._tab_profiles(nb)

        self._status_var = tk.StringVar(value="Ready.")
        tk.Label(self, textvariable=self._status_var, bg=C["panel"], fg=C["muted"],
                 font=(_F, 9), anchor="w", padx=12).pack(fill="x", side="bottom")

    # ── Tab 1: Room Inventory ──────────────────────────────────────────────
    def _tab_inventory(self, nb: ttk.Notebook):
        frm = ttk.Frame(nb)
        nb.add(frm, text="  Room Inventory  ")

        top = tk.Frame(frm, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(top, text="AV Room Inventory",
                 font=(_F, 12, "bold"), bg=C["panel"], fg=C["text"]).pack(side="left", padx=12)

        body = tk.Frame(frm, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=6)

        # Left: room list
        left = tk.Frame(body, bg=C["panel"], width=220)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        tk.Label(left, text="Rooms", font=(_F, 10, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(pady=(10, 4))
        self._room_list = tk.Listbox(left, bg=C["notebk"], fg=C["text"],
                                      selectbackground=C["accent"],
                                      font=(_F, 10), activestyle="none", relief="flat")
        self._room_list.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self._room_list.bind("<<ListboxSelect>>", self._on_room_select)
        for lbl, cmd in [
            ("New Room",    self._new_room),
            ("Save Room",   self._save_room),
            ("Delete Room", self._delete_room),
            ("Export CSV",  self._export_inventory_csv),
        ]:
            tk.Button(left, text=lbl, bg=C["btn"], fg=C["text"], font=(_F, 9),
                      relief="flat", pady=4, command=cmd).pack(fill="x", padx=8, pady=2)

        # Right: form
        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)

        canvas = tk.Canvas(right, bg=C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["bg"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_conf(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win_id, width=canvas.winfo_width())
        inner.bind("<Configure>", _on_conf)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        self._inv_vars: Dict[str, tk.StringVar] = {}
        for i, (field, hint) in enumerate(ROOM_FIELDS):
            tk.Label(inner, text=field, font=(_F, 9, "bold"), bg=C["bg"],
                     fg=C["text"], anchor="w").grid(row=i, column=0, sticky="w",
                                                    padx=(8, 4), pady=3)
            var = tk.StringVar()
            self._inv_vars[field] = var
            if field == "Notes":
                ent = tk.Text(inner, height=3, bg=C["notebk"], fg=C["text"],
                              insertbackground=C["text"], font=(_F, 9), relief="flat")
                ent.grid(row=i, column=1, sticky="ew", padx=(0, 8), pady=3)
                self._notes_widget = ent
            else:
                ent = tk.Entry(inner, textvariable=var, bg=C["notebk"], fg=C["text"],
                               insertbackground=C["text"], font=(_F, 9), relief="flat")
                ent.grid(row=i, column=1, sticky="ew", padx=(0, 8), pady=3)
                if hint:
                    tk.Label(inner, text=hint, font=(_F, 8), bg=C["bg"],
                             fg=C["faint"]).grid(row=i, column=2, sticky="w", padx=4)
        inner.columnconfigure(1, weight=1)

        self._refresh_room_list()

    def _refresh_room_list(self):
        self._room_list.delete(0, "end")
        for rec in self._inventory:
            self._room_list.insert("end", rec.get("Room ID", "?"))

    def _on_room_select(self, _evt=None):
        sel = self._room_list.curselection()
        if not sel:
            return
        rec = self._inventory[sel[0]]
        for field, var in self._inv_vars.items():
            if field != "Notes":
                var.set(rec.get(field, ""))
        if hasattr(self, "_notes_widget"):
            self._notes_widget.delete("1.0", "end")
            self._notes_widget.insert("end", rec.get("Notes", ""))

    def _new_room(self):
        for var in self._inv_vars.values():
            var.set("")
        if hasattr(self, "_notes_widget"):
            self._notes_widget.delete("1.0", "end")
        self._inv_vars["Last Inspected"].set(date.today().isoformat())
        self._room_list.selection_clear(0, "end")

    def _save_room(self):
        rec = {f: v.get() for f, v in self._inv_vars.items() if f != "Notes"}
        if hasattr(self, "_notes_widget"):
            rec["Notes"] = self._notes_widget.get("1.0", "end").strip()
        room_id = rec.get("Room ID", "").strip()
        if not room_id:
            messagebox.showwarning("Save", "Room ID is required.")
            return
        existing = next((i for i, r in enumerate(self._inventory)
                         if r.get("Room ID") == room_id), None)
        if existing is not None:
            self._inventory[existing] = rec
        else:
            self._inventory.append(rec)
        _save_inventory(self._inventory)
        self._refresh_room_list()
        self._status(f"Room '{room_id}' saved.")

    def _delete_room(self):
        sel = self._room_list.curselection()
        if not sel:
            messagebox.showinfo("Delete", "Select a room first.")
            return
        rec = self._inventory[sel[0]]
        if messagebox.askyesno("Delete", f"Delete room '{rec.get('Room ID')}'?"):
            self._inventory.pop(sel[0])
            _save_inventory(self._inventory)
            self._refresh_room_list()
            self._new_room()

    def _export_inventory_csv(self):
        if not self._inventory:
            messagebox.showinfo("Export", "No rooms in inventory.")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = EXPORTS_DIR / f"room_inventory_{ts}.csv"
        fields = [f for f, _ in ROOM_FIELDS]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(self._inventory)
        self._status(f"Exported: {path}")
        messagebox.showinfo("Export", f"Saved to:\n{path}")

    # ── Tab 2: Driver Manager ──────────────────────────────────────────────
    def _tab_driver(self, nb: ttk.Notebook):
        frm = ttk.Frame(nb)
        nb.add(frm, text="  Driver Manager  ")

        top = tk.Frame(frm, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(top, text="AV Driver Check, Log & Rollback Guide",
                 font=(_F, 12, "bold"), bg=C["panel"], fg=C["text"]).pack(side="left", padx=12)

        btn_row = tk.Frame(frm, bg=C["bg"], pady=4)
        btn_row.pack(fill="x", padx=10)
        for label, ps in [
            ("Scan All AV Drivers",       PS_DRIVER_SCAN),
            ("Display Driver Detail",      PS_DRIVER_DETAIL),
            ("Open Device Manager",        r'Start-Process devmgmt.msc'),
            ("Open Windows Update",        r'Start-Process "ms-settings:windowsupdate"'),
        ]:
            tk.Button(btn_row, text=label, bg=C["btn"], fg=C["text"], font=(_F, 9),
                      relief="flat", padx=8, pady=4,
                      command=lambda p=ps: self._run_ps(p)).pack(side="left", padx=4)

        panes = tk.PanedWindow(frm, orient="vertical", bg=C["bg"], sashwidth=6)
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # Driver output
        out_frm = tk.Frame(panes, bg=C["bg"])
        panes.add(out_frm, stretch="always")
        tk.Label(out_frm, text="Driver Scan Output", font=(_F, 9, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w")
        self._driver_out = scrolledtext.ScrolledText(
            out_frm, bg=C["notebk"], fg=C["text"], font=("Consolas", 9),
            insertbackground=C["text"], wrap="none")
        self._driver_out.pack(fill="both", expand=True)

        # Rollback guide
        guide_frm = tk.Frame(panes, bg=C["bg"])
        panes.add(guide_frm, stretch="always")
        hdr2 = tk.Frame(guide_frm, bg=C["panel"], pady=4)
        hdr2.pack(fill="x")
        tk.Label(hdr2, text="Rollback Guide", font=(_F, 9, "bold"),
                 bg=C["panel"], fg=C["gold"]).pack(side="left", padx=8)
        tk.Button(hdr2, text="Log Driver Versions", bg=C["btn_gold"], fg=C["text"],
                  font=(_F, 9), relief="flat", padx=8,
                  command=self._log_driver_versions).pack(side="right", padx=8)
        tk.Button(hdr2, text="View Driver History", bg=C["btn"], fg=C["text"],
                  font=(_F, 9), relief="flat", padx=8,
                  command=self._show_driver_log).pack(side="right", padx=4)
        guide_txt = scrolledtext.ScrolledText(
            guide_frm, bg=C["notebk"], fg=C["text"], font=("Consolas", 9),
            insertbackground=C["text"], state="normal", wrap="word")
        guide_txt.pack(fill="both", expand=True)
        guide_txt.insert("end", ROLLBACK_GUIDE)
        guide_txt.configure(state="disabled")

    def _log_driver_versions(self):
        self._status("Logging driver versions...")
        def _work():
            raw = _ps(PS_DRIVER_SCAN, timeout=30)
            entry = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "raw": raw,
            }
            log = []
            if DRIVER_LOG_FILE.exists():
                try:
                    log = json.loads(DRIVER_LOG_FILE.read_text(encoding="utf-8"))
                except Exception:
                    pass
            log.insert(0, entry)
            log = log[:50]  # keep 50 most recent
            DRIVER_LOG_FILE.write_text(json.dumps(log, indent=2), encoding="utf-8")
            self.after(0, lambda: self._status(
                f"Driver versions logged ({entry['timestamp']})."))
        threading.Thread(target=_work, daemon=True).start()

    def _show_driver_log(self):
        if not DRIVER_LOG_FILE.exists():
            messagebox.showinfo("Driver Log", "No driver log found. Use 'Log Driver Versions' first.")
            return
        try:
            log = json.loads(DRIVER_LOG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            messagebox.showerror("Driver Log", str(e))
            return
        win = tk.Toplevel(self)
        win.title("Driver Version History")
        win.geometry("800x600")
        win.configure(bg=C["bg"])
        lb = tk.Listbox(win, bg=C["notebk"], fg=C["text"], font=(_F, 10),
                        activestyle="none", selectbackground=C["accent"])
        lb.pack(side="left", fill="y", padx=(10, 0), pady=10)
        for entry in log:
            lb.insert("end", entry.get("timestamp", "?"))
        detail = scrolledtext.ScrolledText(win, bg=C["notebk"], fg=C["text"],
                                            font=("Consolas", 9))
        detail.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        def _on_sel(_e=None):
            sel = lb.curselection()
            if sel:
                detail.delete("1.0", "end")
                detail.insert("end", log[sel[0]].get("raw", ""))
        lb.bind("<<ListboxSelect>>", _on_sel)

    def _run_ps(self, script: str):
        self._status("Running...")
        self._driver_out.insert("end", f"\n{'='*60}\n[{datetime.now():%H:%M:%S}]\n")
        self._driver_out.see("end")
        def _work():
            result = _ps(script, timeout=45)
            def _done():
                self._driver_out.insert("end", result + "\n")
                self._driver_out.see("end")
                self._status("Done.")
            self.after(0, _done)
        threading.Thread(target=_work, daemon=True).start()

    # ── Tab 3: Field Checklist ─────────────────────────────────────────────
    def _tab_checklist(self, nb: ttk.Notebook):
        frm = ttk.Frame(nb)
        nb.add(frm, text="  Field Checklist  ")

        top = tk.Frame(frm, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(top, text="Rapid Field Inspection Checklist",
                 font=(_F, 12, "bold"), bg=C["panel"], fg=C["text"]).pack(side="left", padx=12)
        tk.Button(top, text="Export Checklist Report", bg=C["btn_acc"], fg=C["text"],
                  font=(_F, 9), relief="flat", padx=8,
                  command=self._export_checklist).pack(side="right", padx=12)
        tk.Button(top, text="Reset All", bg=C["btn"], fg=C["muted"],
                  font=(_F, 9), relief="flat", padx=8,
                  command=self._reset_checklist).pack(side="right", padx=4)

        # Room ID entry
        meta = tk.Frame(frm, bg=C["bg"], pady=4)
        meta.pack(fill="x", padx=12)
        tk.Label(meta, text="Room ID:", font=(_F, 9, "bold"), bg=C["bg"],
                 fg=C["text"]).pack(side="left")
        self._check_room_var = tk.StringVar()
        tk.Entry(meta, textvariable=self._check_room_var, bg=C["notebk"], fg=C["text"],
                 font=(_F, 10), width=16, relief="flat",
                 insertbackground=C["text"]).pack(side="left", padx=6)
        tk.Label(meta, text="Technician:", font=(_F, 9, "bold"), bg=C["bg"],
                 fg=C["text"]).pack(side="left", padx=(16, 0))
        self._check_tech_var = tk.StringVar()
        tk.Entry(meta, textvariable=self._check_tech_var, bg=C["notebk"], fg=C["text"],
                 font=(_F, 10), width=20, relief="flat",
                 insertbackground=C["text"]).pack(side="left", padx=6)

        # Scrollable checklist
        canvas = tk.Canvas(frm, bg=C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(frm, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=6)
        inner = tk.Frame(canvas, bg=C["bg"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        self._checklist_vars = {}
        for section, items in CHECKLIST_SECTIONS:
            tk.Label(inner, text=section, font=(_F, 11, "bold"),
                     bg=C["panel"], fg=C["gold"]).pack(fill="x", pady=(10, 2), padx=4)
            for item in items:
                row = tk.Frame(inner, bg=C["bg"])
                row.pack(fill="x", padx=16, pady=1)
                var = tk.IntVar()
                self._checklist_vars[item] = var
                cb = tk.Checkbutton(row, text=item, variable=var,
                                    bg=C["bg"], fg=C["text"], selectcolor=C["good"],
                                    activebackground=C["bg"], activeforeground=C["text"],
                                    font=(_F, 9), anchor="w")
                cb.pack(side="left", fill="x")

    def _reset_checklist(self):
        for var in self._checklist_vars.values():
            var.set(0)

    def _export_checklist(self):
        room = self._check_room_var.get().strip() or "Unknown"
        tech = self._check_tech_var.get().strip() or "Unknown"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = EXPORTS_DIR / f"checklist_{room}_{ts}.txt"
        lines = [
            f"CITL Field Inspection Checklist",
            f"Room: {room}    Technician: {tech}    Date: {date.today().isoformat()}",
            "=" * 60,
        ]
        for section, items in CHECKLIST_SECTIONS:
            lines.append(f"\n{section}")
            lines.append("-" * len(section))
            for item in items:
                status = "[X]" if self._checklist_vars.get(item, tk.IntVar()).get() else "[ ]"
                lines.append(f"  {status} {item}")
        total = sum(v.get() for v in self._checklist_vars.values())
        pct = int(100 * total / max(len(self._checklist_vars), 1))
        lines.append(f"\nSCORE: {total}/{len(self._checklist_vars)} ({pct}%)")
        path.write_text("\n".join(lines), encoding="utf-8")
        self._status(f"Checklist exported: {path}")
        messagebox.showinfo("Export", f"Checklist saved to:\n{path}")

    # ── Tab 4: Room Display Profiles ───────────────────────────────────────
    def _tab_profiles(self, nb: ttk.Notebook):
        frm = ttk.Frame(nb)
        nb.add(frm, text="  Display Profiles  ")

        top = tk.Frame(frm, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(top, text="Room Display Profile Saver",
                 font=(_F, 12, "bold"), bg=C["panel"], fg=C["text"]).pack(side="left", padx=12)
        tk.Label(top, text="Save per-room display layouts; re-apply on return visits",
                 font=(_F, 9), bg=C["panel"], fg=C["muted"]).pack(side="right", padx=16)

        body = tk.Frame(frm, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=6)

        # Left: profile list
        left = tk.Frame(body, bg=C["panel"], width=280)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        tk.Label(left, text="Room Profiles", font=(_F, 10, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(pady=(10, 4))
        self._dp_list = tk.Listbox(left, bg=C["notebk"], fg=C["text"],
                                    selectbackground=C["accent"],
                                    font=(_F, 10), activestyle="none", relief="flat")
        self._dp_list.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self._dp_list.bind("<<ListboxSelect>>", self._on_dp_select)

        # Room ID for capture
        rid_row = tk.Frame(left, bg=C["panel"])
        rid_row.pack(fill="x", padx=8, pady=(4, 2))
        tk.Label(rid_row, text="Room ID:", font=(_F, 9), bg=C["panel"],
                 fg=C["text"]).pack(side="left")
        self._dp_room_var = tk.StringVar()
        tk.Entry(rid_row, textvariable=self._dp_room_var, bg=C["notebk"], fg=C["text"],
                 font=(_F, 9), width=12, relief="flat",
                 insertbackground=C["text"]).pack(side="left", padx=4)
        for lbl, cmd in [
            ("Save Profile for Room", self._save_dp),
            ("Apply Profile (extend/single)", self._apply_dp),
            ("Delete Profile", self._delete_dp),
            ("Refresh List", self._refresh_dp_list),
        ]:
            tk.Button(left, text=lbl, bg=C["btn"], fg=C["text"], font=(_F, 9),
                      relief="flat", pady=4, command=cmd).pack(fill="x", padx=8, pady=2)

        # Right: detail
        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="Profile Detail", font=(_F, 10, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w")
        self._dp_detail = scrolledtext.ScrolledText(
            right, bg=C["notebk"], fg=C["text"], font=("Consolas", 9),
            insertbackground=C["text"], state="disabled")
        self._dp_detail.pack(fill="both", expand=True)

        self._dp_profiles: List[Dict] = []
        self._refresh_dp_list()

    def _refresh_dp_list(self):
        self._dp_list.delete(0, "end")
        self._dp_profiles = []
        for f in sorted(PROFILES_DIR.glob("*.json")):
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                self._dp_profiles.append(p)
                sc = len(p.get("screens", []))
                ts = p.get("captured", "?")[:16]
                self._dp_list.insert("end", f"{p.get('room_id','?')}  [{sc}scr  {ts}]")
            except Exception:
                pass

    def _on_dp_select(self, _evt=None):
        sel = self._dp_list.curselection()
        if not sel:
            return
        p = self._dp_profiles[sel[0]]
        self._dp_detail.configure(state="normal")
        self._dp_detail.delete("1.0", "end")
        self._dp_detail.insert("end", json.dumps(p, indent=2))
        self._dp_detail.configure(state="disabled")

    def _save_dp(self):
        room_id = self._dp_room_var.get().strip()
        if not room_id:
            messagebox.showwarning("Save Profile", "Enter a Room ID first.")
            return
        self._status(f"Capturing display state for {room_id}...")
        def _work():
            data = _capture_room_profile(room_id)
            path = _room_profile_path(room_id)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self.after(0, lambda: self._status(f"Profile saved for '{room_id}'."))
            self.after(0, self._refresh_dp_list)
        threading.Thread(target=_work, daemon=True).start()

    def _apply_dp(self):
        sel = self._dp_list.curselection()
        if not sel:
            messagebox.showinfo("Apply", "Select a profile first.")
            return
        p = self._dp_profiles[sel[0]]
        screens = p.get("screens", [])
        count = len(screens)
        if count == 1:
            ps = r'Start-Process "displayswitch.exe" -ArgumentList "/internal" -NoNewWindow'
            mode = "PC Screen Only"
        else:
            ps = r'Start-Process "displayswitch.exe" -ArgumentList "/extend" -NoNewWindow'
            mode = "Extend"
        self._status(f"Applying '{mode}' for room '{p.get('room_id')}'...")
        threading.Thread(target=lambda: _ps(ps), daemon=True).start()
        messagebox.showinfo("Apply Profile",
                            f"Display mode '{mode}' applied for room '{p.get('room_id')}'.\n"
                            f"Saved: {p.get('captured','?')}\n"
                            f"Screens: {count}\n\n"
                            "Tip: Use Windows Display Settings to fine-tune resolution/refresh.")

    def _delete_dp(self):
        sel = self._dp_list.curselection()
        if not sel:
            messagebox.showinfo("Delete", "Select a profile first.")
            return
        p = self._dp_profiles[sel[0]]
        if messagebox.askyesno("Delete", f"Delete profile for room '{p.get('room_id')}'?"):
            _room_profile_path(p.get("room_id", "")).unlink(missing_ok=True)
            self._refresh_dp_list()

    # ------------------------------------------------------------------ Helpers
    def _status(self, msg: str):
        self._status_var.set(msg)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    if sys.platform != "win32":
        print("CITL Field Apps is Windows-only (uses PowerShell / WMI).")
        sys.exit(1)
    app = FieldApp()
    app.mainloop()


if __name__ == "__main__":
    main()
