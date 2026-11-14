"""Pure parsers for SEC submissions JSON and the 'latest filings' Atom feed."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_NS = {"a": "http://www.w3.org/2005/Atom"}


def pad_cik(cik: int | str) -> str:
    return f"{int(cik):010d}"


@dataclass(frozen=True)
class ParsedFiling:
    cik: str
    accession: str
    form: str
    filed_date: date
    accepted_at_utc: datetime
    primary_document: str
    items: str
    date_basis_differs: bool  # EDGAR filing date != the ET calendar date of acceptance

    @property
    def _folder(self) -> str:
        return f"{ARCHIVES}/{int(self.cik)}/{self.accession.replace('-', '')}"

    @property
    def index_url(self) -> str:
        return f"{self._folder}/{self.accession}-index.htm"

    @property
    def primary_url(self) -> str | None:
        return f"{self._folder}/{self.primary_document}" if self.primary_document else None


@dataclass(frozen=True)
class AtomEntry:
    accession: str
    cik: str
    form: str
    company: str
    filed_date: date
    updated: datetime
    index_url: str


def parse_submissions(data: dict[str, Any]) -> list[ParsedFiling]:
    """Filings from ``filings.recent``. ``acceptanceDateTime`` is UTC and authoritative (verified
    against the filing index in docs/edgar-timing.md); a malformed row is skipped, not fatal."""
    cik = pad_cik(data["cik"])
    rec = data["filings"]["recent"]
    out: list[ParsedFiling] = []
    for i in range(len(rec["accessionNumber"])):
        try:
            accepted = datetime.fromisoformat(rec["acceptanceDateTime"][i].replace("Z", "+00:00"))
            accepted = accepted.astimezone(UTC)
            filed = date.fromisoformat(rec["filingDate"][i])
            items = rec.get("items", [""] * len(rec["accessionNumber"]))[i] or ""
            out.append(
                ParsedFiling(
                    cik=cik,
                    accession=rec["accessionNumber"][i],
                    form=rec["form"][i],
                    filed_date=filed,
                    accepted_at_utc=accepted,
                    primary_document=rec.get("primaryDocument", [""] * len(rec["form"]))[i] or "",
                    items=items,
                    date_basis_differs=accepted.astimezone(NY).date() != filed,
                )
            )
        except (KeyError, ValueError, TypeError, IndexError):
            log.warning("skipping malformed submissions row", extra={"index": i, "cik": cik})
    return out


_TITLE_RE = re.compile(r"^(?P<form>.+?) - (?P<company>.+?) \((?P<cik>\d{10})\)")
_FILED_RE = re.compile(r"Filed:</b>\s*(\d{4}-\d{2}-\d{2})")
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def parse_atom(xml_text: str) -> list[AtomEntry]:
    """Entries of a getcurrent Atom page. The Atom feed carries no labelled acceptance time, so it
    is for discovery only; ``updated`` is kept but never treated as authoritative."""
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"not valid Atom XML: {e}") from e
    out: list[AtomEntry] = []
    for entry in root.findall("a:entry", _NS):
        try:
            title = entry.findtext("a:title", default="", namespaces=_NS)
            m = _TITLE_RE.match(title)
            summary = entry.findtext("a:summary", default="", namespaces=_NS)
            fm = _FILED_RE.search(summary.replace("&lt;", "<").replace("&gt;", ">"))
            acc = (entry.findtext("a:id", default="", namespaces=_NS)).split("accession-number=")[
                -1
            ]
            link = entry.find("a:link", _NS)
            if m is None or fm is None or not _ACCESSION_RE.match(acc) or link is None:
                raise ValueError("unexpected entry shape")
            out.append(
                AtomEntry(
                    accession=acc,
                    cik=m.group("cik"),
                    form=m.group("form"),
                    company=m.group("company"),
                    filed_date=date.fromisoformat(fm.group(1)),
                    updated=datetime.fromisoformat(
                        entry.findtext("a:updated", namespaces=_NS) or ""
                    ),
                    index_url=link.get("href", ""),
                )
            )
        except (ValueError, TypeError):
            log.warning("skipping malformed atom entry")
    return out
