"""
citl_theme.py — Accessible light/dark color palettes for the CITL GUI.

Palettes include:
  - ops (crimson/slate dark, default)
  - vision-focused dark/light variants (low glare + high contrast)
  - legacy terminal palettes (amber/green/c64/sinclair/cga)

Usage:
    from citl_theme import apply_theme, PALETTE_NAMES, PALETTE_DISPLAY
    apply_theme(root_window, "ops")
"""

import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# Palette definitions
# ---------------------------------------------------------------------------

_PALETTES = {
    # Default: institution crimson + graphite gray.
    "ops": {
        "bg":         "#111317",
        "fg":         "#e8eaed",
        "accent":     "#c41e3a",
        "highlight":  "#2a2f38",
        "button_bg":  "#1b2028",
        "button_fg":  "#f2f4f7",
        "entry_bg":   "#0b0e12",
        "entry_fg":   "#e6e9ee",
        "text_bg":    "#0b0e12",
        "text_fg":    "#d4d9e1",
        "select_bg":  "#7f1428",
        "select_fg":  "#ffffff",
        "tab_bg":     "#171b22",
        "tab_fg":     "#b5bcc8",
        "status_fg":  "#ff5a75",
        "cursor":     "#ff5a75",
    },
    # Accessible dark variants.
    "graphite": {
        "bg":         "#161a1f",
        "fg":         "#dbe1e8",
        "accent":     "#a3384b",
        "highlight":  "#252c35",
        "button_bg":  "#1d232c",
        "button_fg":  "#edf1f5",
        "entry_bg":   "#11161c",
        "entry_fg":   "#e3e8ef",
        "text_bg":    "#11161c",
        "text_fg":    "#ccd3dc",
        "select_bg":  "#7b2336",
        "select_fg":  "#ffffff",
        "tab_bg":     "#1b2028",
        "tab_fg":     "#aeb7c4",
        "status_fg":  "#ff8aa0",
        "cursor":     "#ff8aa0",
    },
    "soft_midnight": {
        "bg":         "#1b1f24",
        "fg":         "#cfd5dd",
        "accent":     "#d05f70",
        "highlight":  "#2a3038",
        "button_bg":  "#242a33",
        "button_fg":  "#e2e7ee",
        "entry_bg":   "#171b20",
        "entry_fg":   "#dce2ea",
        "text_bg":    "#171b20",
        "text_fg":    "#c6ced8",
        "select_bg":  "#5d2f39",
        "select_fg":  "#f4f4f4",
        "tab_bg":     "#20262e",
        "tab_fg":     "#a8b1bf",
        "status_fg":  "#f0a7b3",
        "cursor":     "#f0a7b3",
    },
    "midnight_hc": {
        "bg":         "#07090d",
        "fg":         "#f5f7fa",
        "accent":     "#ff4d6d",
        "highlight":  "#1d2430",
        "button_bg":  "#121822",
        "button_fg":  "#ffffff",
        "entry_bg":   "#0b1018",
        "entry_fg":   "#ffffff",
        "text_bg":    "#0b1018",
        "text_fg":    "#eef2f8",
        "select_bg":  "#b3133d",
        "select_fg":  "#ffffff",
        "tab_bg":     "#101621",
        "tab_fg":     "#cad2e0",
        "status_fg":  "#ff7a94",
        "cursor":     "#ff7a94",
    },
    "night_amber": {
        "bg":         "#1a1712",
        "fg":         "#e7dccb",
        "accent":     "#b6485a",
        "highlight":  "#2b2620",
        "button_bg":  "#24201b",
        "button_fg":  "#efe5d6",
        "entry_bg":   "#15120e",
        "entry_fg":   "#e6ddcf",
        "text_bg":    "#15120e",
        "text_fg":    "#d8cebf",
        "select_bg":  "#6b3a32",
        "select_fg":  "#fff4e5",
        "tab_bg":     "#211d18",
        "tab_fg":     "#c7bcaf",
        "status_fg":  "#efb08f",
        "cursor":     "#efb08f",
    },
    # Accessible light variants.
    "paper_light": {
        "bg":         "#f4f6f8",
        "fg":         "#1e232b",
        "accent":     "#9b1c33",
        "highlight":  "#d8dee7",
        "button_bg":  "#e7ebf1",
        "button_fg":  "#1f2430",
        "entry_bg":   "#ffffff",
        "entry_fg":   "#1b212b",
        "text_bg":    "#ffffff",
        "text_fg":    "#202733",
        "select_bg":  "#b73550",
        "select_fg":  "#ffffff",
        "tab_bg":     "#e5eaf1",
        "tab_fg":     "#2a3443",
        "status_fg":  "#9b1c33",
        "cursor":     "#9b1c33",
    },
    "warm_light": {
        "bg":         "#f6f1e8",
        "fg":         "#2a251f",
        "accent":     "#a63a4a",
        "highlight":  "#e6dccd",
        "button_bg":  "#efe4d3",
        "button_fg":  "#2a251f",
        "entry_bg":   "#fffaf0",
        "entry_fg":   "#2d2923",
        "text_bg":    "#fffaf0",
        "text_fg":    "#2f2a24",
        "select_bg":  "#b24656",
        "select_fg":  "#fff9f1",
        "tab_bg":     "#ede2d2",
        "tab_fg":     "#3a342d",
        "status_fg":  "#a63a4a",
        "cursor":     "#a63a4a",
    },
    "day_hc": {
        "bg":         "#ffffff",
        "fg":         "#111111",
        "accent":     "#8a102b",
        "highlight":  "#d9d9d9",
        "button_bg":  "#eeeeee",
        "button_fg":  "#111111",
        "entry_bg":   "#ffffff",
        "entry_fg":   "#111111",
        "text_bg":    "#ffffff",
        "text_fg":    "#111111",
        "select_bg":  "#8a102b",
        "select_fg":  "#ffffff",
        "tab_bg":     "#e6e6e6",
        "tab_fg":     "#111111",
        "status_fg":  "#8a102b",
        "cursor":     "#8a102b",
    },
    # Legacy terminal themes.
    "amber": {
        "bg":         "#1a0e00",
        "fg":         "#ffb000",
        "accent":     "#ffd060",
        "highlight":  "#3a2000",
        "button_bg":  "#2a1800",
        "button_fg":  "#ffb000",
        "entry_bg":   "#120900",
        "entry_fg":   "#ffb000",
        "text_bg":    "#120900",
        "text_fg":    "#e09000",
        "select_bg":  "#3a2000",
        "select_fg":  "#ffd060",
        "tab_bg":     "#1e1000",
        "tab_fg":     "#cc8800",
        "status_fg":  "#ffd060",
        "cursor":     "#ffd060",
    },
    "green": {
        "bg":         "#001200",
        "fg":         "#00cc00",
        "accent":     "#00ff44",
        "highlight":  "#003300",
        "button_bg":  "#001a00",
        "button_fg":  "#00cc00",
        "entry_bg":   "#000e00",
        "entry_fg":   "#00cc00",
        "text_bg":    "#000e00",
        "text_fg":    "#00aa00",
        "select_bg":  "#003300",
        "select_fg":  "#00ff44",
        "tab_bg":     "#001500",
        "tab_fg":     "#009900",
        "status_fg":  "#00ff44",
        "cursor":     "#00ff44",
    },
    "c64": {
        "bg":         "#40318d",
        "fg":         "#7869c4",
        "accent":     "#ffffff",
        "highlight":  "#352879",
        "button_bg":  "#352879",
        "button_fg":  "#ffffff",
        "entry_bg":   "#2d2068",
        "entry_fg":   "#a496e0",
        "text_bg":    "#2d2068",
        "text_fg":    "#a496e0",
        "select_bg":  "#ffffff",
        "select_fg":  "#40318d",
        "tab_bg":     "#352879",
        "tab_fg":     "#7869c4",
        "status_fg":  "#ffffff",
        "cursor":     "#ffffff",
    },
    "sinclair": {
        "bg":         "#000000",
        "fg":         "#ffffff",
        "accent":     "#ffff00",
        "highlight":  "#0000cc",
        "button_bg":  "#0000cc",
        "button_fg":  "#ffffff",
        "entry_bg":   "#000000",
        "entry_fg":   "#ffffff",
        "text_bg":    "#000000",
        "text_fg":    "#ffffff",
        "select_bg":  "#0000cc",
        "select_fg":  "#ffff00",
        "tab_bg":     "#000000",
        "tab_fg":     "#cccccc",
        "status_fg":  "#ffff00",
        "cursor":     "#ffff00",
    },
    "cga": {
        "bg":         "#000000",
        "fg":         "#55ffff",
        "accent":     "#ff55ff",
        "highlight":  "#005555",
        "button_bg":  "#005555",
        "button_fg":  "#55ffff",
        "entry_bg":   "#000000",
        "entry_fg":   "#55ffff",
        "text_bg":    "#000000",
        "text_fg":    "#55ffff",
        "select_bg":  "#ff55ff",
        "select_fg":  "#000000",
        "tab_bg":     "#002222",
        "tab_fg":     "#aaffff",
        "status_fg":  "#ff55ff",
        "cursor":     "#ff55ff",
    },
}

