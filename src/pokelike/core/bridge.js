// Bridge between the game engine and Python.
//
// Injected into the page AFTER the game bundle has booted. It exposes a handful
// of functions on `window`, and that is the entire surface Python uses:
//
//   __pk_layer()    which screen or modal is active right now
//   __pk_choices()  the legal actions, as a stable ordered list
//   __pk_apply(c)   perform one of them
//   __pk_obs()      the full state, as plain JSON
//
// Worth stressing: no pixels are involved. `state` is a JavaScript object in
// memory and the buttons are DOM objects, both of which exist perfectly well
// without a window ever being drawn.
(() => {
  // The engine's names are globals declared with `let`/`function`: they live in
  // the script's global scope, not on `window`, so they need eval to read.
  const g = (n) => { try { return eval(n); } catch (e) { return undefined; } };

  const CFG = window.__PK_CFG;

  const shown = (e) => {
    if (!e) return false;
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  // Where each screen keeps its choices; falls back to the screen itself.
  const CONTAINERS = {
    'starter-screen': '#starter-choices',
    'trainer-screen': '#trainer-choices',
    'catch-screen': '#catch-choices',
    'item-screen': '#item-choices',
    'passive-screen': '#passive-choices',
    'swap-screen': '#swap-choices',
  };

  const NOISE = /run-menu|btn-shop|pokechain|settings|typechart|pokedex|achievements|credits|patch/i;

  window.__pk_layer = () => {
    for (const id of CFG.modals) {
      if (shown(document.getElementById(id))) return { kind: 'modal', id };
    }
    const s = [...document.querySelectorAll('.screen')]
      .find((e) => getComputedStyle(e).display !== 'none');
    return { kind: 'screen', id: s ? s.id : '(none)' };
  };

  // Single source of truth for the action list: __pk_apply indexes into exactly
  // this array, so a choice can never end up pointing at a different button.
  const choiceElements = () => {
    const L = window.__pk_layer();
    if (L.kind === 'screen' && L.id === 'map-screen') return { L, nodes: true };
    const sel = L.kind === 'modal' ? '#' + L.id : (CONTAINERS[L.id] || '#' + L.id);
    const root = document.querySelector(sel) || document.getElementById(L.id);
    if (!root) return { L, els: [] };
    const els = [...root.querySelectorAll(
      '.poke-card, .choice-card, .trainer-card, .item-card, .equip-pokemon-row button, button'
    )].filter((e) => shown(e) && !e.disabled && !NOISE.test(e.id + ' ' + e.className));
    return { L, els };
  };

  // A button's own text is sometimes useless on its own. The equip modal shows
  // five buttons all reading "EQUIP", one per team member, and which Pokemon
  // each belongs to lives in the row around it. A bot reading only labels cannot
  // tell them apart, so it has to guess — which is a silent, invisible handicap.
  // Where a button sits in a row carrying the context, we label it with that.
  const ROW_SELECTOR = '.equip-pokemon-row, .swap-choice, .poke-card';

  const labelFor = (e) => {
    const own = (e.innerText || '').replace(/\s+/g, ' ').trim();
    const row = e.closest && e.closest(ROW_SELECTOR);
    if (row && row !== e) {
      const context = (row.innerText || '').replace(/\s+/g, ' ').trim();
      // "Squirtle Lv5 — empty — EQUIP" says which button this is; "EQUIP" does not.
      if (context && context !== own) return `${own} — ${context}`.slice(0, 160);
    }
    return own.slice(0, 160);
  };

  window.__pk_choices = () => {
    const { L, nodes, els } = choiceElements();
    if (nodes) {
      const st = g('state');
      if (!st || !st.map) return [];
      return Object.values(st.map.nodes)
        .filter((n) => n.accessible && !n.visited)
        .sort((a, b) => (a.layer - b.layer) || (a.col - b.col))
        .map((n) => ({ kind: 'node', id: n.id, node: n.type, layer: n.layer, col: n.col }));
    }
    return (els || []).map((e, i) => ({
      kind: 'element', idx: i, layer: L.id, id: e.id || null,
      label: labelFor(e),
    }));
  };

  window.__pk_apply = (c) => {
    if (c.kind === 'node') {
      const st = g('state');
      const n = st && st.map && st.map.nodes[c.id];
      if (!n || !n.accessible || n.visited) return false;
      g('onNodeClick')(n); // async by design; Python polls until things settle
      return true;
    }
    const { els } = choiceElements();
    const el = els && els[c.idx];
    if (!el) return false;
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    return true;
  };

  window.__pk_point = () => {
    const L = window.__pk_layer();
    if (L.kind === 'screen' && CFG.terminal.includes(L.id)) return 'terminal';
    if (L.kind === 'modal') return 'decision';
    return CFG.decision.includes(L.id) ? 'decision' : 'transient';
  };

  // Advances anything that is not a decision by itself: battle playback,
  // level-up banners, "Continue" buttons.
  window.__pk_advance = () => {
    for (const id of ['btn-continue-battle', 'btn-auto-battle']) {
      const b = document.getElementById(id);
      if (b && getComputedStyle(b).display !== 'none' && !b.disabled) { b.click(); return id; }
    }
    const L = window.__pk_layer();
    const root = document.getElementById(L.id);
    if (!root) return null;
    const btns = [...root.querySelectorAll('button')]
      .filter((b) => shown(b) && !b.disabled && !NOISE.test(b.id + ' ' + b.className));
    if (btns.length === 1) { btns[0].click(); return btns[0].id || 'single'; }
    return null;
  };

  // One step of the settle loop: is the game ready, and if not, nudge it.
  //
  // Returns true when there is a real decision to make or the run is over. It
  // has a side effect on purpose — a forced single choice, or a Continue button,
  // is taken here rather than reported back for Python to take.
  //
  // BECAUSE it has side effects, it must never be handed to a poller as a
  // predicate. Call it from `__pk_settle` below, which controls the cadence.
  window.__pk_pump = () => {
    const point = window.__pk_point();
    if (point === 'terminal') return { ready: true, acted: false };
    if (point === 'decision') {
      const n = window.__pk_choices().length;
      if (n > 1) return { ready: true, acted: false };
      if (n === 1) {
        window.__pk_apply(window.__pk_choices()[0]);
        return { ready: false, acted: true };
      }
    }
    return { ready: false, acted: Boolean(window.__pk_advance()) };
  };

  // Run the pump until the game is ready, all inside one call.
  //
  // It must NOT be used as a polling predicate. `__pk_pump` clicks things, and a
  // poller calls its predicate an unpredictable number of times: the clicks then
  // land at different moments, the engine consumes its seeded Math.random in a
  // different order, and the same seed stops replaying the same run. That was a
  // real regression, caught by the determinism test.
  //
  // So the loop lives here, its iteration count driven by the game rather than
  // by a poller, and paced with a real timeout so a click never lands in the
  // middle of the redraw the previous one caused.
  window.__pk_settle = async (timeoutMs) => {
    const started = performance.now();
    while (performance.now() - started < timeoutMs) {
      const r = window.__pk_pump();
      if (r.ready) return true;
      // Pace only after actually clicking, so the click never lands on top of
      // the redraw it caused. While merely waiting for the engine's own async
      // work there is nothing to disturb, so check often.
      await new Promise((k) => window.__pk_realTimeout(k, r.acted ? 15 : 2));
    }
    return false;
  };

  // What the screen is asking. Without it a choice can be read backwards: the
  // swap screen lists your team and its prompt is "Choose a Pokémon to
  // release", but a bot seeing only the list may take it for "choose your
  // lead" — and release its best Pokemon believing it promoted it. Observed
  // happening to an LLM, which is what prompted exposing this.
  const promptOf = (id) => {
    const root = document.getElementById(id);
    if (!root) return null;
    const bits = [...root.querySelectorAll('h2, [id$="-prompt"], .screen-desc')]
      .filter(shown)
      .map((e) => (e.innerText || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    return bits.length ? [...new Set(bits)].join(' — ').slice(0, 160) : null;
  };

  // -------------------------------------------------------------------
  // Team order.
  //
  // Slot 0 leads, so the order is a real decision, and until now no bot could
  // make it: the game binds reordering to a hand-rolled pointer drag on the
  // team bar, which lives outside any `.screen`, so `__pk_choices` never saw it.
  //
  // We do NOT simulate the drag. Underneath all the pointer handling the
  // engine's drop does exactly one thing:
  //     [team[a], team[b]] = [team[b], team[a]]; renderTeamBar(team)
  // and the Elite Four prep screen, which has its own drag, mutates that SAME
  // `state.team` array and then calls `window._elitePrepRefresh()`. So one
  // primitive covers both, with no dependence on coordinates or on layout
  // existing, which is what makes it safe headless.
  window.__pk_can_reorder = () => {
    const st = g('state');
    return Boolean(st && Array.isArray(st.team) && st.team.length > 1);
  };

  window.__pk_reorder = (a, b) => {
    const st = g('state');
    if (!st || !Array.isArray(st.team)) return false;
    const t = st.team;
    if (!Number.isInteger(a) || !Number.isInteger(b)) return false;
    if (a === b || a < 0 || b < 0 || a >= t.length || b >= t.length) return false;

    [t[a], t[b]] = [t[b], t[a]];

    // Repaint through whichever renderer owns the screen we are on. Both read
    // the array we just mutated, so a missing one costs the picture, never the
    // swap: the state is already correct either way.
    try {
      if (window.__pk_layer().id === 'elite-prep-screen'
          && typeof window._elitePrepRefresh === 'function') {
        window._elitePrepRefresh();
      } else if (typeof renderTeamBar === 'function') {
        renderTeamBar(t);
      }
    } catch (e) { /* cosmetic only */ }
    return true;
  };

  window.__pk_obs = () => {
    const st = g('state');
    const L = window.__pk_layer();
    const o = { layer: L.kind, screen: L.id, prompt: promptOf(L.id) };
    if (st) {
      o.run = {
        run_seed: st.runSeed, map: st.currentMap, badges: st.badges,
        max_team_size: st.maxTeamSize, nuzlocke: !!st.nuzlockeMode,
        anyone_fainted: !!st.anyFainted, finished: !!st._finished,
        items_this_run: st.itemsThisRun || 0, elite: st.eliteIndex,
      };
      o.team = (st.team || []).map((p) => ({
        uid: p._uid, species_id: p.speciesId, name: p.name, level: p.level,
        hp: p.currentHp, max_hp: p.maxHp, types: p.types, base_stats: p.baseStats,
        move_tier: p.moveTier, item: p.heldItem ? p.heldItem.name : null,
        mega_stone: p.megaStone ? p.megaStone.name : null, shiny: !!p.isShiny,
      }));
      o.bag = (st.items || []).map((i) => i && (i.name || i.id));
      if (st.map) {
        o.map = {
          nodes: Object.values(st.map.nodes).map((n) => ({
            id: n.id, kind: n.type, layer: n.layer, col: n.col,
            accessible: !!n.accessible, visited: !!n.visited, revealed: !!n.revealed,
          })),
          edges: st.map.edges.map((e) => [e.from, e.to]),
          current: st.currentNode ? st.currentNode.id : null,
        };
      }
      // Counters accumulated by our runBattle hook (see __pk_attach_score).
      if (window.__pk_stats) o.stats = { ...window.__pk_stats };
    }
    // Reordering is a FREE action: it does not consume the turn, so it is not
    // one of `actions`. Advertised separately, or a bot would have to guess
    // whether the verb applies right now.
    o.can_reorder = window.__pk_can_reorder();
    o.actions = window.__pk_choices();
    return o;
  };

  // ---------------------------------------------------------------------
  // Scoring.
  //
  // The engine already knows how to count (foldBattleIntoRunStats) and how to
  // apply the formula (finalizeRunScore), but it only wires the two together in
  // Challenge mode: the call site reads
  //     state.challengeId && state.runStats && fold(...)
  // so in Story mode the counters would stay at zero forever.
  //
  // Setting challengeId would be the obvious shortcut and it is WRONG: that flag
  // changes the rules, among other things raising the Elite Four's levels
  //     state.challengeId ? Math.max(0, 10 + challengeEliteLevelMod) : 0
  // so the run would no longer be a normal one. Wrapping runBattle leaves the
  // game untouched and still gives us the engine's own counters.
  // ---------------------------------------------------------------------
  window.__pk_attach_score = () => {
    // CAREFUL: no local variable may share a name with a global we intend to
    // replace, or we shadow it and rewrite the wrong copy.
    const foldOrig = g('foldBattleIntoRunStats');
    const newStatsOrig = g('newRunStats');
    const battleOrig = g('runBattle');
    if (typeof battleOrig !== 'function' || typeof foldOrig !== 'function'
        || typeof newStatsOrig !== 'function') {
      return { ok: false, reason: 'scoring functions not found' };
    }
    if (window.__pk_attached) return { ok: true, already: true };

    // Whatever goes wrong here must NOT stop the run: the score is a bonus,
    // the game comes first.
    try {
      const st = g('state');
      if (st && !st.runStats) st.runStats = newStatsOrig();

      // runBattle is a top-level function declaration, so it lives on window
      // and is writable.
      window.runBattle = function (...args) {
        const r = battleOrig.apply(this, args);
        try {
          const s = g('state');
          if (s) {
            if (!s.runStats) s.runStats = newStatsOrig();
            // Same argument order as the engine's own call site:
            //   fold(detailedLog, <runBattle's first argument>, playerWon, pTeam)
            foldOrig(r.detailedLog, args[0], r.playerWon, r.pTeam);
            window.__pk_stats = JSON.parse(JSON.stringify(s.runStats));
          }
        } catch (e) {
          window.__pk_score_error = String(e);
        }
        return r;
      };
      window.__pk_attached = true;
      return { ok: true, mode: 'runBattle-wrapped' };
    } catch (e) {
      return { ok: false, reason: String(e) };
    }
  };

  // Applies the game's official formula to the latest stats snapshot.
  //
  // A note on the time bonus: the formula computes it as 1000 minus 100 per
  // minute of real play, but we freeze Date.now() to make runs reproducible. The
  // upshot is that the bonus sits pinned near 1000 and carries no information.
  // So we also return `points_no_time`, which is the number to use when
  // comparing players or strategies.
  window.__pk_score = (completed) => {
    const fin = g('finalizeRunScore');
    const st = g('state');
    const stats = (st && st.runStats) || window.__pk_stats;
    if (!stats || typeof fin !== 'function') return null;
    const copy = JSON.parse(JSON.stringify(stats));
    const points = fin(copy, { cleared: !!completed });
    const b = copy.scoreBreakdown || {};
    return {
      points,
      points_no_time: points - (b.timeBonus || 0),
      breakdown: b,
      stats: copy,
    };
  };
})();
