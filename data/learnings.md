# DK Lineup Maker — learnings log

Running notebook of what worked. `scripts/grade.py` appends auto-graded results every Tuesday (actual DK points
vs. projections, must plays, sleepers, boom players, source accuracy). Claude's research runs read this file first
and add a short "Why" note after each graded week: what the boom players had in common (salary tier, game total,
injury opening, matchup, weather, ownership), which sources were closest, and what to weight differently next time.

## Standing rules (update as evidence builds)
- Highest game total on the slate concentrates ceiling: build the core there, then get different elsewhere.
- Injury openings (starter ruled out late in the week) create the cheapest boom plays: backup RBs and WR2/WR3s.
- Cheap pass catchers on teams with 3+ receivers out are prime "game of their life" candidates.
- Defenses facing rookie/backup QBs or teams with high turnover rates are the best DST punts.
- Late news beats projections: a Sunday-morning "unlikely"/"not expected to play" (Schefter/Rapoport/Fowler) = treat the starter as OUT (mult 0-0.2) and boost the direct backup 1.08-1.15. "Hopeful"/GTD = mult ~0.5-0.65.
- Backup QB starting: boost the opposing DST (1.15+) and the opponent's lead RB (positive script); trim the backup QB's WR/TE (0.88-0.92).
- Must plays must fit one valid lineup with realistic fill-ins: validate with an ILP before publishing; 3-4 max.
- Check article dates: searches often surface prior-season pieces with the same week number (e.g. 2025 Week 5 weather, Athlon sleepers). Verify year and opponent.
- Concurrent research runs overwrite each other (last commit wins). Before uploading, re-read data/picks.json and data/overrides.json from main and merge, never blind-replace; keep per-slate entries under "slates".

## Week 5 (2026) — pre-game notes
- Core: Lions–Cardinals 54.5 total. Must plays Gibbs, Brissett, St. Brown, McBride.
- Sleepers/boom picks: Jameson Williams, Quinshon Judkins, Rome Odunze, Roman Wilson, Tre' Harris, Antonio Williams, Mike Gesicki, Bears DST.
- Update (Sun ~10:50 ET, merged run): per-slate picks restored for all 6 slates.
  - Main/default: must plays Gibbs, Brissett, McBride, St. Brown. Sleepers add Emanuel Wilson (Charbonnet OUT), Courtland Sutton, Bo Nix.
  - Primetime (SNF BAL@ATL + MNF BUF@LAR): must plays Bijan, Josh Allen, Puka. Sleepers Falcons DST vs Huntley, Colby Parkinson (Ferguson IR), Keon Coleman (Palmer OUT), Blake Corum, Kyle Pitts, Khalil Shakir. Fades Flowers, Henry, Ravens DST.
  - Early only: must plays Swift, Chase Brown, Maye, Braelon Allen. Afternoon/Turbo: Gibbs, Brissett, McBride (sleepers J. Williams, E. Wilson, Shaheed, Barner, Tre' Harris, Sutton).
  - Key news: Lamar OUT (Huntley starts), Charbonnet OUT, Nick Bosa OUT, Joshua Palmer OUT, Terrance Ferguson IR, DJ Moore Q.
