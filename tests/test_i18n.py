"""Interface languages (NF-13): choosing a language, translating, and complete catalogs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from babel.messages.extract import extract_from_dir
from babel.messages.frontend import parse_mapping_cfg
from babel.messages.pofile import read_po

from tellybox import i18n

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, "en"),
        ("", "en"),
        ("nl", "nl"),
        ("nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7", "nl"),
        ("nl-BE", "nl"),
        ("de-DE,de;q=0.9", "de"),
        ("de-AT", "de"),
        ("en-GB,en;q=0.9,nl;q=0.8", "en"),
        ("fr-FR,fr;q=0.9", "en"),  # unsupported: the default
        ("fr-FR,fr;q=0.9,nl;q=0.5", "nl"),  # first supported one by preference
        ("en;q=0.3,de;q=0.8", "de"),  # q-values win over order
        ("nl;q=0,de", "de"),  # q=0 means "not this one"
        ("*", "en"),
        ("NL-nl", "nl"),  # case-insensitive
        ("nl;q=abc,de", "de"),  # a broken q counts as 0
        (" , ;q=1", "en"),
    ],
)
def test_negotiate(header, expected):
    assert i18n.negotiate(header) == expected


@pytest.fixture
def catalogs(tmp_path, monkeypatch):
    """A small Dutch catalog in a temporary locale dir."""
    po = tmp_path / "nl" / "LC_MESSAGES" / "messages.po"
    po.parent.mkdir(parents=True)
    po.write_text(
        'msgid ""\nmsgstr ""\n"Language: nl\\n"\n"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n\n'
        'msgid "Library"\nmsgstr "Bibliotheek"\n\n'
        'msgid "Untranslated"\nmsgstr ""\n\n'
        '#, fuzzy\nmsgid "Guess"\nmsgstr "Gok"\n\n'
        'msgid "%(num)d video"\nmsgid_plural "%(num)d videos"\nmsgstr[0] "%(num)d video"\nmsgstr[1] "%(num)d video\'s"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)
    i18n.catalog.cache_clear()
    yield
    i18n.catalog.cache_clear()


def test_gettext_follows_the_current_locale(catalogs):
    assert i18n.gettext("Library") == "Library"
    with i18n.use_locale("nl"):
        assert i18n.current_locale() == "nl"
        assert i18n._("Library") == "Bibliotheek"
        assert i18n._("Untranslated") == "Untranslated"  # empty msgstr: the English
        assert i18n._("Guess") == "Guess"  # fuzzy entries are not used
        assert i18n._("Unknown") == "Unknown"
    assert i18n.current_locale() == "en"


def test_ngettext(catalogs):
    with i18n.use_locale("nl"):
        assert i18n.ngettext("%(num)d video", "%(num)d videos", 1) % {"num": 1} == "1 video"
        assert i18n.ngettext("%(num)d video", "%(num)d videos", 3) % {"num": 3} == "3 video's"
    assert i18n.ngettext("%(num)d video", "%(num)d videos", 0) % {"num": 0} == "0 videos"


def test_unknown_locale_falls_back_to_english():
    with i18n.use_locale("fr"):
        assert i18n.current_locale() == "en"


def test_format_date():
    from datetime import date

    assert i18n.format_date(date(2026, 9, 28)) == "Monday 28 September 2026"
    with i18n.use_locale("nl"):
        assert i18n.format_date(date(2026, 9, 28)) == "maandag 28 september 2026"
    with i18n.use_locale("de"):
        assert i18n.format_date(date(2026, 9, 28)) == "Montag, 28. September 2026"


# --------------------------------------------------------------------------- the web app


def _app(tmp_path):
    from fastapi.testclient import TestClient

    from tellybox.web.app import create_app
    from tests.web.conftest import FakeCast, make_config

    config = make_config(tmp_path)
    config.data_dir.mkdir(parents=True)
    config.media_dir.mkdir(parents=True)
    app = create_app(config, cast=FakeCast())

    @app.get("/_locale")
    def locale_probe() -> dict:  # a sync endpoint runs in the thread pool: the locale must follow
        return {"lang": i18n.current_locale(), "library": i18n._("Library")}

    app.router.routes.insert(0, app.router.routes.pop())
    return TestClient(app)


def test_middleware_sets_the_locale_and_headers(tmp_path):
    client = _app(tmp_path)
    r = client.get("/_locale", headers={"Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"})
    assert r.json()["lang"] == "nl"
    assert r.headers["content-language"] == "nl"
    assert "Accept-Language" in r.headers["vary"]
    r = client.get("/_locale")
    assert r.json()["lang"] == "en"
    assert client.get("/healthz").headers.get("content-language") is None  # no Vary on language-free paths


def test_admin_pages_carry_the_language(tmp_path):
    client = _app(tmp_path)
    for header, lang in [("de-DE,de;q=0.9", "de"), ("nl", "nl"), ("en-GB", "en")]:
        r = client.get("/admin/login", headers={"Accept-Language": header})
        assert f'<html lang="{lang}">' in r.text
        assert 'id="i18n"' in r.text


# --------------------------------------------------------------------------- catalogs


def _extracted() -> dict[str | tuple[str, str], set[str]]:
    """Every marked string in the code and templates, as scripts/i18n.sh extracts it."""
    method_map, options_map = parse_mapping_cfg((ROOT / "babel.cfg").open())
    keywords = {"_": None, "gettext": None, "ngettext": (1, 2), "N_": None, "Nn_": (1, 2)}
    found: dict = {}
    for filename, _lineno, message, _comments, _context in extract_from_dir(
        str(ROOT), method_map, options_map, keywords=keywords
    ):
        key = tuple(message) if isinstance(message, tuple) else message
        found.setdefault(key, set()).add(filename)
    return found


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"%\((\w+)\)[sd]", text))


@pytest.mark.parametrize("lang", ["nl", "de"])
def test_every_string_is_translated(lang):
    """NF-13: nothing ships untranslated. Run scripts/i18n.sh, then fill in the .po file."""
    with (ROOT / "tellybox" / "locale" / lang / "LC_MESSAGES" / "messages.po").open("rb") as f:
        po = read_po(f, locale=lang)
    translations = {}
    for m in po:
        if not m.id:
            continue
        key = tuple(m.id) if isinstance(m.id, (list, tuple)) else m.id
        translations[key] = (m.string, m.fuzzy)
    missing, fuzzy, bad_placeholders = [], [], []
    for key, files in sorted(_extracted().items(), key=lambda kv: str(kv[0])):
        if key not in translations:
            missing.append(f"{key!r} ({', '.join(sorted(files))})")
            continue
        string, is_fuzzy = translations[key]
        strings = list(string) if isinstance(string, (list, tuple)) else [string]
        if not all(strings):
            missing.append(f"{key!r} ({', '.join(sorted(files))})")
        elif is_fuzzy:
            fuzzy.append(repr(key))
        else:
            source = key if isinstance(key, tuple) else (key,)
            wanted = set().union(*(_placeholders(s) for s in source))
            for s in strings:
                if _placeholders(s) - wanted or (not isinstance(key, tuple) and _placeholders(s) != wanted):
                    bad_placeholders.append(f"{key!r} -> {s!r}")
    assert not missing, f"{len(missing)} untranslated in {lang} (run scripts/i18n.sh):\n" + "\n".join(missing)
    assert not fuzzy, f"fuzzy in {lang}:\n" + "\n".join(fuzzy)
    assert not bad_placeholders, f"placeholders differ in {lang}:\n" + "\n".join(bad_placeholders)
