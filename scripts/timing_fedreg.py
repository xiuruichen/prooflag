"""F4(b): Federal Register timing check. For recent executive orders (and a sample of other
presidential docs), compare signing date, public-inspection filed_at and official publication
date. Writes data/fedreg_timing.json and prints a summary. Stdlib only; <= 1 req/s."""

from __future__ import annotations

import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

B = "https://www.federalregister.gov/api/v1"
UA = "Prooflag-research/0.1"
ET = ZoneInfo("America/New_York")


def g(path: str, params: dict | None = None) -> dict | None:
    url = B + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    time.sleep(1.0)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"_error": e.code}


def main() -> None:
    eos = []
    page = 1
    while len(eos) < 40:
        d = g(
            "/documents.json",
            {
                "conditions[presidential_document_type][]": "executive_order",
                "order": "newest",
                "per_page": 20,
                "page": page,
                "fields[]": [
                    "document_number",
                    "title",
                    "publication_date",
                    "signing_date",
                    "executive_order_number",
                ],
            },
        )
        assert d and "results" in d, d
        eos += d["results"]
        page += 1
    eos = eos[:40]
    rows = []
    for e in eos:
        full = g(f"/documents/{e['document_number']}.json") or {}
        pi = g(f"/public-inspection-documents/{e['document_number']}.json") or {}
        row = {
            "doc": e["document_number"],
            "eo": e.get("executive_order_number"),
            "signing_date": full.get("signing_date"),
            "publication_date": e["publication_date"],
            "pi_status": "missing" if pi.get("_error") else "present",
            "pi_error": pi.get("_error"),
            "pi_filed_at": pi.get("filed_at"),
            "pi_filing_type": pi.get("filing_type"),
            "pi_publication_date": pi.get("publication_date"),
            "pi_pdf_updated_at": pi.get("pdf_updated_at"),
        }
        rows.append(row)
        print(row, flush=True)
    lead_h, sign_lag_d = [], []
    for r in rows:
        if r["signing_date"]:
            sd = datetime.fromisoformat(r["signing_date"])
            pd = datetime.fromisoformat(r["publication_date"])
            sign_lag_d.append((pd - sd).days)
        if r["pi_filed_at"]:
            f = datetime.fromisoformat(r["pi_filed_at"])
            # official issue date treated as 00:00 ET of publication_date (conservative lower bound)
            pub = datetime.fromisoformat(r["publication_date"]).replace(tzinfo=ET)
            r["pi_lead_hours_to_pubdate_0000ET"] = round((pub - f).total_seconds() / 3600, 1)
            lead_h.append(r["pi_lead_hours_to_pubdate_0000ET"])
    out = {"n": len(rows), "rows": rows}
    out["pi_present"] = sum(r["pi_status"] == "present" for r in rows)
    out["pi_missing_docs"] = [r["doc"] for r in rows if r["pi_status"] == "missing"]
    if lead_h:
        out["lead_hours"] = {
            "n": len(lead_h),
            "min": min(lead_h),
            "median": statistics.median(lead_h),
            "max": max(lead_h),
            "n_negative": sum(h < 0 for h in lead_h),
        }
    if sign_lag_d:
        out["signing_to_publication_days"] = {
            "min": min(sign_lag_d),
            "median": statistics.median(sign_lag_d),
            "max": max(sign_lag_d),
        }
    from pathlib import Path

    Path("data").mkdir(exist_ok=True)
    Path("data/fedreg_timing.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print({k: v for k, v in out.items() if k != "rows"})


if __name__ == "__main__":
    main()
