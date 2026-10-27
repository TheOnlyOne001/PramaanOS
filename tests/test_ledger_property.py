"""Property tests for the signed hash chain (hypothesis).

For a random ledger, ANY single direct-SQL mutation of a row is caught by
Ledger.verify(); a clean ledger always verifies; every Merkle inclusion proof
verifies and a proof for the wrong leaf does not.
"""
from __future__ import annotations

import json

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as s  # noqa: E402

from saakshi.crypto import merkle_root, verify_merkle_proof  # noqa: E402

DAYS = ["2026-10-25", "2026-10-26", "2026-10-27"]
TYPES = ["punch.in", "punch.out", "ot.request", "production.count", "edge.event"]
WORKERS = ["W001", "W002", "W003", None]
COLUMNS = ["ts", "payload", "type", "worker_id", "prev_hash", "hash", "sig"]

SETTINGS = settings(max_examples=40, deadline=None, derandomize=True,
                    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])

event_st = s.fixed_dictionaries({
    "day": s.sampled_from(DAYS),
    "hm": s.tuples(s.integers(6, 22), s.integers(0, 59)),
    "type": s.sampled_from(TYPES),
    "worker_id": s.sampled_from(WORKERS),
    "payload": s.dictionaries(s.sampled_from(["a", "b", "note", "hours"]),
                              s.one_of(s.integers(-1000, 1000), s.text(max_size=8)), max_size=3),
})
ledger_st = s.lists(event_st, min_size=1, max_size=12)


def _build(st, events):
    """Fresh ledger with `events` appended (in day order) and every day's root published."""
    with st.lock:
        for t in ("events", "daily_roots", "wallet_receipts"):
            st.conn.execute(f"DELETE FROM {t}")
    events = sorted(events, key=lambda e: e["day"])
    for e in events:
        h, m = e["hm"]
        ts = f"{e['day']}T{h:02d}:{m:02d}:00+05:30"
        st.ledger.append(e["type"], e["payload"], worker_id=e["worker_id"], ts=ts, receipt=False)
    for d in sorted({e["day"] for e in events}):
        st.ledger.publish_root(d)
    return st.conn.execute("SELECT seq FROM events ORDER BY seq").fetchall()


def _mutated(col, old):
    """A value different from `old` for column `col`."""
    if col == "ts":
        return old[:11] + ("23:59:59" if old[11:19] != "23:59:59" else "00:00:01") + old[19:]
    if col == "payload":
        p = json.loads(old)
        p["_edited"] = True
        return json.dumps(p, sort_keys=True)
    if col == "type":
        return "punch.out" if old != "punch.out" else "punch.in"
    if col == "worker_id":
        return "W008" if old != "W008" else "W007"
    # hex columns: flip the first nibble
    return ("1" if old[0] != "1" else "2") + old[1:]


@SETTINGS
@given(events=ledger_st)
def test_clean_random_ledger_always_verifies(st, events):
    _build(st, events)
    v = st.ledger.verify()
    assert v["ok"], v["problems"]
    assert v["n_events"] == len(events)


@SETTINGS
@given(events=ledger_st, col=s.sampled_from(COLUMNS), pick=s.integers(0, 10_000))
def test_any_single_column_edit_is_detected(st, events, col, pick):
    rows = _build(st, events)
    seq = rows[pick % len(rows)]["seq"]
    old = st.conn.execute(f"SELECT {col} FROM events WHERE seq=?", (seq,)).fetchone()[0]  # noqa: S608
    if col == "worker_id" and old is None:
        old = ""
    st.conn.execute(f"UPDATE events SET {col}=? WHERE seq=?", (_mutated(col, old), seq))  # noqa: S608
    v = st.ledger.verify()
    assert not v["ok"], f"edit of {col} on seq {seq} went unnoticed"


@SETTINGS
@given(events=ledger_st, pick=s.integers(0, 10_000))
def test_deleting_any_row_is_detected(st, events, pick):
    rows = _build(st, events)
    seq = rows[pick % len(rows)]["seq"]
    st.conn.execute("DELETE FROM events WHERE seq=?", (seq,))
    v = st.ledger.verify()
    assert not v["ok"], f"deleting seq {seq} of {len(rows)} went unnoticed"


@SETTINGS
@given(events=s.lists(event_st, min_size=2, max_size=12), a=s.integers(0, 10_000), b=s.integers(0, 10_000))
def test_swapping_two_rows_seq_is_detected(st, events, a, b):
    rows = _build(st, events)
    i, j = a % len(rows), b % len(rows)
    if i == j:
        j = (i + 1) % len(rows)
    sa, sb = rows[i]["seq"], rows[j]["seq"]
    with st.lock:
        st.conn.execute("UPDATE events SET seq=-1 WHERE seq=?", (sa,))
        st.conn.execute("UPDATE events SET seq=? WHERE seq=?", (sa, sb))
        st.conn.execute("UPDATE events SET seq=? WHERE seq=-1", (sb,))
    v = st.ledger.verify()
    assert not v["ok"], f"swapping seq {sa}<->{sb} went unnoticed"


@SETTINGS
@given(events=ledger_st)
def test_merkle_inclusion_proof_for_every_leaf(st, events):
    rows = _build(st, events)
    for r in rows:
        p = st.ledger.inclusion_proof(r["seq"])
        assert verify_merkle_proof(p["hash"], p["proof"], p["root"])
        # root in the proof equals the published root for that day
        pub = st.conn.execute("SELECT root FROM daily_roots WHERE day=?", (p["day"],)).fetchone()[0]
        assert p["root"] == pub
        wrong = ("f" if p["hash"][0] != "f" else "e") + p["hash"][1:]
        assert not verify_merkle_proof(wrong, p["proof"], p["root"])


@SETTINGS
@given(hashes=s.lists(s.binary(min_size=32, max_size=32).map(bytes.hex), min_size=1, max_size=17, unique=True))
def test_merkle_proof_pure(st, hashes):
    from saakshi.crypto import merkle_proof
    root = merkle_root(hashes)
    for i, h in enumerate(hashes):
        proof = merkle_proof(hashes, i)
        assert verify_merkle_proof(h, proof, root)
        other = hashes[(i + 1) % len(hashes)]
        if other != h:
            assert not verify_merkle_proof(other, proof, root)
