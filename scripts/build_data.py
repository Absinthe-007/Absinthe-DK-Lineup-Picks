#!/usr/bin/env python3
"""Build data/slate.json for the DK Lineup Maker.

Sources (all public):
  * DraftKings lobby + official salary CSV (salaries, player IDs, game info, injury tags)
  * Sleeper projections API (Rotowire stat-line projections) -> converted to DK scoring
  * ESPN Fantasy projections (PPR) + estimated DK bonuses
  * ESPN scoreboard (Vegas spread / total -> implied team totals)
  * data/overrides.json (manual injury/news research layer)

Usage: python3 scripts/build_data.py [--week N]   (week auto-detected from Sleeper if omitted)
Builds every upcoming DraftKings NFL Classic slate into data/slates/<draftGroupId>.json + data/slates/index.json,
and keeps data/slate.json as the default (main) slate.
"""
import argparse, csv, io, json, math, re, sys, unicodedata, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
SEASON = 2026

def get(url, headers=None, as_json=True):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read().decode("utf-8-sig")
    return json.loads(data) if as_json else data

def norm(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[.'`,]", "", n)
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()

TEAM_FIX = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR"}
def tm(t): return TEAM_FIX.get(t, t)

def phi(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def p_over(mean, threshold, sd):
    if mean <= 0: return 0.0
    return 1 - phi((threshold - mean) / sd)

# ---------- DraftKings ----------
def classic_groups():
    lobby = get("https://www.draftkings.com/lobby/getcontests?sport=NFL")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out = []
    for g in lobby["DraftGroups"]:
        if g.get("GameTypeId") != 1 or g.get("ContestTypeId") != 21 or g.get("GameCount", 0) < 2:
            continue
        start = datetime.fromisoformat(g["StartDateEst"].split(".")[0])
        if (start - now).days > 6:
            continue
        suffix = (g.get("ContestStartTimeSuffix") or "").strip().strip("()") or "Main"
        out.append(dict(id=g["DraftGroupId"], name=suffix, start=g["StartDateEst"][:16], games=g["GameCount"],
                        featured=g.get("DraftGroupTag") == "Featured"))
    out.sort(key=lambda g: (g["start"], g["name"] != "Main", -g["games"]))
    return out

def dk_players(dg):
    txt = get(f"https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=21&draftGroupId={dg}", as_json=False)
    rows = list(csv.DictReader(io.StringIO(txt)))
    out = []
    for r in rows:
        gi = r["Game Info"]
        m = re.match(r"(\w+)@(\w+) (\S+) (\S+)", gi)
        away, home, date, time = m.groups() if m else ("", "", "", "")
        team = r["TeamAbbrev"]
        opp = home if team == away else away
        out.append(dict(id=int(r["ID"]), name=r["Name"].strip(), pos=r["Position"], team=team, opp=opp,
                        home=team == home, salary=int(r["Salary"]), game=f"{away}@{home}", kickoff=f"{date} {time}",
                        dkavg=float(r["AvgPointsPerGame"] or 0), status=(r["Status"] or "").strip()))
    return out

# ---------- Sleeper (Rotowire) ----------
def dk_from_stats(s, pos):
    g = lambda k: float(s.get(k) or 0)
    if pos == "DEF":
        pa = g("pts_allow")
        bands = [(0, 0.5, 10), (0.5, 6.5, 7), (6.5, 13.5, 4), (13.5, 20.5, 1), (20.5, 27.5, 0), (27.5, 34.5, -1), (34.5, 99, -4)]
        sd = 9.0
        pa_pts = sum(pts * (phi((hi - pa) / sd) - phi((lo - pa) / sd)) for lo, hi, pts in bands)
        pa_pts += 10 * phi((0 - pa) / sd)
        return (g("sack") + 2 * g("int") + 2 * g("fum_rec") + 6 * (g("def_td") + g("st_td")) +
                2 * g("safe") + 2 * g("blk_kick") + pa_pts)
    pts = (0.04 * g("pass_yd") + 4 * g("pass_td") - g("pass_int") +
           0.1 * g("rush_yd") + 6 * g("rush_td") +
           g("rec") + 0.1 * g("rec_yd") + 6 * g("rec_td") -
           g("fum_lost") + 2 * (g("pass_2pt") + g("rush_2pt") + g("rec_2pt")))
    pts += 3 * p_over(g("pass_yd"), 300, 65)
    pts += 3 * p_over(g("rush_yd"), 100, max(18, 0.45 * g("rush_yd")))
    pts += 3 * p_over(g("rec_yd"), 100, max(18, 0.5 * g("rec_yd")))
    return pts

def sleeper_proj(week):
    """Returns {(name|DST, team, game_date): pts} and {(team, game_date): week}."""
    url = (f"https://api.sleeper.app/projections/nfl/{SEASON}/{week}?season_type=regular"
           "&position%5B%5D=QB&position%5B%5D=RB&position%5B%5D=WR&position%5B%5D=TE&position%5B%5D=DEF")
    out, team_week = {}, {}
    for r in get(url):
        p = r.get("player") or {}
        pos = p.get("position")
        team = tm(r.get("team") or p.get("team") or "")
        if not pos or not team: continue
        date = r.get("date") or ""
        team_week[(team, date)] = week
        pts = dk_from_stats(r.get("stats") or {}, pos)
        key = ("DST" if pos == "DEF" else norm(f"{p.get('first_name','')} {p.get('last_name','')}"), team, date)
        out[key] = round(pts, 2)
        out.setdefault((key[0], team, f"W{week}"), round(pts, 2))
    return out, team_week

# ---------- ESPN ----------
ESPN_TEAMS = {1:"ATL",2:"BUF",3:"CHI",4:"CIN",5:"CLE",6:"DAL",7:"DEN",8:"DET",9:"GB",10:"TEN",11:"IND",12:"KC",13:"LV",14:"LAR",
              15:"MIA",16:"MIN",17:"NE",18:"NO",19:"NYG",20:"NYJ",21:"PHI",22:"ARI",23:"PIT",24:"LAC",25:"SF",26:"SEA",27:"TB",
              28:"WAS",29:"CAR",30:"JAX",33:"BAL",34:"HOU"}
def espn_proj(week):
    flt = {"players": {"filterSlotIds": {"value": [0, 2, 4, 6, 16]},
                       "filterStatsForTopScoringPeriodIds": {"value": 2, "additionalValue": [f"00{SEASON}", f"10{SEASON}", f"11{SEASON}{week}"]},
                       "limit": 1000, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}
    url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{SEASON}/segments/0/leaguedefaults/3?scoringPeriodId={week}&view=kona_player_info"
    d = get(url, {"X-Fantasy-Filter": json.dumps(flt)})
    out = {}
    for e in d.get("players", []):
        p = e["player"]
        team = ESPN_TEAMS.get(p.get("proTeamId"))
        if not team: continue
        proj = next((s.get("appliedTotal") for s in p.get("stats", [])
                     if s.get("scoringPeriodId") == week and s.get("statSourceId") == 1 and s.get("statSplitTypeId") == 1), None)
        if proj is None: continue
        out[("DST" if p.get("defaultPositionId") == 16 else norm(p["fullName"]), team, week)] = proj
    return out

def vegas(dates):
    games = {}
    for dt in dates:
        d = get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={dt}")
        for ev in d.get("events", []):
            c = ev["competitions"][0]
            teams = {x["homeAway"]: tm(x["team"]["abbreviation"]) for x in c["competitors"]}
            odds = (c.get("odds") or [{}])[0]
            total = odds.get("overUnder")
            det = odds.get("details") or ""
            m = re.match(r"(\w+) (-?[\d.]+)", det)
            if not total: continue
            fav, spread = (tm(m.group(1)), abs(float(m.group(2)))) if m else (teams["home"], 0.0)
            fav_tot = total / 2 + spread / 2
            dog_tot = total / 2 - spread / 2
            h, a = teams["home"], teams["away"]
            games[f"{a}@{h}"] = dict(away=a, home=h, total=total, spread=spread, fav=fav,
                                    implied={h: round(fav_tot if fav == h else dog_tot, 1), a: round(fav_tot if fav == a else dog_tot, 1)})
    return games

def current_week():
    try:
        st = get("https://api.sleeper.app/v1/state/nfl")
        return int(st.get("week") or st.get("display_week"))
    except Exception:
        return None

def build_slate(group, sl, team_week, es, adj, week):
    dg = group["id"]
    players = dk_players(dg)
    dates = sorted({datetime.strptime(p["kickoff"].split()[0], "%m/%d/%Y").strftime("%Y%m%d") for p in players})
    games = vegas(dates)
    matched = {"sleeper": 0, "espn": 0}
    for p in players:
        gdate = datetime.strptime(p["kickoff"].split()[0], "%m/%d/%Y").strftime("%Y-%m-%d")
        who = "DST" if p["pos"] == "DST" else norm(p["name"])
        wk = team_week.get((p["team"], gdate), week)
        s = sl.get((who, p["team"], gdate))
        if s is None: s = sl.get((who, p["team"], f"W{wk}"))
        e = es.get((who, p["team"], wk))
        if s is not None: matched["sleeper"] += 1
        if e is not None:
            matched["espn"] += 1
            if p["pos"] != "DST":  # ESPN PPR -> add expected DK yardage bonuses (scaled)
                e = e * 1.04
        srcs, wts = [], []
        if s is not None: srcs.append(s); wts.append(0.5)
        if e is not None: srcs.append(e); wts.append(0.35)
        if p["dkavg"] > 0 and srcs: srcs.append(p["dkavg"]); wts.append(0.15)
        proj = sum(x * w for x, w in zip(srcs, wts)) / sum(wts) if wts else 0.0
        p["src"] = {"sleeper": s, "espn": round(e, 2) if e is not None else None, "dkavg": p["dkavg"]}
        mult, note = 1.0, ""
        if p["status"] in ("O", "IR", "D", "OUT", "PUP", "SUS", "NFI"):
            mult, note = 0.0, f"DK status {p['status']}"
        o = adj.get(norm(p["name"]))
        if o and (not o.get("team") or o["team"] == p["team"]):
            if o.get("proj") is not None and p["status"] not in ("O", "IR"):
                proj = float(o["proj"])  # researched projection override
            mult = mult * o.get("mult", 1.0) if p["status"] not in ("O", "IR") else 0.0
            note = o.get("note", note)
        p["proj"] = round(proj * mult, 2)
        p["note"] = note
        vol = {"QB": 0.45, "RB": 0.6, "WR": 0.75, "TE": 0.75, "DST": 0.8}[p["pos"]]
        p["ceil"] = round(p["proj"] * (1 + vol), 2)
        g = games.get(p["game"])
        p["implied"] = g["implied"].get(p["team"]) if g else None
    return dict(updated=datetime.now(timezone.utc).isoformat(timespec="minutes"), week=week, season=SEASON,
                draftGroupId=dg, slateName=group["name"], start=group["start"],
                games=[games[k] for k in sorted({p["game"] for p in players}) if k in games],
                players=sorted(players, key=lambda p: -p["proj"]), matched=matched,
                sources=["DraftKings salary CSV", "Sleeper/Rotowire projections", "ESPN Fantasy projections",
                         "ESPN/Vegas lines", "Claude's multi-site injury, news & DFS research (overrides.json, picks.json)"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int)
    ap.add_argument("--draft-group", type=int, action="append", help="limit to these draft group IDs")
    a = ap.parse_args()
    week = a.week or current_week()
    if not week: sys.exit("could not detect NFL week; pass --week")
    groups = classic_groups()
    if a.draft_group: groups = [g for g in groups if g["id"] in a.draft_group]
    if not groups: sys.exit("no upcoming DraftKings Classic slates found")
    sl, team_week, es = {}, {}, {}
    for w in (week, week + 1):
        try:
            s1, t1 = sleeper_proj(w); sl.update(s1); team_week.update(t1)
        except Exception as e: print("sleeper failed", w, e, file=sys.stderr)
        try: es.update(espn_proj(w))
        except Exception as e: print("espn failed", w, e, file=sys.stderr)
    ov = json.loads((ROOT / "data/overrides.json").read_text())
    adj = {norm(k): v for k, v in {**ov.get("players", {}), **ov.get("boosts", {})}.items()}
    outdir = ROOT / "data/slates"; outdir.mkdir(parents=True, exist_ok=True)
    index = []
    for g in groups:
        try:
            slate = build_slate(g, sl, team_week, es, adj, week)
        except Exception as e:
            print("slate failed", g, e, file=sys.stderr); continue
        if not slate["players"]:
            print(f"{g['name']} ({g['id']}): no players yet, skipped", file=sys.stderr); continue
        (outdir / f"{g['id']}.json").write_text(json.dumps(slate, separators=(",", ":")))
        index.append(dict(g, players=len(slate["players"]), matched=slate["matched"]))
        print(f"{g['name']} ({g['id']}): {len(slate['players'])} players, matched {slate['matched']}", file=sys.stderr)
        if g["id"] == next((x["id"] for x in groups if x["name"] == "Main"), None):
            (ROOT / "data/slate.json").write_text(json.dumps(slate, separators=(",", ":")))
    # default = first upcoming Main slate, else first slate
    default = next((i["id"] for i in index if i["name"] == "Main"), index[0]["id"] if index else None)
    keep = {f"{i['id']}.json" for i in index}
    for f in outdir.glob("*.json"):
        if f.name != "index.json" and f.name not in keep: f.unlink()
    (outdir / "index.json").write_text(json.dumps(dict(updated=datetime.now(timezone.utc).isoformat(timespec="minutes"),
                                                       week=week, default=default, slates=index), indent=1))

if __name__ == "__main__":
    main()
