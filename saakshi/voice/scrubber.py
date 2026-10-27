"""Scrub: suggest a rewrite of a report that removes identifying details (rules and the roster, no LLM).

Nothing is stored or logged; the worker decides whether to use the suggestion.
"""
from __future__ import annotations

import re
from typing import NamedTuple, TypedDict

from ..state import State
from .store import resolve


class _Rule(NamedTuple):
    pattern: str
    replacement: str
    reason: str


class _Hit(NamedTuple):
    start: int
    end: int
    replacement: str
    reason: str


class Flag(TypedDict):
    """One identifying span found in the text and what it would be replaced with."""

    span: str
    start: int
    end: int
    reason: str
    replacement: str


class Scrubbed(TypedDict):
    """A suggested rewrite plus the spans that triggered it."""

    suggested: str
    changed: bool
    flags: list[Flag]


MIN_NAME_PART = 3
"""Shortest part of a roster name matched on its own (shorter parts give false hits)."""

_WORDS = r"(?:woman|women|lady|ladies|girl|man|men|boy|female|male|one|person|worker|operator|checker|helper|" \
         r"tailor|[a-z]+\s+speaker|[a-z]+\s+(?:woman|man|girl|boy|worker))"
_RULES: list[_Rule] = [
    _Rule(r"\b(?:i\s+am\s+|i'm\s+)?(?:the\s+)?only\s+" + _WORDS + r"\b", "[a worker]", "describes a group of one"),
    _Rule(r"\b(?i:(?:my\s+)?(?:supervisor|manager|in-?charge|boss|maistry|mestri)\s+(?:sir\s+|madam\s+)?)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?",
          "[a supervisor]", "names a supervisor"),
    _Rule(r"\b(?:my\s+|our\s+)?line\s*(?:no\.?|number|num|#)?\s*\d+\b", "[my line]", "names a line"),
    _Rule(r"\b(?:machine|table|seat|m/c)\s*(?:no\.?|number|#)?\s*\d+\b", "[my machine]", "names a machine"),
    _Rule(r"(?:\+?91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b", "[phone]", "phone number"),
    _Rule(r"\b\d{10}\b", "[phone]", "phone number"),
    _Rule(r"\b[WS]\d{3,}\b", "[id]", "employee id"),
    _Rule(r"\b(?:emp(?:loyee)?|staff|token|badge)\s*(?:id|no\.?|number|#)\s*[:#]?\s*\w+", "[id]", "employee id"),
]


def _roster_rules(st: State) -> list[_Rule]:
    """Rules for every contractor and worker name on the roster, longest first so full names win."""
    fulls: list[tuple[str, str]] = []
    parts: list[tuple[str, str]] = []
    contractors: set[str] = set()
    for r in st.conn.execute("SELECT name, is_supervisor, contractor FROM workers").fetchall():
        repl = "[a supervisor]" if r["is_supervisor"] else "[a worker]"
        fulls.append((r["name"], repl))
        parts.extend((p, repl) for p in r["name"].split() if len(p) >= MIN_NAME_PART)
        if r["contractor"]:
            contractors.add(r["contractor"])
    out = [_Rule(r"\b" + re.escape(c) + r"\b", "[a contractor]", "names a contractor")
           for c in sorted(contractors, key=len, reverse=True)]
    out.extend(_Rule(r"\b" + re.escape(name) + r"\b", repl, "names a person")
               for name, repl in [*sorted(fulls, key=lambda x: -len(x[0])), *parts])
    return out


def _non_overlapping(hits: list[_Hit]) -> list[_Hit]:
    """Keep the earliest, then longest, hit; drop any that overlap one already kept."""
    chosen: list[_Hit] = []
    last_end = -1
    for h in sorted(hits, key=lambda h: (h.start, -(h.end - h.start))):
        if h.start >= last_end:
            chosen.append(h)
            last_end = h.end
    return chosen


def scrub(text: str, st: State | None = None) -> Scrubbed:
    """Suggest a rewrite of text with identifying details replaced, plus the flagged spans and reasons."""
    s = resolve(st)
    text = text or ""
    hits: list[_Hit] = []
    for rule in _RULES + _roster_rules(s):
        flags = 0 if "[A-Z]" in rule.pattern else re.IGNORECASE  # case-sensitive rules look for capitalised names
        hits.extend(_Hit(mt.start(), mt.end(), rule.replacement, rule.reason)
                    for mt in re.finditer(rule.pattern, text, flags) if mt.end() > mt.start())
    chosen = _non_overlapping(hits)
    pieces: list[str] = []
    pos = 0
    for h in chosen:
        pieces += [text[pos:h.start], h.replacement]
        pos = h.end
    pieces.append(text[pos:])
    suggested = re.sub(r"\s{2,}", " ", "".join(pieces)).strip()
    return {"suggested": suggested, "changed": bool(chosen),
            "flags": [{"span": text[h.start:h.end], "start": h.start, "end": h.end, "reason": h.reason,
                       "replacement": h.replacement} for h in chosen]}
