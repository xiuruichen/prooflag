# ruff: noqa: RUF001
"""Deterministic extraction (dates/timezones, form lexicon) and the verbatim span verifier."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

_QUOTES = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
    }
)


def normalize_text(s: str) -> str:
    """Canonical form for verbatim checks: NFKC, straight quotes and dashes, one space."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).translate(_QUOTES)).strip()


def verify_span(span: str, corpus: str) -> bool:
    n = normalize_text(span)
    return bool(n) and n in normalize_text(corpus)


_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b")
_TZ = r"(ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|UTC|GMT)"
_TIME = re.compile(
    rf"\b(\d{{1,2}})(?::(\d{{2}}))?\s*([AaPp])\.?[Mm]\.?(?:\s*{_TZ}\b)?",
)
_VAGUE = re.compile(r"\b(end of (the )?day|midnight|close of business|COB|EOD)\b", re.I)
_TITLE_DATE = re.compile(r"date (specified )?in the (market )?title|date in the title", re.I)

_FIXED = {"EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6, "PST": -8, "PDT": -7}
_ZONES = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
}


def _tz(token: str) -> tzinfo:
    if token in _ZONES:
        return ZoneInfo(_ZONES[token])
    if token in _FIXED:
        return timezone(timedelta(hours=_FIXED[token]))
    return UTC


@dataclass(frozen=True)
class Deadline:
    status: str  # ok | none | date_only | vague_time | naive_timezone | no_date
    utc: datetime | None = None
    tz_original: str | None = None
    span: str | None = None  # the clock-time text as written (with its zone)
    date_text: str | None = None


def extract_deadline(title: str, rules: str) -> Deadline:
    """Parse a clock-time deadline. A time without a zone, or a date without a time, is never
    completed by assumption: the status says what is missing and ``utc`` stays None."""
    dm = _DATE.search(rules)
    if dm is None and _TITLE_DATE.search(rules):
        dm = _DATE.search(title)
    tm = _TIME.search(rules)
    vague = _VAGUE.search(rules)
    if dm is None:
        return Deadline("no_date", span=tm.group(0).strip()) if tm else Deadline("none")
    date_text = dm.group(0)
    if tm is None:
        return Deadline("vague_time" if vague else "date_only", date_text=date_text)
    span = tm.group(0).strip()
    tz_token = tm.group(4)
    if tz_token is None:
        return Deadline("naive_timezone", span=span, date_text=date_text)
    hour, minute = int(tm.group(1)) % 12, int(tm.group(2) or 0)
    if tm.group(3).lower() == "p":
        hour += 12
    day = datetime.strptime(f"{dm.group(1)} {dm.group(2)} {dm.group(3)}", "%B %d %Y")
    local = day.replace(hour=hour, minute=minute, tzinfo=_tz(tz_token))
    return Deadline("ok", local.astimezone(UTC), tz_token, span, date_text)


_FORMS = re.compile(
    r"\b(8-K/A|8-K|10-Q|10-K|S-1/A|S-1|424B\d|20-F|6-K|SC 13[DG]|EFFECT)\b|\bForm\s+([345])\b"
)


def extract_forms(text: str) -> list[str]:
    out: list[str] = []
    for m in _FORMS.finditer(text):
        f = m.group(1) or m.group(2)
        if f not in out:
            out.append(f)
    return out


_PUBLICATION = re.compile(
    r"\b(?:filed|published|posted|reported|announced|disclosed)\b[^.;]{0,40}?"
    r"\b(?:on or before|no later than|before|by)\b",
    re.I,
)


def publication_phrase(rules: str) -> str | None:
    """The rules attach the deadline to a filing/publication event, e.g. 'filed on or before'."""
    m = _PUBLICATION.search(rules)
    return m.group(0) if m else None
