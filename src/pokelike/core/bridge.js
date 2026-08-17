// Ponte fra il motore del gioco e Python.
//
// Viene iniettato nella pagina DOPO che il bundle e' partito. Espone quattro
// funzioni su window, che sono tutta la superficie che Python usa:
//
//   __pk_layer()    quale schermata/modale e' attiva adesso
//   __pk_choices()  le azioni legali, come lista ordinata e stabile
//   __pk_apply(c)   esegue una di quelle azioni
//   __pk_obs()      lo stato completo, come JSON puro
//
// Nota importante: qui non si guardano pixel. `state` e' un oggetto JavaScript
// in memoria e i bottoni sono oggetti del DOM, che esistono anche senza finestra.
(() => {
  // I nomi del motore sono globali dichiarati con `let`/`function`: stanno nello
  // scope globale dello script, non su window, quindi vanno letti con eval.
  const g = (n) => { try { return eval(n); } catch (e) { return undefined; } };

  const CFG = window.__PK_CFG;

  const shown = (e) => {
    if (!e) return false;
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  // Contenitore delle scelte per ogni schermata; se manca si usa la schermata stessa.
  const CONTENITORI = {
    'starter-screen': '#starter-choices',
    'trainer-screen': '#trainer-choices',
    'catch-screen': '#catch-choices',
    'item-screen': '#item-choices',
    'passive-screen': '#passive-choices',
    'swap-screen': '#swap-choices',
  };

  const RUMORE = /run-menu|btn-shop|pokechain|settings|typechart|pokedex|achievements|credits|patch/i;

  window.__pk_layer = () => {
    for (const id of CFG.modali) {
      if (shown(document.getElementById(id))) return { tipo: 'modale', id };
    }
    const s = [...document.querySelectorAll('.screen')]
      .find((e) => getComputedStyle(e).display !== 'none');
    return { tipo: 'schermata', id: s ? s.id : '(nessuna)' };
  };

  // Unica fonte di verita' per le azioni: __pk_apply indicizza esattamente
  // questa lista, cosi' una scelta non puo' mai riferirsi a un altro bottone.
  const elementiScelta = () => {
    const L = window.__pk_layer();
    if (L.tipo === 'schermata' && L.id === 'map-screen') return { L, nodi: true };
    const sel = L.tipo === 'modale' ? '#' + L.id : (CONTENITORI[L.id] || '#' + L.id);
    const root = document.querySelector(sel) || document.getElementById(L.id);
    if (!root) return { L, els: [] };
    const els = [...root.querySelectorAll(
      '.poke-card, .choice-card, .trainer-card, .item-card, .equip-pokemon-row button, button'
    )].filter((e) => shown(e) && !e.disabled && !RUMORE.test(e.id + ' ' + e.className));
    return { L, els };
  };

  window.__pk_choices = () => {
    const { L, nodi, els } = elementiScelta();
    if (nodi) {
      const st = g('state');
      if (!st || !st.map) return [];
      return Object.values(st.map.nodes)
        .filter((n) => n.accessible && !n.visited)
        .sort((a, b) => (a.layer - b.layer) || (a.col - b.col))
        .map((n) => ({ tipo: 'nodo', id: n.id, nodo: n.type, livello: n.layer, colonna: n.col }));
    }
    return (els || []).map((e, i) => ({
      tipo: 'elemento', idx: i, layer: L.id, id: e.id || null,
      etichetta: (e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120),
    }));
  };

  window.__pk_apply = (c) => {
    if (c.tipo === 'nodo') {
      const st = g('state');
      const n = st && st.map && st.map.nodes[c.id];
      if (!n || !n.accessible || n.visited) return false;
      g('onNodeClick')(n); // asincrona: Python aspetta che le cose si assestino
      return true;
    }
    const { els } = elementiScelta();
    const el = els && els[c.idx];
    if (!el) return false;
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    return true;
  };

  window.__pk_stato_punto = () => {
    const L = window.__pk_layer();
    if (L.tipo === 'schermata' && CFG.terminali.includes(L.id)) return 'finale';
    if (L.tipo === 'modale') return 'decisione';
    return CFG.decisionali.includes(L.id) ? 'decisione' : 'transitorio';
  };

  // Avanza da solo tutto cio' che non e' una decisione: riproduzione delle
  // battaglie, banner di livello, bottoni "Continua".
  window.__pk_avanza = () => {
    for (const id of ['btn-continue-battle', 'btn-auto-battle']) {
      const b = document.getElementById(id);
      if (b && getComputedStyle(b).display !== 'none' && !b.disabled) { b.click(); return id; }
    }
    const L = window.__pk_layer();
    const root = document.getElementById(L.id);
    if (!root) return null;
    const btns = [...root.querySelectorAll('button')]
      .filter((b) => shown(b) && !b.disabled && !RUMORE.test(b.id + ' ' + b.className));
    if (btns.length === 1) { btns[0].click(); return btns[0].id || 'unico'; }
    return null;
  };

  window.__pk_obs = () => {
    const st = g('state');
    const L = window.__pk_layer();
    const o = { layer: L.tipo, schermata: L.id };
    if (st) {
      o.run = {
        seed_run: st.runSeed, mappa: st.currentMap, medaglie: st.badges,
        squadra_max: st.maxTeamSize, nuzlocke: !!st.nuzlockeMode,
        qualcuno_svenuto: !!st.anyFainted, finita: !!st._finished,
        item_raccolti: st.itemsThisRun || 0, elite: st.eliteIndex,
      };
      o.squadra = (st.team || []).map((p) => ({
        uid: p._uid, specie_id: p.speciesId, nome: p.name, livello: p.level,
        hp: p.currentHp, hp_max: p.maxHp, tipi: p.types, stats_base: p.baseStats,
        tier_mosse: p.moveTier, oggetto: p.heldItem ? p.heldItem.name : null,
        megastone: p.megaStone ? p.megaStone.name : null, shiny: !!p.isShiny,
      }));
      o.zaino = (st.items || []).map((i) => i && (i.name || i.id));
      if (st.map) {
        o.mappa = {
          nodi: Object.values(st.map.nodes).map((n) => ({
            id: n.id, tipo: n.type, livello: n.layer, colonna: n.col,
            accessibile: !!n.accessible, visitato: !!n.visited, rivelato: !!n.revealed,
          })),
          archi: st.map.edges.map((e) => [e.from, e.to]),
          attuale: st.currentNode ? st.currentNode.id : null,
        };
      }
      // Statistiche accumulate dal nostro aggancio a runBattle (vedi __pk_stats).
      if (window.__pk_stats) o.statistiche = { ...window.__pk_stats };
    }
    o.azioni = window.__pk_choices();
    return o;
  };

  // ---------------------------------------------------------------------
  // Punteggio.
  //
  // Il gioco sa gia' calcolarlo (finalizeRunScore) e sa gia' contare le
  // statistiche (foldBattleIntoRunStats), ma le collega solo in modalita'
  // Challenge: il call site e' `state.challengeId && state.runStats && fold(...)`.
  // In Story i contatori resterebbero a zero.
  //
  // Invece di forzare challengeId — che cambierebbe le regole di gioco —
  // avvolgiamo runBattle: chiamiamo l'originale e poi passiamo il risultato
  // alla funzione di conteggio del gioco. Le regole restano intatte e i
  // contatori sono quelli nativi.
  // ---------------------------------------------------------------------
  window.__pk_aggancia_punteggio = () => {
    // ATTENZIONE: niente variabili locali con lo stesso nome dei globali che
    // vogliamo sostituire, altrimenti le oscuriamo e riscriviamo la copia
    // sbagliata.
    const foldOrig = g('foldBattleIntoRunStats');
    const nuoveOrig = g('newRunStats');
    const battagliaOrig = g('runBattle');
    if (typeof battagliaOrig !== 'function' || typeof foldOrig !== 'function'
        || typeof nuoveOrig !== 'function') {
      return { ok: false, motivo: 'funzioni di punteggio non trovate' };
    }
    if (window.__pk_agganciato) return { ok: true, gia: true };

    // Perche' non usiamo invece il gate nativo (`state.challengeId`): impostarlo
    // CAMBIA LE REGOLE. Fra le altre cose alza i livelli della Superquattro
    //     state.challengeId ? Math.max(0, 10 + challengeEliteLevelMod) : 0
    // quindi la partita non sarebbe piu' quella normale. Avvolgere runBattle
    // lascia il gioco identico e ci da' comunque i contatori nativi.
    //
    // runBattle e' una `function` dichiarata al livello globale: sta su window
    // ed e' scrivibile.
    try {
      const st = g('state');
      if (st && !st.runStats) st.runStats = nuoveOrig();

      window.runBattle = function (...args) {
        const r = battagliaOrig.apply(this, args);
        try {
          const s = g('state');
          if (s) {
            if (!s.runStats) s.runStats = nuoveOrig();
            // Stessa firma del punto di chiamata originale del gioco:
            //   fold(detailedLog, <primo argomento di runBattle>, playerWon, pTeam)
            foldOrig(r.detailedLog, args[0], r.playerWon, r.pTeam);
            window.__pk_stats = JSON.parse(JSON.stringify(s.runStats));
          }
        } catch (e) {
          window.__pk_errore_punteggio = String(e);
        }
        return r;
      };
      window.__pk_agganciato = true;
      return { ok: true, modo: 'runBattle-avvolta' };
    } catch (e) {
      return { ok: false, motivo: String(e) };
    }
  };

  // Applica la formula ufficiale del gioco all'ultimo snapshot di statistiche.
  //
  // Nota sul bonus tempo: la formula lo calcola come 1000 - 100 per ogni minuto
  // di gioco reale, ma noi congeliamo Date.now() per rendere le partite
  // riproducibili. Il risultato e' che il bonus resta inchiodato vicino a 1000 e
  // non porta informazione. Restituiamo quindi anche `punti_senza_tempo`, che e'
  // il numero da usare per confrontare fra loro giocatori o strategie.
  window.__pk_punteggio = (completata) => {
    const fin = g('finalizeRunScore');
    const st = g('state');
    const stats = (st && st.runStats) || window.__pk_stats;
    if (!stats || typeof fin !== 'function') return null;
    const copia = JSON.parse(JSON.stringify(stats));
    const punti = fin(copia, { cleared: !!completata });
    const d = copia.scoreBreakdown || {};
    return {
      punti,
      punti_senza_tempo: punti - (d.timeBonus || 0),
      dettaglio: d,
      statistiche: copia,
    };
  };
})();
