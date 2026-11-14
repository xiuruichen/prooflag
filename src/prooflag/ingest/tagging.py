"""Tagging (why a market matched), correlated-cluster assignment, and the watch decision."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from prooflag.ingest.models import RawMarket

# Recall-oriented regexes over rule text; every tag carries the exact matched span as its reason.
DOC_PATTERNS: dict[str, re.Pattern[str]] = {
    "sec": re.compile(
        r"\b(SEC|EDGAR|Securities and Exchange Commission|8-K|10-Q|10-K|Form 4|S-1|424B\d?|"
        r"13D|13G|sec\.gov|prospectus|registration statement)\b"
    ),
    "court": re.compile(
        r"\b(docket|court|ruling|judge|indictment|CourtListener|PACER|lawsuit|verdict|"
        r"Supreme Court|appeals|sentenced|convicted)\b",
        re.I,
    ),
    "fed_register": re.compile(
        r"\b(Federal Register|federalregister\.gov|Code of Federal)\b", re.I
    ),
    "press_release": re.compile(
        r"\b(press release|official announcement|newsroom|investor relations|"
        r"official website|official statement|official blog)\b",
        re.I,
    ),
}
FOMC_RE = re.compile(
    r"\b(FOMC|Fed (decision|decisions|rate|rates|funds)|federal funds rate|"
    r"Fed (increase|decrease)|Fed interest)\b",
    re.I,
)
IPO_RE = re.compile(r"\bIPO\b", re.I)
ISSUER_RE = re.compile(r"\b(Anthropic|OpenAI)\b", re.I)

WEEKLY_EO_SERIES = "KXEOWEEK"  # primary eval source: settles weekly on the Federal Register
EO_TERM_SERIES = "KXEOTRUMPTERM"
DOC_FAMILY_TAGS = {"sec", "fed_register", "court", "weekly_eo", "eo_second_term", "ipo_family"}
_EVENT_DATE_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})$")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1
    )
}


@dataclass(frozen=True)
class Tag:
    tag: str
    reason: str
    span: str | None = None


@dataclass(frozen=True)
class Cluster:
    cluster_id: str
    label: str
    rule: str


def tag_market(m: RawMarket) -> list[Tag]:
    text = " ".join([m.rules_primary, m.rules_secondary, m.resolution_source])
    tags: list[Tag] = []
    for name, pat in DOC_PATTERNS.items():
        hit = pat.search(text)
        if hit:
            tags.append(Tag(name, f"regex:{name}", hit.group(0)))
    headline = f"{m.title} {m.event_title or ''}"
    fomc = FOMC_RE.search(headline)
    if fomc:
        tags.append(Tag("fomc", "headline", fomc.group(0)))
    if m.series_ticker == WEEKLY_EO_SERIES:
        tags.append(Tag("weekly_eo", f"series:{WEEKLY_EO_SERIES}"))
        tags.append(Tag("primary_eval", "weekly executive-order series settles weekly on the FR"))
    if m.series_ticker == EO_TERM_SERIES:
        tags.append(Tag("eo_second_term", f"series:{EO_TERM_SERIES}"))
    issuer = ISSUER_RE.search(headline)
    if issuer and IPO_RE.search(headline):
        tags.append(Tag("ipo_family", "headline", issuer.group(0)))
    return tags


def _week_end(event_id: str | None) -> date | None:
    mt = _EVENT_DATE_RE.search(event_id or "")
    if not mt or mt.group(2) not in _MONTHS:
        return None
    return date(2000 + int(mt.group(1)), _MONTHS[mt.group(2)], int(mt.group(3)))


def assign_cluster(m: RawMarket) -> Cluster:
    """Correlated markets share a cluster so evals and the ledger count them once."""
    names = {t.tag for t in tag_market(m)}
    if "ipo_family" in names:
        return Cluster("issuer_ipo_family", "Anthropic/OpenAI IPO family", "issuer+IPO headline")
    if "weekly_eo" in names:
        end = _week_end(m.event_id) or (m.close_time.date() if m.close_time else None)
        cid = f"weekly_eo:{end.isoformat()}" if end else f"weekly_eo:{m.event_id}"
        return Cluster(cid, f"Executive orders, week ending {end}", f"series:{WEEKLY_EO_SERIES}")
    if "eo_second_term" in names:
        return Cluster(
            "eo_second_term", "Executive orders, second term", f"series:{EO_TERM_SERIES}"
        )
    ev = m.event_id or m.market_id
    return Cluster(f"event:{m.venue}:{ev}", m.event_title or m.title, "same event")


def is_meaningful(m: RawMarket, min_usd: float) -> bool:
    """Real 24h activity only. Kalshi open interest and Polymarket liquidity never count."""
    return m.vol24_usd_est is not None and m.vol24_usd_est >= min_usd


def is_watch_candidate(tags: list[Tag], m: RawMarket, min_usd: float) -> bool:
    names = {t.tag for t in tags}
    if "fomc" in names or not (names & DOC_FAMILY_TAGS):
        return False
    return "primary_eval" in names or is_meaningful(m, min_usd)