PALETTE_NAMES: list = list(_PALETTES.keys())

PALETTE_DISPLAY: dict = {
    "ops":           "Crimson Ops (default)",
    "graphite":      "Graphite Dark (low glare)",
    "soft_midnight": "Soft Midnight (low contrast)",
    "midnight_hc":   "Midnight High Contrast",
    "night_amber":   "Night Amber (low blue)",
    "paper_light":   "Paper Light",
    "warm_light":    "Warm Light (low blue)",
    "day_hc":        "Daylight High Contrast",
    "amber":         "Amber Terminal",
    "green":         "Green Phosphor",
    "c64":           "Commodore 64",
    "sinclair":      "Sinclair ZX",
    "cga":           "CGA Cyan/Magenta",
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_theme(root: tk.Tk, palette_name: str) -> None:
    """Apply a named palette to a Tk root window (TTK + bare tk widgets)."""
    p = _PALETTES.get(palette_name, _PALETTES["ops"])

    style = ttk.Style(root)
    style.theme_use("clam")

    # General
    style.configure(".", background=p["bg"], foreground=p["fg"],
                    fieldbackground=p["entry_bg"], troughcolor=p["bg"],
                    selectbackground=p["select_bg"], selectforeground=p["select_fg"],
                    insertcolor=p["cursor"])

    # Frame / LabelFrame
    style.configure("TFrame",      background=p["bg"])
    style.configure("TLabelframe", background=p["bg"], foreground=p["accent"])
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["accent"])

    # Label
    style.configure("TLabel", background=p["bg"], foreground=p["fg"])

    # Button
    style.configure("TButton",
                    background=p["button_bg"], foreground=p["button_fg"],
                    bordercolor=p["accent"], darkcolor=p["bg"], lightcolor=p["highlight"],
                    relief="flat", borderwidth=1, padding=[8, 4])
    style.map("TButton",
              background=[("active", p["highlight"]), ("pressed", p["select_bg"])],
              foreground=[("active", p["button_fg"]), ("pressed", p["select_fg"])])

    # Entry / Combobox
    style.configure("TEntry", fieldbackground=p["entry_bg"], foreground=p["entry_fg"],
                    insertcolor=p["cursor"])
    style.configure("TCombobox", fieldbackground=p["entry_bg"], foreground=p["entry_fg"],
                    selectbackground=p["select_bg"], selectforeground=p["select_fg"],
                    background=p["button_bg"])
    style.map("TCombobox",
              fieldbackground=[("readonly", p["entry_bg"])],
              selectbackground=[("readonly", p["select_bg"])],
              foreground=[("readonly", p["entry_fg"])])
    # Drop-down listbox for readonly combobox
    root.option_add("*TCombobox*Listbox.background", p["entry_bg"])
    root.option_add("*TCombobox*Listbox.foreground", p["entry_fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["select_bg"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["select_fg"])

    # Notebook tabs
    style.configure("TNotebook",      background=p["bg"], tabmargins=[2, 5, 2, 0])
    style.configure("TNotebook.Tab",  background=p["tab_bg"], foreground=p["tab_fg"],
                    padding=[8, 4])
    style.map("TNotebook.Tab",
              background=[("selected", p["highlight"])],
              foreground=[("selected", p["fg"])])

    # Toggle controls
    style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"])
    style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"])
    style.map("TCheckbutton", foreground=[("active", p["accent"])])
    style.map("TRadiobutton", foreground=[("active", p["accent"])])

    # Scrollbar
    style.configure("Vertical.TScrollbar",   background=p["button_bg"], troughcolor=p["bg"],
                    arrowcolor=p["accent"])
    style.configure("Horizontal.TScrollbar", background=p["button_bg"], troughcolor=p["bg"],
                    arrowcolor=p["accent"])

    # Separator
    style.configure("TSeparator", background=p["accent"])

    # Apply to bare tk widgets recursively
    root.configure(bg=p["bg"])
    _apply_tk_widgets(root, p)


def _apply_tk_widgets(widget: tk.BaseWidget, p: dict) -> None:
    """Recursively style bare-tk widgets that ttk.Style doesn't reach."""
    cls = widget.winfo_class()
    try:
        if cls == "Text":
            widget.configure(bg=p["text_bg"], fg=p["text_fg"],
                             insertbackground=p["cursor"],
                             selectbackground=p["select_bg"],
                             selectforeground=p["select_fg"])
        elif cls == "Entry":
            widget.configure(bg=p["entry_bg"], fg=p["entry_fg"],
                             insertbackground=p["cursor"],
                             selectbackground=p["select_bg"],
                             selectforeground=p["select_fg"])
        elif cls in ("Frame", "LabelFrame"):
            widget.configure(bg=p["bg"])
        elif cls == "Label":
            widget.configure(bg=p["bg"], fg=p["fg"])
        elif cls == "Button":
            widget.configure(bg=p["button_bg"], fg=p["button_fg"],
                             activebackground=p["highlight"],
                             activeforeground=p["select_fg"])
    except tk.TclError:
        pass

    for child in widget.winfo_children():
        _apply_tk_widgets(child, p)
