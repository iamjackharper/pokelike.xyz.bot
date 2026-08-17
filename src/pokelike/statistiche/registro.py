"""Registro delle partite giocate, per confrontare i bot fra loro.

Un file SQLite in `stats/partite.db`: sta nella libreria standard, si interroga
con SQL e non aggiunge dipendenze. Una riga per partita.

    from pokelike.statistiche import registra, riepilogo
    registra(bot="casuale", seed=1, stato=obs, punteggio=p, passi=12)
    print(riepilogo())
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PERCORSO = Path(__file__).resolve().parents[3] / "stats" / "partite.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS partite (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    quando           TEXT    NOT NULL,
    bot              TEXT    NOT NULL,
    seed             INTEGER NOT NULL,
    passi            INTEGER,
    fine             TEXT,
    vinta            INTEGER,
    medaglie         INTEGER,
    punti            INTEGER,   -- senza bonus tempo: l'unico confrontabile
    punti_grezzi     INTEGER,   -- come lo calcola il gioco, bonus tempo incluso
    ko               INTEGER,
    svenuti          INTEGER,
    mappe            INTEGER,
    catture          INTEGER,
    danno_inflitto   INTEGER,
    livello_max      INTEGER,
    squadra          TEXT,      -- JSON
    extra            TEXT       -- JSON libero, per note del singolo bot
);
CREATE INDEX IF NOT EXISTS idx_bot ON partite(bot);
"""


def _connessione(percorso: Path | None = None) -> sqlite3.Connection:
    p = Path(percorso or PERCORSO)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA)
    return conn


def registra(
    bot: str,
    seed: int,
    stato: dict[str, Any],
    punteggio: dict[str, Any] | None,
    passi: int,
    extra: dict[str, Any] | None = None,
    vivo: dict[str, Any] | None = None,
    percorso: Path | None = None,
) -> int:
    """Salva l'esito di una partita. Restituisce l'id della riga.

    `stato` è l'osservazione finale, `vivo` l'ultima con la partita ancora in
    corso. Servono entrambe: sulla schermata di game over il motore azzera
    `state`, quindi squadra e medaglie vanno letti da `vivo`.
    """
    p = punteggio or {}
    d = p.get("dettaglio") or {}
    s = p.get("statistiche") or {}
    ultimo = vivo or stato
    run = ultimo.get("run") or stato.get("run") or {}

    riga = (
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        bot,
        seed,
        passi,
        stato.get("schermata"),
        1 if stato.get("schermata") == "win-screen" else 0,
        run.get("medaglie"),
        p.get("punti_senza_tempo"),
        p.get("punti"),
        d.get("enemiesKO"),
        d.get("faints"),
        d.get("mapsCleared"),
        s.get("catches"),
        s.get("totalDamageDealt"),
        s.get("highestLevel"),
        json.dumps(ultimo.get("squadra") or [], ensure_ascii=False),
        json.dumps(extra or {}, ensure_ascii=False),
    )
    with _connessione(percorso) as conn:
        cur = conn.execute(
            "INSERT INTO partite (quando, bot, seed, passi, fine, vinta, medaglie,"
            " punti, punti_grezzi, ko, svenuti, mappe, catture, danno_inflitto,"
            " livello_max, squadra, extra)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            riga,
        )
        return int(cur.lastrowid or 0)


def riepilogo(percorso: Path | None = None) -> list[dict[str, Any]]:
    """Una riga per bot, con medie e massimi."""
    with _connessione(percorso) as conn:
        conn.row_factory = sqlite3.Row
        righe = conn.execute(
            "SELECT bot,"
            "       COUNT(*)              AS partite,"
            "       SUM(vinta)            AS vittorie,"
            "       ROUND(AVG(punti), 1)  AS punti_medi,"
            "       MAX(punti)            AS punti_max,"
            "       MIN(punti)            AS punti_min,"
            "       ROUND(AVG(passi), 1)  AS passi_medi,"
            "       MAX(medaglie)         AS medaglie_max,"
            "       ROUND(AVG(ko), 1)     AS ko_medi,"
            "       ROUND(AVG(svenuti),1) AS svenuti_medi"
            " FROM partite GROUP BY bot ORDER BY punti_medi DESC"
        ).fetchall()
        return [dict(r) for r in righe]


def ultime(n: int = 10, bot: str | None = None, percorso: Path | None = None) -> list[dict[str, Any]]:
    with _connessione(percorso) as conn:
        conn.row_factory = sqlite3.Row
        if bot:
            righe = conn.execute(
                "SELECT id, quando, bot, seed, passi, fine, medaglie, punti"
                " FROM partite WHERE bot = ? ORDER BY id DESC LIMIT ?", (bot, n)
            ).fetchall()
        else:
            righe = conn.execute(
                "SELECT id, quando, bot, seed, passi, fine, medaglie, punti"
                " FROM partite ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [dict(r) for r in righe]


def formatta_riepilogo(righe: list[dict[str, Any]]) -> str:
    if not righe:
        return "nessuna partita registrata"
    testa = (
        f"{'bot':<12}{'partite':>8}{'vinte':>7}{'punti medi':>12}"
        f"{'min':>7}{'max':>7}{'passi':>8}{'KO':>7}{'svenuti':>9}"
    )
    out = [testa, "-" * len(testa)]
    for r in righe:
        out.append(
            f"{r['bot']:<12}{r['partite']:>8}{r['vittorie'] or 0:>7}"
            f"{r['punti_medi'] if r['punti_medi'] is not None else '-':>12}"
            f"{r['punti_min'] if r['punti_min'] is not None else '-':>7}"
            f"{r['punti_max'] if r['punti_max'] is not None else '-':>7}"
            f"{r['passi_medi'] if r['passi_medi'] is not None else '-':>8}"
            f"{r['ko_medi'] if r['ko_medi'] is not None else '-':>7}"
            f"{r['svenuti_medi'] if r['svenuti_medi'] is not None else '-':>9}"
        )
    return "\n".join(out)
