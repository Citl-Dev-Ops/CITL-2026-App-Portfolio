#!/usr/bin/env python3
"""
CITL Workstation Apps
Display port tester, profile save/restore, connection diagnostics, and quick-fix
actions for campus workstations that have persistent display difficulties.
Non-admin, USB-portable, Windows 10/11.
"""
from __future__ import annotations
import json, os, subprocess, sys, threading, time
from datetime import datetime
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
PROFILES_DIR = REPO / "documents" / "display_profiles"
EXPORTS_DIR  = REPO / "documents" / "workstation_exports"
for _d in (PROFILES_DIR, EXPORTS_DIR):
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
APP_NAME    = "CITL Workstation Apps"
APP_VERSION = "v1.0"


# ---------------------------------------------------------------------------
# PowerShell helper
# ---------------------------------------------------------------------------
def _ps(script: str, timeout: int = 30) -> str:
    """Run an inline PowerShell snippet and return stdout."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, timeout=timeout
        )
        return (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except FileNotFoundError:
        return "[powershell not found]"


def _cmd(args: List[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return str(e)


# ---------------------------------------------------------------------------
# Display data queries (non-admin)
# ---------------------------------------------------------------------------
PS_SCREENS = r"""
Add-Type -AssemblyName System.Windows.Forms
$screens = [System.Windows.Forms.Screen]::AllScreens
foreach ($s in $screens) {
    $tag = if ($s.Primary) {"[PRIMARY]"} else {"[EXTENDED]"}
    "$tag  $($s.DeviceName)  $($s.Bounds.Width)x$($s.Bounds.Height)  BPP=$($s.BitsPerPixel)"
}
"""

PS_ADAPTERS = r"""
Get-WmiObject Win32_VideoController | Select-Object -Property Name,DriverVersion,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate,VideoModeDescription,AdapterRAM | ForEach-Object {
    $ram = if ($_.AdapterRAM) { [math]::Round($_.AdapterRAM/1MB,0).ToString() + " MB" } else { "N/A" }
    "$($_.Name)  |  Driver: $($_.DriverVersion)  |  $($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution) @ $($_.CurrentRefreshRate)Hz  |  VRAM: $ram"
}
"""

PS_MONITORS = r"""
Get-PnpDevice -Class Monitor -PresentOnly -ErrorAction SilentlyContinue | Select-Object FriendlyName,Status,DeviceID | ForEach-Object {
    "$($_.Status.PadRight(8))  $($_.FriendlyName)  [$($_.DeviceID -replace '.*\\','' )]"
}
"""

PS_DISPLAY_FULL = r"""
Add-Type -AssemblyName System.Windows.Forms
Write-Host "=== ATTACHED SCREENS ==="
$screens = [System.Windows.Forms.Screen]::AllScreens
$i = 1
foreach ($s in $screens) {
    $tag = if ($s.Primary) {"PRIMARY"} else {"EXTENDED"}
    Write-Host "  Screen $i ($tag): $($s.DeviceName)  $($s.Bounds.Width)x$($s.Bounds.Height)  BPP=$($s.BitsPerPixel)"
    $i++
}
Write-Host ""
Write-Host "=== DISPLAY ADAPTERS ==="
Get-WmiObject Win32_VideoController | ForEach-Object {
    $ram = if ($_.AdapterRAM) { [math]::Round($_.AdapterRAM/1MB,0).ToString() + " MB" } else { "N/A" }
    Write-Host "  $($_.Name)"
    Write-Host "    Driver : $($_.DriverVersion)"
    Write-Host "    Mode   : $($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution) @ $($_.CurrentRefreshRate) Hz"
    Write-Host "    VRAM   : $ram"
}
Write-Host ""
Write-Host "=== PNP MONITORS ==="
Get-PnpDevice -Class Monitor -PresentOnly -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  [$($_.Status)] $($_.FriendlyName)"
}
Write-Host ""
Write-Host "=== DisplayPort / HDMI AUDIO (signal indicator) ==="
Get-PnpDevice -Class AudioEndpoint -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match "HDMI|DisplayPort|DP|Display Audio" } | ForEach-Object {
    Write-Host "  [$($_.Status)] $($_.FriendlyName)"
}
"""

PS_DIAG = r"""
Add-Type -AssemblyName System.Windows.Forms
$issues = @()
# Check: screens attached
$screens = [System.Windows.Forms.Screen]::AllScreens
if ($screens.Count -eq 0) { $issues += "CRITICAL: No display output detected." }
if ($screens.Count -eq 1) { Write-Host "INFO: Single display mode (only primary screen active)." }
else { Write-Host "OK: $($screens.Count) screens detected." }

