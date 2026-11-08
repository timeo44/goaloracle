import json, requests, collections
H = {"User-Agent": "Mozilla/5.0 goaloracle", "Origin": "https://timeo44.github.io"}
S = "https://site.api.espn.com/apis/site/v2/sports/soccer/{}/summary"
for slug, eid in [("eng.1", "740686"), ("eng.1", None), ("uefa.champions", None)]:
    if eid is None:
        sb = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard", params={"dates": "20261101"}, headers=H, timeout=30).json()
        evs = [e for e in sb.get("events", []) if e["status"]["type"]["completed"]] or [None]
        if not evs[0]:
            sb = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard", params={"dates": "20261022"}, headers=H, timeout=30).json()
            evs = [e for e in sb.get("events", []) if e["status"]["type"]["completed"]]
        eid = evs[0]["id"]
    r = requests.get(S.format(slug), params={"event": eid}, headers=H, timeout=30)
    print("=====", slug, eid, r.status_code, "CORS:", r.headers.get("access-control-allow-origin"), "size", len(r.content))
    j = r.json()
    print("TOP KEYS", list(j.keys()))
    ke = j.get("keyEvents", [])
    print("keyEvents", len(ke), collections.Counter((k.get("type") or {}).get("text") for k in ke))
    for k in ke[:6]:
        print("  KE", json.dumps({x: k.get(x) for x in ("type","text","shortText","clock","team","participants","scoringPlay","period")}, ensure_ascii=False)[:420])
    com = j.get("commentary", [])
    print("commentary", len(com), json.dumps(com[:2], ensure_ascii=False)[:500] if com else "")
    if com:
        types = collections.Counter(((c.get("play") or {}).get("type") or {}).get("text") for c in com)
        print("commentary play types", types.most_common(30))
        corners = [c for c in com if "corner" in (c.get("text") or "").lower()][:2]
        print("corner sample", json.dumps(corners, ensure_ascii=False)[:500])
        var = [c for c in com if "var" in (c.get("text") or "").lower()][:3]
        print("VAR sample", json.dumps(var, ensure_ascii=False)[:600])
    bs = j.get("boxscore", {})
    for t in bs.get("teams", [])[:1]:
        print("BOX stats", [(s.get("name"), s.get("displayValue")) for s in t.get("statistics", [])])
    print("rosters?", len(j.get("rosters", [])), "headToHead?", bool(j.get("headToHeadGames")))
    plays = j.get("plays")
    print("plays", len(plays) if plays else None)
