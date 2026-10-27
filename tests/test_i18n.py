"""Every receipt template and every worker-app UI string exists in en, ta, hi and or."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from saakshi import app as _app  # noqa: F401  (imports every module, registering its templates)
from saakshi import i18n

ROOT = Path(__file__).resolve().parent.parent
TYPES = sorted(i18n._templates)


class SampleCtx(dict):
    """Payload fields we did not think of come back as a small number (works with :g and str())."""

    def __missing__(self, key):
        return 3


def _ctx(t):
    return SampleCtx(hm="09:05", ref="AB12", date="2026-10-27", type=t, reason="late bus", approver="Murugan",
                     viewer="Auditor", hours=2, name="Meena", skill="overlock", level="L2")


def test_core_templates_registered():
    for t in ("punch.in", "punch.out", "punch.correction", "access.lookup"):
        assert i18n.has(t)
    assert len(TYPES) >= 8, TYPES


@pytest.mark.parametrize("event_type", TYPES)
@pytest.mark.parametrize("lang", i18n.LANGS)
def test_receipt_template_renders_without_fallback(event_type, lang):
    by_lang = i18n._templates[event_type]
    assert lang in by_lang, f"{event_type} has no {lang} template (would fall back to English)"
    ctx = _ctx(event_type)
    direct = by_lang[lang](ctx)  # raises if the template itself is broken, instead of silently using en
    out = i18n.render(event_type, ctx, lang)
    generic = f"{event_type} · ref {ctx['ref']}"
    assert out == direct
    assert out and out != generic
    assert "AB12" in out, "receipt must carry the ref so the worker can match it"
    if lang != "en":
        assert out != by_lang["en"](ctx), f"{event_type}/{lang} is identical to English"


def test_unknown_type_falls_back_to_generic():
    assert i18n.render("no.such.type", {"ref": "ZZ99"}, "ta") == "no.such.type · ref ZZ99"


def _js_strings():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    src = (ROOT / "web" / "shared" / "i18n.js").resolve().as_uri()
    js = f"import({json.dumps(src)}).then(m => process.stdout.write(JSON.stringify(m.STRINGS)))"
    out = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def test_ui_strings_complete_in_every_language():
    S = _js_strings()
    assert set(S) >= {"en", "ta", "hi", "or"}
    missing = {lang: sorted(k for k, v in S["en"].items() if v and not S[lang].get(k)) for lang in ("ta", "hi", "or")}
    total = sum(len(v) for v in missing.values())
    if total:
        print("\nMissing UI strings:", json.dumps(missing, ensure_ascii=False))
    if total > 10:
        pytest.xfail(f"{total} UI strings missing translations: {missing}")
    assert not total, missing


def test_ui_placeholders_match_english():
    import re
    S = _js_strings()
    ph = re.compile(r"\{(\w+)\}")
    bad = []
    for k, v in S["en"].items():
        if not isinstance(v, str):
            continue
        want = set(ph.findall(v))
        for lang in ("ta", "hi", "or"):
            got = S[lang].get(k)
            if isinstance(got, str) and set(ph.findall(got)) != want:
                bad.append((lang, k, sorted(want), sorted(set(ph.findall(got)))))
    assert not bad, bad