# Check: adapters
$adapters = Get-WmiObject Win32_VideoController
foreach ($a in $adapters) {
    if ($a.Status -and $a.Status -ne "OK") { $issues += "WARN: Adapter '$($a.Name)' status = $($a.Status)" }
    if (-not $a.DriverVersion) { $issues += "WARN: Adapter '$($a.Name)' missing driver version." }
    else { Write-Host "OK: $($a.Name) driver $($a.DriverVersion)" }
    if ($a.CurrentRefreshRate -and $a.CurrentRefreshRate -lt 50) { $issues += "WARN: Refresh rate $($a.CurrentRefreshRate)Hz is unusually low on $($a.Name)" }
}

# Check: PNP monitors
$mons = Get-PnpDevice -Class Monitor -ErrorAction SilentlyContinue
$errMons = $mons | Where-Object { $_.Status -ne "OK" }
if ($errMons) { foreach ($m in $errMons) { $issues += "WARN: Monitor '$($m.FriendlyName)' PNP status = $($m.Status)" } }
else { Write-Host "OK: All PNP monitors report OK status." }

# Check: HDMI/DP audio (signal presence indicator)
$dpAudio = Get-PnpDevice -Class AudioEndpoint -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match "HDMI|DisplayPort|DP|Display Audio" }
if ($dpAudio) { Write-Host "OK: HDMI/DP audio endpoint present ($($dpAudio.Count) device(s)) -- signal confirmed." }
else { $issues += "WARN: No HDMI/DisplayPort audio endpoint found. Display may not be receiving signal." }

Write-Host ""
if ($issues.Count -eq 0) { Write-Host "RESULT: No display issues detected." }
else {
    Write-Host "RESULT: $($issues.Count) issue(s) found:"
    $issues | ForEach-Object { Write-Host "  >> $_" }
}
"""


# ---------------------------------------------------------------------------
# Profile management (JSON, stored in PROFILES_DIR)
# ---------------------------------------------------------------------------
def _capture_profile() -> Optional[Dict]:
    """Capture current display state as a dict."""
    raw = _ps(PS_DISPLAY_FULL, timeout=20)
    screens_raw = _ps(r"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
    "$($_.DeviceName)|$($_.Bounds.Width)|$($_.Bounds.Height)|$($_.BitsPerPixel)|$($_.Primary)"
}
""")
    adapters_raw = _ps(r"""
Get-WmiObject Win32_VideoController | ForEach-Object {
    "$($_.Name)|$($_.DriverVersion)|$($_.CurrentHorizontalResolution)|$($_.CurrentVerticalResolution)|$($_.CurrentRefreshRate)"
}
""")
    monitors_raw = _ps(r"""
Get-PnpDevice -Class Monitor -PresentOnly -ErrorAction SilentlyContinue | ForEach-Object {
    "$($_.FriendlyName)|$($_.Status)"
}
""")
    screens = []
    for line in screens_raw.strip().splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 5:
            screens.append({
                "device": parts[0], "width": parts[1], "height": parts[2],
                "bpp": parts[3], "primary": parts[4]
            })
    adapters = []
    for line in adapters_raw.strip().splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 5:
            adapters.append({
                "name": parts[0], "driver": parts[1],
                "width": parts[2], "height": parts[3], "refresh": parts[4]
            })
    monitors = []
    for line in monitors_raw.strip().splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 2:
            monitors.append({"name": parts[0], "status": parts[1]})

    return {
        "captured": datetime.now().isoformat(timespec="seconds"),
        "screens":  screens,
        "adapters": adapters,
        "monitors": monitors,
        "raw_snapshot": raw,
    }


