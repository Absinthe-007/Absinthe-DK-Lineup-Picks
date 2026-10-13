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
- overrides.json applies to every slate (matched by name), so prior-week injury/boost notes leak into the next week's slates. Each run: drop finished-week entries and rewrite notes that cite last week's opponent; give later-week slates a stub picks entry instead of letting a stale "default" apply.
- Anytime-TD prices are a fast tiebreaker for must plays: shortest-priced RB/QB in the highest total are the floor anchors.

## Week 5 (2026) — pre-game notes
- Core: Lions–Cardinals 54.5 total. Must plays Gibbs, Brissett, St. Brown, McBride.
- Sleepers/boom picks: Jameson Williams, Quinshon Judkins, Rome Odunze, Roman Wilson, Tre' Harris, Antonio Williams, Mike Gesicki, Bears DST.
- Update (Sun ~10:50 ET, merged run): per-slate picks restored for all 6 slates.
  - Main/default: must plays Gibbs, Brissett, McBride, St. Brown. Sleepers add Emanuel Wilson (Charbonnet OUT), Courtland Sutton, Bo Nix.
  - Primetime (SNF BAL@ATL + MNF BUF@LAR): must plays Bijan, Josh Allen, Puka. Sleepers Falcons DST vs Huntley, Colby Parkinson (Ferguson IR), Keon Coleman (Palmer OUT), Blake Corum, Kyle Pitts, Khalil Shakir. Fades Flowers, Henry, Ravens DST.
  - Early only: must plays Swift, Chase Brown, Maye, Braelon Allen. Afternoon/Turbo: Gibbs, Brissett, McBride (sleepers J. Williams, E. Wilson, Shaheed, Barner, Tre' Harris, Sutton).
  - Key news: Lamar OUT (Huntley starts), Charbonnet OUT, Nick Bosa OUT, Joshua Palmer OUT, Terrance Ferguson IR, DJ Moore Q.
- 11:40 ET actives: Jefferson, Jeanty, Chase, Higgins ACTIVE; Addison INACTIVE -> Hockenson added as sleeper; Gesicki and Mike Washington Jr. dropped from Early sleepers.
- Mon 10/12 (Mon-Thu slate 154520: MNF BUF@LAR 54.5 + TNF SEA@DEN 41.5): must plays Josh Allen, Kyren Williams, Puka Nacua, Keon Coleman. Core Stafford, Adams, Higbee, E. Wilson, Shakir, Dobbins. Sleepers Kincaid (high), Shaheed (high), Ty Johnson, Higbee, Sutton, Engram, Broncos DST, Kupp. Fades Corum, Parkinson, RJ Harvey, DJ Moore (Q shoulder), Darnold. News: Palmer OUT, Ed Oliver OUT, Moore Q; Charbonnet not playing W6.
- Mon 10/12 deep-research refresh (~2:30-3:15pm ET, 2 subagents, ~50 sources): Classic 154520 must plays Allen, Puka, Kyren (proj trimmed 20.3->18.5 on props), Coleman. Sleepers now Broncos DST (high), Parkinson (returns; was a fade), Kincaid, Barner, Ty Johnson, Engram, Sutton, Holani, Shaheed, Dortch (only if Moore OUT); Higbee/Kupp out of sleepers. New fades Cook (0.9), Waddle (0.75), Nix (proj 12.8), Harvey (0.65). Moore mult 0.45 (~50/50, sources split). TNF line moved to SEA -3 / 40.5. Showdown 154488: CPT Allen + Puka + Kyren ($38,900), core Stafford/Coleman/Mevis/Adams, sleepers Parkinson, Ty Johnson, Bills DST, Knox, Dortch; fades Cook, Corum, Rams DST, Moore, Shakir. Lesson: props-implied pts (SBD/Covers) disagreed most with ESPN/CBS on Higbee, Adams, Kyren; subagent research also surfaced dubious claims (e.g. retired players) - cross-check before using.
- Mon 10/12 Final inactives (6:58pm ET, MNF BUF@LAR): DJ Moore INACTIVE (shoulder; CBS/Rotowire), Palmer + Ed Oliver OUT; Parkinson active. Benefited: Keon Coleman (1.1, de facto WR1), Greg Dortch (proj 5, WR3 snaps), Knox/Kincaid (more 12 personnel), Shakir; rookie Skyler Bell active for debut (Showdown $200 punt). No must-play changes.
- Tue 10/13 (W6 Main 154941, early): sleepers Germie Bernard, Keon Coleman (high), Higbee, Kendre Miller, Kendrick Bourne, Michael Mayer, Kalif Raymond, Hunter Henry, Ravens DST. Site change: "Max points" now keeps Claude's sleepers in (sleepers slider; 0 = pure max), still capped at $50,000.

## Week 5 results (auto-graded 2026-10-13T12:50+00:00)
- Max-points lineup: projected 149.2, scored 173.6 (hindsight optimal 284.8)
- sleepers: Broncos 12.0 (3.75x), AJ Barner 5.0 (1.56x), Evan Engram 9.5 (3.39x), Courtland Sutton 9.8 (2.13x), George Holani 6.1 (1.36x), Rashid Shaheed 4.3 (1.07x)
- Boom players: Isaiah Likely $4300 32.4 pts (proj 12.59), 49ers $2400 18.0 pts (proj 5.21), Drake Maye $6300 42.46 pts (proj 19.05), Packers $2700 18.0 pts (proj 4.69), DeMario Douglas $3500 22.5 pts (proj 7.02), Jameis Winston $4800 29.74 pts (proj 13.51), Jaylen Warren $6700 39.8 pts (proj 20.41), Jets $2700 16.0 pts (proj 7.55), Jayden Daniels $6000 35.26 pts (proj 19.16), Kyle Williams $3100 18.1 pts (proj 4.04)
- Source MAE so far: numberfire 1.455, dff 2.36, props 3.052, sleeper 4.907, blend 5.121, espn 5.287, cbs 5.485, dkavg 5.959, fantasypros 6.828
