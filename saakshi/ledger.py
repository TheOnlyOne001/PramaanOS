"""Proof of record: a signed, hash-chained event ledger with daily Merkle roots.

Every event body is {seq, site, ts, type, worker_id, payload, prev_hash}.
hash = sha256(canonical(body)); sig = Ed25519(signer key, bytes(hash)).
A correction is a new event, never an overwrite.

verify() recomputes every hash from the stored content, checks every
signature and link, and compares each published daily root with the root
recomputed from content. Any direct database edit shows up in at least one.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from . import i18n
from .config import SITE_ID
from .crypto import KeyStore, canonical, merkle_proof, merkle_root, sha256_hex, verify_sig

GENESIS = "0" * 64


def now_ts() -> str:
    """Current time in IST, ISO 8601 with offset, second precision."""
    from datetime import timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).replace(microsecond=0).isoformat()


def ref_of(hash_hex: str) -> str:
    return hash_hex[:4].upper()


def _row_to_event(r) -> dict:
    return {
        "seq": r["seq"], "site": r["site"], "ts": r["ts"], "day": r["day"], "type": r["type"],
        "worker_id": r["worker_id"], "payload": json.loads(r["payload"]),
        "prev_hash": r["prev_hash"], "hash": r["hash"], "sig": r["sig"], "signer": r["signer"],
        "ref": ref_of(r["hash"]),
    }


def body_of(ev: dict) -> dict:
    return {k: ev[k] for k in ("seq", "site", "ts", "type", "worker_id", "payload", "prev_hash")}


class Ledger:
    def __init__(self, conn, keys: KeyStore, lock: threading.RLock, site: str = SITE_ID):
        self.conn = conn
        self.keys = keys
        self.lock = lock
        self.site = site

    # --- write ---------------------------------------------------------------

    def append(self, type: str, payload: dict, worker_id: str | None = None, ts: str | None = None,
               signer: str = "site", receipt: bool = True, channel: str = "whatsapp") -> dict:
        """Append one signed event. If it names a worker, also drop a receipt in their wallet.

        Returns the event dict, plus "receipt" (or None).
        """
        ts = ts or now_ts()
        with self.lock:
            last = self.conn.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            seq = (last["seq"] + 1) if last else 1
            prev = last["hash"] if last else GENESIS
            body = {"seq": seq, "site": self.site, "ts": ts, "type": type,
                    "worker_id": worker_id, "payload": payload, "prev_hash": prev}
            h = sha256_hex(canonical(body))
            sig = self.keys.sign(signer, bytes.fromhex(h))
            self.conn.execute(
                "INSERT INTO events(seq, site, ts, day, type, worker_id, payload, prev_hash, hash, sig, signer)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (seq, self.site, ts, ts[:10], type, worker_id,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True), prev, h, sig, signer),
            )
            ev = {**body, "day": ts[:10], "hash": h, "sig": sig, "signer": signer, "ref": ref_of(h)}
            ev["receipt"] = self._issue_receipt(ev, channel) if (worker_id and receipt) else None
        return ev

    def _issue_receipt(self, ev: dict, channel: str) -> dict:
        w = self.conn.execute("SELECT lang FROM workers WHERE id=?", (ev["worker_id"],)).fetchone()
        lang = w["lang"] if w else "en"
        ctx = receipt_ctx(ev)
        text = i18n.render(ev["type"], ctx, lang)
        text_en = i18n.render(ev["type"], ctx, "en")
        created = now_ts()
        self.conn.execute(
            "INSERT INTO wallet_receipts(worker_id, seq, ref, ts, type, hash, text, text_en, channel, created)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ev["worker_id"], ev["seq"], ev["ref"], ev["ts"], ev["type"], ev["hash"], text, text_en, channel, created),
        )
        return {"worker_id": ev["worker_id"], "seq": ev["seq"], "ref": ev["ref"], "ts": ev["ts"],
                "type": ev["type"], "hash": ev["hash"], "text": text, "text_en": text_en,
                "lang": lang, "channel": channel}

    # --- read ----------------------------------------------------------------

    def get(self, seq: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM events WHERE seq=?", (seq,)).fetchone()
        return _row_to_event(r) if r else None

    def events(self, worker_id: str | None = None, type: str | None = None, type_prefix: str | None = None,
               day: str | None = None, day_from: str | None = None, day_to: str | None = None,
               since_seq: int | None = None, limit: int | None = None, desc: bool = False) -> list[dict]:
        filters = [("worker_id=?", worker_id), ("type=?", type),
                   ("type LIKE ?", None if type_prefix is None else type_prefix + "%"),
                   ("day=?", day), ("day>=?", day_from), ("day<=?", day_to), ("seq>?", since_seq)]
        q, args = ["SELECT * FROM events WHERE 1=1"], []
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
        return self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    # --- integrity -----------------------------------------------------------

    def content_hash(self, ev: dict) -> str:
        return sha256_hex(canonical(body_of(ev)))

    def verify(self) -> dict:
        """Full integrity check. Returns {ok, n_events, problems, roots}."""
        problems: list[dict] = []
        pubs: dict[str, str] = {}
        prev_hash, prev_seq = GENESIS, 0
        with self.lock:
            rows = self.conn.execute("SELECT * FROM events ORDER BY seq ASC").fetchall()
        for r in rows:
            try:
                ev = _row_to_event(r)
            except (ValueError, TypeError):
                problems.append({"seq": r["seq"], "kind": "unreadable", "detail": "payload is not valid JSON",
                                 "worker_id": r["worker_id"], "type": r["type"]})
                prev_hash, prev_seq = r["hash"], r["seq"]
                continue
            base = {"seq": ev["seq"], "worker_id": ev["worker_id"], "type": ev["type"], "ts": ev["ts"]}
            if ev["seq"] != prev_seq + 1:
                problems.append({**base, "kind": "missing_events",
                                 "detail": f"events {prev_seq + 1}..{ev['seq'] - 1} are missing"})
            if ev["prev_hash"] != prev_hash:
                problems.append({**base, "kind": "broken_link",
                                 "detail": "prev_hash does not match the previous event's hash"})
            recomputed = self.content_hash(ev)
            if recomputed != ev["hash"]:
                problems.append({**base, "kind": "content_edited",
                                 "detail": "content no longer matches its signed hash (edited after signing)",
                                 "stored_hash": ev["hash"], "recomputed_hash": recomputed})
            if ev["signer"] not in pubs:
                pubs[ev["signer"]] = self.keys.public_hex(ev["signer"])
            if not verify_sig(pubs[ev["signer"]], bytes.fromhex(ev["hash"]), ev["sig"]):
                problems.append({**base, "kind": "bad_signature",
                                 "detail": f"signature by '{ev['signer']}' does not verify"})
            prev_hash, prev_seq = ev["hash"], ev["seq"]
        roots = self.roots_status()
        for rt in roots:
            if not rt["ok"]:
                problems.append({"seq": None, "worker_id": None, "type": "daily_root", "ts": rt["day"],
                                 "kind": "root_mismatch",
                                 "detail": f"published root for {rt['day']} no longer matches the ledger"})
        return {"ok": not problems, "n_events": len(rows), "problems": problems, "roots": roots,
                "head": prev_hash, "checked_at": now_ts()}

    def day_content_hashes(self, day: str, upto_seq: int | None = None) -> list[str]:
        """Hashes recomputed from content (not the stored hash column)."""
        evs = self.events(day=day)
        if upto_seq is not None:
            evs = [e for e in evs if e["seq"] <= upto_seq]
        return [self.content_hash(e) for e in evs]

    def compute_root(self, day: str, upto_seq: int | None = None) -> str:
        return merkle_root(self.day_content_hashes(day, upto_seq))

    def publish_root(self, day: str) -> dict:
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
        return {"day": day, "root": root, "n_events": len(evs), "last_seq": last_seq,
                "published_at": published, "sig": sig, "site_public_key": self.keys.public_hex("site")}

    def roots(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM daily_roots ORDER BY day").fetchall()]

    def roots_status(self) -> list[dict]:
        out = []
        for rt in self.roots():
            current = self.compute_root(rt["day"], upto_seq=rt["last_seq"])
            out.append({"day": rt["day"], "published": rt["root"], "current": current,
                        "ok": current == rt["root"], "n_events": rt["n_events"], "published_at": rt["published_at"]})
        return out

    def inclusion_proof(self, seq: int) -> dict | None:
        ev = self.get(seq)
        if not ev:
            return None
        evs = self.events(day=ev["day"])
        hashes = [e["hash"] for e in evs]
        idx = [e["seq"] for e in evs].index(seq)
        return {"seq": seq, "hash": ev["hash"], "day": ev["day"], "root": merkle_root(hashes),
                "proof": merkle_proof(hashes, idx)}


def receipt_ctx(ev: dict) -> dict:
    p = ev.get("payload") or {}
    ctx = {**p, "ref": ev["ref"], "type": ev["type"], "hm": ev["ts"][11:16], "date": ev["ts"][:10]}
    return ctx
