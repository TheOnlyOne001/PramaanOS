"""Proof of record: a signed, hash-chained event ledger with daily Merkle roots.

Every event body is {seq, site, ts, type, worker_id, payload, prev_hash}; `type` is one of the
constants in `saakshi/events.py` (e.g. events.PUNCH_IN == "punch.in").
hash = sha256(canonical(body)); sig = Ed25519(signer key, bytes(hash)).
A correction is a new event, never an overwrite.

verify() recomputes every hash from the stored content, checks every
signature and link, and compares each published daily root with the root
recomputed from content. Any direct database edit shows up in at least one.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
from collections.abc import Callable, Hashable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, NotRequired, TypedDict, TypeVar

from . import i18n
from .config import SITE_ID
from .crypto import KeyStore, ProofStep, canonical, merkle_proof, merkle_root, sha256_hex, verify_sig

GENESIS = "0" * 64
IST = timezone(timedelta(hours=5, minutes=30))
T = TypeVar("T")


# --- return shapes (plain dicts on the wire; these only describe them) ----------------------------

class Receipt(TypedDict):
    """The wallet copy dropped for the worker an event names, rendered in the worker's language."""
    worker_id: str
    seq: int
    ref: str
    ts: str
    type: str
    hash: str
    text: str
    text_en: str
    lang: str
    channel: str


class Event(TypedDict):
    """One ledger event: the hashed body plus day, hash, signature, signer and short ref.

    `receipt` is present only on the dict returned by Ledger.append().
    """
    seq: int
    site: str
    ts: str
    day: str
    type: str
    worker_id: str | None
    payload: dict[str, Any]
    prev_hash: str
    hash: str
    sig: str
    signer: str
    ref: str
    receipt: NotRequired[Receipt | None]


class Problem(TypedDict):
    """One integrity finding from verify(). `kind` names what failed (see API.md)."""
    seq: int | None
    kind: str
    detail: str
    worker_id: str | None
    type: str
    ts: NotRequired[str]
    stored_hash: NotRequired[str]
    recomputed_hash: NotRequired[str]
    worker_name: NotRequired[str | None]


class RootStatus(TypedDict):
    """A published daily Merkle root next to the root recomputed from content now."""
    day: str
    published: str
    current: str
    ok: bool
    n_events: int
    published_at: str


class VerifyResult(TypedDict):
    """Result of Ledger.verify()."""
    ok: bool
    n_events: int
    problems: list[Problem]
    roots: list[RootStatus]
    head: str
    checked_at: str


class PublishedRoot(TypedDict):
    """A signed daily root as returned by Ledger.publish_root()."""
    day: str
    root: str
    n_events: int
    last_seq: int
    published_at: str
    sig: str
    site_public_key: str


class InclusionProof(TypedDict):
    """Merkle inclusion proof of one event in its day's root."""
    seq: int
    hash: str
    day: str
    root: str
    proof: list[ProofStep]


class _Snapshot(TypedDict):
    total_changes: int
    own: int
    data_version: int
    count: int
    max_seq: int


class _Checkpoint(TypedDict):
    """Chain state after verifying events 1..seq; lets verify() re-check only an appended tail."""
    snap: _Snapshot
    head: str
    seq: int
    n: int
    problems: list[Problem]
    days: dict[str, list[tuple[int, str]]]
    unreadable: bool
    root_memo: dict[tuple[str, int], str]
    result: NotRequired[VerifyResult]


Fingerprint = tuple[int, int, int]


def now_ts() -> str:
    """Current time in IST, ISO 8601 with offset, second precision."""
    return datetime.now(IST).replace(microsecond=0).isoformat()


def ref_of(hash_hex: str) -> str:
    """Return the short uppercase reference code for an event hash."""
    return hash_hex[:4].upper()


def _row_to_event(r: sqlite3.Row) -> Event:
    return {
        "seq": r["seq"], "site": r["site"], "ts": r["ts"], "day": r["day"], "type": r["type"],
        "worker_id": r["worker_id"], "payload": json.loads(r["payload"]),
        "prev_hash": r["prev_hash"], "hash": r["hash"], "sig": r["sig"], "signer": r["signer"],
        "ref": ref_of(r["hash"]),
    }


