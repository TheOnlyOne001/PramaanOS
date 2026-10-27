"""Site-wide settings. One demo site: an export garment unit in Tamil Nadu."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

if os.environ.get("VERCEL"):
    DB_PATH = os.environ.get("SAAKSHI_DB", "/tmp/saakshi.db")
else:
    DB_PATH = os.environ.get("SAAKSHI_DB", str(ROOT / "data" / "saakshi.db"))

AUTOSEED = os.environ.get("SAAKSHI_AUTOSEED", "1") != "0"

SITE_ID = "TUP-03"
SITE_NAME = "Tiruppur Knits — Export Unit 3"
STATE = "TN"  # Tamil Nadu rule tables
TZ = "+05:30"
DEMO_DAY = "2026-10-27"  # "today" for the scripted demo

# Demo-only endpoints (/api/demo/reset, /api/demo/tamper). Set SAAKSHI_DEMO=0 in any real deployment.
DEMO_MODE = os.environ.get("SAAKSHI_DEMO", "1") != "0"
