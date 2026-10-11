# DK Lineup Maker 🏈

DraftKings NFL **Classic** ($50K cap) lineup optimizer. Static site — runs on GitHub Pages, no server.

**Roster:** QB · RB · RB · WR · WR · WR · TE · FLEX (RB/WR/TE) · DST — always ≤ $50,000.

## What it does
- Builds 1–150 lineups with an exact integer-programming solver (maximizes projected points under the cap).
- **Game Predictions** tab: type your predicted score for any team — its players scale up/down and the opposing DST adjusts. Force "Min N" players from a team.
- **Scenarios:** save several prediction sets ("DET shootout", "CIN blowout") and build across them at once.
- Lock / exclude players, edit any projection, per-player max exposure.
- Stacking (QB + 1/2/3), bring-back, no offense vs. your DST, max per team, min salary, min unique players, randomness, median vs. ceiling.
- **Download DK upload CSV** → DraftKings: Lineups → Upload Lineups. FLEX gets your latest-kickoff flex player for late swap.

## Projections (`data/slate.json`)
Blend of: Sleeper/Rotowire stat-line projections converted to DK scoring (50%), ESPN Fantasy projections (35%), DK season average (15%), then adjusted by `data/overrides.json` (injury/news research). Salaries, IDs and injury tags come from DraftKings' official salary CSV; Vegas lines from ESPN.

## Weekly refresh
```bash
python3 scripts/build_data.py --week 6
```
The GitHub Action (`.github/workflows/refresh.yml`) also runs it on a schedule and can be triggered manually from the Actions tab.

_Projections are estimates, not guarantees. Play responsibly._
