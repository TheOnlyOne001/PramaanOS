"""Efficiency guards: verify() cache correctness (cannot hide a tamper) and latency bounds."""
import sqlite3
import time

from saakshi.tamper import tamper_punch_out


def _punches(st, n=40):
    for i in range(n):
        st.ledger.append("punch.in" if i % 2 == 0 else "punch.out", {"device": "t"}, worker_id="W001",
                         ts=f"2026-10-{1 + i // 2:02d}T{'08' if i % 2 == 0 else '17'}:00:00+05:30", receipt=False)


def _strip(v):
    return {k: v[k] for k in v if k != "checked_at"}


def test_cache_hit_same_result_and_copy(st):
    _punches(st)
    v1 = st.ledger.verify()
    t0 = time.perf_counter()
    v2 = st.ledger.verify()
    assert time.perf_counter() - t0 < 0.05
    assert _strip(v1) == _strip(v2) and v2["ok"]
    v2["problems"].append({"kind": "x"})
    v2["roots"].append({})
    assert st.ledger.verify()["problems"] == []


def test_same_connection_update_invalidates(st):
    _punches(st)
    st.ledger.publish_root("2026-10-01")
    assert st.ledger.verify()["ok"]
    tamper_punch_out(st.conn, worker_id="W001")
    v = st.ledger.verify()
    assert not v["ok"] and "content_edited" in {p["kind"] for p in v["problems"]}


def test_other_connection_update_invalidates(st):
    _punches(st)
    assert st.ledger.verify()["ok"]
    other = sqlite3.connect(st.path, isolation_level=None)
    other.row_factory = sqlite3.Row
    tamper_punch_out(other, worker_id="W001", mode="rehash")
    other.close()
    v = st.ledger.verify()
    assert not v["ok"] and "bad_signature" in {p["kind"] for p in v["problems"]}


def test_incremental_tail_equals_full(st):
    _punches(st, 20)
    st.ledger.publish_root("2026-10-01")
    st.ledger.verify()
    _punches(st, 30)  # appends only: tail path
    st.ledger.append("ot.request", {"request_id": "R1", "date": "2026-10-20", "hours": 2}, worker_id="W002",
                     ts="2026-10-20T10:00:00+05:30")  # with a wallet receipt
    inc = st.ledger.verify()
    full = st.ledger.verify(full=True)
    assert _strip(inc) == _strip(full) and inc["ok"] and inc["n_events"] == 51


def test_tamper_after_append_still_detected(st):
    _punches(st, 20)
    st.ledger.verify()
    _punches(st, 2)
    st.conn.execute("UPDATE events SET payload='{\"device\":\"x\"}' WHERE seq=3")
    v = st.ledger.verify()
    assert {p["seq"] for p in v["problems"]} >= {3}


def test_console_overview_fast_on_seeded_db(client, st):
    from saakshi import seed
    seed.seed_all(st)
    client.get("/api/console/overview")
    t0 = time.perf_counter()
    r = client.get("/api/console/overview")
    assert r.status_code == 200
    assert time.perf_counter() - t0 < 1.5
