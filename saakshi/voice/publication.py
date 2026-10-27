"""Themes: threshold publication, escalation, case status, management responses and the "You said, we did" board.

A theme (topic, month) reaches the employer only once >= THRESHOLD distinct tokens were spent on it, and never
on a site with fewer than MIN_GROUP enrolled workers. Safety-critical topics escalate on the first report.
"""
from __future__ import annotations

import sqlite3
from typing import Any, TypedDict

from fastapi import HTTPException

from ..ledger import now_ts
from ..state import State
from .store import enrolled, latest_response, report_count, resolve, sha256_hex
from .topics import LABELS, MIN_GROUP, ROUTES, SAFETY, THRESHOLD, TOPIC_IDS, Labels, check_topic, current_month, status


class BoardEntry(TypedDict):
    """One "You said, we did" line: the first report of a theme and management's answer."""

    topic: str
    month: str
    label: Labels
    count: int
    you_said: str
    we_did: str
    by: str
    ts: str
    seq: int | None


def theme(month: str, topic: str, st: State) -> dict[str, Any]:
    """Console view of one theme; report texts only once published or escalated."""
    count = report_count(month, topic, st)
    published = count >= THRESHOLD
    escalated = topic in SAFETY and count > 0
    t: dict[str, Any] = {
        "topic": topic, "month": month, "label": LABELS[topic], "count": count, "threshold": THRESHOLD,
        "published": published, "escalated": escalated, "status": status(topic, count),
        "safety_critical": topic in SAFETY, "response": latest_response(month, topic, st)}
    if topic in ROUTES:
        t["route_to"] = ROUTES[topic]
    if published or escalated:
        t["reports"] = [{"text": r["text"], "ts": r["hour"], "lang": r["lang"]} for r in st.conn.execute(
            "SELECT text, hour, lang FROM voice_reports WHERE month=? AND topic=? ORDER BY hour, rowid",
            (month, topic)).fetchall()]
    else:
        t["note"] = "waiting for corroboration"
    return t


def themes(month: str | None = None, st: State | None = None) -> list[dict[str, Any]]:
    """Console view. Topics with at least one report this month; texts only once published or escalated."""
    s = resolve(st)
    month = month or current_month()
    if enrolled(s) < MIN_GROUP:
        return []  # group-size guard: too few workers to stay anonymous
    used = {r[0] for r in s.conn.execute("SELECT DISTINCT topic FROM voice_reports WHERE month=?", (month,))}
    return [theme(month, tid, s) for tid in TOPIC_IDS if tid in used]


def case_status(case_key: str, st: State | None = None) -> dict[str, Any]:
    """What the holder of a case key may see: the theme's status and the latest response; 404 if unknown."""
    s = resolve(st)
    r = s.conn.execute("SELECT topic, month FROM voice_reports WHERE case_key_hash=?", (sha256_hex(case_key),)).fetchone()
    if not r:
        raise HTTPException(404, "unknown case key")
    topic, month = r["topic"], r["month"]
    count = report_count(month, topic, s)
    out: dict[str, Any] = {
        "case_key": case_key, "topic": topic, "month": month, "label": LABELS[topic],
        "status": status(topic, count), "corroborations": count, "threshold": THRESHOLD,
        "response": latest_response(month, topic, s)}
    if topic in ROUTES:
        out["route_to"] = ROUTES[topic]
    return out


def board_entry(row: sqlite3.Row, st: State) -> BoardEntry:
    """Turn a voice_responses row into a board entry."""
    first = st.conn.execute("SELECT text FROM voice_reports WHERE month=? AND topic=? ORDER BY hour, rowid LIMIT 1",
                            (row["month"], row["topic"])).fetchone()
    return {"topic": row["topic"], "month": row["month"], "label": LABELS[row["topic"]],
            "count": report_count(row["month"], row["topic"], st),
            "you_said": first["text"] if first else LABELS[row["topic"]]["en"],
            "we_did": row["text"], "by": row["by"], "ts": row["ts"], "seq": row["seq"]}


def respond(topic: str, text: str, by: str, month: str | None = None, ts: str | None = None,
            st: State | None = None) -> BoardEntry:
    """Record a management response to a published or escalated theme; 409 if it has not reached management."""
    s = resolve(st)
    check_topic(topic)
    month = month or current_month()
    text, by = (text or "").strip(), (by or "").strip()
    if not text or not by:
        raise HTTPException(422, "text and by are required")
    with s.lock:
        th = theme(month, topic, s)
        if not (th["published"] or th["escalated"]):
            raise HTTPException(409, "this theme has not reached management yet")
        ts = ts or now_ts()
        ev = s.ledger.append("voice.response", {"topic": topic, "month": month, "text": text, "by": by},
                             worker_id=None, ts=ts, receipt=False)
        cur = s.conn.execute("INSERT INTO voice_responses(topic, month, text, by, ts, seq) VALUES (?,?,?,?,?,?)",
                             (topic, month, text, by, ts, ev["seq"]))
        row = s.conn.execute("SELECT * FROM voice_responses WHERE id=?", (cur.lastrowid,)).fetchone()
        return board_entry(row, s)


def board(st: State | None = None) -> list[BoardEntry]:
    """"You said, we did": newest first."""
    s = resolve(st)
    rows = s.conn.execute("SELECT * FROM voice_responses ORDER BY ts DESC, id DESC").fetchall()
    return [board_entry(r, s) for r in rows]
