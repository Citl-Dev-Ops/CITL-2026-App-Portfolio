#!/usr/bin/env python3
import runpy
import sys
from pathlib import Path

here = Path(__file__).resolve()
root = here.parents[1]
real = root / "CITL_FACTBOOK_UBUNTU V1" / "factbook-assistant" / here.name
if not real.exists():
    sys.stderr.write(f"Missing redirected source: {real}\n")
    raise SystemExit(2)
sys.path.insert(0, str(real.parent))
runpy.run_path(str(real), run_name="__main__")
