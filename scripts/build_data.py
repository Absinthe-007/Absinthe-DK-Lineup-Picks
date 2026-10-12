#!/usr/bin/env python3
"""Build data/slate.json for the DK Lineup Maker.

Sources (all public, no login / API key):
  * DraftKings lobby + official salary CSV (salaries, player IDs, game info, injury tags)
  * Sleeper projections API (Rotowire stat-line projections) -> converted to DK scoring
  * ESPN Fantasy projections (PPR) + estimated DK bonuses
  * FantasyPros expert consensus (ECR rank-to-points), CBS Sports stat projections
  * numberFire / FanDuel Research stat projections, DailyFantasyFuel DraftKings projections
  * DraftKings Sportsbook player props via ESPN (yardage / reception / TD / kicking lines -> DK points)
  * ESPN scoreboard (Vegas spread / total -> implied team totals)
  * data/overrides.json (manual injury/news research layer)

Usage: python3 scripts/build_data.py [--week N]   (week auto-detected from Sleeper if omitted)
Builds every upcoming DraftKings NFL Classic and Showdown slate into data/slates/<draftGroupId>.json +
data/slates/index.json, and keeps data/slate.json as the default (main) slate.
"""
import argparse, csv, io, json, math, re, sys, time, unicodedata, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
SEASON = 2026
# Projection-source weights (renormalized per player over the sources that have him)
SOURCE_WEIGHTS = {"sleeper": 0.2, "espn": 0.15, "fantasypros": 0.17, "cbs": 0.1, "numberfire": 0.12, "dff": 0.1,
                  "props": 0.1, "dkavg": 0.06}
SOURCES = [k for k in SOURCE_WEIGHTS if k != "dkavg"]

def get(url, headers=None, as_json=True, tries=3):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    for attempt in range(tries):  # retry transient network errors / 5xx, never 4xx
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read().decode("utf-8-sig")
            break
        except Exception as e:
            if attempt == tries - 1 or 400 <= getattr(e, "code", 0) < 500: raise
            time.sleep(2 * (attempt + 1))
    return json.loads(data) if as_json else data

