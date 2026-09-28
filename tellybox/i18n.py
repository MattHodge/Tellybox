"""Interface languages (NF-13): English, Dutch and German, chosen from the browser's preferences.

The English text is the message id. Translations live in gettext catalogs,
tellybox/locale/<lang>/LC_MESSAGES/messages.po, read with Babel at first use (no compiled
.mo files, no build step). The language of the current request is a context variable set
by the web app's middleware (`use_locale`); everything here reads it.

    from tellybox.i18n import _, ngettext
    _("Published to the kid app.")
    ngettext("Added %(num)d video", "Added %(num)d videos", n) % {"num": n}

Strings that are defined before a request (module constants, the admin JS string list)
are marked with N_() so extraction finds them, and translated with _() when used.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from functools import cache
from pathlib import Path

from babel.dates import format_date as _babel_format_date
from babel.messages.pofile import read_po

LANGUAGES = ("en", "nl", "de")  # the first is the source language and the fallback
DEFAULT = LANGUAGES[0]
LOCALE_DIR = Path(__file__).parent / "locale"

_current: contextvars.ContextVar[str] = contextvars.ContextVar("tellybox_locale", default=DEFAULT)


# --------------------------------------------------------------------------- choosing a language


def negotiate(accept_language: str | None, supported: tuple[str, ...] = LANGUAGES) -> str:
    """The best supported language for an Accept-Language header; DEFAULT when nothing matches.

    Honours q-values (q=0 means "not this one"); regional variants match their language
    (nl-BE -> nl); on equal q the header's order wins; "*" means the default.
    """
    if not accept_language:
        return DEFAULT
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate(accept_language.split(",")):
        fields = [f.strip() for f in part.split(";")]
        tag = fields[0].lower()
        if not tag:
            continue
        q = 1.0
        for param in fields[1:]:
            name, _sep, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if q <= 0:
            continue
        ranked.append((-q, index, tag))
    for _q, _index, tag in sorted(ranked):
        if tag == "*":
            return DEFAULT
        primary = tag.split("-")[0]
        if primary in supported:
            return primary
    return DEFAULT


def current_locale() -> str:
    return _current.get()


@contextmanager
def use_locale(lang: str) -> Iterator[None]:
    """Translate in `lang` inside the block (the web middleware wraps each request in this)."""
    token = _current.set(lang if lang in LANGUAGES else DEFAULT)
    try:
        yield
    finally:
        _current.reset(token)


# --------------------------------------------------------------------------- catalogs


@cache
def catalog(lang: str) -> dict[str | tuple[str, str], str | tuple[str, ...]]:
    """msgid -> translation for `lang`, from its .po file. Untranslated and fuzzy entries are left out."""
    path = LOCALE_DIR / lang / "LC_MESSAGES" / "messages.po"
    if lang == DEFAULT or not path.is_file():
        return {}
    with path.open("rb") as f:
        po = read_po(f, locale=lang)
    entries: dict = {}
    for message in po:
        if not message.id or message.fuzzy:
            continue
        if isinstance(message.id, (list, tuple)):  # plural: key (singular, plural) -> (forms...)
            forms = tuple(message.string)
            if all(forms):
                entries[(message.id[0], message.id[1])] = forms
        elif message.string:
            entries[message.id] = message.string
    return entries


def _plural_index(n: int) -> int:
    # English, Dutch and German share one rule: singular for exactly one, plural otherwise.
    # A language with more forms would read its catalog's Plural-Forms header here.
    return 0 if n == 1 else 1


def gettext(message: str) -> str:
    lang = _current.get()
    if lang == DEFAULT:
        return message
    translated = catalog(lang).get(message)
    return translated if isinstance(translated, str) else message


def ngettext(singular: str, plural: str, n: int) -> str:
    lang = _current.get()
    forms = catalog(lang).get((singular, plural)) if lang != DEFAULT else None
    if not isinstance(forms, tuple):
        return singular if n == 1 else plural
    index = _plural_index(n)
    return forms[index] if 0 <= index < len(forms) else forms[-1]


_ = gettext


def N_(message: str) -> str:
    """Mark a string for extraction without translating it yet (module constants)."""
    return message


def Nn_(singular: str, plural: str) -> tuple[str, str]:
    """Mark a plural pair for extraction without translating it yet (see js_strings.py)."""
    return singular, plural


# --------------------------------------------------------------------------- formatting


# format_date(..., "day"): a weekday and date, as History's day headings show them. Babel's
# "full" format is right for Dutch and German; English keeps the look it had before (no comma,
# day before month).
_DAY_PATTERNS = {"en": "EEEE d MMMM y"}


def format_date(value: date | datetime, format: str = "day") -> str:
    """A date in the current language: "Monday 28 September 2026", "maandag 28 september 2026",
    "Montag, 28. September 2026". `format` is "day" or a Babel format name or pattern."""
    if isinstance(value, datetime):
        value = value.date()
    lang = _current.get()
    if format == "day":
        format = _DAY_PATTERNS.get(lang, "full")
    return _babel_format_date(value, format=format, locale=lang)
