"""Efficiency benchmark for the Saakshi ledger, pay and console.

    python3 scripts/bench.py            # demo seed + 20,000 synthetic punches
    python3 scripts/bench.py --n 5000

Builds a throw-away DB in a temp dir (never touches data/), then times:
append throughput, verify cold / warm / after 100 appends, GET /api/console/overview
and one payslip. Prints a table.
"""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _t(fn, reps=1):
    best = float("inf")
    out = None
    for _ in range(reps):
        t0 = time.perf_counter()
        out = fn()
        best = min(best, time.perf_counter() - t0)
    return best, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20000, help="synthetic punch events to add")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="saakshi-bench-")
    os.environ.setdefault("SAAKSHI_DB", os.path.join(tmp, "bench.db"))
    from fastapi.testclient import TestClient

    from saakshi import app as appmod
    from saakshi import pay, seed, state

    st = state.reset(os.path.join(tmp, "bench.db"), wipe=True)
    seed.seed_all(st)
    L = st.ledger

    # Synthetic punches: 100 extra (non-payroll) worker ids across September, so October pay is unchanged.
    t0 = time.perf_counter()
    for i in range(a.n):
        wid = f"X{i % 100:03d}"
        day = f"2026-09-{1 + (i // 200) % 28:02d}"
        typ = "punch.in" if i % 2 == 0 else "punch.out"
        hh = "08" if typ == "punch.in" else "17"
        L.append(typ, {"device": "bench"}, worker_id=wid, ts=f"{day}T{hh}:00:00+05:30", receipt=False)
    append_s = time.perf_counter() - t0
    n_events = L.count()

    cold, v = _t(L.verify)
    assert v["ok"], v["problems"][:3]
    warm, _ = _t(L.verify, reps=5)
    for _i in range(100):
        L.append("punch.in", {"device": "bench"}, worker_id="X999", ts="2026-09-30T08:00:00+05:30", receipt=False)
    inc, v2 = _t(L.verify)
    assert v2["ok"] and v2["n_events"] == n_events + 100

    client = TestClient(appmod.app)
    try:  # role-based auth, when present: act as HR
        from saakshi import auth
        client.headers["Authorization"] = "Bearer " + auth.issue_token("hr", sub="bench")
    except Exception:
        pass
    client.get("/api/console/overview")  # warm imports
    ov, r = _t(lambda: client.get("/api/console/overview"), reps=3)
    assert r.status_code == 200, r.status_code
    sc, r2 = _t(lambda: client.get("/api/sdg8/scorecard"), reps=3)
    assert r2.status_code == 200, r2.status_code
    ps, _ = _t(lambda: pay.payslip("W001", "2026-10"), reps=3)
    fa, _ = _t(lambda: pay.fairness("2026-10"), reps=3)

    rows = [
        ("events in ledger", f"{n_events + 100:,}"),
        ("append throughput", f"{a.n / append_s:,.0f} events/s"),
        ("verify, cold (full)", f"{cold * 1000:,.1f} ms"),
        ("verify, warm (cached)", f"{warm * 1000:,.3f} ms"),
        ("verify after 100 appends", f"{inc * 1000:,.1f} ms"),
        ("GET /api/console/overview", f"{ov * 1000:,.1f} ms"),
        ("GET /api/sdg8/scorecard", f"{sc * 1000:,.1f} ms"),
        ("payslip(W001)", f"{ps * 1000:,.1f} ms"),
        ("fairness()", f"{fa * 1000:,.1f} ms"),
    ]
    w = max(len(k) for k, _ in rows)
    print(f"{'metric'.ljust(w)}  value")
    print(f"{'-' * w}  {'-' * 20}")
    for k, val in rows:
        print(f"{k.ljust(w)}  {val}")
    st.close()


if __name__ == "__main__":
    main()
