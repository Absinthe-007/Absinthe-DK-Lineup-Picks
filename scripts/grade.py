#!/usr/bin/env python3
"""Grade a finished NFL week against what the site projected and picked, so the model keeps learning.

Reads   data/history/w<week>/slate-<id>.json  (pre-lock projection snapshots written by build_data.py)
        data/history/w<week>/picks.json       (Claude's must plays / core / sleepers / fades for that week)
Writes  data/history/w<week>/results.json     (actual DK points, boom players, pick hit rates, max lineup vs optimal)
        data/history/source_accuracy.json     (running projection error per source -> build_data re-weights sources)
        data/learnings.md                     (appends a dated summary; Claude's research runs add the "why")

Usage: python3 scripts/grade.py [--week N]   (default: last completed week from Sleeper state)
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_data import get, norm, tm, SEASON, ROOT  # noqa: E402

HIST = ROOT / "data/history"


def dk_actual(s, pos):
    g = lambda k: float(s.get(k) or 0)
    if pos == "K":
        return round(3 * (g("fgm_0_19") + g("fgm_20_29") + g("fgm_30_39")) + 4 * g("fgm_40_49") + 5 * g("fgm_50p") + g("xpm"), 2)
    if pos == "DEF":
        pa = g("pts_allow")
        pa_pts = 10 if pa == 0 else 7 if pa <= 6 else 4 if pa <= 13 else 1 if pa <= 20 else 0 if pa <= 27 else -1 if pa <= 34 else -4
        return (g("sack") + 2 * g("int") + 2 * g("fum_rec") + 6 * (g("def_td") + g("st_td") + g("def_st_td")) +
                2 * g("safe") + 2 * g("blk_kick") + pa_pts)
    pts = (0.04 * g("pass_yd") + 4 * g("pass_td") - g("pass_int") + 0.1 * g("rush_yd") + 6 * g("rush_td") +
           g("rec") + 0.1 * g("rec_yd") + 6 * g("rec_td") - g("fum_lost") +
           2 * (g("pass_2pt") + g("rush_2pt") + g("rec_2pt")) + 6 * (g("kr_td") + g("pr_td") + g("fum_rec_td")))
    pts += 3 * (g("pass_yd") >= 300) + 3 * (g("rush_yd") >= 100) + 3 * (g("rec_yd") >= 100)
    return round(pts, 2)


def actuals(week):
    url = (f"https://api.sleeper.app/stats/nfl/{SEASON}/{week}?season_type=regular"
           "&position%5B%5D=QB&position%5B%5D=RB&position%5B%5D=WR&position%5B%5D=TE&position%5B%5D=DEF&position%5B%5D=K")
    out = {}
    for r in get(url):
        p = r.get("player") or {}
        pos, team = p.get("position"), tm(r.get("team") or p.get("team") or "")
        if not pos or not team: continue
        who = "DST" if pos == "DEF" else norm(f"{p.get('first_name','')} {p.get('last_name','')}")
        out[(who, team)] = dk_actual(r.get("stats") or {}, pos)
    return out


def best_lineup(players, key):
    """Exact max of `key` under DK Classic rules (SciPy MILP)."""
    import numpy as np
    from scipy.optimize import milp, LinearConstraint, Bounds
    P = [p for p in players if p.get(key) is not None]
    if len(P) < 9: return None
    v = np.array([float(p[key]) for p in P])
    pos = lambda k: np.array([1.0 if p["pos"] == k else 0.0 for p in P])
    A = np.array([[p["salary"] for p in P], pos("QB"), pos("DST"), pos("RB"), pos("WR"), pos("TE"), pos("RB") + pos("WR") + pos("TE")])
    r = milp(-v, constraints=LinearConstraint(A, [0, 1, 1, 2, 3, 1, 7], [50000, 1, 1, np.inf, np.inf, np.inf, 7]),
             integrality=np.ones(len(P)), bounds=Bounds(0, 1))
    if not r.success: return None
    return [P[i] for i in range(len(P)) if r.x[i] > 0.5]


def best_showdown(players, key):
    """Exact max of `key` under DK Showdown rules: 1 CPT (1.5x pts, cptSalary) + 5 FLEX, both teams, $50K."""
    import numpy as np
    from scipy.optimize import milp, LinearConstraint, Bounds
    P = [p for p in players if p.get(key) is not None and p.get("cptSalary")]
    n = len(P)
    if n < 6: return None
    v = np.array([float(p[key]) for p in P])
    eye = np.eye(n)
    A = [np.r_[[p["cptSalary"] for p in P], [p["salary"] for p in P]], np.r_[np.ones(n), np.zeros(n)], np.r_[np.zeros(n), np.ones(n)]]
    lo, hi = [0, 1, 5], [50000, 1, 5]
    for t in {p["team"] for p in P}:
        m = np.array([1.0 if p["team"] == t else 0.0 for p in P]); A.append(np.r_[m, m]); lo.append(1); hi.append(5)
    A = np.vstack(A + [np.hstack([eye, eye])]); lo += [0] * n; hi += [1] * n
    r = milp(-np.r_[1.5 * v, v], constraints=LinearConstraint(A, lo, hi), integrality=np.ones(2 * n), bounds=Bounds(0, 1))
    if not r.success: return None
    cpt = [dict(P[i], cpt=True) for i in range(n) if r.x[i] > 0.5]
    return cpt + [P[i] for i in range(n) if r.x[n + i] > 0.5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int)
    a = ap.parse_args()
    week = a.week
    if not week:
        st = get("https://api.sleeper.app/v1/state/nfl")
        week = int(st["week"]) - 1  # run on Tuesday, after Sleeper rolls to the new week
    wdir = HIST / f"w{week}"
    if not wdir.exists(): sys.exit(f"no snapshots for week {week}")
    act = actuals(week)
    picks = json.loads((wdir / "picks.json").read_text()) if (wdir / "picks.json").exists() else {}
    acc_path = HIST / "source_accuracy.json"
    acc = json.loads(acc_path.read_text()) if acc_path.exists() else {"weeks": [], "sources": {}}
    results = {"week": week, "graded": datetime.now(timezone.utc).isoformat(timespec="minutes"), "slates": []}
    seen_players = set()
    for f in sorted(wdir.glob("slate-*.json")):
        if any((HIST / f"w{w}" / f.name).exists() for w in (week + 1, week + 2)):
            continue  # older builds filed next week's slates under the current week; the real snapshot lives in that week
        sl = json.loads(f.read_text())
        P = sl["players"]
        for p in P:
            p["actual"] = act.get(("DST" if p["pos"] == "DST" else norm(p["name"]), p["team"]))
        played = [p for p in P if p["actual"] is not None]
        if not played: continue
        # source accuracy (each player counted once per week, only if projected > 2 and he played)
        if week not in acc["weeks"]:
            for p in played:
                key = (p["name"], p["team"])
                if key in seen_players or (p.get("proj") or 0) < 2: continue
                seen_players.add(key)
                for src, val in (p.get("src") or {}).items():
                    if val is None: continue
                    s = acc["sources"].setdefault(src, {"abs_err": 0.0, "n": 0})
                    s["abs_err"] += abs(float(val) - p["actual"]); s["n"] += 1
                s = acc["sources"].setdefault("blend", {"abs_err": 0.0, "n": 0})
                s["abs_err"] += abs(p["proj"] - p["actual"]); s["n"] += 1
        boom = sorted([p for p in played if p["actual"] >= 20 or p["actual"] >= 4 * p["salary"] / 1000],
                      key=lambda p: -p["actual"] / (p["salary"] / 1000))[:20]
        name_pk = (picks.get("slates") or {}).get(str(sl["draftGroupId"])) or picks.get("default") or {}
        def grade_list(lst):
            out = []
            for r in lst or []:
                m = next((p for p in P if norm(p["name"]) == norm(r["name"]) and (not r.get("team") or p["team"] == r["team"])), None)
                if m: out.append({"name": m["name"], "salary": m["salary"], "proj": m["proj"], "actual": m["actual"],
                                  "value_x": round((m["actual"] or 0) / (m["salary"] / 1000), 2)})
            return out
        sd = sl.get("type") == "showdown"
        best = best_showdown if sd else best_lineup
        mult = lambda p: 1.5 if p.get("cpt") else 1.0
        sal = lambda p: p["cptSalary"] if p.get("cpt") else p["salary"]
        tag = lambda p: ("CPT " if p.get("cpt") else "") + p["name"]
        mx = best([p for p in P if p.get("proj", 0) > 0], "proj")
        opt = best(played, "actual")
        results["slates"].append({
            "id": sl["draftGroupId"], "name": sl.get("slateName"), "type": sl.get("type", "classic"),
            "maxProjLineup": {"proj": round(sum(p["proj"] * mult(p) for p in mx), 1), "actual": round(sum((p["actual"] or 0) * mult(p) for p in mx), 1),
                              "players": [tag(p) for p in mx]} if mx else None,
            "optimalLineup": {"actual": round(sum(p["actual"] * mult(p) for p in opt), 1), "players": [f"{tag(p)} ${sal(p)}" for p in opt]} if opt else None,
            "mustPlays": grade_list(name_pk.get("mustPlays")), "core": grade_list(name_pk.get("core")),
            "sleepers": grade_list(name_pk.get("sleepers")), "fades": grade_list(name_pk.get("fades")),
            "boomPlayers": [{"name": p["name"], "pos": p["pos"], "team": p["team"], "salary": p["salary"], "proj": p["proj"],
                             "actual": p["actual"], "value_x": round(p["actual"] / (p["salary"] / 1000), 2)} for p in boom],
        })
    if week not in acc["weeks"]: acc["weeks"].append(week)
    for s in acc["sources"].values(): s["mae"] = round(s["abs_err"] / max(s["n"], 1), 3)
    acc_path.write_text(json.dumps(acc, indent=1))
    (wdir / "results.json").write_text(json.dumps(results, indent=1))
    # learnings log
    lines = [f"\n## Week {week} results (auto-graded {results['graded']})"]
    for s in results["slates"]:
        if s["name"] not in ("Main",): continue
        if s["maxProjLineup"]: lines.append(f"- Max-points lineup: projected {s['maxProjLineup']['proj']}, scored {s['maxProjLineup']['actual']} (hindsight optimal {s['optimalLineup']['actual'] if s['optimalLineup'] else '?'})")
        for lab in ("mustPlays", "sleepers"):
            if s[lab]: lines.append(f"- {lab}: " + ", ".join(f"{x['name']} {x['actual']} ({x['value_x']}x)" for x in s[lab]))
        lines.append("- Boom players: " + ", ".join(f"{b['name']} ${b['salary']} {b['actual']} pts (proj {b['proj']})" for b in s["boomPlayers"][:10]))
    lines.append("- Source MAE so far: " + ", ".join(f"{k} {v['mae']}" for k, v in sorted(acc["sources"].items(), key=lambda kv: kv[1]["mae"])))
    with open(ROOT / "data/learnings.md", "a") as fh: fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
