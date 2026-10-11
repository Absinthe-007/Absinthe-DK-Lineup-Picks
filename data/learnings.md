# DK Lineup Picks — Learnings

Knowledge base for Claude's research runs. Standing rules are edited in place; each week gets a pre-game line and, once graded, a "### Why" note.

## Standing rules (edit, don't just append)

1. **Start where the points are.** Build the core from the highest game total / implied team totals; a game 7+ points above the rest gets most of the must plays.
2. **Late news beats projections.** A Sunday-morning "unlikely"/"not expected to play" (Schefter/Rapoport/Fowler) is treated as OUT for the starter (mult 0-0.15) and a boost for the direct backup (1.08-1.15). "Hopeful"/GTD = mult ~0.6.
3. **Backup QB = boost the opposing DST and RB, cap the receivers.** When a starting QB is out, bump the opposing DST (1.15+), the opponent's lead RB (positive script), and trim the backup's WR/TE (0.88-0.92).
4. **Depleted WR rooms create cheap boom WRs.** When 2+ receivers are out, the next man up under $4,500 is a sleeper (ceil_mult 1.2).
5. **Must plays must fit together** with realistic fill-ins under $50K. Validate with an ILP before publishing; 3-4 must plays max.
6. **Sleepers need a concrete path to a ceiling:** a role change, a depth-chart opening, a high total, or TD regression (high aDOT/red-zone looks with 0 TDs). Prefer ~10% owned or lower.
7. **Check dates.** Search results often surface prior-season articles with the same week number (e.g., 2025 Week 5 weather and Athlon sleepers). Verify the year and the opponent before using a source.

## Source notes

- Sunday-morning NFL.com "injuries to monitor" (Rapoport/Schefter/Fowler) was the best single late-news source.
- FantasyLabs leverage and DK Network chalk/GPP articles are free and give ownership context. 4for4 and Fantasy Footballers are mostly paywalled.
- No graded results yet (data/history/ not created). Once results.json and source_accuracy.json exist, weight sources by accuracy.

## Infrastructure gaps (as of 2026-10-11)

- The site does not yet render or force `sleepers` from picks.json, and build_data.py ignores `ceil_mult`. There is no "Build max points" button and no data/history grading. The data is written in the expected format so it works once those features land.

## Weekly log

### 2026 Week 5

- **Pre-game (2026-10-11, Sun ~10:45 ET):**
  - Main: must plays Gibbs, Brissett, McBride, St. Brown. Core: Warren (Dowdle unlikely), Braelon Allen, Swift, M. Wilson, LaPorta, Goff. Sleepers: Jameson Williams (high), Emanuel Wilson (high, Charbonnet out), Tre' Harris (high, LAC WRs out), Judkins, Sutton, Roman Wilson, Odunze, Bo Nix.
  - Primetime (SNF BAL@ATL + MNF BUF@LAR): must plays Bijan, Josh Allen, Puka. Sleepers: Falcons DST vs Huntley (high), Colby Parkinson (high, Ferguson IR), Keon Coleman, Corum, Pitts, Shakir. Fades: Flowers, Henry, Ravens DST.
  - Early only: must plays Swift, Chase Brown, Maye, Braelon Allen. Afternoon/Turbo: Gibbs, Brissett, McBride.
  - Key news: Lamar OUT (Huntley), Dowdle unlikely, McConkey not expected to play, Charbonnet OUT, Palmer OUT, Ferguson IR, Nick Bosa OUT. Jeanty hopeful (GTD). Jefferson/Addison work out pregame.
- **Graded:** pending (Tuesday).
