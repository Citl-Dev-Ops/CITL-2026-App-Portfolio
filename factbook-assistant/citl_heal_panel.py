"""
citl_heal_panel.py  —  CITL Self-Heal Diagnostic Panel (Tkinter)
═════════════════════════════════════════════════════════════════
A reusable Tkinter frame that embeds as a tab in any CITL app.

Shows:
  • Colored status dot (green / yellow / red) per check
  • One-line result message
  • Expand/collapse detail text
  • Action buttons that stream live output into a log pane

Usage (embed as a tab)
-----------------------
    from citl_heal_panel import HealPanel
    nb.add(HealPanel(nb, theme=pal), text="Diagnostics")

Usage (standalone window)
-------------------------
    from citl_heal_panel import open_heal_window
    open_heal_window(parent, theme=pal)

Theme dict keys used: bg, fg, accent, highlight, button_bg, button_fg,
                      text_bg, text_fg, status_fg, entry_bg, entry_fg
"""
from __future__ import annotations

import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable, Dict, List, Optional

from citl_heal import (
    DiagnosticResult, HealAction,
    run_full_diagnostic, run_quick_diagnostic, summary,
)

# ── Default teal theme (matches FLEX Troubleshooter) ─────────────────────────

_DEFAULT_THEME: Dict[str, str] = {
    "bg":         "#071A1E",
    "fg":         "#C8E8EC",
    "accent":     "#00C8A8",
    "highlight":  "#0A3040",
    "button_bg":  "#0D2838",
    "button_fg":  "#B8E8E4",
    "text_bg":    "#041214",
    "text_fg":    "#B4DCE0",
    "status_fg":  "#00E5C8",
    "entry_bg":   "#041214",
    "entry_fg":   "#C0E4E8",
    "error_fg":   "#FF6B6B",
    "warn_fg":    "#FFD166",
    "ok_fg":      "#06D6A0",
}

# ── Status dot colours ────────────────────────────────────────────────────────
_DOT = {"ok": "●", "warn": "●", "error": "●"}
_DOT_COLOR = {"ok": "#06D6A0", "warn": "#FFD166", "error": "#FF6B6B"}


class _CheckRow(tk.Frame):
    """One row: status dot  |  name + message  |  action buttons  |  [Detail ▸]"""

    def __init__(self, parent: tk.Widget, result: DiagnosticResult,
                 theme: Dict, log_cb: Callable[[str], None], **kw):
        super().__init__(parent, bg=theme["bg"], **kw)
        self._theme = theme
        self._result = result
        self._log_cb = log_cb
        self._expanded = False
        self._detail_frame: Optional[tk.Frame] = None
        self._build()

    def _build(self):
        t = self._theme
        r = self._result

        dot_color = _DOT_COLOR.get(r.status, t["fg"])
        tk.Label(self, text=_DOT[r.status], fg=dot_color, bg=t["bg"],
                 font=("Consolas", 12)).pack(side="left", padx=(4, 6))

        # Name + message
        info_frame = tk.Frame(self, bg=t["bg"])
        info_frame.pack(side="left", fill="x", expand=True)
        tk.Label(info_frame, text=f"[{r.category}] {r.name}",
                 fg=t["accent"], bg=t["bg"],
                 font=("Consolas", 9, "bold"), anchor="w").pack(anchor="w")
        tk.Label(info_frame, text=r.message,
                 fg=t["fg"], bg=t["bg"],
                 font=("Consolas", 9), wraplength=480, justify="left",
                 anchor="w").pack(anchor="w")

        btn_frame = tk.Frame(self, bg=t["bg"])
        btn_frame.pack(side="right", padx=4)

        # Action buttons
        for action in r.actions:
            _a = action  # closure capture
            tk.Button(
                btn_frame, text=_a.label,
                bg=t["button_bg"], fg=t["button_fg"],
                activebackground=t["accent"], activeforeground=t["bg"],
                relief="flat", padx=6, pady=2, cursor="hand2",
                font=("Consolas", 8),
                command=lambda a=_a: self._run_action(a),
            ).pack(side="left", padx=2)

        # Detail toggle
        if r.detail:
            tk.Button(
                btn_frame, text="Detail ▸",
                bg=t["button_bg"], fg=t["status_fg"],
                activebackground=t["highlight"],
                relief="flat", padx=4, pady=2, cursor="hand2",
                font=("Consolas", 8),
                command=self._toggle_detail,
            ).pack(side="left", padx=2)

        # Separator line
        tk.Frame(self, height=1, bg=t["highlight"]).pack(fill="x", side="bottom")

    def _toggle_detail(self):
        t = self._theme
        r = self._result
        if self._expanded:
            if self._detail_frame:
                self._detail_frame.destroy()
                self._detail_frame = None
            self._expanded = False
        else:
            self._detail_frame = tk.Frame(self, bg=t["highlight"], padx=8, pady=4)
            self._detail_frame.pack(fill="x", after=self.winfo_children()[1])
            tk.Label(self._detail_frame, text=r.detail,
                     fg=t["warn_fg"], bg=t["highlight"],
                     font=("Consolas", 8), justify="left", wraplength=540,
                     anchor="w").pack(anchor="w")
            self._expanded = True

    def _run_action(self, action: HealAction):
        self._log_cb(f"\n{'─'*50}")
        self._log_cb(f"▶  {action.description}")
        self._log_cb(f"{'─'*50}")
        if action.is_async:
            threading.Thread(
                target=action.run_fn,
                args=(self._log_cb,),
                daemon=True,
            ).start()
        else:
            action.run_fn(self._log_cb)


