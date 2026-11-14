"""F4(a): EDGAR acceptance-time validation. For recent filings of several CIKs, compare
submissions JSON acceptanceDateTime with the filing index page 'Accepted' stamp and the SGML
header ACCEPTANCE-DATETIME. Stdlib only; <= 2 req/s. Writes data/edgar_timing.json."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = os.environ.get("PROOFLAG_UA", "Prooflag research-bot admin@prooflag.invalid")
ET = ZoneInfo("America/New_York")
CIKS = {
    "Strategy": "0001050446",
    "Apple": "0000320193",
    "NVIDIA": "0001045810",
    "Tesla": "0001318605",
    "Coinbase": "0001679788",
}


def get(url: str) -> str:
    time.sleep(0.6)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def main() -> None:
    rows = []
    for name, cik in CIKS.items():
        sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
        rec = sub["filings"]["recent"]
        picked = 0
        for i, form in enumerate(rec["form"]):
            if picked >= 3:
                break
            if form not in ("8-K", "4", "10-Q", "10-K", "8-K/A"):
                continue
            acc = rec["accessionNumber"][i]
            nodash = acc.replace("-", "")
            idx = get(
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nodash}/{acc}-index.htm"
            )
            m_idx = re.search(r"Accepted</div>\s*<div class=\"info\">([^<]+)<", idx)
            m_fd = re.search(r"Filing Date</div>\s*<div class=\"info\">([^<]+)<", idx)
            hdr = get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nodash}/{acc}.txt")[
                :3000
            ]
            m_hdr = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", hdr)
            api = rec["acceptanceDateTime"][i]
            api_utc = datetime.fromisoformat(api.replace("Z", "+00:00"))
            row = {
                "who": name,
                "acc": acc,
                "form": form,
                "filingDate": rec["filingDate"][i],
                "api_acceptanceDateTime": api,
                "api_as_ET": api_utc.astimezone(ET).isoformat(),
                "index_accepted": m_idx.group(1).strip() if m_idx else None,
                "index_filing_date": m_fd.group(1).strip() if m_fd else None,
                "txt_acceptance_datetime": m_hdr.group(1) if m_hdr else None,
            }
            if row["index_accepted"]:
                ia = datetime.strptime(row["index_accepted"], "%Y-%m-%d %H:%M:%S")
                row["api_vs_index_ET_delta_s"] = (
                    api_utc.astimezone(ET).replace(tzinfo=None) - ia
                ).total_seconds()
            if m_hdr:
                th = datetime.strptime(m_hdr.group(1), "%Y%m%d%H%M%S")
                row["txt_header_vs_api_UTC_delta_s"] = (
                    api_utc.replace(tzinfo=None) - th
                ).total_seconds()
            rows.append(row)
            picked += 1
            print(row, flush=True)
    Path("data").mkdir(exist_ok=True)
    Path("data/edgar_timing.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
