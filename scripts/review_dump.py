import json, re, sys, collections

c = [x for x in json.load(open("data/slice_candidates.json", encoding="utf-8")) if x["meaningful"]]
want = set(sys.argv[1].split(","))
g = collections.OrderedDict()
for x in c:
    ts = [t for t in x["tags"] if t in want]
    if not ts:
        continue
    k = (x["venue"], x["event_title"] or x["title"])
    d = g.setdefault(k, {"n": 0, "vol": 0, "ex": x, "tags": set(), "cat": x.get("category")})
    d["n"] += 1
    d["vol"] += x["vol24"]
    d["tags"].update(ts)
print(len(g), "events", sum(d["n"] for d in g.values()), "markets")
for (v, t), d in sorted(g.items(), key=lambda kv: -kv[1]["vol"]):
    x = d["ex"]
    tg = sorted(d["tags"])[0]
    m = re.search(re.escape(x["tags"][tg]), x["rules"])
    s = x["rules"][max(0, m.start() - 90) : m.end() + 90].replace("\n", " ") if m else ""
    print(
        f"{v[:1]}|{(t or '')[:60]}|n={d['n']}|v={d['vol']:.0f}|{x.get('category') or ''}|{','.join(sorted(d['tags']))}|..{s}.."
    )
