"""End to end: the scripted three-minute demo runs clean against a fresh database."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_demo_script_passes(tmp_path):
    env = {**os.environ, "SAAKSHI_DB": str(tmp_path / "demo.db"), "PYTHONUNBUFFERED": "1",
           # in-process demo is the trusted local path; auth is covered by its own tests
           "SAAKSHI_AUTH": "0"}
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "demo.py")], cwd=str(ROOT), env=env,
                       capture_output=True, text=True, timeout=180)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out[-4000:]
    assert "All demo checks passed" in out, out[-4000:]