class HealPanel(tk.Frame):
    """
    Full diagnostic panel — scrollable check list + log pane.
    Designed to be added as a Notebook tab.
    """

    def __init__(self, parent: tk.Widget, theme: Dict = None, quick: bool = False, **kw):
        self._theme = dict(_DEFAULT_THEME)
        if theme:
            self._theme.update(theme)
        t = self._theme
        super().__init__(parent, bg=t["bg"], **kw)
        self._quick = quick
        self._results: List[DiagnosticResult] = []
        self._build_ui()

    def _build_ui(self):
        t = self._theme

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = tk.Frame(self, bg=t["bg"], pady=4)
        toolbar.pack(fill="x")

        tk.Label(toolbar, text="  CITL Diagnostics & Self-Heal",
                 fg=t["accent"], bg=t["bg"],
                 font=("Consolas", 11, "bold")).pack(side="left")

        tk.Button(toolbar, text="▶  Run Full Diagnostic",
                  bg=t["accent"], fg=t["bg"],
                  activebackground=t["status_fg"], activeforeground=t["bg"],
                  relief="flat", padx=10, pady=3, cursor="hand2",
                  font=("Consolas", 9, "bold"),
                  command=self._run_full).pack(side="right", padx=6)

        tk.Button(toolbar, text="Quick Check",
                  bg=t["button_bg"], fg=t["button_fg"],
                  activebackground=t["highlight"],
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  font=("Consolas", 9),
                  command=self._run_quick).pack(side="right", padx=2)

        tk.Button(toolbar, text="Clear Log",
                  bg=t["button_bg"], fg=t["button_fg"],
                  activebackground=t["highlight"],
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  font=("Consolas", 9),
                  command=self._clear_log).pack(side="right", padx=2)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Click 'Run Full Diagnostic' to begin.")
        tk.Label(self, textvariable=self._status_var,
                 fg=t["status_fg"], bg=t["highlight"],
                 font=("Consolas", 9), anchor="w", padx=8).pack(fill="x")

        # ── Paned split: check list | log ─────────────────────────────────────
        paned = tk.PanedWindow(self, orient="vertical",
                               bg=t["highlight"], sashwidth=4,
                               sashrelief="flat")
        paned.pack(fill="both", expand=True, pady=2)

        # ── Scrollable check list ─────────────────────────────────────────────
        list_outer = tk.Frame(paned, bg=t["bg"])
        paned.add(list_outer, minsize=120)

        canvas = tk.Canvas(list_outer, bg=t["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_outer, orient="vertical",
                                  command=canvas.yview)
        self._check_frame = tk.Frame(canvas, bg=t["bg"])

        self._check_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self._check_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Mouse-wheel scroll
        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>",
                                              lambda ev: canvas.yview_scroll(
                                                  int(-1*(ev.delta/120)), "units")))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))

        # ── Log pane ──────────────────────────────────────────────────────────
        log_outer = tk.Frame(paned, bg=t["bg"])
        paned.add(log_outer, minsize=80)

        tk.Label(log_outer, text=" Action Log",
                 fg=t["accent"], bg=t["bg"],
                 font=("Consolas", 9, "bold"), anchor="w").pack(fill="x")

        self._log = ScrolledText(
            log_outer, state="disabled", wrap="word",
            bg=t["text_bg"], fg=t["text_fg"],
            insertbackground=t["accent"],
            font=("Consolas", 9), relief="flat", padx=6, pady=4,
        )
        self._log.pack(fill="both", expand=True)

        # Configure text tags for color coding
        self._log.tag_configure("error", foreground=t["error_fg"])
        self._log.tag_configure("ok",    foreground=t["ok_fg"])
        self._log.tag_configure("warn",  foreground=t["warn_fg"])
        self._log.tag_configure("cmd",   foreground=t["accent"])

        # Auto-run quick check
        if self._quick:
            self.after(500, self._run_quick)

    # ── Internal methods ──────────────────────────────────────────────────────

    def _log_line(self, line: str):
        """Thread-safe log append."""
        def _append():
            self._log.configure(state="normal")
            # Simple color tagging
            tag = None
            low = line.lower()
            if low.startswith("error") or "error:" in low:
                tag = "error"
            elif low.startswith("$") or low.startswith("▶"):
                tag = "cmd"
            elif low.startswith("done") or "✓" in line or low.startswith("[exit 0]"):
                tag = "ok"
            elif "warning" in low or "warn" in low:
                tag = "warn"
            if tag:
                self._log.insert("end", line + "\n", tag)
            else:
                self._log.insert("end", line + "\n")
            self._log.configure(state="disabled")
            self._log.see("end")
        try:
            self.after(0, _append)
        except Exception:
            pass

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _clear_checks(self):
        for w in self._check_frame.winfo_children():
            w.destroy()

    def _populate(self, results: List[DiagnosticResult]):
        self._results = results
        self._clear_checks()
        for r in results:
            row = _CheckRow(self._check_frame, r,
                            theme=self._theme, log_cb=self._log_line)
            row.pack(fill="x", pady=1)
        # Update status bar
        s = summary(results)
        self._status_var.set(f"  {s}")
        self._log_line(f"\n{'═'*50}")
        self._log_line(f"Diagnostic complete: {s}")
        self._log_line(f"{'═'*50}")

    def _run_full(self):
        self._status_var.set("  Running full diagnostic…")
        self._clear_checks()
        # Placeholder row
        tk.Label(self._check_frame, text="  Running checks…",
                 fg=self._theme["status_fg"], bg=self._theme["bg"],
                 font=("Consolas", 10)).pack(pady=20)

        def _bg():
            results = run_full_diagnostic()
            self.after(0, lambda: self._populate(results))

        threading.Thread(target=_bg, daemon=True).start()

    def _run_quick(self):
        self._status_var.set("  Running quick check…")
        self._clear_checks()

        def _bg():
            results = run_quick_diagnostic()
            self.after(0, lambda: self._populate(results))

        threading.Thread(target=_bg, daemon=True).start()


