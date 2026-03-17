"""
EXE entry point — wraps main() in a crash-catcher so the window never
silently disappears if an unhandled exception occurs.

PyInstaller uses this file as the Analysis target instead of
factbook_assistant_gui.py directly, so the main module stays clean.
"""

import sys
import traceback


def _fatal(msg: str) -> None:
    """Show a Tk error dialog (doesn't require the app to be running)."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("CITL — Fatal Error", msg)
        root.destroy()
    except Exception:
        # Absolute last resort: write to a log file next to the EXE
        import os
        log = os.path.join(os.path.dirname(sys.executable), "citl_crash.log")
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass


def main() -> None:
    try:
        from factbook_assistant_gui import main as _main
        _main()
    except SystemExit:
        pass
    except Exception:
        tb = traceback.format_exc()
        _fatal(
            "CITL Desktop LLM Assistant encountered an unexpected error.\n\n"
            + tb
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