def norm(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[.'`,]", "", n).replace("-", " ")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()

TEAM_FIX = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR", "LVR": "LV", "GBP": "GB", "KCC": "KC", "NOS": "NO", "NEP": "NE",
            "SFO": "SF", "TBB": "TB", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
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

def showdown_groups():
    """Single-game Showdown Captain Mode draft groups (GameTypeId 96) starting within 6 days."""
    lobby = get("https://www.draftkings.com/lobby/getcontests?sport=NFL")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out = []
    for g in lobby["DraftGroups"]:
        if g.get("GameTypeId") != 96 or g.get("GameCount") != 1:
            continue
        start = datetime.fromisoformat(g["StartDateEst"].split(".")[0])
        if (start - now).days > 6:
            continue
        name = (g.get("ContestStartTimeSuffix") or "").strip().strip("()").strip() or "Showdown"
        out.append(dict(id=g["DraftGroupId"], name=name, start=g["StartDateEst"][:16], games=1,
                        featured=g.get("DraftGroupTag") == "Featured", type="showdown", contestTypeId=g.get("ContestTypeId") or 96))
    out.sort(key=lambda g: g["start"])
    return out

def dk_showdown_players(dg, ctype=96):
    """Showdown CSV lists every player twice (CPT at 1.5x salary, FLEX): merge into one record with cptId/cptSalary."""
    rows = dk_players(dg, ctype)
    flex = {(r["name"], r["team"], r["pos"]): r for r in rows if r["slot"] == "FLEX"}
    out = []
    for r in rows:
        if r["slot"] != "CPT": continue
        f = flex.get((r["name"], r["team"], r["pos"]))
        if not f: continue
        out.append(dict(f, cptId=r["id"], cptSalary=r["salary"]))
    for p in out: p.pop("slot", None)
    return out

def dk_players(dg, ctype=21):
    txt = get(f"https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId={ctype}&draftGroupId={dg}", as_json=False)
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
        if ctype != 21: out[-1]["slot"] = r["Roster Position"]
    return out

# ---------- Sleeper (Rotowire) ----------
def dk_from_stats(s, pos):
    g = lambda k: float(s.get(k) or 0)
    if pos == "K":  # DK kicker: FG 0-39 3, 40-49 4, 50+ 5, XP 1
        if "kpts" in s: return g("kpts")
        short = g("fgm_0_19") + g("fgm_20_29") + g("fgm_30_39")
        if not short and not g("fgm_40_49") and not g("fgm_50p"): short = g("fgm")
        return 3 * short + 4 * g("fgm_40_49") + 5 * g("fgm_50p") + g("xpm")
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
           "&position%5B%5D=QB&position%5B%5D=RB&position%5B%5D=WR&position%5B%5D=TE&position%5B%5D=DEF&position%5B%5D=K")
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
ESPN_IDS = {}  # ESPN athlete id -> (name key, team, position id); filled by espn_proj, used by props_proj
def espn_proj(week):
    flt = {"players": {"filterSlotIds": {"value": [0, 2, 4, 6, 16, 17]},
                       "filterStatsForTopScoringPeriodIds": {"value": 2, "additionalValue": [f"00{SEASON}", f"10{SEASON}", f"11{SEASON}{week}"]},
                       "limit": 1500, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}
    url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{SEASON}/segments/0/leaguedefaults/3?scoringPeriodId={week}&view=kona_player_info"
    d = get(url, {"X-Fantasy-Filter": json.dumps(flt)})
    out = {}
    for e in d.get("players", []):
        p = e["player"]
        team = ESPN_TEAMS.get(p.get("proTeamId"))
        if not team: continue
        ESPN_IDS[p["id"]] = ("DST" if p.get("defaultPositionId") == 16 else norm(p["fullName"]), team, p.get("defaultPositionId"))
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


# ---------- FantasyPros (expert consensus) & CBS Sports ----------
TEAM_NAMES = {"Arizona":"ARI","Atlanta":"ATL","Baltimore":"BAL","Buffalo":"BUF","Carolina":"CAR","Chicago":"CHI","Cincinnati":"CIN",
    "Cleveland":"CLE","Dallas":"DAL","Denver":"DEN","Detroit":"DET","Green Bay":"GB","Houston":"HOU","Indianapolis":"IND",
    "Jacksonville":"JAX","Kansas City":"KC","Las Vegas":"LV","L.A. Chargers":"LAC","Los Angeles Chargers":"LAC","L.A. Rams":"LAR",
    "Los Angeles Rams":"LAR","Miami":"MIA","Minnesota":"MIN","New England":"NE","New Orleans":"NO","N.Y. Giants":"NYG",
    "New York Giants":"NYG","N.Y. Jets":"NYJ","New York Jets":"NYJ","Philadelphia":"PHI","Pittsburgh":"PIT","San Francisco":"SF",
    "Seattle":"SEA","Tampa Bay":"TB","Tennessee":"TEN","Washington":"WAS"}
def team_from_name(n):
    n = n.strip()
    for k in sorted(TEAM_NAMES, key=len, reverse=True):
        if n.startswith(k): return TEAM_NAMES[k]
    return None

def _read_tables(url):
    import pandas as pd
    html = get(url, as_json=False)
    return pd.read_html(io.StringIO(html))

def _num(v):
    try: return float(v)
    except Exception: return 0.0

def fantasypros_proj(week):
    """FantasyPros expert consensus. The stat-projection tables now show only the top 10 rows without a login, so use the
    weekly ECR rankings pages, which embed every ranked player with ECR-implied points (r2p_pts, PPR) -> DK.
    {(name|DST, team, week): pts}"""
    out = {}
    for pg in ("qb", "ppr-rb", "ppr-wr", "ppr-te", "dst", "k"):
        html = get(f"https://www.fantasypros.com/nfl/rankings/{pg}.php?week={week}", as_json=False)
        m = re.search(r"var ecrData = (\{.*?\});\s*\n", html, re.S)
        if not m: continue
        d = json.loads(m.group(1))
        if str(d.get("week")) != str(week): continue
        for r in d.get("players", []):
            pos, team = r.get("player_position_id"), tm(r.get("player_team_id") or "")
            if r.get("r2p_pts") in (None, "") or not team: continue
            pts = float(r["r2p_pts"])
            who = "DST" if pos == "DST" else norm(r["player_name"])
            out[(who, team, week)] = round(pts if pos in ("DST", "K") else pts * 1.04, 2)  # PPR -> add expected DK bonuses
    return out

def cbs_proj(week):
    """CBS Sports weekly stat projections -> DK points. {(name, team, week): pts}"""
    out = {}
    keymap = {"QB": [("yds  Passing", "pass_yd"), ("td  Touchdow", "pass_td"), ("int  Interce", "pass_int"),
                     ("yds  Rushing", "rush_yd"), ("td  Rushing", "rush_td"), ("fl  Fumbles", "fum_lost")],
              "RB": [("yds  Rushing", "rush_yd"), ("td  Rushing", "rush_td"), ("rec  Recepti", "rec"),
                     ("yds  Receivi", "rec_yd"), ("td  Receivi", "rec_td"), ("fl  Fumbles", "fum_lost")],
              "K": [("1-19  ", "fgm_0_19"), ("20-29  ", "fgm_20_29"), ("30-39  ", "fgm_30_39"), ("40-49  ", "fgm_40_49"),
                    ("50+  ", "fgm_50p"), ("xpm  ", "xpm")]}
    keymap["WR"] = keymap["TE"] = keymap["RB"]
    for pos in ("QB", "RB", "WR", "TE", "K"):
        t = _read_tables(f"https://www.cbssports.com/fantasy/football/stats/{pos}/{SEASON}/{week}/projections/ppr/")[0]
        labels = {c: c[1] for c in t.columns}
        for _, row in t.iterrows():
            raw = re.sub(r"\s+", " ", str(row[t.columns[0]])).strip()
            m = re.match(r".*?\b(QB|RB|FB|WR|TE|K) ([A-Z]{2,3}) (.+?) (QB|RB|FB|WR|TE|K) ([A-Z]{2,3})$", raw)
            if not m: continue
            stats = {}
            for c, lab in labels.items():
                for prefix, key in keymap[pos]:
                    if lab.startswith(prefix) and key not in stats:
                        stats[key] = _num(row[c])
            out[(norm(m.group(3)), tm(m.group(5)), week)] = round(dk_from_stats(stats, pos), 2)
    t = _read_tables(f"https://www.cbssports.com/fantasy/football/stats/DST/{SEASON}/{week}/projections/ppr/")[0]
    col = lambda pre: next((c for c in t.columns if c[1].startswith(pre)), None)
    dmap = {"int": "int  ", "safe": "sfty  ", "sack": "sck  ", "fum_rec": "frec  ", "def_td": "dtd  ", "pts_allow": "pts  "}
    for _, row in t.iterrows():
        team = team_from_name(str(row[t.columns[0]]))
        if not team: continue
        stats = {k: _num(row[col(pre)]) for k, pre in dmap.items() if col(pre) is not None}
        out[("DST", team, week)] = round(dk_from_stats(stats, "DEF"), 2)
    return out

def numberfire_proj():
    """numberFire / FanDuel Research weekly stat projections (current week only) -> DK points.
    Keyed by opponent instead of week: {(name, team, opp): pts}"""
    q = ("query($input: ProjectionsInput!) { getProjections(input: $input) { ... on NflSkill { player { name position } "
         "team { abbreviation } gameInfo { homeTeam { abbreviation } awayTeam { abbreviation } } passingYards passingTouchdowns "
         "interceptionsThrown rushingYards rushingTouchdowns receptions receivingYards receivingTouchdowns fumLost } } }")
    body = json.dumps({"query": q, "variables": {"input": {"type": "PPR", "position": "NFL_SKILL", "sport": "NFL"}}}).encode()
    req = urllib.request.Request("https://fdresearch-api.fanduel.com/graphql", data=body,
                                 headers={**UA, "content-type": "application/json", "origin": "https://www.fanduel.com"})
    for attempt in range(4):  # the endpoint intermittently answers 502
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                rows = json.loads(r.read())["data"]["getProjections"]
            break
        except Exception:
            if attempt == 3: raise
            time.sleep(3 * (attempt + 1))
    out = {}
    for r in rows:
        gi = r.get("gameInfo") or {}
        team = tm((r.get("team") or {}).get("abbreviation") or "")
        h, a = (tm(((gi.get(k) or {}).get("abbreviation") or "")) for k in ("homeTeam", "awayTeam"))
        if not team or not h or not a: continue
        g = lambda k: float(r.get(k) or 0)
        stats = {"pass_yd": g("passingYards"), "pass_td": g("passingTouchdowns"), "pass_int": g("interceptionsThrown"),
                 "rush_yd": g("rushingYards"), "rush_td": g("rushingTouchdowns"), "rec": g("receptions"),
                 "rec_yd": g("receivingYards"), "rec_td": g("receivingTouchdowns"), "fum_lost": g("fumLost")}
        out[(norm(r["player"]["name"]), team, a if team == h else h)] = round(dk_from_stats(stats, "X"), 2)
    return out

def dff_proj():
    """DailyFantasyFuel DraftKings projections for every upcoming classic + showdown slate. {(name|DST, team, week): pts}"""
    base = "https://www.dailyfantasyfuel.com"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = {}
    dates = [d["start_date"] for d in get(f"{base}/data/slates/recent/NFL/draftkings?date={today}&url=")["dates"] if d["start_date"] >= today]
    for dt in dates:
        for sl in get(f"{base}/data/slates/recent/NFL/draftkings?date={dt}&url=").get("slates", []):
            path = "showdown-single-game-projections" if str(sl.get("showdown_flag")) == "1" else "projections"
            html = get(f"{base}/nfl/{path}/draftkings/{dt}?slate={sl['url']}", as_json=False)
            for tr in re.findall(r'<tr class="[^"]*projections-listing[^>]*>', html):
                r = dict(re.findall(r'data-([a-z_0-9]+)=\s*"([^"]*)"', tr))
                pts = _num(r.get("ppg_proj"))
                if pts <= 0 or not r.get("week"): continue
                who = "DST" if r.get("pos") == "DST" else norm(r.get("name", ""))
                out.setdefault((who, tm(r.get("team", "")), int(r["week"])), pts)
    return out

PROP_KEYS = {"Total Passing Yards": "pass_yd", "Total Passing Touchdowns": "pass_td", "Total Passing Interceptions": "pass_int",
             "Total Rushing Yards": "rush_yd", "Total Receiving Yards": "rec_yd", "Total Receptions": "rec",
             "Total Kicking Points": "kpts"}
def props_proj(dates):
    """DraftKings Sportsbook player props (via ESPN's public odds API) -> implied DK points.
    O/U lines are medians: counts get a Poisson mean shift, yardage a small right-skew bump; TDs come from the TD lines
    (passing) or league yards-per-TD rates (rushing/receiving). {(name|DST, team, week): pts}"""
    out = {}
    for dt in dates:
        for ev in get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={dt}").get("events", []):
            if ev.get("status", {}).get("type", {}).get("state") != "pre": continue
            eid, wk = ev["id"], (ev.get("week") or {}).get("number")
            items, page = [], 1
            while True:
                try:
                    d = get(f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{eid}/competitions/{eid}"
                            f"/odds/100/propBets?lang=en&region=us&limit=1000&page={page}")
                except Exception:
                    break  # no props posted for this game yet
                items += d.get("items", [])
                if page >= d.get("pageCount", 1): break
                page += 1
            lines = {}
            for it in items:
                k = PROP_KEYS.get(it.get("type", {}).get("name", "").replace(" (incl. overtime)", ""))
                v = ((it.get("current") or {}).get("target") or {}).get("value")
                m = re.search(r"athletes/(\d+)", (it.get("athlete") or {}).get("$ref", ""))
                if k and v is not None and m: lines.setdefault(int(m.group(1)), {}).setdefault(k, float(v))
            for aid, L in lines.items():
                if aid not in ESPN_IDS: continue
                who, team, pos = ESPN_IDS[aid]
                if "kpts" in L: out[(who, team, wk)] = round(L["kpts"], 2); continue
                if not any(k in L for k in ("pass_yd", "rush_yd", "rec_yd")): continue
                st = {"pass_yd": L.get("pass_yd", 0), "rush_yd": 1.04 * L.get("rush_yd", 0), "rec_yd": 1.04 * L.get("rec_yd", 0)}
                st["pass_td"] = L["pass_td"] + 0.17 if "pass_td" in L else st["pass_yd"] / 160
                st["pass_int"] = L["pass_int"] + 0.19 if "pass_int" in L else st["pass_yd"] / 400
                st["rec"] = L["rec"] + 0.2 if "rec" in L else st["rec_yd"] / (8 if pos == 2 else 12)
                st["rush_td"] = st["rush_yd"] / (100 if pos == 1 else 115)
                st["rec_td"] = st["rec_yd"] / 150
                st["fum_lost"] = 0.05
                out[(who, team, wk)] = round(dk_from_stats(st, "X"), 2)
    return out

def tuned_weights():
    """Re-weight sources by measured accuracy (data/history/source_accuracy.json, written by grade.py).
    Weight ~ 1/MAE^2, blended 50/50 with the defaults once a source has 150+ graded players."""
    w = dict(SOURCE_WEIGHTS)
    try:
        acc = json.loads((ROOT / "data/history/source_accuracy.json").read_text())["sources"]
    except Exception:
        return w
    inv = {k: 1 / max(v["mae"], 0.5) ** 2 for k, v in acc.items() if k in w and v.get("n", 0) >= 150}
    if len(inv) >= 2:
        tot_def = sum(SOURCE_WEIGHTS[k] for k in inv); tot_inv = sum(inv.values())
        for k in inv: w[k] = 0.5 * SOURCE_WEIGHTS[k] + 0.5 * tot_def * inv[k] / tot_inv
    return w

def archive(slate, picks_path, week):
    """Keep a slim pre-lock snapshot of each slate + Claude's picks so grade.py can learn from results."""
    try:
        start = datetime.fromisoformat(slate["start"])
        from zoneinfo import ZoneInfo
        if datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None) >= start:
            return  # slate already locked: keep the last pre-lock snapshot
    except Exception:
        pass
    d = ROOT / f"data/history/w{week}"; d.mkdir(parents=True, exist_ok=True)
    keep = ("id", "name", "team", "pos", "salary", "proj", "ceil", "src", "status", "game", "cptId", "cptSalary")
    slim = dict({k: slate[k] for k in ("draftGroupId", "slateName", "start", "week", "updated")}, type=slate.get("type", "classic"),
                players=[{k: p[k] for k in keep if k in p} for p in slate["players"] if p["proj"] > 0 or p["salary"] >= 4000])
    (d / f"slate-{slate['draftGroupId']}.json").write_text(json.dumps(slim, separators=(",", ":")))
    if picks_path.exists():
        (d / "picks.json").write_text(picks_path.read_text())

def current_week():
    try:
        st = get("https://api.sleeper.app/v1/state/nfl")
        return int(st.get("week") or st.get("display_week"))
    except Exception:
        return None

def _alt(n): return f"{n[0]} {n.split()[-1]}" if n and n != "DST" and " " in n else n

class Source(dict):
    """Projection dict keyed (name|DST, team, week|opp) with a first-initial + last-name fallback (Josh/Joshua Palmer)."""
    def __init__(self, d=None):
        super().__init__(d or {})
        self.alt = {}
        for k, v in self.items():
            ak = (_alt(k[0]),) + k[1:]
            self.alt[ak] = None if ak in self.alt else v  # ambiguous -> no fallback
    def look(self, who, team, key):
        v = self.get((who, team, key))
        return v if v is not None else self.alt.get((_alt(who), team, key))

def project(p, wk, srcs, W, adj):
    """Blend every reachable source for one DK player, then apply DK status + overrides.json. Shared by Classic and Showdown."""
    gdate = datetime.strptime(p["kickoff"].split()[0], "%m/%d/%Y").strftime("%Y-%m-%d")
    who = "DST" if p["pos"] == "DST" else norm(p["name"])
    sl = srcs.get("sleeper") or Source()
    val = {}
    s = sl.look(who, p["team"], gdate)
    val["sleeper"] = s if s is not None else sl.look(who, p["team"], f"W{wk}")
    for k in SOURCES:
        if k == "sleeper": continue
        val[k] = (srcs.get(k) or Source()).look(who, p["team"], p["opp"] if k == "numberfire" else wk)
    if val["espn"] is not None and p["pos"] not in ("DST", "K"):
        val["espn"] = val["espn"] * 1.04  # ESPN PPR -> add expected DK yardage bonuses (scaled)
    # weighted blend of every projection source we could reach (weights renormalize if a source is missing)
    wsum = sum(W[k] for k in SOURCES if val[k] is not None)
    tot = sum(val[k] * W[k] for k in SOURCES if val[k] is not None)
    if p["dkavg"] > 0 and wsum: tot += p["dkavg"] * W["dkavg"]; wsum += W["dkavg"]
    proj = tot / wsum if wsum else 0.0
    p["src"] = {k: (round(v, 2) if v is not None else None) for k, v in val.items()}
    p["src"]["dkavg"] = p["dkavg"]
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
    vol = {"QB": 0.45, "RB": 0.6, "WR": 0.75, "TE": 0.75, "DST": 0.8, "K": 0.6}[p["pos"]]
    p["ceil"] = round(p["proj"] * (1 + vol) * (o.get("ceil_mult", 1.0) if o else 1.0), 2)  # boom/sleeper ceiling bump
    return {k for k, v in val.items() if v is not None}

SOURCE_NAMES = ["DraftKings salary CSV", "Sleeper/Rotowire projections", "ESPN Fantasy projections",
                "FantasyPros expert consensus", "CBS Sports projections", "numberFire/FanDuel Research projections",
                "DailyFantasyFuel projections", "DraftKings Sportsbook player props (via ESPN)", "ESPN/Vegas lines",
                "Claude's multi-site injury, news & DFS research (overrides.json, picks.json)"]

def build_slate(group, srcs, team_week, adj, week):
    W = tuned_weights()
    dg, sd = group["id"], group.get("type") == "showdown"
    players = dk_showdown_players(dg, group.get("contestTypeId", 96)) if sd else dk_players(dg)
    dates = sorted({datetime.strptime(p["kickoff"].split()[0], "%m/%d/%Y").strftime("%Y%m%d") for p in players})
    games = vegas(dates)
    matched = {k: 0 for k in SOURCES}
    wks = []
    for p in players:
        gdate = datetime.strptime(p["kickoff"].split()[0], "%m/%d/%Y").strftime("%Y-%m-%d")
        wk = team_week.get((p["team"], gdate), week); wks.append(wk)
        for k in project(p, wk, srcs, W, adj): matched[k] += 1
        g = games.get(p["game"])
        p["implied"] = g["implied"].get(p["team"]) if g else None
    return dict(updated=datetime.now(timezone.utc).isoformat(timespec="minutes"), week=min(wks or [week]), season=SEASON,
                type="showdown" if sd else "classic", draftGroupId=dg, slateName=group["name"], start=group["start"],
                games=[games[k] for k in sorted({p["game"] for p in players}) if k in games],
                players=sorted(players, key=lambda p: -p["proj"]), matched=matched, sources=SOURCE_NAMES)

def fetch_sources(week, dates):
    """Every projection source, each isolated so one failure never breaks the build."""
    raw = {k: {} for k in SOURCES}
    team_week = {}
    for w in (week, week + 1):
        for k, fn in (("fantasypros", fantasypros_proj), ("cbs", cbs_proj), ("espn", espn_proj)):
            try: raw[k].update(fn(w))
            except Exception as e: print(k, "failed", w, e, file=sys.stderr)
        try:
            s1, t1 = sleeper_proj(w); raw["sleeper"].update(s1); team_week.update(t1)
        except Exception as e: print("sleeper failed", w, e, file=sys.stderr)
    for k, fn in (("numberfire", numberfire_proj), ("dff", dff_proj), ("props", lambda: props_proj(dates))):
        try: raw[k].update(fn())
        except Exception as e: print(k, "failed", e, file=sys.stderr)
    for k, v in raw.items(): print(f"source {k}: {len(v)} projections", file=sys.stderr)
    return {k: Source(v) for k, v in raw.items()}, team_week

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int)
    ap.add_argument("--draft-group", type=int, action="append", help="limit to these draft group IDs")
    a = ap.parse_args()
    week = a.week or current_week()
    if not week: sys.exit("could not detect NFL week; pass --week")
    groups = [dict(g, type="classic") for g in classic_groups()]
    try: groups += showdown_groups()
    except Exception as e: print("showdown lobby failed", e, file=sys.stderr)
    if a.draft_group: groups = [g for g in groups if g["id"] in a.draft_group]
    if not groups: sys.exit("no upcoming DraftKings slates found")
    dates = sorted({(datetime.fromisoformat(g["start"]) + timedelta(days=d)).strftime("%Y%m%d") for g in groups for d in range(5)})
    srcs, team_week = fetch_sources(week, dates)
    ov = json.loads((ROOT / "data/overrides.json").read_text())
    adj = {norm(k): v for k, v in {**ov.get("players", {}), **ov.get("boosts", {})}.items()}
    outdir = ROOT / "data/slates"; outdir.mkdir(parents=True, exist_ok=True)
    index = []
    try: old_index = json.loads((outdir / "index.json").read_text())["slates"]
    except Exception: old_index = []
    main_id = next((x["id"] for x in groups if x["type"] == "classic" and x["name"] == "Main"), None)
    for g in groups:
        try:
            slate = build_slate(g, srcs, team_week, adj, week)
        except Exception as e:
            print("slate failed", g, e, file=sys.stderr)
            prev = next((i for i in old_index if i["id"] == g["id"]), None)
            if prev and (outdir / f"{g['id']}.json").exists(): index.append(prev)  # keep the last good build
            continue
        if not slate["players"]:
            print(f"{g['name']} ({g['id']}): no players yet, skipped", file=sys.stderr); continue
        (outdir / f"{g['id']}.json").write_text(json.dumps(slate, separators=(",", ":")))
        index.append(dict({k: v for k, v in g.items() if k != "contestTypeId"}, players=len(slate["players"]), matched=slate["matched"]))
        archive(slate, ROOT / "data/picks.json", slate["week"])  # snapshot under the slate's own NFL week for grading
        print(f"{g['type']} {g['name']} ({g['id']}): {len(slate['players'])} players, matched {slate['matched']}", file=sys.stderr)
        if g["id"] == main_id:
            (ROOT / "data/slate.json").write_text(json.dumps(slate, separators=(",", ":")))
    # default = first upcoming Main Classic slate, else first Classic slate, else first slate
    classic = [i for i in index if i.get("type", "classic") == "classic"]
    default = next((i["id"] for i in classic if i["name"] == "Main"), (classic or index)[0]["id"] if index else None)
    keep = {f"{i['id']}.json" for i in index}
    for f in outdir.glob("*.json"):
        if f.name != "index.json" and f.name not in keep: f.unlink()
    (outdir / "index.json").write_text(json.dumps(dict(updated=datetime.now(timezone.utc).isoformat(timespec="minutes"),
                                                       week=week, default=default, slates=index), indent=1))

if __name__ == "__main__":
    main()
