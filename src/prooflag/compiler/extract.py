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


_MONTHS = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_DATE = re.compile(rf"\b({_MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b")
_TZ = r"(ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|UTC|GMT)"
_TIME = re.compile(
    rf"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([AaPp])\.?[Mm](?![A-Za-z])\.?(?:\s*{_TZ}\b)?",
)
_VAGUE = re.compile(r"\b(end of (the )?day|midnight|close of business|COB|EOD)\b", re.I)
_TITLE_DATE = re.compile(r"date (specified )?in the (market )?title|date in the title", re.I)

_FIXED = {"EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6, "PST": -8, "PDT": -7}
_REGION = {"E": "America/New_York", "C": "America/Chicago", "M": "America/Denver",
           "P": "America/Los_Angeles"}  # fmt: skip


def _zone(token: str) -> tzinfo:
    if token in ("UTC", "GMT"):
        return UTC
    return ZoneInfo(_REGION[token[0]])


@dataclass(frozen=True)
class Deadline:
    # ok | none | date_only | vague_time | naive_timezone | no_date | conflicting | invalid
    # | dst_ambiguous | tz_season_mismatch
    status: str
    utc: datetime | None = None
    tz_original: str | None = None
    span: str | None = None  # the clock-time text as written (with its zone)
    date_text: str | None = None


def extract_deadline(title: str, rules: str) -> Deadline:
    """Parse a clock-time deadline. Anything missing, conflicting or not uniquely defined (naive
    zone, several dates or times, DST gaps/overlaps, wrong-season EST/EDT) is never resolved by
    assumption: the status says why and ``utc`` stays None."""
    dates = list(_DATE.finditer(rules))
    if not dates and _TITLE_DATE.search(rules):
        dates = list(_DATE.finditer(title))
    times = list(_TIME.finditer(rules))
    vague = _VAGUE.search(rules)
    if not dates:
        return Deadline("no_date", span=times[0].group(0).strip()) if times else Deadline("none")
    dm, date_text = dates[0], dates[0].group(0)
    if (
        len({(d.group(1)[:3].lower(), int(d.group(2)), d.group(3)) for d in dates}) > 1
        or len({(t.group(1), t.group(2) or "00", t.group(3).lower(), t.group(4)) for t in times})
        > 1
    ):
        return Deadline("conflicting", date_text=date_text)
    if not times:
        return Deadline("vague_time" if vague else "date_only", date_text=date_text)
    tm = times[0]
    span = tm.group(0).strip()
    tz_token = tm.group(4)
    if tz_token is None:
        return Deadline("naive_timezone", span=span, date_text=date_text)
    hour, minute = int(tm.group(1)) % 12, int(tm.group(2) or 0)
    if tm.group(3).lower() == "p":
        hour += 12
    try:
        day = datetime.strptime(f"{dm.group(1)[:3]} {dm.group(2)} {dm.group(3)}", "%b %d %Y")
    except ValueError:
        return Deadline("invalid", span=span, date_text=date_text)
    naive = day.replace(hour=hour, minute=minute)
    zone = _zone(tz_token)
    first, second = naive.replace(tzinfo=zone, fold=0), naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        return Deadline("dst_ambiguous", tz_original=tz_token, span=span, date_text=date_text)
    if tz_token in _FIXED:
        fixed = timezone(timedelta(hours=_FIXED[tz_token]))
        if first.utcoffset() != timedelta(hours=_FIXED[tz_token]):
            return Deadline(
                "tz_season_mismatch", tz_original=tz_token, span=span, date_text=date_text
            )
        return Deadline(
            "ok", naive.replace(tzinfo=fixed).astimezone(UTC), tz_token, span, date_text
        )
    return Deadline("ok", first.astimezone(UTC), tz_token, span, date_text)


_FORMS = re.compile(
    r"\b(8-K/A|8-K|10-Q/A|10-Q|10-K/A|10-K|S-1/A|S-1|424B\d|20-F|6-K|SC 13[DG]|EFFECT)\b"
    r"|\bForm\s+([345])\b"
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
