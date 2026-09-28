"""NF-13: every string the admin scripts translate is declared in js_strings.py."""

from __future__ import annotations

import re
from pathlib import Path

from tellybox.i18n import use_locale
from tellybox.web.admin.js_strings import PLURALS, STRINGS, js_catalog

STATIC = Path(__file__).resolve().parents[3] / "tellybox" / "web" / "admin" / "static"
LITERAL = r'"((?:[^"\\]|\\.)*)"'


def _used() -> tuple[set[str], set[tuple[str, str]], list[str]]:
    singles: set[str] = set()
    plurals: set[tuple[str, str]] = set()
    dynamic: list[str] = []
    for path in sorted(STATIC.glob("*.js")):
        if path.name == "i18n.js":
            continue
        text = path.read_text(encoding="utf-8")
        singles |= set(re.findall(rf"\bt\({LITERAL}", text))
        plurals |= set(re.findall(rf"\btn\({LITERAL},\s*{LITERAL}", text))
        # t(...) / tn(...) with anything but a string literal can't be checked (or extracted)
        dynamic += [f"{path.name}: {m}" for m in re.findall(r"\btn?\((?!\")[^)]*\)", text)]
    return singles, plurals, dynamic


def test_scripts_only_use_declared_strings():
    singles, plurals, dynamic = _used()
    assert singles and plurals
    assert not dynamic, dynamic
    assert singles <= set(STRINGS), sorted(singles - set(STRINGS))
    assert plurals <= set(PLURALS), sorted(plurals - set(PLURALS))


def test_no_unused_declarations():
    singles, plurals, _dynamic = _used()
    assert set(STRINGS) <= singles, sorted(set(STRINGS) - singles)
    assert set(PLURALS) <= plurals, sorted(set(PLURALS) - plurals)


def test_catalog_is_english_by_default():
    with use_locale("en"):
        data = js_catalog()
    assert data["s"]["Nothing is playing."] == "Nothing is playing."
    assert data["p"]["%(num)d failed job"] == ["%(num)d failed job", "%(num)d failed jobs"]
