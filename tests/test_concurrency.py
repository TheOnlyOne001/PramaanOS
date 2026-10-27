"""Many threads sharing one SQLite connection must never hit 'API misuse' or break the chain."""
import concurrent.futures as cf


def test_parallel_appends_and_reads_keep_chain_valid(st):
    def work(i: int) -> int:
        wid = f"W00{i % 8 + 1}"
        for k in range(15):
            st.ledger.append("punch.in", {"device": "t"}, worker_id=wid, ts=f"2026-10-27T08:{k:02d}:00+05:30")
            st.conn.execute("SELECT * FROM wallet_receipts WHERE worker_id=?", (wid,)).fetchall()
            st.ledger.events(worker_id=wid, limit=5, desc=True)
        return i

    with cf.ThreadPoolExecutor(16) as ex:
        assert sorted(ex.map(work, range(16))) == list(range(16))
    result = st.ledger.verify()
    assert result["ok"], result["problems"][:3]
    assert result["n_events"] == 16 * 15


def test_rows_behave_like_a_cursor(st):
    rows = st.conn.execute("SELECT id FROM workers ORDER BY id")
    assert rows.fetchone()["id"] == "S001"
    assert [r["id"] for r in rows][:2] == ["S001", "W001"]
    assert st.conn.execute("SELECT 1 WHERE 0").fetchone() is None
