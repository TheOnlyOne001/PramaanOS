"""Demo data for one export garment unit in Tiruppur, Tamil Nadu.

seed_workers(): workers and keys only (used by tests).
seed_all(): workers plus a week of signed history (used by the running app).
"""
from __future__ import annotations

from .state import State

WORKERS = [
    # id, name, lang, role, line, operation, skill_band, gender, contract_type, contractor, joined, is_supervisor
    ("W001", "Meena Selvam", "ta", "Overlock operator", "Line 4", "overlock", "semi-skilled", "F", "permanent", None, "2025-06-02", 0),
    ("W002", "Lakshmi Murugan", "ta", "Overlock operator", "Line 4", "overlock", "semi-skilled", "F", "permanent", None, "2023-01-16", 0),
    ("W003", "Sabita Nayak", "or", "Flatlock operator", "Line 4", "flatlock", "semi-skilled", "F", "contract", "Sri Balaji Manpower", "2024-08-05", 0),
    ("W004", "Ravi Kumar", "hi", "Cutting helper", "Line 4", "cutting", "unskilled", "M", "contract", "Sri Balaji Manpower", "2026-02-10", 0),
    ("W005", "Kavitha Raman", "ta", "Quality checker", "Line 4", "checking", "skilled", "F", "permanent", None, "2021-03-01", 0),
    ("W006", "Anjali Das", "or", "Overlock operator", "Line 4", "overlock", "semi-skilled", "F", "contract", "Sri Balaji Manpower", "2025-11-20", 0),
    ("W007", "Suresh Babu", "ta", "Ironing and packing", "Line 4", "packing", "unskilled", "M", "permanent", None, "2022-07-11", 0),
    ("W008", "Fatima Begum", "hi", "Lockstitch operator", "Line 4", "lockstitch", "semi-skilled", "F", "permanent", None, "2024-04-22", 0),
    ("S001", "Murugan Pandi", "ta", "Line supervisor", "Line 4", None, "highly-skilled", "M", "permanent", None, "2019-05-06", 1),
]

KEY_NAMES = ["site", "site-issuer", "edge-box-1"]


def seed_workers(st: State) -> None:
    """Insert demo workers and ensure their signing keys exist."""
    with st.lock:
        for w in WORKERS:
            st.conn.execute(
                "INSERT OR IGNORE INTO workers(id, name, lang, role, line, operation, skill_band, gender,"
                " contract_type, contractor, joined, is_supervisor) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", w)
        for k in KEY_NAMES:
            st.keys.get(k)
        for w in WORKERS:
            st.keys.get(f"worker:{w[0]}")


def seed_all(st: State) -> None:
    """Workers plus history. History hooks are filled in by seed_history."""
    seed_workers(st)
    try:
        from .seed_history import seed_history
    except ImportError:
        return
    seed_history(st)
