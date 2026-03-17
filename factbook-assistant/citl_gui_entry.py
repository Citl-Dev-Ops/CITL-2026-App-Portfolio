import os
import sys
import traceback

def _fatal(msg: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("CITL — Fatal Error", msg)
        root.destroy()
    except Exception:
        try:
            import pathlib
            log = pathlib.Path.home() / ".local" / "share" / "CITL" / "citl_crash.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(msg, encoding="utf-8")
        except Exception:
            pass

def main() -> None:
    try:
        # Import GUI module
        import factbook_assistant_gui as gui

        # Force a visible window and a stable WM_CLASS for GNOME dock grouping.
        if hasattr(gui, "App"):
            app = gui.App()  # type: ignore
            try:
                # WM_CLASS is what GNOME uses with StartupWMClass for correct pin/group behavior.
                app.wm_class("citl-portable")
            except Exception:
                try:
                    app.tk.call("wm", "class", app._w, "citl-portable")  # type: ignore
                except Exception:
                    pass
            app.mainloop()
            return

        # Fallback to gui.main()
        if hasattr(gui, "main"):
            gui.main()  # type: ignore
            # If main returned, keep process alive only if a root exists; otherwise exit.
            return

        raise RuntimeError("No App class or main() found in factbook_assistant_gui.py")
    except SystemExit:
        return
    except Exception:
        _fatal("CITL crashed:\n\n" + traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
