"""Rendering testuale dello stato.

Tutto quello che c'è qui è ricostruito da `state`, cioè da un oggetto
JavaScript letto come JSON. Nessun pixel viene guardato: la mappa qui sotto non
è letta da un'immagine, è disegnata da noi a partire dai nodi e dagli archi.
"""

from __future__ import annotations

from typing import Any

ICONE = {
    "start": "@", "battle": "x", "trainer": "T", "catch": "o", "item": "i",
    "pokecenter": "+", "question": "?", "trade": "$", "move_tutor": "M",
    "boss": "B", "shiny": "*", "pokemart": "S", "mutation": "%",
    "evil_team": "E", "silver": "s", "legendary": "L",
}

LEGENDA = (
    "@ inizio   x lotta   T allenatore   o cattura   i oggetto   + centro cure\n"
    "? ignoto   $ scambio  M tutor mosse  B boss     S negozio   * shiny"
)


def mappa(m: dict[str, Any] | None) -> str:
    if not m:
        return "  (nessuna mappa)"
    per_livello: dict[int, list[dict]] = {}
    for n in m["nodi"]:
        if not n["rivelato"]:
            continue
        per_livello.setdefault(n["livello"], []).append(n)

    righe = []
    for liv in sorted(per_livello):
        celle = []
        for n in sorted(per_livello[liv], key=lambda x: x["colonna"]):
            ic = ICONE.get(n["tipo"], ".")
            if n["id"] == m.get("attuale"):
                celle.append(f"[{ic}]")       # dove sei ora
            elif n["accessibile"] and not n["visitato"]:
                celle.append(f"<{ic}>")       # mossa legale
            elif n["visitato"]:
                celle.append(f" {ic}'")       # già fatto
            else:
                celle.append(f" {ic} ")
        righe.append(f"  liv {liv:>2} | " + " ".join(celle))
    return "\n".join(righe)


def squadra(team: list[dict] | None) -> str:
    if not team:
        return "  (squadra vuota)"
    righe = []
    for i, p in enumerate(team):
        pieno = round((p["hp"] / p["hp_max"]) * 10) if p["hp_max"] else 0
        barra = "#" * max(0, pieno) + "." * max(0, 10 - pieno)
        oggetto = f"  [{p['oggetto']}]" if p.get("oggetto") else ""
        shiny = " *" if p.get("shiny") else ""
        righe.append(
            f"  {i}. {p['nome']:<13}Lv{p['livello']:>2}  {barra} {p['hp']:>3}/{p['hp_max']:<3}"
            f"  {'/'.join(p.get('tipi') or [])}{oggetto}{shiny}"
        )
    return "\n".join(righe)


def azioni(lista: list[dict]) -> str:
    if not lista:
        return "  (nessuna azione)"
    righe = []
    for i, a in enumerate(lista):
        if a["tipo"] == "nodo":
            righe.append(f"  [{i}] vai al nodo {a['id']:<6} ({a['nodo']})")
        else:
            righe.append(f"  [{i}] {a['etichetta']}")
    return "\n".join(righe)


def schermo(obs: dict[str, Any], con_legenda: bool = False) -> str:
    """La vista completa di un turno, in testo."""
    run = obs.get("run") or {}
    testa = (
        f"passo {obs.get('passi', 0)}   schermata: {obs.get('schermata')}   "
        f"mappa {run.get('mappa', '-')}   medaglie {run.get('medaglie', '-')}"
    )
    parti = ["=" * 72, testa, "=" * 72, "", "SQUADRA", squadra(obs.get("squadra"))]

    zaino = obs.get("zaino") or []
    if zaino:
        parti += ["", "ZAINO", "  " + ", ".join(str(z) for z in zaino)]

    if obs.get("mappa"):
        parti += ["", "MAPPA   [qui]  <mossa legale>  x'=fatto", mappa(obs["mappa"])]
        if con_legenda:
            parti += ["", LEGENDA]

    parti += ["", "AZIONI", azioni(obs.get("azioni") or [])]

    if obs.get("finita"):
        parti += ["", ">>> PARTITA FINITA <<<"]
    return "\n".join(parti)


def punteggio(p: dict[str, Any] | None) -> str:
    if not p:
        return "punteggio non disponibile"
    d = p.get("dettaglio") or {}
    s = p.get("statistiche") or {}
    righe = [
        f"PUNTEGGIO: {p.get('punti')}   (senza bonus tempo: {p.get('punti_senza_tempo')})",
        "",
        f"  bonus vittoria     {d.get('winBonus', 0):>6}",
        f"  nemici sconfitti   {d.get('enemiesKO', 0):>6}  (x5)",
        f"  svenimenti         {d.get('faints', 0):>6}  (x-10)",
        f"  mappe completate   {d.get('mapsCleared', 0):>6}  (x50)",
        f"  leggendari         {d.get('legendaries', 0):>6}  (x20)",
        f"  shiny              {d.get('shinies', 0):>6}  (x20)",
        f"  bonus tempo        {d.get('timeBonus', 0):>6}",
        "",
        f"  battaglie vinte    {s.get('battlesWon', 0):>6}",
        f"  catture            {s.get('catches', 0):>6}",
        f"  danno inflitto     {s.get('totalDamageDealt', 0):>6}",
        f"  danno subito       {s.get('totalDamageTaken', 0):>6}",
        f"  critici            {s.get('critHits', 0):>6}",
        f"  livello massimo    {s.get('highestLevel', 0):>6}",
    ]
    return "\n".join(righe)
