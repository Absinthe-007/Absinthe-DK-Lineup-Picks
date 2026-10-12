# DK Lineup Maker 🏈

DraftKings NFL **Classic** and **Showdown Captain Mode** ($50K cap) lineup optimizer. Static site — runs on GitHub Pages, no server.

**Classic roster:** QB · RB · RB · WR · WR · WR · TE · FLEX (RB/WR/TE) · DST — always ≤ $50,000.
**Showdown roster:** CPT + 5 FLEX from one game — any position (QB/RB/WR/TE/K/DST), Captain scores 1.5x and costs his CPT salary, both teams required.

## What it does
- Builds 1–150 lineups with an exact integer-programming solver (maximizes projected points under the cap).
- **Game Predictions** tab: type your predicted score for any team — its players scale up/down and the opposing DST adjusts. Force "Min N" players from a team.
- **Scenarios:** save several prediction sets ("DET shootout", "CIN blowout") and build across them at once.
- Lock / exclude players, edit any projection, per-player max exposure.
- Stacking (QB + 1/2/3), bring-back, no offense vs. your DST, max per team, min salary, min unique players, randomness, median vs. ceiling.
- **Download DK upload CSV** → DraftKings: Lineups → Upload Lineups. FLEX gets your latest-kickoff flex player for late swap.

## Claude's picks & must plays
`data/picks.json` holds Claude's researched **must plays**, core plays, stacks and fades. The app shows them on the Build tab and locks the must plays into (at least) the first 3 lineups — adjustable with the "Lock Claude's must plays" slider.

## Sleepers & boom picks
`picks.json` also lists Claude's **sleepers** (low-owned players with "game of their life" upside). They get a ceiling bump (`ceil_mult` in `overrides.json`), a ✦ in the player table, and the app puts at least one in every lineup after the must-play lineups (slider).

## Learning loop
Every refresh saves a pre-lock snapshot of each slate and Claude's picks in `data/history/w<week>/`. Each Tuesday `scripts/grade.py` scores the week with actual DK points: max-points lineup vs. hindsight optimal, must plays / sleepers / fades, the week's boom players, and each projection source's error. Sources are re-weighted automatically by accuracy, and `data/learnings.md` collects the lessons Claude's research runs use next time.

## Slates
Every upcoming DraftKings **Classic** slate (Main, Sun–Mon, Early, Afternoon, Primetime, Mon–Thu, Thu–…) and every single-game **Showdown** slate is built into `data/slates/` (`"type": "classic"` / `"showdown"`) — pick one from the dropdown at the top (grouped Classic / Showdown).

## Showdown (Captain Mode)
- Player records carry both IDs and salaries: `id`/`salary` (FLEX) and `cptId`/`cptSalary` (CPT, 1.5x) straight from DK's CSV. Kickers are projected too.
- Optimizer (`DKOpt.optimizeShowdown` / `optimizeShowdownAsync`): two binary slots per player, exactly 1 CPT + 5 FLEX, each player once, CPT salary for the Captain, 1.5x Captain points, 1+ player from each team, optional max from one team.
- Options: no K/DST at Captain (default on), Captain QB needs 1+ of his WR/TE (default on), no offense vs. my DST (default off), plus the usual locks, **lock as Captain** (C button), excludes, exposure, min unique, randomness, median/ceiling, min salary.
- Build max points = the single highest-projected legal Showdown lineup, then the next best.
- CSV: `CPT,FLEX,FLEX,FLEX,FLEX,FLEX` with the Captain's CPT ID — upload it to a Showdown contest.
- Claude's picks: `picks.json` → `slates["<showdown draftGroupId>"]` (same shape; falls back to `default`). A must play / sleeper with `"slot": "CPT"` is locked at Captain.

## Projections (`data/slates/*.json`)
Weighted blend (weights renormalize over the sources that cover each player; `p.src` keeps every source's number):

| Source | Key | Start weight | How |
|---|---|---|---|
| Sleeper (Rotowire stat lines) | `sleeper` | 0.20 | stat line → DK scoring incl. 300/100-yd bonus probabilities, DST points-allowed bands, DK kicker scoring |
| ESPN Fantasy | `espn` | 0.15 | PPR projection × 1.04 for DK bonuses (QB/RB/WR/TE/DST/K) |
| FantasyPros consensus | `fantasypros` | 0.17 | weekly ECR rankings pages (`ecrData` → rank-to-points), PPR × 1.04 |
| CBS Sports | `cbs` | 0.10 | stat projections (incl. FB, DST, K) → DK scoring |
| numberFire / FanDuel Research | `numberfire` | 0.12 | public GraphQL stat projections (current week) → DK scoring |
| DailyFantasyFuel | `dff` | 0.10 | DraftKings projections for every classic + showdown slate |
| DK Sportsbook player props (via ESPN odds API) | `props` | 0.10 | yardage / reception / pass-TD / INT / kicking-points lines → implied DK points |
| DK season average | `dkavg` | 0.06 | from the salary CSV |

Every source is fetched in its own try/except (a failure never breaks the build) and per-slate `matched` counts are in `data/slates/index.json`. `grade.py` tracks each source's error weekly in `data/history/source_accuracy.json`, and `tuned_weights()` re-weights any source with 150+ graded players. Then `data/overrides.json` (injury/news research) adjusts. Salaries, IDs and injury tags come from DraftKings' official salary CSV; Vegas lines from ESPN.
Not used: FFToday (database error page), NFL.com projections (page retired), RotoGrinders / Fantasy Footballers (premium / JS-only).

## Refresh
```bash
python3 scripts/build_data.py          # week auto-detected
```
The GitHub Action (`.github/workflows/refresh.yml`) runs daily, before Sunday/Thursday/Monday kickoffs, and whenever `data/overrides.json` or `data/picks.json` changes. Claude's scheduled research runs update those two files.

_Projections are estimates, not guarantees. Play responsibly._