def _problem(ev: Event, kind: str, detail: str) -> Problem:
    return {"seq": ev["seq"], "worker_id": ev["worker_id"], "type": ev["type"], "ts": ev["ts"],
            "kind": kind, "detail": detail}


def body_of(ev: Mapping[str, Any]) -> dict[str, Any]:
    """Return the hashed body fields of an event."""
    return {k: ev[k] for k in ("seq", "site", "ts", "type", "worker_id", "payload", "prev_hash")}


class Ledger:
    """Append-only, hash-chained, signed event ledger for a site."""
    def __init__(self, conn: sqlite3.Connection, keys: KeyStore, lock: threading.RLock, site: str = SITE_ID) -> None:
        self.conn = conn
        self.keys = keys
        self.lock = lock
        self.site = site
        # Efficiency: verify() result cache + verified checkpoint for incremental (append-only) re-checks.
        self._own_changes = 0                 # rows this Ledger itself wrote (appends, receipts, root publishes)
        self._ck: _Checkpoint | None = None   # last verified checkpoint, see _verify_full / _verify_tail
        self._pubs: dict[str, str] = {}
        self._memo_fp: Fingerprint | None = None
        self._memo_data: dict[Hashable, Any] = {}

    # --- write ---------------------------------------------------------------

    def append(self, type: str, payload: dict, worker_id: str | None = None, ts: str | None = None,
               signer: str = "site", receipt: bool = True, channel: str = "whatsapp") -> Event:
        """Append one signed event. If it names a worker, also drop a receipt in their wallet.

        Returns the event dict, plus "receipt" (or None).
        """
        ts = ts or now_ts()
        with self.lock:
            last = self.conn.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            seq = (last["seq"] + 1) if last else 1
            prev = last["hash"] if last else GENESIS
            body: dict[str, Any] = {"seq": seq, "site": self.site, "ts": ts, "type": type,
                                    "worker_id": worker_id, "payload": payload, "prev_hash": prev}
            h = sha256_hex(canonical(body))
            sig = self.keys.sign(signer, bytes.fromhex(h))
            self.conn.execute(
                "INSERT INTO events(seq, site, ts, day, type, worker_id, payload, prev_hash, hash, sig, signer)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (seq, self.site, ts, ts[:10], type, worker_id,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True), prev, h, sig, signer),
            )
            self._own_changes += 1
            ev: Event = {"seq": seq, "site": self.site, "ts": ts, "day": ts[:10], "type": type, "worker_id": worker_id,
                         "payload": payload, "prev_hash": prev, "hash": h, "sig": sig, "signer": signer, "ref": ref_of(h)}
            ev["receipt"] = self._issue_receipt(ev, worker_id, channel) if (worker_id and receipt) else None
        return ev

    def _issue_receipt(self, ev: Event, worker_id: str, channel: str) -> Receipt:
        w = self.conn.execute("SELECT lang FROM workers WHERE id=?", (worker_id,)).fetchone()
        lang = w["lang"] if w else "en"
        ctx = receipt_ctx(ev)
        text = i18n.render(ev["type"], ctx, lang)
        text_en = i18n.render(ev["type"], ctx, "en")
        created = now_ts()
        self.conn.execute(
            "INSERT INTO wallet_receipts(worker_id, seq, ref, ts, type, hash, text, text_en, channel, created)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (worker_id, ev["seq"], ev["ref"], ev["ts"], ev["type"], ev["hash"], text, text_en, channel, created),
        )
        self._own_changes += 1
        return {"worker_id": worker_id, "seq": ev["seq"], "ref": ev["ref"], "ts": ev["ts"],
                "type": ev["type"], "hash": ev["hash"], "text": text, "text_en": text_en,
                "lang": lang, "channel": channel}

    # --- read ----------------------------------------------------------------

    def get(self, seq: int) -> Event | None:
        """Return the event with sequence number `seq`, or None."""
        r = self.conn.execute("SELECT * FROM events WHERE seq=?", (seq,)).fetchone()
        return _row_to_event(r) if r else None

    def events(self, worker_id: str | None = None, type: str | None = None, type_prefix: str | None = None,
               day: str | None = None, day_from: str | None = None, day_to: str | None = None,
               since_seq: int | None = None, limit: int | None = None, desc: bool = False) -> list[Event]:
        """Events matching every filter given (None means 'any'), in seq order (newest first with desc)."""
        filters: list[tuple[str, str | int | None]] = [("worker_id=?", worker_id), ("type=?", type),
                   ("type LIKE ?", None if type_prefix is None else type_prefix + "%"),
                   ("day=?", day), ("day>=?", day_from), ("day<=?", day_to), ("seq>?", since_seq)]
        q: list[str] = ["SELECT * FROM events WHERE 1=1"]
        args: list[str | int] = []
        for clause, value in filters:
            if value is not None:
                q.append("AND " + clause)
                args.append(value)
        q.append("ORDER BY seq DESC" if desc else "ORDER BY seq ASC")
        if limit:
            q.append("LIMIT ?")
            args.append(int(limit))
        return [_row_to_event(r) for r in self.conn.execute(" ".join(q), args).fetchall()]

    def count(self) -> int:
        """Number of events in the ledger."""
        return self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    # --- change detection ----------------------------------------------------

    def db_fingerprint(self) -> Fingerprint:
        """Changes on ANY write to this database: by this connection (total_changes, which counts every
        INSERT/UPDATE/DELETE row, raw SQL included) or by any other connection/process (data_version)."""
        return (id(self.conn), self.conn.total_changes, self.conn.execute("PRAGMA data_version").fetchone()[0])

    def memo(self, key: Hashable, fn: Callable[[], T]) -> T:
        """Return fn() cached until the next write to the database (see db_fingerprint). Callers get a copy."""
        fp = self.db_fingerprint()
        if self._memo_fp != fp:
            self._memo_fp, self._memo_data = fp, {}
        if key not in self._memo_data:
            self._memo_data[key] = fn()
        value: T = copy.deepcopy(self._memo_data[key])
        return value

    def _snapshot(self) -> _Snapshot:
        """Read under the lock, BEFORE reading rows: any write not reflected here forces a later re-check."""
        n, mx = self.conn.execute("SELECT COUNT(*), COALESCE(MAX(seq), 0) FROM events").fetchone()
        return {"total_changes": self.conn.total_changes, "own": self._own_changes,
                "data_version": self.conn.execute("PRAGMA data_version").fetchone()[0], "count": n, "max_seq": mx}

    @staticmethod
    def _fp(snap: _Snapshot) -> tuple[int, int, int, int]:
        return (snap["total_changes"], snap["data_version"], snap["count"], snap["max_seq"])

    # --- integrity -----------------------------------------------------------

    def content_hash(self, ev: Mapping[str, Any]) -> str:
        """sha256 of the event body recomputed from its content (not the stored hash column)."""
        return sha256_hex(canonical(body_of(ev)))

    def _pub(self, signer: str) -> str:
        if signer not in self._pubs:
            self._pubs[signer] = self.keys.public_hex(signer)
        return self._pubs[signer]

    def _check_rows(self, rows: Sequence[sqlite3.Row], ck: _Checkpoint) -> None:
        """Hash, signature and link checks for `rows` (seq order), continuing the chain state in `ck`."""
        problems, days = ck["problems"], ck["days"]
        prev_hash, prev_seq = ck["head"], ck["seq"]
        for r in rows:
            try:
                ev = _row_to_event(r)
            except (ValueError, TypeError):
                problems.append({"seq": r["seq"], "kind": "unreadable", "detail": "payload is not valid JSON",
                                 "worker_id": r["worker_id"], "type": r["type"]})
                ck["unreadable"] = True
                prev_hash, prev_seq = r["hash"], r["seq"]
                continue
            if ev["seq"] != prev_seq + 1:
                problems.append(_problem(ev, "missing_events", f"events {prev_seq + 1}..{ev['seq'] - 1} are missing"))
            if ev["prev_hash"] != prev_hash:
                problems.append(_problem(ev, "broken_link", "prev_hash does not match the previous event's hash"))
            recomputed = self.content_hash(ev)
            if recomputed != ev["hash"]:
                edited = _problem(ev, "content_edited", "content no longer matches its signed hash (edited after signing)")
                edited["stored_hash"], edited["recomputed_hash"] = ev["hash"], recomputed
                problems.append(edited)
            if not verify_sig(self._pub(ev["signer"]), bytes.fromhex(ev["hash"]), ev["sig"]):
                problems.append(_problem(ev, "bad_signature", f"signature by '{ev['signer']}' does not verify"))
            days.setdefault(r["day"], []).append((ev["seq"], recomputed))
            prev_hash, prev_seq = ev["hash"], ev["seq"]
        ck["head"], ck["seq"], ck["n"] = prev_hash, prev_seq, ck["n"] + len(rows)

    def _roots_from(self, ck: _Checkpoint) -> list[RootStatus]:
        """roots_status() computed from the checkpoint's content hashes instead of re-reading every event."""
        if ck["unreadable"]:
            return self._roots_status_scan()  # same behaviour as before for unreadable rows
        out: list[RootStatus] = []
        for rt in self.roots():
            key = (rt["day"], rt["last_seq"])
            current = ck["root_memo"].get(key)
            if current is None:
                current = merkle_root([h for seq, h in ck["days"].get(rt["day"], []) if seq <= rt["last_seq"]])
                if rt["last_seq"] <= ck["seq"]:  # only memoise roots whose events are all in the checkpoint
                    ck["root_memo"][key] = current
            out.append({"day": rt["day"], "published": rt["root"], "current": current,
                        "ok": current == rt["root"], "n_events": rt["n_events"], "published_at": rt["published_at"]})
        return out

    def _verify_full(self) -> _Checkpoint:
        with self.lock:
            snap = self._snapshot()
            rows = self.conn.execute("SELECT * FROM events ORDER BY seq ASC").fetchall()
        self._pubs = {}
        ck: _Checkpoint = {"snap": snap, "head": GENESIS, "seq": 0, "n": 0, "problems": [], "days": {},
                           "unreadable": False, "root_memo": {}}
        self._check_rows(rows, ck)
        return ck

    def _verify_tail(self, ck: _Checkpoint) -> _Checkpoint | None:
        """Re-check only events appended since `ck`. None means 'not provably append-only: do a full check'."""
        old = ck["snap"]
        with self.lock:
            snap = self._snapshot()
            foreign = (snap["total_changes"] - old["total_changes"]) - (snap["own"] - old["own"])
            if foreign or snap["data_version"] != old["data_version"] or snap["count"] < old["count"]:
                return None
            rows = self.conn.execute("SELECT * FROM events WHERE seq>? ORDER BY seq ASC", (ck["seq"],)).fetchall()
        if len(rows) != snap["count"] - old["count"]:
            return None
        new: _Checkpoint = {**ck, "snap": snap, "problems": list(ck["problems"]),
                            "days": {d: list(v) for d, v in ck["days"].items()}, "root_memo": dict(ck["root_memo"])}
        self._check_rows(rows, new)
        return new

    def verify(self, full: bool = False) -> VerifyResult:
        """Full integrity check. Returns {ok, n_events, problems, roots}.

        Cached: the result is reused only while the database fingerprint (rows written by this connection,
        commits by any other connection, event count, max seq) is unchanged. A miss caused purely by this
        ledger's own appends re-checks just the new tail; anything else (a raw UPDATE/DELETE, a write from
        another process) re-checks every event from genesis.
        """
        ck = self._ck
        if not full and ck is not None:
            with self.lock:
                hit = self._fp(self._snapshot()) == self._fp(ck["snap"]) and "result" in ck
            if hit:
                return self._fresh(ck["result"])
        new = None if (full or ck is None) else self._verify_tail(ck)
        if new is None:
            new = self._verify_full()
        problems = list(new["problems"])
        roots = self._roots_from(new)
        problems.extend(Problem(seq=None, worker_id=None, type="daily_root", ts=rt["day"], kind="root_mismatch",
                                detail=f"published root for {rt['day']} no longer matches the ledger")
                        for rt in roots if not rt["ok"])
        new["result"] = {"ok": not problems, "n_events": new["n"], "problems": problems, "roots": roots,
                         "head": new["head"], "checked_at": now_ts()}
        self._ck = new
        return self._fresh(new["result"])

    @staticmethod
    def _fresh(cached: VerifyResult) -> VerifyResult:
        """A private copy of a cached result, stamped with the time of this call."""
        res = copy.deepcopy(cached)
        res["checked_at"] = now_ts()
        return res

    def day_content_hashes(self, day: str, upto_seq: int | None = None) -> list[str]:
        """Hashes recomputed from content (not the stored hash column)."""
        evs = self.events(day=day)
        if upto_seq is not None:
            evs = [e for e in evs if e["seq"] <= upto_seq]
        return [self.content_hash(e) for e in evs]

    def compute_root(self, day: str, upto_seq: int | None = None) -> str:
        """Merkle root of `day` recomputed from content, optionally only up to `upto_seq`."""
        return merkle_root(self.day_content_hashes(day, upto_seq))

    def publish_root(self, day: str) -> PublishedRoot:
        """Publish (or re-publish) the Merkle root of every event so far on `day`."""
        with self.lock:
            evs = self.events(day=day)
            hashes = [e["hash"] for e in evs]
            root = merkle_root(hashes)
            last_seq = evs[-1]["seq"] if evs else 0
            msg = canonical({"site": self.site, "day": day, "root": root, "n_events": len(evs), "last_seq": last_seq})
            sig = self.keys.sign("site", msg)
            published = now_ts()
            self.conn.execute(
                "INSERT INTO daily_roots(day, root, n_events, last_seq, published_at, sig) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(day) DO UPDATE SET root=excluded.root, n_events=excluded.n_events,"
                " last_seq=excluded.last_seq, published_at=excluded.published_at, sig=excluded.sig",
                (day, root, len(evs), last_seq, published, sig),
            )
            self._own_changes += 1
        return {"day": day, "root": root, "n_events": len(evs), "last_seq": last_seq,
                "published_at": published, "sig": sig, "site_public_key": self.keys.public_hex("site")}

    def roots(self) -> list[dict[str, Any]]:
        """Published daily roots (raw `daily_roots` rows), oldest day first."""
        return [dict(r) for r in self.conn.execute("SELECT * FROM daily_roots ORDER BY day").fetchall()]

    def roots_status(self) -> list[RootStatus]:
        """Each published root next to the root recomputed now (from the cached verify())."""
        return self.verify()["roots"]

    def _roots_status_scan(self) -> list[RootStatus]:
        out: list[RootStatus] = []
        for rt in self.roots():
            current = self.compute_root(rt["day"], upto_seq=rt["last_seq"])
            out.append({"day": rt["day"], "published": rt["root"], "current": current,
                        "ok": current == rt["root"], "n_events": rt["n_events"], "published_at": rt["published_at"]})
        return out

    def inclusion_proof(self, seq: int) -> InclusionProof | None:
        """Merkle path proving event `seq` is in its day's root, or None if there is no such event."""
        ev = self.get(seq)
        if not ev:
            return None
        evs = self.events(day=ev["day"])
        hashes = [e["hash"] for e in evs]
        idx = [e["seq"] for e in evs].index(seq)
        return {"seq": seq, "hash": ev["hash"], "day": ev["day"], "root": merkle_root(hashes),
                "proof": merkle_proof(hashes, idx)}


def receipt_ctx(ev: Mapping[str, Any]) -> dict[str, Any]:
    """Return the template context used to render an event's receipt."""
    p = ev.get("payload") or {}
    return {**p, "ref": ev["ref"], "type": ev["type"], "hm": ev["ts"][11:16], "date": ev["ts"][:10]}
