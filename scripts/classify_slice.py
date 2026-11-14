"""Hand-review classification of slice candidates (event-title substring rules written after
reading every candidate event's rule snippet and settlement sources). Unmapped => INCIDENTAL."""

import json, collections, sys

C = json.load(open("data/slice_candidates.json", encoding="utf-8"))
SEC_STRICT = [
    "which bank will lead anthropic",
    "which bank will lead openai",
    "super-voting",
    "what will openai's ipo valuation",
    "what will anthropic's ipo valuation",
    "how much will anthropic raise",
    "what % of anthropic will be sold",
    "eliminate the quarterly reporting",
]
FR_STRICT = [
    "executive orders will trump sign",
    "declares election interference national emergency",
]
CT_STRICT = [
    "ncaa settlement",
    "amazon a monopoly",
    "apple a monopoly",
    "3rd amendment",
    "ballroom injunction",
    "overturn gay marriage",
    "trump's tariffs in",
    "about flag burning",
    "cases will the supreme court agree to hear",
    "ai and copyright",
    "first circuit fully affirms",
    "brigitte macron",
    "national defense information",
    "threat case be dismissed",
    "crypto mining ownership ban",
    "cit strike down",
    "75-country visa",
    "block the fcc",
    "denaturalization case",
    "doj fine nvidia",
]
ANYOF = [
    "officially announce an ipo",
    "official announce an ipo",
    "banks will take anthropic public",
    "bank will take kraken public",
    "next permanent ceo",
    "tesla and spacex merge",
    "q3 earnings call be postponed",
    "gta vi preorders",
    "sign the open weights",
    "one-time layoff",
    "nextera",
    "anthropic ipo by",
    "which companies will commerce add",
    "ban transgender girls",
    "trump win his bbc lawsuit",
    "sue jerome powell",
    "citizenship be revoked",
    "2020 election was fraudulent",
    "2024 election was fraudulent",
    "comey indictment reinstated",
    "biden pardon is void",
    "ftc investigation into ai book",
    "move to revoke ilhan",
]
LEADING = ["marijuana be rescheduled"]
FOMC = ["fed decision", "fed funds rate", "fed rate", "fed decisions", "another fed"]


def fam(t):
    return t


def bucket(x):
    t = ((x["event_title"] or "") + " | " + (x["title"] or "")).lower().replace("’", "'")
    if any(k in t for k in FOMC):
        return "EXCLUDED_FOMC", "-"
    for k in SEC_STRICT:
        if k in t:
            return "DOC_SETTLED_STRICT", "sec"
    for k in FR_STRICT:
        if k in t:
            return "DOC_SETTLED_STRICT", "federal_register"
    for k in CT_STRICT:
        if k in t:
            return "DOC_SETTLED_STRICT", "court/agency"
    for k in ANYOF:
        if k in t:
            return "DOC_SETTLED_ANYOF", "mixed"
    for k in LEADING:
        if k in t:
            return "DOC_LEADING", "federal_register"
    return "INCIDENTAL", "-"


DOCTAGS = {"sec", "court", "fed_register", "press_release"}
seen = set()
rows = []
for x in C:
    k = (x["venue"], x["id"])
    if k in seen:
        continue
    seen.add(k)
    b, f = bucket(x)
    x["bucket"] = b
    x["family"] = f
    x["pass_kalshi_oi_or_vol"] = x["vol24"] >= 1000 or (x["oi"] is not None and x["oi"] >= 2000)
    x["active"] = (
        x["vol24"] >= 1000
    )  # tightened filter: real 24h activity only (no OI-only, no liquidity)
    t = ((x["event_title"] or "") + " " + (x["title"] or "")).lower()
    if ("anthropic" in t or "openai" in t) and "ipo" in t:
        x["cluster"] = "issuer_ipo_family"
    elif "executive orders will trump sign this week" in t:
        x["cluster"] = "weekly_eo:" + (x["event_title"] or "")[-13:]
    elif "executive orders will trump sign" in t:
        x["cluster"] = "eo_second_term"
    else:
        x["cluster"] = (x["venue"], x["event_title"])
    x["poly_liq_only"] = (
        x["venue"] == "polymarket" and x["vol24"] < 1000 and (x["liquidity"] or 0) >= 2000
    )
    rows.append(x)
out = collections.defaultdict(lambda: [set(), 0, 0])  # events, markets, poly_liq_only_markets
for x in rows:
    key = (x["bucket"], x["family"])
    if x["meaningful"]:
        out[key][0].add((x["venue"], x["event_title"]))
        out[key][1] += 1
    if x["poly_liq_only"]:
        out[key][2] += 1
print(
    "bucket | family | events | markets(vol24>=1000 or Kalshi OI>=2000) | +poly liquidity-only markets"
)
for (b, f), (ev, m, pl) in sorted(out.items()):
    print(f"{b} | {f} | {len(ev)} | {m} | {pl}")
for b in ("DOC_SETTLED_STRICT", "DOC_SETTLED_ANYOF", "DOC_LEADING"):
    ev = set()
    m = 0
    for x in rows:
        if x["bucket"] == b and x["meaningful"]:
            ev.add((x["venue"], x["event_title"]))
            m += 1
    print("TOTAL", b, "events", len(ev), "markets", m)
    act = [x for x in rows if x["bucket"] == b and x["active"]]
    print(
        "   TIGHT(vol24>=1000):",
        len(act),
        "markets,",
        len({x["cluster"] if isinstance(x["cluster"], str) else x["cluster"] for x in act}),
        "clusters; by family",
        dict(collections.Counter(x["family"] for x in act)),
    )
    if "-v" in sys.argv:
        for e in sorted(ev):
            print("   ", e)
json.dump(rows, open("data/slice_classified.json", "w", encoding="utf-8"), indent=1)
