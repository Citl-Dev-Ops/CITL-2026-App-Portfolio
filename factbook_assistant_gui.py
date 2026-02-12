import runpy
import sys
from pathlib import Path

repo = Path(__file__).resolve().parent
sub  = repo / "factbook-assistant"
target = sub / "factbook_assistant_gui.py"

# Ensure imports like "import citl_audio_ffmpeg_graceful_v2" work
sys.path.insert(0, str(sub))

runpy.run_path(str(target), run_name="__main__")
