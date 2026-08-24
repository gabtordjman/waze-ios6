#!/usr/bin/env python3
import runpy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
runpy.run_path(str(Path(__file__).resolve().parent / "run-ultimate.py"), run_name="__main__")
