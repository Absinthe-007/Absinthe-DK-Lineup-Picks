/* DK NFL Classic optimizer core. Works in browser (window.DKOpt) and Node (module.exports).
   Requires javascript-lp-solver as `solver`. */
(function (root) {
  const CAP = 50000;
  const ROSTER = { QB: 1, RB: 2, WR: 3, TE: 1, DST: 1 };
  const FLEXPOS = ["RB", "WR", "TE"];

  function gauss() { let u = 0, v = 0; while (!u) u = Math.random(); while (!v) v = Math.random(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }

  function kickTime(k) { // "10/11/2026 04:25PM"
    const m = /(\d+)\/(\d+)\/(\d+) (\d+):(\d+)(AM|PM)/.exec(k || ""); if (!m) return 0;
    let h = +m[4] % 12; if (m[6] === "PM") h += 12; return Date.UTC(+m[3], +m[1] - 1, +m[2], h, +m[5]);
  }

  // pool: [{id,pos,team,opp,salary,pts}] ; opts: see defaults
  function prune(pool, opts) {
    const keep = opts.max ? { QB: 40, RB: 70, WR: 100, TE: 40, DST: 32 } : { QB: 24, RB: 45, WR: 70, TE: 24, DST: 18 };
    const out = [];
    for (const pos of Object.keys(keep)) {
      const ps = pool.filter(p => p.pos === pos && p.pts > 0);
      const byPts = [...ps].sort((a, b) => b.pts - a.pts).slice(0, keep[pos]);
      const byVal = [...ps].sort((a, b) => b.pts / b.salary - a.pts / a.salary).slice(0, Math.ceil(keep[pos] / 2));
      const inGroup = p => (opts.groupMins || []).some(g => g.ids.has(p.id));
      const set = new Set([...byPts, ...byVal, ...ps.filter(p => opts.locked.has(p.id) || opts.teamMins[p.team] || inGroup(p))]);
      out.push(...set);
    }
    return out;
  }

  function buildModel(pool, opts, prevLineups) {
    const constraints = {
      salary: { max: CAP, min: opts.minSalary },
      QB: { equal: 1 }, RB: { min: 2, max: 3 }, WR: { min: 3, max: 4 }, TE: { min: 1, max: opts.allowTEFlex ? 2 : 1 }, DST: { equal: 1 },
      total: { equal: 9 },
    };
    const variables = {}, binaries = {};
    const byTeam = {};
    for (const p of pool) (byTeam[p.team] = byTeam[p.team] || []).push(p);

    for (const p of pool) {
      const v = { pts: p.pts, salary: p.salary, total: 1 }; v[p.pos] = 1;
      if (opts.locked.has(p.id)) { constraints["lock_" + p.id] = { equal: 1 }; v["lock_" + p.id] = 1; }
      variables["p" + p.id] = v; binaries["p" + p.id] = 1;
    }
    const add = (p, c, coef) => { variables["p" + p.id][c] = (variables["p" + p.id][c] || 0) + coef; };

    // QB stacking + bring-back
    if (opts.stackCount > 0 || opts.bringBack) {
      for (const q of pool.filter(p => p.pos === "QB")) {
        const mates = (byTeam[q.team] || []).filter(p => (opts.stackRB ? FLEXPOS : ["WR", "TE"]).includes(p.pos));
        if (opts.stackCount > 0) {
          const c = "stk_" + q.id; constraints[c] = { min: 0 };
          mates.forEach(m => add(m, c, 1)); add(q, c, -opts.stackCount);
        }
        if (opts.bringBack) {
          const c = "bb_" + q.id; constraints[c] = { min: 0 };
          (byTeam[q.opp] || []).filter(p => FLEXPOS.includes(p.pos)).forEach(m => add(m, c, 1)); add(q, c, -1);
        }
      }
    }
    // no offense vs own DST
    if (opts.noOffVsDst) {
      for (const d of pool.filter(p => p.pos === "DST")) {
        const c = "dst_" + d.id; constraints[c] = { max: 8 };
        (byTeam[d.opp] || []).filter(p => p.pos !== "DST").forEach(m => add(m, c, 1)); add(d, c, 8);
      }
    }
    // max players per team
    if (opts.maxPerTeam && opts.maxPerTeam < 8) {
      for (const t of Object.keys(byTeam)) {
        const c = "mt_" + t; constraints[c] = { max: opts.maxPerTeam };
        byTeam[t].filter(p => p.pos !== "DST").forEach(m => add(m, c, 1));
      }
    }
    // team minimums from predictions
    for (const [t, n] of Object.entries(opts.teamMins || {})) {
      if (!n || !byTeam[t]) continue;
      const c = "tmin_" + t; constraints[c] = { min: n };
      byTeam[t].filter(p => p.pos !== "DST").forEach(m => add(m, c, 1));
    }
    // group minimums (e.g. at least N of Claude's sleepers)
    (opts.groupMins || []).forEach((g, gi) => {
      const members = pool.filter(p => g.ids.has(p.id));
      if (!g.min || !members.length) return;
      const c = "grp_" + gi; constraints[c] = { min: Math.min(g.min, members.length) };
      members.forEach(m => add(m, c, 1));
    });
    // uniqueness vs previous lineups
    prevLineups.forEach((L, i) => {
      const c = "u" + i; constraints[c] = { max: 9 - opts.minUnique };
      L.forEach(id => { if (variables["p" + id]) variables["p" + id][c] = 1; });
    });
    return { optimize: "pts", opType: "max", constraints, variables, binaries };
  }

  function arrange(players) { // order into DK slots; latest-kickoff flex-eligible extra goes to FLEX (late-swap friendly)
    const by = pos => players.filter(p => p.pos === pos);
    const qb = by("QB"), dst = by("DST");
    const rb = by("RB"), wr = by("WR"), te = by("TE");
    const extras = [];
    if (rb.length > 2) extras.push(...rb); if (wr.length > 3) extras.push(...wr); if (te.length > 1) extras.push(...te);
    const flexCand = extras.sort((a, b) => kickTime(b.kickoff) - kickTime(a.kickoff))[0];
    const rm = arr => arr.filter(p => p !== flexCand);
    const R = rm(rb), W = rm(wr), T = rm(te);
    return [qb[0], R[0], R[1], W[0], W[1], W[2], T[0], flexCand, dst[0]];
  }

  function* optimizeIter(allPlayers, opts, solver) {
    opts = Object.assign({ n: 20, minSalary: 49000, minUnique: 2, maxExposure: 1, randomness: 0, stackCount: 1, stackRB: false,
      bringBack: false, noOffVsDst: true, maxPerTeam: 4, allowTEFlex: true, useCeiling: 0, locked: new Set(), excluded: new Set(),
      exposure: {}, teamMins: {} }, opts);
    const base = allPlayers.filter(p => !opts.excluded.has(p.id) && (p.proj > 0 || opts.locked.has(p.id)));
    const counts = {}, lineups = [], prev = (opts.prev || []).map(x => x);
    let fails = 0;
    for (let k = 0; k < opts.n && fails < 3; k++) {
      const pool = base.filter(p => {
        const cap = opts.exposure[p.id] != null ? opts.exposure[p.id] : opts.maxExposure;
        return opts.locked.has(p.id) || (counts[p.id] || 0) < Math.max(1, Math.round(cap * opts.n)) || cap >= 1;
      }).map(p => {
        const med = p.proj, cl = p.ceil || p.proj;
        let pts = med * (1 - opts.useCeiling) + cl * opts.useCeiling;
        if (opts.randomness > 0) pts *= Math.max(0, 1 + opts.randomness * gauss());
        return Object.assign({}, p, { pts: Math.round(pts * 100) / 100 });
      });
      const pruned = prune(pool, opts);
      const res = solver.Solve(buildModel(pruned, opts, prev));
      if (!res.feasible) { fails++; k--; if (opts.randomness === 0 && fails) break; continue; }
      const ids = Object.keys(res).filter(k2 => k2[0] === "p" && res[k2] > 0.5).map(k2 => +k2.slice(1));
      if (ids.length !== 9) { fails++; k--; continue; }
      const ps = ids.map(id => allPlayers.find(p => p.id === id));
      const ordered = arrange(ps);
      prev.push(ids); ids.forEach(id => counts[id] = (counts[id] || 0) + 1);
      lineups.push({ players: ordered, salary: ps.reduce((s, p) => s + p.salary, 0), proj: Math.round(ps.reduce((s, p) => s + p.proj, 0) * 100) / 100,
        ceil: Math.round(ps.reduce((s, p) => s + (p.ceil || p.proj), 0) * 10) / 10 });
      yield { lineups, counts, done: false };
    }
    return { lineups, counts, done: true };
  }

  function optimize(allPlayers, opts, solver) {
    const it = optimizeIter(allPlayers, opts, solver); let r;
    do { r = it.next(); } while (!r.done);
    return r.value;
  }

  async function optimizeAsync(allPlayers, opts, solver, onProgress) {
    const it = optimizeIter(allPlayers, opts, solver); let r;
    while (true) {
      r = it.next();
      if (r.done) return r.value;
      if (onProgress) onProgress(r.value.lineups.length);
      await new Promise(res => setTimeout(res, 0));
    }
  }

  function toCSV(lineups) {
    const head = "QB,RB,RB,WR,WR,WR,TE,FLEX,DST";
    return [head, ...lineups.map(L => L.players.map(p => p.id).join(","))].join("\n");
  }

  const api = { optimize, optimizeAsync, toCSV, kickTime, CAP, ROSTER };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.DKOpt = api;
})(typeof window !== "undefined" ? window : globalThis);
