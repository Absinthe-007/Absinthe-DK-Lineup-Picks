/* DK Lineup Maker UI */
(() => {
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const fmt$ = n => "$" + n.toLocaleString();
  const store = {
    get(k, d) { try { const v = localStorage.getItem("dklm_" + k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem("dklm_" + k, JSON.stringify(v)); } catch {} },
  };

  let slate, players = [], vegas = {}, gameOf = {}, slateIndex = null, picksAll = null, picks = null, mustIds = [], coreIds = [], sleeperIds = [];
  let isSD = false, cptPickIds = new Set(); // showdown slate; Claude's picks tagged "slot": "CPT"
  let S; // per-week state
  let lineups = [];
  let sort = { key: "adj", dir: -1 }, posF = "ALL";

  function freshState() {
    return { edits: {}, locked: [], lockedCpt: [], excluded: [], exposure: {}, teamScores: {}, teamMins: {}, scenarios: {}, scenPick: [] };
  }
  const save = () => store.set("state_" + slate.draftGroupId, S);

  // ---------- projections with predictions ----------
  function teamFactor(p, scores) {
    if (p.pos === "DST") {
      const g = gameOf[p.team]; if (!g) return 1;
      const oppV = g.implied[p.opp], oppM = scores[p.opp];
      if (oppM == null || oppV == null) return 1;
      return Math.max(0.15, 1 - 0.045 * (oppM - oppV));
    }
    const v = p.implied, m = scores[p.team];
    if (m == null || !v) return 1;
    return Math.max(0, Math.pow(Math.max(m, 0) / v, 0.9));
  }
  function adjusted(p, st = S) {
    if (st.edits[p.id] != null) { const e = +st.edits[p.id]; return { adj: e, ceil: p.proj ? e * p.ceil / p.proj : e * 1.6 }; }
    const f = teamFactor(p, st.teamScores);
    return { adj: Math.round(p.proj * f * 100) / 100, ceil: Math.round(p.ceil * f * 100) / 100 };
  }

  // ---------- load ----------
  const getJSON = async url => { const r = await fetch(url + "?v=" + Date.now()); if (!r.ok) throw new Error(url + " " + r.status); return r.json(); };
  async function load() {
    try { slateIndex = await getJSON("data/slates/index.json"); } catch { slateIndex = null; }
    try { picksAll = await getJSON("data/picks.json"); } catch { picksAll = null; }
    const sel = $("#slatePick");
    if (slateIndex && slateIndex.slates.length) {
      const opt = x => {
        const d = new Date(x.start + ":00-04:00"), when = `${d.toLocaleDateString([], { weekday: "short" })} ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
        return `<option value="${x.id}">${x.name} · ${x.type === "showdown" ? "Showdown" : x.games + " games"} · ${when}</option>`;
      };
      const cl = slateIndex.slates.filter(x => x.type !== "showdown"), sd = slateIndex.slates.filter(x => x.type === "showdown");
      sel.innerHTML = sd.length ? `<optgroup label="Classic">${cl.map(opt).join("")}</optgroup><optgroup label="Showdown · single game">${sd.map(opt).join("")}</optgroup>`
        : cl.map(opt).join("");
      const saved = store.get("slate", null);
      sel.value = slateIndex.slates.some(x => x.id === saved) ? saved : slateIndex.default;
      sel.onchange = () => { store.set("slate", +sel.value); loadSlate(+sel.value); };
      await loadSlate(+sel.value);
    } else {
      sel.hidden = true;
      await loadSlate(null);
    }
  }
  async function loadSlate(id) {
    slate = id ? await getJSON(`data/slates/${id}.json`) : await getJSON("data/slate.json");
    players = slate.players; vegas = {};
    isSD = slate.type === "showdown"; document.body.classList.toggle("showdown", isSD);
    if (!isSD && posF === "K") { posF = "ALL"; $$("#posFilter button").forEach(b => b.classList.toggle("active", b.dataset.pos === "ALL")); }
    slate.games.forEach(g => { vegas[g.away] = g; vegas[g.home] = g; });
    gameOf = vegas;
    S = Object.assign(freshState(), store.get("state_" + slate.draftGroupId, {}));
    lineups = []; renderLineups();
    const upd = new Date(slate.updated);
    $("#slateMeta").textContent = `NFL ${slate.season} · Week ${slate.week} · ${slate.slateName || "Main"} ${isSD ? "Showdown (Captain Mode)" : "slate · " + slate.games.length + " games"} · ${players.length} players · updated ${upd.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}`;
    $("#sources").textContent = "Sources: " + slate.sources.join(" · ");
    resolvePicks();
    bindSettings(); renderGames(); renderPlayers(); renderScen(); renderValue(); renderPicks();
  }

  // ---------- Claude's picks ----------
  const nm = s => (s || "").toLowerCase().normalize("NFKD").replace(/[^a-z0-9 ]/g, "").replace(/\b(jr|sr|ii|iii|iv)\b/g, "").replace(/\s+/g, " ").trim();
  function findPlayer(ref) {
    if (ref.id) { const p = players.find(x => x.id === ref.id); if (p) return p; }
    const n = nm(ref.name);
    return players.find(x => nm(x.name) === n && (!ref.team || x.team === ref.team)) ||
           (ref.pos === "DST" ? players.find(x => x.pos === "DST" && x.team === ref.team) : null);
  }
  function resolvePicks() {
    picks = null; mustIds = []; coreIds = []; sleeperIds = []; cptPickIds = new Set();
    if (!picksAll) return;
    const sl = picksAll.slates || {};
    picks = sl[String(slate.draftGroupId)] || sl[slate.slateName] || picksAll.default || null;
    if (!picks) return;
    mustIds = (picks.mustPlays || []).map(findPlayer).filter(p => p && p.proj > 0).map(p => p.id);
    coreIds = (picks.core || []).map(findPlayer).filter(Boolean).map(p => p.id);
    sleeperIds = (picks.sleepers || []).map(findPlayer).filter(p => p && p.proj > 0).map(p => p.id);
    if (isSD) [...(picks.mustPlays || []), ...(picks.sleepers || [])].filter(r => r.slot === "CPT").map(findPlayer).forEach(p => p && cptPickIds.add(p.id));
  }
  function renderPicks() {
    const card = $("#picksCard");
    if (!picks) { card.hidden = true; return; }
    card.hidden = false;
    $("#picksUpdated").textContent = picksAll.updated ? "Researched " + new Date(picksAll.updated).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }) : "";
    const row = (ref, tag) => {
      const p = findPlayer(ref);
      return `<div class="pickrow"><span class="pos ${p ? p.pos : ref.pos || "FLEX"}">${p ? p.pos : ref.pos || "?"}</span>
        <div><b>${p ? p.name : ref.name}</b> <span class="muted small">${p ? p.team + (p.home ? " vs " : " @ ") + p.opp : ref.team || ""}</span>${isSD && ref.slot === "CPT" ? ' <span class="pos CPT">CPT</span>' : ""}${tag || ""}<div class="why">${ref.why || ""}</div></div>
        <span class="sal">${p ? fmt$(isSD && ref.slot === "CPT" ? p.cptSalary : p.salary) + " · " + adjusted(p).adj.toFixed(1) : "not on slate"}</span></div>`;
    };
    const must = picks.mustPlays || [], core = picks.core || [], fades = picks.fades || [], stacks = picks.stacks || [], sleepers = picks.sleepers || [];
    $("#picksBody").innerHTML =
      (must.length ? `<h3>Must plays · locked into lineups 1–${$("#optMust").value}</h3>` + must.map(r => row(r)).join("") : "") +
      (core.length ? `<h3>Core plays</h3>` + core.map(r => row(r)).join("") : "") +
      (sleepers.length ? `<h3>Sleepers & boom candidates · at least ${$("#optSleep").value} per lineup after the must plays</h3>` + sleepers.map(r => row(r, r.boom ? ' <span class="chip boom">boom ' + r.boom + '</span>' : "")).join("") : "") +
      (stacks.length ? `<h3>Stacks</h3><div class="chips">${stacks.map(x => `<span class="chip">${x}</span>`).join("")}</div>` : "") +
      (fades.length ? `<h3>Fades</h3><div class="chips">${fades.map(x => `<span class="chip fade" title="${(x.why || "").replace(/"/g, "&quot;")}">${x.name || x}</span>`).join("")}</div>` : "") +
      (picks.notes ? `<p class="picknote">${picks.notes.replace(/</g, "&lt;")}</p>` : "");
  }

  // ---------- settings ----------
  let settingsBound = false;
  function bindSettings() {
    if (settingsBound) return; settingsBound = true;
    const saved = store.get("settings", {});
    const ids = ["optMode", "optSleep", "optMust", "optN", "optMinSal", "optUnique", "optExp", "optRand", "optCeil", "optStack", "optStackRB", "optBB", "optDst", "optTEFlex", "optMaxTeam",
      "optSdNoKDst", "optSdQbStack", "optSdDst", "optSdMaxTeam"];
    ids.forEach(id => {
      const el = $("#" + id);
      if (saved[id] != null) el.type === "checkbox" ? (el.checked = saved[id]) : (el.value = saved[id]);
      el.addEventListener("input", () => { saved[id] = el.type === "checkbox" ? el.checked : el.value; store.set("settings", saved); outs(); });
    });
    const outs = () => {
      $("#nOut").textContent = $("#optN").value;
      $("#minSalOut").textContent = fmt$(+$("#optMinSal").value);
      $("#expOut").textContent = $("#optExp").value + "%";
      $("#randOut").textContent = $("#optRand").value + "%";
      $("#mustOut").textContent = $("#optMust").value;
      $("#sleepOut").textContent = $("#optSleep").value;
      const isMax = $("#optMode").value === "max";
      $("#maxNote").hidden = !isMax; document.body.classList.toggle("maxmode", isMax);
      if (picks) renderPicks();
    };
    outs();
  }
  function readOpts() {
    if (isSD) {
      if ($("#optMode").value === "max") // pure max points under DK Showdown rules only
        return { n: +$("#optN").value, minSalary: 0, minUnique: 1, maxExposure: 1, randomness: 0, useCeiling: 0, maxPerTeam: 5,
          noKDstCpt: false, cptQbStack: false, noOffVsDst: false, max: true };
      return { n: +$("#optN").value, minSalary: +$("#optMinSal").value, minUnique: +$("#optUnique").value,
        maxExposure: +$("#optExp").value / 100, randomness: +$("#optRand").value / 100, useCeiling: +$("#optCeil").value,
        maxPerTeam: +$("#optSdMaxTeam").value, noKDstCpt: $("#optSdNoKDst").checked, cptQbStack: $("#optSdQbStack").checked, noOffVsDst: $("#optSdDst").checked };
    }
    if ($("#optMode").value === "max") {
      // Pure max points: maximize total projection under the cap, nothing else
      return { n: +$("#optN").value, minSalary: 0, minUnique: 1, maxExposure: 1, randomness: 0, useCeiling: 0,
        stackCount: 0, stackRB: false, bringBack: false, noOffVsDst: false, allowTEFlex: true, maxPerTeam: 8, max: true };
    }
    return {
      n: +$("#optN").value, minSalary: +$("#optMinSal").value, minUnique: +$("#optUnique").value,
      maxExposure: +$("#optExp").value / 100, randomness: +$("#optRand").value / 100, useCeiling: +$("#optCeil").value,
      stackCount: +$("#optStack").value, stackRB: $("#optStackRB").checked, bringBack: $("#optBB").checked,
      noOffVsDst: $("#optDst").checked, allowTEFlex: $("#optTEFlex").checked, maxPerTeam: +$("#optMaxTeam").value,
    };
  }

  // ---------- games ----------
  function renderGames() {
    const g = $("#gamesGrid"); g.innerHTML = "";
    for (const gm of slate.games) {
      const kick = players.find(p => p.game === `${gm.away}@${gm.home}`)?.kickoff?.split(" ").slice(1).join(" ") || "";
      const div = document.createElement("div"); div.className = "game";
      div.innerHTML = `<div class="meta">${gm.away} @ ${gm.home} · ${kick} · O/U ${gm.total} · ${gm.fav} -${gm.spread}</div>` +
        [gm.away, gm.home].map(t => {
          const v = gm.implied[t], m = S.teamScores[t];
          const cls = m == null ? "" : m > v ? "up" : m < v ? "down" : "";
          return `<div class="team"><b>${t}</b><span class="vg">Vegas ${v} <span class="${cls}">${m != null && m !== v ? (m > v ? "▲" : "▼") : ""}</span></span>
            <input type="number" step="0.5" min="0" data-team="${t}" value="${m ?? v}" title="Your predicted points">
            <select data-min="${t}" title="Min players from ${t}">${[0, 1, 2, 3, 4].map(n => `<option value="${n}" ${+(S.teamMins[t] || 0) === n ? "selected" : ""}>${n ? "Min " + n : "Any"}</option>`).join("")}</select></div>`;
        }).join("");
      g.appendChild(div);
    }
    g.querySelectorAll("input[data-team]").forEach(inp => inp.addEventListener("change", () => {
      const t = inp.dataset.team, v = vegas[t].implied[t], val = parseFloat(inp.value);
      if (isNaN(val) || val === v) delete S.teamScores[t]; else S.teamScores[t] = val;
      save(); renderGames(); renderPlayers(); renderValue();
    }));
    g.querySelectorAll("select[data-min]").forEach(sel => sel.addEventListener("change", () => {
      const n = +sel.value; if (n) S.teamMins[sel.dataset.min] = n; else delete S.teamMins[sel.dataset.min]; save();
    }));
  }
  $("#resetGames").onclick = () => { S.teamScores = {}; S.teamMins = {}; save(); renderGames(); renderPlayers(); renderValue(); };

  // ---------- players ----------
  function renderPlayers() {
    const q = $("#search").value.trim().toLowerCase(), hide = $("#hideZero").checked;
    const locked = new Set(S.locked), lockedCpt = new Set(S.lockedCpt || []), excl = new Set(S.excluded);
    let rows = players.map(p => { const a = adjusted(p); return Object.assign({}, p, a, { value: a.adj / (p.salary / 1000) }); })
      .filter(p => (posF === "ALL" || p.pos === posF) && (!q || p.name.toLowerCase().includes(q) || p.team.toLowerCase() === q) && (!hide || p.adj > 0 || locked.has(p.id)));
    rows.sort((a, b) => { const x = a[sort.key], y = b[sort.key]; return (typeof x === "string" ? x.localeCompare(y) : x - y) * sort.dir; });
    rows = rows.slice(0, 400);
    $("#ptable tbody").innerHTML = rows.map(p => `
      <tr class="${locked.has(p.id) ? "locked" : ""} ${lockedCpt.has(p.id) ? "cptlock" : ""} ${excl.has(p.id) ? "excluded" : ""}" data-id="${p.id}">
        <td><button class="ic lk ${locked.has(p.id) ? "on" : ""}" title="Lock">🔒</button><button class="ic cp sd-only ${lockedCpt.has(p.id) ? "on" : ""}" title="Lock as Captain">C</button><button class="ic x ${excl.has(p.id) ? "on" : ""}" title="Exclude">✕</button></td>
        <td>${p.name}${cptPickIds.has(p.id) ? ' <span class="pos CPT" title="Claude: play him at Captain">CPT</span>' : ""}${mustIds.includes(p.id) ? '<span class="star" title="Claude must play">★</span>' : coreIds.includes(p.id) ? '<span class="star" title="Claude core play">☆</span>' : sleeperIds.includes(p.id) ? '<span class="star sleeper" title="Claude sleeper / boom pick">✦</span>' : ""}</td><td><span class="pos ${p.pos}">${p.pos}</span></td><td>${p.team}</td><td class="muted">${p.home ? "vs" : "@"} ${p.opp}</td>
        <td class="num">${fmt$(p.salary)}</td>${isSD ? `<td class="num muted">${fmt$(p.cptSalary || 0)}</td>` : ""}
        <td class="num"><input class="edit ${S.edits[p.id] != null ? "edited" : ""}" type="number" step="0.1" value="${p.adj.toFixed(1)}"></td>
        <td class="num">${p.value.toFixed(2)}</td><td class="num muted">${p.ceil.toFixed(1)}</td>
        <td><input class="exp" type="number" min="0" max="100" step="5" placeholder="def" value="${S.exposure[p.id] != null ? Math.round(S.exposure[p.id] * 100) : ""}"></td>
        <td class="note">${p.note || (p.status ? "DK: " + p.status : "")}</td>
      </tr>`).join("");
  }
  $("#ptable tbody").addEventListener("click", e => {
    const tr = e.target.closest("tr"); if (!tr) return; const id = +tr.dataset.id;
    S.lockedCpt = S.lockedCpt || [];
    const tog = (arr, ...others) => { const i = S[arr].indexOf(id); if (i >= 0) S[arr].splice(i, 1); else { S[arr].push(id); others.forEach(o => S[o] = S[o].filter(x => x !== id)); } };
    if (e.target.classList.contains("lk")) { tog("locked", "excluded", "lockedCpt"); save(); renderPlayers(); }
    if (e.target.classList.contains("cp")) { tog("lockedCpt", "excluded", "locked"); save(); renderPlayers(); }
    if (e.target.classList.contains("x")) { tog("excluded", "locked", "lockedCpt"); save(); renderPlayers(); }
  });
  $("#ptable tbody").addEventListener("change", e => {
    const tr = e.target.closest("tr"); const id = +tr.dataset.id;
    if (e.target.classList.contains("edit")) {
      const p = players.find(x => x.id === id), v = parseFloat(e.target.value);
      const auto = adjusted(p, Object.assign({}, S, { edits: {} })).adj;
      if (isNaN(v) || Math.abs(v - auto) < 0.05) delete S.edits[id]; else S.edits[id] = v;
    }
    if (e.target.classList.contains("exp")) {
      const v = parseFloat(e.target.value); if (isNaN(v)) delete S.exposure[id]; else S.exposure[id] = Math.min(100, Math.max(0, v)) / 100;
    }
    save(); renderPlayers(); renderValue();
  });
  $("#search").addEventListener("input", renderPlayers);
  $("#hideZero").addEventListener("change", renderPlayers);
  $$("#posFilter button").forEach(b => b.onclick = () => { $$("#posFilter button").forEach(x => x.classList.remove("active")); b.classList.add("active"); posF = b.dataset.pos; renderPlayers(); });
  $$("#ptable th[data-sort]").forEach(th => th.onclick = () => { const k = th.dataset.sort; sort = { key: k, dir: sort.key === k ? -sort.dir : (["name", "pos", "team"].includes(k) ? 1 : -1) }; renderPlayers(); });
  $("#clearLocks").onclick = () => { S.locked = []; S.lockedCpt = []; S.excluded = []; S.edits = {}; S.exposure = {}; save(); renderPlayers(); renderValue(); };

  // ---------- value board ----------
  function renderValue() {
    const html = (isSD ? ["QB", "RB", "WR", "TE", "K", "DST"] : ["QB", "RB", "WR", "TE", "DST"]).map(pos => {
      const top = players.filter(p => p.pos === pos).map(p => Object.assign({}, p, adjusted(p))).filter(p => p.adj > 0)
        .sort((a, b) => b.adj / b.salary - a.adj / a.salary).slice(0, 6);
      return `<div class="vb"><h4><span class="pos ${pos}">${pos}</span> best value</h4>${top.map(p => `<div><span>${p.name} <span class="muted">${p.team}</span></span><span>${fmt$(p.salary)} · ${p.adj.toFixed(1)}</span></div>`).join("")}</div>`;
    }).join("");
    $("#valueBoard").innerHTML = html;
  }

  // ---------- scenarios ----------
  function renderScen() {
    const names = Object.keys(S.scenarios);
    $("#scenList").innerHTML = names.length ? names.map(n => `<div class="scen" data-n="${encodeURIComponent(n)}">
      <input type="checkbox" class="pick" ${S.scenPick.includes(n) ? "checked" : ""} title="Include in build"><span>${n.replace(/</g, "&lt;")}</span>
      <button class="ghost ld">Load</button><button class="ghost del">Delete</button></div>`).join("") +
      `<p class="muted small">Checked scenarios split the lineup count between them when you build. None checked = current predictions only.</p>`
      : `<p class="muted small">No saved scenarios yet.</p>`;
  }
  $("#saveScen").onclick = () => {
    const n = $("#scenName").value.trim() || `Scenario ${Object.keys(S.scenarios).length + 1}`;
    S.scenarios[n] = { teamScores: { ...S.teamScores }, teamMins: { ...S.teamMins }, edits: { ...S.edits } };
    if (!S.scenPick.includes(n)) S.scenPick.push(n);
    $("#scenName").value = ""; save(); renderScen();
  };
  $("#scenList").addEventListener("click", e => {
    const row = e.target.closest(".scen"); if (!row) return; const n = decodeURIComponent(row.dataset.n);
    if (e.target.classList.contains("ld")) { Object.assign(S, JSON.parse(JSON.stringify(S.scenarios[n]))); save(); renderGames(); renderPlayers(); renderValue(); }
    if (e.target.classList.contains("del")) { delete S.scenarios[n]; S.scenPick = S.scenPick.filter(x => x !== n); save(); renderScen(); }
    if (e.target.classList.contains("pick")) { S.scenPick = e.target.checked ? [...new Set([...S.scenPick, n])] : S.scenPick.filter(x => x !== n); save(); }
  });

  // ---------- build ----------
  $("#maxBtn").onclick = () => {
    const m = $("#optMode"); m.value = "max"; m.dispatchEvent(new Event("input")); $("#buildBtn").click();
  };
  $("#buildBtn").onclick = async () => {
    const base = readOpts();
    const runs = base.max ? [] : S.scenPick.filter(n => S.scenarios[n]).map(n => ({ name: n, st: Object.assign({}, S, S.scenarios[n]) }));
    if (!runs.length) runs.push({ name: null, st: S });
    const btn = $("#buildBtn"), bar = $("#progress"), msg = $("#buildMsg");
    btn.disabled = true; $("#maxBtn").disabled = true; bar.classList.remove("hidden"); msg.textContent = "Optimizing…";
    const all = []; const t0 = performance.now();
    let doneCount = 0;
    const OPT = isSD ? DKOpt.optimizeShowdownAsync : DKOpt.optimizeAsync;
    const sdLocks = ids => isSD ? { locked: new Set([...S.locked, ...ids.filter(id => !cptPickIds.has(id))]),
      lockedCpt: new Set([...(S.lockedCpt || []), ...ids.filter(id => cptPickIds.has(id))]) } : { locked: new Set([...S.locked, ...ids]) };
    // Phase A: Claude's must plays locked into the first N lineups
    let mustN = base.max ? 0 : Math.min(+$("#optMust").value, base.n);
    let must = mustIds.filter(id => !S.excluded.includes(id));
    if (mustN > 0 && must.length) {
      const pool = players.map(p => { const a = adjusted(p, runs[0].st); return Object.assign({}, p, { proj: a.adj, ceil: a.ceil }); });
      while (must.length) {
        const opts = Object.assign({}, base, sdLocks(must), { n: mustN, excluded: new Set(S.excluded),
          exposure: S.exposure, teamMins: runs[0].st.teamMins || {}, maxExposure: 1, prev: [] });
        const res = await OPT(pool, opts, window.solver, k => {
          $("#progress div").style.width = (k / base.n * 100) + "%"; msg.textContent = `Lineup ${k} of ${base.n} · must plays`;
        });
        if (res.lineups.length) { res.lineups.forEach(L => L.must = true); all.push(...res.lineups); doneCount = res.lineups.length; break; }
        must = must.slice(0, -1); // couldn't fit them all: drop the lowest-priority must play and retry
      }
    }
    const remaining = base.n - doneCount;
    for (let i = 0; i < runs.length && remaining > 0; i++) {
      const n = Math.floor(remaining / runs.length) + (i < remaining % runs.length ? 1 : 0); if (!n) continue;
      const pool = players.map(p => { const a = adjusted(p, runs[i].st); return Object.assign({}, p, { proj: a.adj, ceil: a.ceil }); });
      const sleepMin = base.max ? 0 : +$("#optSleep").value;
      const sleepSet = new Set(sleeperIds.filter(id => !S.excluded.includes(id)));
      const opts = Object.assign({}, base, sdLocks([]), {
        n, excluded: new Set(S.excluded), exposure: base.max ? {} : S.exposure, teamMins: base.max ? {} : runs[i].st.teamMins || {},
        prev: all.map(L => L.players.map(p => p.id)),
        groupMins: sleepMin && sleepSet.size ? [{ ids: sleepSet, min: sleepMin, cptIds: cptPickIds }] : [],
      });
      const prog = k => {
        $("#progress div").style.width = ((doneCount + k) / base.n * 100) + "%";
        msg.textContent = `Lineup ${doneCount + k} of ${base.n}${runs[i].name ? " · " + runs[i].name : ""}`;
      };
      let res = await OPT(pool, opts, window.solver, prog);
      if (res.lineups.length < n && opts.groupMins.length) { // sleepers couldn't fit every lineup: fill the rest without that rule
        const more = await OPT(pool, Object.assign({}, opts, { n: n - res.lineups.length, groupMins: [],
          prev: [...opts.prev, ...res.lineups.map(L => L.players.map(p => p.id))] }), window.solver, prog);
        res = { lineups: [...res.lineups, ...more.lineups] };
      }
      res.lineups.forEach(L => { L.scenario = runs[i].name; L.maxMode = !!base.max; });
      all.push(...res.lineups); doneCount += n;
    }
    lineups = all;
    btn.disabled = false; $("#maxBtn").disabled = false; bar.classList.add("hidden");
    msg.textContent = lineups.length ? `Built ${lineups.length} lineup${lineups.length > 1 ? "s" : ""} in ${((performance.now() - t0) / 1000).toFixed(1)}s` :
      "No valid lineups — loosen locks, team minimums or the min salary.";
    renderLineups();
    if (lineups.length) switchTab("lineups");
  };

  function renderLineups() {
    $("#lineupCount").textContent = lineups.length;
    $("#dlCsv").disabled = !lineups.length; $("#copyCsv").disabled = !lineups.length; $("#csvBox").hidden = true;
    const slots = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"];
    const slot = (L, p, j) => L.showdown ? (p.cpt ? "CPT" : "FLEX") : slots[j];
    $("#lineups").innerHTML = lineups.map((L, i) => `<div class="lu ${L.must ? "must" : ""}"><div class="hd">#${i + 1} ${L.must ? `<span class="tag">★ Claude's must plays</span>` : ""}${L.maxMode && i === 0 ? `<span class="tag">Max points</span>` : ""}${L.scenario ? `<span>${L.scenario}</span>` : ""}<span>${fmt$(L.salary)} · ${L.proj.toFixed(1)} pts</span></div>
      ${L.players.map((p, j) => `<div class="pl"><span class="pos ${slot(L, p, j)}">${slot(L, p, j)}</span><span>${p.name} <span class="muted small">${L.showdown ? p.pos + " " : ""}${p.team}${p.cpt ? " · 1.5x" : ""}</span></span><span class="s">${fmt$(p.salary)}</span><span class="p">${(+p.proj).toFixed(1)}</span></div>`).join("")}</div>`).join("");
    const cnt = {}; lineups.forEach(L => L.players.forEach(p => cnt[p.id] = (cnt[p.id] || 0) + 1));
    const top = Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 30);
    $("#exposure").innerHTML = lineups.length > 1 ? "<b class='small' style='width:100%'>Exposure</b>" + top.map(([id, c]) => `<span class="e">${players.find(p => p.id === +id).name} ${Math.round(c / lineups.length * 100)}%</span>`).join("") : "";
  }
  $("#dlCsv").onclick = () => {
    const blob = new Blob([DKOpt.toCSV(lineups)], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `DK_NFL_W${slate.week}_${(slate.slateName || "Main").replace(/\W+/g, "")}_lineups.csv`; a.click();
  };

  $("#copyCsv").onclick = async () => {
    const txt = DKOpt.toCSV(lineups), box = $("#csvBox"), b = $("#copyCsv");
    box.value = txt; box.hidden = false;
    try { await navigator.clipboard.writeText(txt); b.textContent = "Copied!"; }
    catch { box.select(); b.textContent = "Selected — press Ctrl/Cmd+C"; }
    setTimeout(() => b.textContent = "Copy CSV", 2500);
  };

  // ---------- tabs ----------
  function switchTab(t) { $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === t)); $$(".tab").forEach(s => s.classList.toggle("active", s.id === "tab-" + t)); }
  $$("#tabs button").forEach(b => b.onclick = () => switchTab(b.dataset.tab));

  load().catch(e => { $("#slateMeta").textContent = "Could not load data/slate.json — " + e.message; });
})();