# ── Startup banner (lightweight, for main window toolbar) ─────────────────────

class StartupBanner(tk.Frame):
    """
    A compact one-line banner that runs a quick diagnostic on startup
    and shows a summary.  Click to open the full heal panel.
    """

    def __init__(self, parent: tk.Widget, theme: Dict = None,
                 open_panel_cmd: Callable = None, **kw):
        self._theme = dict(_DEFAULT_THEME)
        if theme:
            self._theme.update(theme)
        t = self._theme
        super().__init__(parent, bg=t["highlight"], **kw)
        self._open_panel_cmd = open_panel_cmd

        self._var = tk.StringVar(value="  System check running…")
        lbl = tk.Label(self, textvariable=self._var,
                       fg=t["status_fg"], bg=t["highlight"],
                       font=("Consolas", 9), anchor="w", padx=6,
                       cursor="hand2" if open_panel_cmd else "")
        lbl.pack(side="left", fill="x", expand=True)
        if open_panel_cmd:
            lbl.bind("<Button-1>", lambda e: open_panel_cmd())
            tk.Label(self, text="[Details ▸]",
                     fg=t["accent"], bg=t["highlight"],
                     font=("Consolas", 9), cursor="hand2",
                     padx=6).pack(side="right")

        threading.Thread(target=self._bg_check, daemon=True).start()

    def _bg_check(self):
        import time
        time.sleep(0.8)  # let GUI finish drawing
        try:
            results = run_quick_diagnostic()
            s = summary(results)
            errors  = [r for r in results if r.status == "error"]
            warns   = [r for r in results if r.status == "warn"]
            if errors:
                color = self._theme["error_fg"]
                msg   = f"  ⚠  {s}  — click for fixes"
            elif warns:
                color = self._theme["warn_fg"]
                msg   = f"  ⚡  {s}"
            else:
                color = self._theme["ok_fg"]
                msg   = f"  ✓  {s}"
            self.after(0, lambda: self._update(msg, color))
        except Exception:
            self.after(0, lambda: self._update("  System check unavailable", self._theme["warn_fg"]))

    def _update(self, msg: str, color: str):
        self._var.set(msg)
        for w in self.winfo_children():
            if isinstance(w, tk.Label):
                w.configure(fg=color)


# ── Standalone window helper ──────────────────────────────────────────────────

def open_heal_window(parent: tk.Widget = None, theme: Dict = None,
                     quick_only: bool = False) -> tk.Toplevel:
    """Open the diagnostic panel in a new top-level window."""
    t = dict(_DEFAULT_THEME)
    if theme:
        t.update(theme)

    win = tk.Toplevel(parent)
    win.title("CITL Diagnostics & Self-Heal")
    win.geometry("820x620")
    win.configure(bg=t["bg"])
    win.resizable(True, True)

    panel = HealPanel(win, theme=t, quick=quick_only)
    panel.pack(fill="both", expand=True)

    tk.Button(win, text="Close",
              bg=t["button_bg"], fg=t["button_fg"],
              relief="flat", padx=12, pady=4, cursor="hand2",
              font=("Consolas", 9),
              command=win.destroy).pack(pady=6)
    return win
