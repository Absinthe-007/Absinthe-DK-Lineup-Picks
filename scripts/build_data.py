#!/usr/bin/env python3
"""Build data/slate.json for the DK Lineup Maker.

Sources (all public):
  * DraftKings lobby + official salary CSV (salaries, player IDs, game info, injury tags)
  * Sleeper projections API (Rotowire stat-line projections) -> converted to DK scoring
  * ESPN Fantasy projections (PPR) + estimated DK bonuses
  * ESPN scoreboard (Vegas spread / total -> implied team totals)
  * data/overrides.json (manual injury/news research layer)

Usage: python3 scripts/build_data.py [--week N] [--draft-group ID]
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
def find_main_group():
    lobby = get("https://www.draftkings.com/lobby/getcontests?sport=NFL")
    groups = [g for g in lobby["DraftGroups"] if g.get("GameTypeId") == 1 and g.get("ContestTypeId") == 21]
    groups.sort(key=lambda g: (g["StartDateEst"][:10], -(g.get("DraftGroupTag") == "Featured"), -g["GameCount"]))
    # main slate = earliest date, Featured, no suffix
    for g in groups:
        if g.get("DraftGroupTag") == "Featured" and not (g.get("ContestStartTimeSuffix") or "").strip():
            return g["DraftGroupId"]
    return groups[0]["DraftGroupId"]

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
        # expected points-allowed score via a rough distribution around the mean (sd ~ 9)
        bands = [(0, 0.5, 10), (0.5, 6.5, 7), (6.5, 13.5, 4), (13.5, 20.5, 1), (20.5, 27.5, 0), (27.5, 34.5, -1), (34.5, 99, -4)]
        sd = 9.0
        pa_pts = sum(pts * (phi((hi - pa) / sd) - phi((lo - pa) / sd)) for lo, hi, pts in bands)
        pa_pts += 10 * phi((0 - pa) / sd)  # tail below zero counts as shutout
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
    url = (f"https://api.sleeper.app/projections/nfl/{SEASON}/{week}?season_type=regular"
           "&position%5B%5D=QB&position%5B%5D=RB&position%5B%5D=WR&position%5B%5D=TE&position%5B%5D=DEF")
    out = {}
    for r in get(url):
        p = r.get("player") or {}
        pos = p.get("position")
        team = tm(r.get("team") or p.get("team") or "")
        if not pos or not team: continue
        pts = dk_from_stats(r.get("stats") or {}, pos)
        key = ("DST", team) if pos == "DEF" else (norm(f"{p.get('first_name','')} {p.get('last_name','')}"), team)
        out[key] = round(pts, 2)
    return out

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
        if p.get("defaultPositionId") == 16:
            out[("DST", team)] = proj
        else:
            out[(norm(p["fullName"]), team)] = proj
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--draft-group", type=int)
    a = ap.parse_args()
    dg = a.draft_group or find_main_group()
    print("draft group", dg, file=sys.stderr)
    players = dk_players(dg)
    try: sl = sleeper_proj(a.week)
    except Exception as e: print("sleeper failed", e, file=sys.stderr); sl = {}
    try: es = espn_proj(a.week)
    except Exception as e: print("espn failed", e, file=sys.stderr); es = {}
    dates = sorted({datetime.strptime(p["kickoff"].split()[0], "%m/%d/%Y").strftime("%Y%m%d") for p in players})
    games = vegas(dates)
    ov = json.loads((ROOT / "data/overrides.json").read_text())
    adj = {norm(k): v for k, v in {**ov.get("players", {}), **ov.get("boosts", {})}.items()}

    matched = {"sleeper": 0, "espn": 0}
    for p in players:
        key = ("DST", p["team"]) if p["pos"] == "DST" else (norm(p["name"]), p["team"])
        s, e = sl.get(key), es.get(key)
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
        if o: mult, note = mult * o["mult"] if p["status"] not in ("O", "IR") else 0.0, o.get("note", note)
        p["proj"] = round(proj * mult, 2)
        p["note"] = note
        # ceiling: position-based volatility
        vol = {"QB": 0.45, "RB": 0.6, "WR": 0.75, "TE": 0.75, "DST": 0.8}[p["pos"]]
        p["ceil"] = round(p["proj"] * (1 + vol), 2)
        g = games.get(p["game"])
        p["implied"] = g["implied"].get(p["team"]) if g else None

    slate = dict(updated=datetime.now(timezone.utc).isoformat(timespec="minutes"), week=a.week, season=SEASON,
                 draftGroupId=dg, games=[games[k] for k in sorted({p["game"] for p in players}) if k in games],
                 players=sorted(players, key=lambda p: -p["proj"]), matched=matched,
                 sources=["DraftKings salary CSV", "Sleeper/Rotowire projections", "ESPN Fantasy projections",
                          "ESPN/Vegas lines", "Rotowire, Footballguys, ESPN, Stokastic injury & DFS news (overrides.json)"])
    (ROOT / "data/slate.json").write_text(json.dumps(slate, separators=(",", ":")))
    print(f"{len(players)} players, matched {matched}, {len(slate['games'])} games", file=sys.stderr)

if __name__ == "__main__":
    main()