def _profile_path(name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    return PROFILES_DIR / f"{safe}.json"


def _save_profile(name: str, data: Dict) -> Path:
    data["name"] = name
    p = _profile_path(name)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _load_profiles() -> List[Dict]:
    profiles = []
    for f in sorted(PROFILES_DIR.glob("*.json")):
        try:
            profiles.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return profiles


# ---------------------------------------------------------------------------
# Quick-fix actions
# ---------------------------------------------------------------------------
QUICK_FIXES = [
    ("Detect / Re-detect Displays",
     r'Start-Process "displayswitch.exe" -ArgumentList "/detect" -NoNewWindow'),
    ("Extend to All Displays",
     r'Start-Process "displayswitch.exe" -ArgumentList "/extend" -NoNewWindow'),
    ("Duplicate (Mirror) Displays",
     r'Start-Process "displayswitch.exe" -ArgumentList "/clone" -NoNewWindow'),
    ("PC Screen Only (Disconnect external)",
     r'Start-Process "displayswitch.exe" -ArgumentList "/internal" -NoNewWindow'),
    ("Second Screen Only",
     r'Start-Process "displayswitch.exe" -ArgumentList "/external" -NoNewWindow'),
    ("Restart Windows Explorer (fixes taskbar/display shell issues)",
     r'Stop-Process -Name explorer -Force; Start-Sleep 1; Start-Process explorer'),
    ("Clear Display Cache (DevMgr scan for hardware changes)",
     r'pnputil /scan-devices'),
    ("Open Display Settings (Windows Control Panel)",
     r'Start-Process "ms-settings:display"'),
    ("Open Device Manager",
     r'Start-Process devmgmt.msc'),
    ("Check HDMI/DP Audio Endpoints",
     PS_DIAG),
]

PORT_TESTS = [
    ("Scan All Connected Displays", PS_SCREENS),
    ("Show Display Adapters + Driver Versions", PS_ADAPTERS),
    ("List PNP Monitors (all, including error state)", r"""
Get-PnpDevice -Class Monitor | Select-Object FriendlyName,Status,DeviceID | Format-Table -AutoSize | Out-String -Width 200
"""),
    ("Detect HDMI/DP Audio Endpoints (signal presence)", r"""
Get-PnpDevice -Class AudioEndpoint -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object { $_.FriendlyName -match "HDMI|DisplayPort|DP|Display Audio" } |
    Select-Object FriendlyName,Status | Format-Table -AutoSize | Out-String -Width 200
"""),
    ("USB Display / Dock Devices", r"""
Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object { $_.FriendlyName -match "dock|docking|usb.*display|displaylink|j5create|plugable" } |
    Select-Object FriendlyName,Status | Format-Table -AutoSize | Out-String -Width 200
"""),
    ("Current Resolution + Refresh Rate (all adapters)", r"""
Get-WmiObject Win32_VideoController | Select-Object Name,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate,DriverVersion | Format-Table -AutoSize | Out-String -Width 200
"""),
]


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class WorkstationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  {APP_VERSION}")
        self.geometry("1040x720")
        self.configure(bg=C["bg"])
        self._busy = False
        self._build_ui()
        self.after(200, self._auto_scan_ports)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=C["panel"], pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text=APP_NAME, font=(_F, 16, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(side="left", padx=16)
        tk.Label(hdr, text=APP_VERSION, font=(_F, 10),
                 bg=C["panel"], fg=C["muted"]).pack(side="left")
        tk.Label(hdr, text="Campus Workstation Display Tools",
                 font=(_F, 10), bg=C["panel"], fg=C["muted"]).pack(side="right", padx=16)

        # Notebook
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",        background=C["bg"],     borderwidth=0)
        style.configure("TNotebook.Tab",    background=C["btn"],    foreground=C["text"],
                        padding=[12, 5],    font=(_F, 10, "bold"))
        style.map("TNotebook.Tab",          background=[("selected", C["accent"])])
        style.configure("TFrame",           background=C["bg"])
        style.configure("TLabel",           background=C["bg"],     foreground=C["text"])
        style.configure("TButton",          background=C["btn"],    foreground=C["text"],
                        font=(_F, 9),       relief="flat",          padding=6)
        style.map("TButton",                background=[("active", C["btn_hi"])])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        self._tab_ports(nb)
        self._tab_profiles(nb)
        self._tab_diagnostics(nb)
        self._tab_quickfix(nb)

        # Status bar
        self._status_var = tk.StringVar(value="Ready.")
        tk.Label(self, textvariable=self._status_var, bg=C["panel"], fg=C["muted"],
                 font=(_F, 9), anchor="w", padx=12).pack(fill="x", side="bottom")

    # ── Tab 1: Port Tester ─────────────────────────────────────────────────
    def _tab_ports(self, nb: ttk.Notebook):
        frm = ttk.Frame(nb)
        nb.add(frm, text="  Display Ports  ")

        top = tk.Frame(frm, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(top, text="Display Port & Connection Tester",
                 font=(_F, 12, "bold"), bg=C["panel"], fg=C["text"]).pack(side="left", padx=12)

        btn_row = tk.Frame(frm, bg=C["bg"], pady=4)
        btn_row.pack(fill="x", padx=10)
        for label, ps in PORT_TESTS:
            b = tk.Button(btn_row, text=label, bg=C["btn"], fg=C["text"],
                          font=(_F, 9), relief="flat", padx=8, pady=4,
                          command=lambda p=ps: self._run_in_output(p, self._port_out))
            b.pack(side="left", padx=4, pady=4)

        self._port_out = scrolledtext.ScrolledText(
            frm, bg=C["notebk"], fg=C["text"], font=("Consolas", 9),
            insertbackground=C["text"], wrap="none")
        self._port_out.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        btm = tk.Frame(frm, bg=C["bg"])
        btm.pack(fill="x", padx=10, pady=4)
        tk.Button(btm, text="Clear", bg=C["btn"], fg=C["muted"], font=(_F, 9),
                  relief="flat", padx=8,
                  command=lambda: self._port_out.delete("1.0", "end")).pack(side="right")
        tk.Button(btm, text="Export Log", bg=C["btn_acc"], fg=C["text"], font=(_F, 9),
                  relief="flat", padx=8,
                  command=lambda: self._export_log(self._port_out, "port_test")).pack(side="right", padx=6)

    # ── Tab 2: Profile Manager ─────────────────────────────────────────────
    def _tab_profiles(self, nb: ttk.Notebook):
        frm = ttk.Frame(nb)
        nb.add(frm, text="  Display Profiles  ")

        top = tk.Frame(frm, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(top, text="Save & Restore Display Configurations",
                 font=(_F, 12, "bold"), bg=C["panel"], fg=C["text"]).pack(side="left", padx=12)

        body = tk.Frame(frm, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=6)

        # Left: list
        left = tk.Frame(body, bg=C["panel"], width=260)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        tk.Label(left, text="Saved Profiles", font=(_F, 10, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(pady=(10, 4))

        self._profile_list = tk.Listbox(left, bg=C["notebk"], fg=C["text"],
                                         selectbackground=C["accent"],
                                         font=(_F, 10), activestyle="none", relief="flat")
        self._profile_list.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self._profile_list.bind("<<ListboxSelect>>", self._on_profile_select)

        for lbl, cmd in [
            ("Save Current Layout", self._save_profile_dialog),
            ("Load Selected", self._load_profile),
            ("Delete Selected", self._delete_profile),
            ("Refresh List", self._refresh_profile_list),
        ]:
            tk.Button(left, text=lbl, bg=C["btn"], fg=C["text"], font=(_F, 9),
                      relief="flat", pady=4, command=cmd).pack(fill="x", padx=8, pady=2)

        # Right: detail
        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="Profile Detail", font=(_F, 10, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w")
        self._profile_detail = scrolledtext.ScrolledText(
            right, bg=C["notebk"], fg=C["text"], font=("Consolas", 9),
            insertbackground=C["text"], state="disabled", height=8)
        self._profile_detail.pack(fill="both", expand=True)

        tk.Label(right, text="Current State Snapshot",
                 font=(_F, 10, "bold"), bg=C["bg"], fg=C["text"]).pack(anchor="w", pady=(8, 0))
        self._profile_snap = scrolledtext.ScrolledText(
            right, bg=C["notebk"], fg=C["text"], font=("Consolas", 9),
            insertbackground=C["text"], state="disabled")
        self._profile_snap.pack(fill="both", expand=True)

        tk.Button(right, text="Capture Current State",
                  bg=C["btn_acc"], fg=C["text"], font=(_F, 9), relief="flat", pady=4,
                  command=self._capture_now).pack(anchor="w", pady=4)

        self._refresh_profile_list()

    def _refresh_profile_list(self):
        self._profile_list.delete(0, "end")
        for p in _load_profiles():
            ts = p.get("captured", "?")[:16]
            sc = len(p.get("screens", []))
            self._profile_list.insert("end", f"{p.get('name','?')}  [{sc} screen(s)  {ts}]")
        self._profiles = _load_profiles()

    def _on_profile_select(self, _evt=None):
        sel = self._profile_list.curselection()
        if not sel:
            return
        p = self._profiles[sel[0]]
        txt = json.dumps(p, indent=2)
        self._profile_detail.configure(state="normal")
        self._profile_detail.delete("1.0", "end")
        self._profile_detail.insert("end", txt)
        self._profile_detail.configure(state="disabled")

    def _save_profile_dialog(self):
        name = simpledialog.askstring("Save Profile", "Profile name:", parent=self)
        if not name or not name.strip():
            return
        self._status("Capturing current display state...")
        def _work():
            data = _capture_profile()
            if data:
                _save_profile(name.strip(), data)
                self.after(0, lambda: self._status(f"Profile '{name}' saved."))
                self.after(0, self._refresh_profile_list)
            else:
                self.after(0, lambda: self._status("Capture failed."))
        threading.Thread(target=_work, daemon=True).start()

    def _load_profile(self):
        sel = self._profile_list.curselection()
        if not sel:
            messagebox.showinfo("Load Profile", "Select a profile first.")
            return
        p = self._profiles[sel[0]]
        screens = p.get("screens", [])
        if not screens:
            messagebox.showinfo("Load Profile", "No screen data in this profile.")
            return
        count = len(screens)
        if count == 1 and screens[0].get("primary") in ("True", True):
            ps = r'Start-Process "displayswitch.exe" -ArgumentList "/internal" -NoNewWindow'
        else:
            ps = r'Start-Process "displayswitch.exe" -ArgumentList "/extend" -NoNewWindow'
        self._status(f"Applying profile '{p.get('name')}' (display mode)...")
        threading.Thread(target=lambda: _ps(ps), daemon=True).start()
        messagebox.showinfo("Apply Profile",
                            f"Display mode applied for '{p.get('name')}'.\n"
                            f"Saved: {p.get('captured','?')}\n"
                            f"Screens: {count}\n\n"
                            "Note: Resolution/refresh settings require Windows Display Settings.")

    def _delete_profile(self):
        sel = self._profile_list.curselection()
        if not sel:
            messagebox.showinfo("Delete", "Select a profile first.")
            return
        p = self._profiles[sel[0]]
        if messagebox.askyesno("Delete", f"Delete profile '{p.get('name')}'?"):
            _profile_path(p.get("name", "")).unlink(missing_ok=True)
            self._refresh_profile_list()
            self._status(f"Profile '{p.get('name')}' deleted.")

    def _capture_now(self):
        self._status("Capturing current display state...")
        def _work():
            raw = _ps(PS_DISPLAY_FULL, timeout=20)
            self.after(0, lambda: self._set_text(self._profile_snap, raw))
            self.after(0, lambda: self._status("Snapshot complete."))
        threading.Thread(target=_work, daemon=True).start()

    # ── Tab 3: Diagnostics ─────────────────────────────────────────────────
    def _tab_diagnostics(self, nb: ttk.Notebook):
        frm = ttk.Frame(nb)
        nb.add(frm, text="  Diagnostics  ")

        top = tk.Frame(frm, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(top, text="Display Connection Diagnostics",
                 font=(_F, 12, "bold"), bg=C["panel"], fg=C["text"]).pack(side="left", padx=12)

        btn_row = tk.Frame(frm, bg=C["bg"], pady=4)
        btn_row.pack(fill="x", padx=10)
        tk.Button(btn_row, text="Run Full Diagnostic", bg=C["btn_acc"], fg=C["text"],
                  font=(_F, 10, "bold"), relief="flat", padx=12, pady=6,
                  command=lambda: self._run_in_output(PS_DIAG, self._diag_out)).pack(side="left", padx=4)
        tk.Button(btn_row, text="Full Display Snapshot", bg=C["btn"], fg=C["text"],
                  font=(_F, 9), relief="flat", padx=8, pady=4,
                  command=lambda: self._run_in_output(PS_DISPLAY_FULL, self._diag_out)).pack(side="left", padx=4)
        tk.Button(btn_row, text="Windows Driver Verifier Info", bg=C["btn"], fg=C["text"],
                  font=(_F, 9), relief="flat", padx=8, pady=4,
                  command=lambda: self._run_in_output(r"""
Get-WmiObject Win32_VideoController | Select-Object Name,Status,DriverVersion,InfFilename | Format-List | Out-String -Width 200
""", self._diag_out)).pack(side="left", padx=4)
        tk.Button(btn_row, text="Event Log (Display Errors, last 20)", bg=C["btn"], fg=C["text"],
                  font=(_F, 9), relief="flat", padx=8, pady=4,
                  command=lambda: self._run_in_output(r"""
Get-WinEvent -LogName System -MaxEvents 200 -ErrorAction SilentlyContinue |
    Where-Object { $_.Message -match "display|monitor|video|HDMI|DisplayPort" } |
    Select-Object -First 20 TimeCreated,Id,LevelDisplayName,Message |
    ForEach-Object { "$($_.TimeCreated)  [$($_.LevelDisplayName)]  ID=$($_.Id)`n  $($_.Message.Substring(0,[Math]::Min(200,$_.Message.Length)))`n" }
""", self._diag_out)).pack(side="left", padx=4)

        self._diag_out = scrolledtext.ScrolledText(
            frm, bg=C["notebk"], fg=C["text"], font=("Consolas", 9),
            insertbackground=C["text"], wrap="none")
        self._diag_out.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        btm = tk.Frame(frm, bg=C["bg"])
        btm.pack(fill="x", padx=10, pady=4)
        tk.Button(btm, text="Clear", bg=C["btn"], fg=C["muted"], font=(_F, 9),
                  relief="flat", padx=8,
                  command=lambda: self._diag_out.delete("1.0", "end")).pack(side="right")
        tk.Button(btm, text="Export Diagnostic Report", bg=C["btn_acc"], fg=C["text"],
                  font=(_F, 9), relief="flat", padx=8,
                  command=lambda: self._export_log(self._diag_out, "diagnostic")).pack(side="right", padx=6)

    # ── Tab 4: Quick Fixes ─────────────────────────────────────────────────
    def _tab_quickfix(self, nb: ttk.Notebook):
        frm = ttk.Frame(nb)
        nb.add(frm, text="  Quick Fixes  ")

        top = tk.Frame(frm, bg=C["panel"], pady=6)
        top.pack(fill="x")
        tk.Label(top, text="Display Quick-Fix Actions",
                 font=(_F, 12, "bold"), bg=C["panel"], fg=C["text"]).pack(side="left", padx=12)
        tk.Label(top, text="These actions use built-in Windows tools — no admin needed",
                 font=(_F, 9), bg=C["panel"], fg=C["muted"]).pack(side="right", padx=16)

        btn_area = tk.Frame(frm, bg=C["bg"])
        btn_area.pack(fill="x", padx=10, pady=8)

        for label, ps in QUICK_FIXES:
            row = tk.Frame(btn_area, bg=C["panel"], pady=6, padx=10)
            row.pack(fill="x", pady=3)
            tk.Button(row, text=label, bg=C["btn_acc"], fg=C["text"],
                      font=(_F, 9, "bold"), relief="flat", padx=10, pady=4, width=42,
                      anchor="w",
                      command=lambda p=ps: self._run_in_output(p, self._fix_out)).pack(side="left")

        self._fix_out = scrolledtext.ScrolledText(
            frm, bg=C["notebk"], fg=C["text"], font=("Consolas", 9),
            insertbackground=C["text"], wrap="none", height=10)
        self._fix_out.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        btm = tk.Frame(frm, bg=C["bg"])
        btm.pack(fill="x", padx=10, pady=4)
        tk.Button(btm, text="Clear", bg=C["btn"], fg=C["muted"], font=(_F, 9),
                  relief="flat", padx=8,
                  command=lambda: self._fix_out.delete("1.0", "end")).pack(side="right")

    # ------------------------------------------------------------------ Helpers
    def _run_in_output(self, ps_script: str, output_widget: scrolledtext.ScrolledText):
        if self._busy:
            self._status("Busy — please wait for current operation to finish.")
            return
        self._busy = True
        self._status("Running...")
        output_widget.insert("end", f"\n{'='*60}\n[{datetime.now():%H:%M:%S}] Running...\n")
        output_widget.see("end")

        def _work():
            result = _ps(ps_script, timeout=45)
            def _done():
                output_widget.insert("end", result + "\n")
                output_widget.see("end")
                self._status("Done.")
                self._busy = False
            self.after(0, _done)
        threading.Thread(target=_work, daemon=True).start()

    def _set_text(self, widget: scrolledtext.ScrolledText, text: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")

    def _status(self, msg: str):
        self._status_var.set(msg)

    def _export_log(self, widget: scrolledtext.ScrolledText, prefix: str):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = EXPORTS_DIR / f"{prefix}_{ts}.txt"
        content = widget.get("1.0", "end")
        path.write_text(content, encoding="utf-8")
        self._status(f"Exported: {path}")
        messagebox.showinfo("Export", f"Saved to:\n{path}")

    def _auto_scan_ports(self):
        self._run_in_output(PS_SCREENS, self._port_out)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    if sys.platform != "win32":
        print("CITL Workstation Apps is Windows-only (uses PowerShell / WMI).")
        sys.exit(1)
    app = WorkstationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
