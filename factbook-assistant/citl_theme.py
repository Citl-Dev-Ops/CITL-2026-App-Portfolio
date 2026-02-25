"""
citl_theme.py — Terminal-inspired color palettes for the CITL GUI.

Palettes: ops (IT dark navy, default), amber, green, c64, sinclair, cga

Usage:
    from citl_theme import apply_theme, PALETTE_NAMES, PALETTE_DISPLAY
    apply_theme(root_window, "ops")
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional

# ---------------------------------------------------------------------------
# Palette definitions
# ---------------------------------------------------------------------------

_PALETTES = {
    "ops": {
        "bg":         "#0d1b2a",
        "fg":         "#e0e8f0",
        "accent":     "#00aaff",
        "highlight":  "#003366",
        "button_bg":  "#1a2e45",
        "button_fg":  "#e0e8f0",
        "entry_bg":   "#0a1520",
        "entry_fg":   "#e0e8f0",
        "text_bg":    "#0a1520",
        "text_fg":    "#c8d8e8",
        "select_bg":  "#003366",
        "select_fg":  "#ffffff",
        "tab_bg":     "#112233",
        "tab_fg":     "#90b0d0",
        "status_fg":  "#00aaff",
        "cursor":     "#00aaff",
    },
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
    "ops":      "IT Ops (default)",
    "amber":    "Amber Terminal",
    "green":    "Green Phosphor",
    "c64":      "Commodore 64",
    "sinclair": "Sinclair ZX",
    "cga":      "CGA Cyan/Magenta",
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
                    bordercolor=p["accent"], darkcolor=p["bg"], lightcolor=p["highlight"])
    style.map("TButton",
              background=[("active", p["highlight"]), ("pressed", p["accent"])],
              foreground=[("active", p["accent"])])

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

    # Notebook tabs
    style.configure("TNotebook",      background=p["bg"], tabmargins=[2, 5, 2, 0])
    style.configure("TNotebook.Tab",  background=p["tab_bg"], foreground=p["tab_fg"],
                    padding=[8, 4])
    style.map("TNotebook.Tab",
              background=[("selected", p["highlight"])],
              foreground=[("selected", p["accent"])])

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
                             activeforeground=p["accent"])
    except tk.TclError:
        pass

    for child in widget.winfo_children():
        _apply_tk_widgets(child, p)
