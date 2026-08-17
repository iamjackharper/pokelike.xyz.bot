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
            "       COUNT(*)                 AS run,"
            "       SUM(vinta)               AS albo,"
            "       ROUND(AVG(medaglie), 2)  AS medaglie_medie,"
            "       MAX(medaglie)            AS medaglie_max,"
            "       ROUND(AVG(mappe), 2)     AS mappe_medie,"
            "       MAX(mappe)               AS mappe_max,"
            "       ROUND(AVG(punti), 1)     AS punti_medi,"
            "       MIN(punti)               AS punti_min,"
            "       MAX(punti)               AS punti_max,"
            "       ROUND(AVG(catture), 1)   AS catture_medie,"
            "       ROUND(AVG(ko), 1)        AS ko_medi,"
            "       ROUND(AVG(svenuti), 1)   AS esausti_medi,"
            "       ROUND(AVG(livello_max),1) AS livello_medio,"
            "       ROUND(AVG(passi), 1)     AS decisioni_medie"
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


# (chiave nel dizionario, intestazione, larghezza)
COLONNE = [
    ("bot", "bot", 11),
    ("run", "run", 5),
    ("albo", "albo", 6),
    ("medaglie_medie", "badge~", 8),
    ("medaglie_max", "badge+", 7),
    ("mappe_medie", "mappe~", 8),
    ("mappe_max", "mappe+", 7),
    ("punti_medi", "score~", 8),
    ("punti_min", "score-", 7),
    ("punti_max", "score+", 7),
    ("catture_medie", "catt~", 7),
    ("ko_medi", "KO~", 6),
    ("esausti_medi", "esaust~", 8),
    ("livello_medio", "Lv max~", 8),
    ("decisioni_medie", "scelte~", 8),
]

SPIEGAZIONE = """
COSA SIGNIFICA OGNI COLONNA
  ~ = media sulle partite     + = massimo raggiunto

  bot        quale bot ha giocato
  run        quante partite ha giocato (una run = dallo starter al game over)
  albo       run COMPLETATE, cioè arrivate alla schermata di vittoria battendo
             tutta la Lega. NON sono le medaglie: con 0 qui e 3 badge vuol dire
             che è arrivato a tre palestre e poi è morto
  badge~ +   medaglie di palestra prese (Gym Badges). Ce ne sono 8 per regione
  mappe~ +   mappe completate: ogni mappa è una tabella di nodi con un boss in
             fondo, completarla vale +50 punti
  score~     punteggio medio, con la formula del gioco:
                 +500  se completi la partita
                 +  5  per ogni nemico messo KO
                 -  10 per ogni Pokémon esausto
                 + 50  per ogni mappa completata
                 + 20  per ogni leggendario e per ogni shiny in squadra
             NON include il bonus tempo, che vale ~1000 e coprirebbe tutto
  score- +   il peggiore e il migliore, per vedere quanto è costante
  catt~      Pokémon catturati (la squadra arriva a 6)
  KO~        Pokémon avversari sconfitti
  esaust~    Pokémon TUOI andati KO. Costano -10 l'uno: è la voce che affonda
             i punteggi
  Lv max~    livello del Pokémon più alto raggiunto in squadra
  scelte~    quante decisioni ha preso il bot prima di finire. Le battaglie si
             giocano da sole, quindi è il numero di bivi affrontati
"""


def formatta_riepilogo(righe: list[dict[str, Any]], dettagli: bool = False) -> str:
    if not righe:
        return "nessuna partita registrata"

    testa = f"{COLONNE[0][1]:<{COLONNE[0][2]}}" + "".join(
        f"{nome:>{largh}}" for _, nome, largh in COLONNE[1:]
    )
    out = [testa, "-" * len(testa)]
    for r in righe:
        cella = [f"{str(r.get('bot', '')):<{COLONNE[0][2]}}"]
        for chiave, _, largh in COLONNE[1:]:
            v = r.get(chiave)
            cella.append(f"{'-' if v is None else v:>{largh}}")
        out.append("".join(cella))

    if dettagli:
        out.append(SPIEGAZIONE)
    return "\n".join(out)
