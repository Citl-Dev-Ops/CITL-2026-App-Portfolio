from pathlib import Path
import re

p = Path("factbook-assistant") / "citl_audio_ffmpeg_graceful_v2.py"
t = p.read_text(encoding="utf-8", errors="replace")
lines = t.splitlines(True)

clean_fn = """def audio_diagnostics(ffmpeg: str) -> str:
    \"\"\"Backwards-compatible diagnostics entrypoint.

    Returns combined sounddevice + DirectShow diagnostics when available.
    \"\"\"
    parts = []

    # sounddevice
    try:
        fn = globals().get("_try_sounddevice_list")
        if callable(fn):
            ok, sd_text, _ = fn()  # type: ignore[misc]
            if sd_text:
                parts.append(sd_text)
    except Exception as e:
        parts.append(f"(sounddevice diagnostics failed: {e})")

    # DirectShow
    try:
        fn = globals().get("dshow_diagnostics")
        if callable(fn):
            parts.append(fn(ffmpeg))  # type: ignore[misc]
    except Exception as e:
        parts.append(f"(DirectShow diagnostics failed: {e})")

    out = "\\n\\n".join([p for p in parts if p]).strip()
    return out or "(no diagnostics)"
"""

out = []
i = 0
replaced = False

while i < len(lines):
    if re.match(r'^\\s*def\\s+audio_diagnostics\\s*\\(', lines[i]):
        replaced = True

        # remove any immediately-preceding comment/header lines we appended earlier
        while out and (out[-1].strip() == "" or out[-1].lstrip().startswith("#")):
            out.pop()

        # skip old function body until the next TOP-LEVEL def/class or EOF
        i += 1
        while i < len(lines) and not re.match(r'^(def|class)\\s+\\w', lines[i]):
            i += 1

        out.append("\n# ---------------------------\n")
        out.append("# Compatibility exports (GUI expects these names)\n")
        out.append("# ---------------------------\n\n")
        out.append(clean_fn)
        out.append("\n")
        continue

    out.append(lines[i])
    i += 1

if not replaced:
    out.append("\n# ---------------------------\n")
    out.append("# Compatibility exports (GUI expects these names)\n")
    out.append("# ---------------------------\n\n")
    out.append(clean_fn)
    out.append("\n")

p.write_text("".join(out).rstrip() + "\n", encoding="utf-8")
print("OK: rewrote audio_diagnostics cleanly in", p)
