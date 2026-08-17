"""Fast tests: no browser, no network, no game copy needed."""

from __future__ import annotations

import pytest

from pokelike.assets.mirror import _contenuto_valido
from pokelike.bot import DISPONIBILI, crea
from pokelike.bot.base import Bot
from pokelike.core import render
from pokelike.statistiche import formatta_riepilogo, registra, riepilogo, ultime

# --------------------------------------------------------------- mirror


GUSCIO_SPA = b"<!DOCTYPE html><html>"


@pytest.mark.parametrize(
    "dati,suffisso,atteso",
    [
        (b"\x89PNG\r\n\x1a\n", ".png", True),
        (GUSCIO_SPA, ".png", False),          # il caso che riempì il mirror di spazzatura
        (b"\xff\xd8\xff\xe0", ".jpg", True),
        (b"ID3\x04", ".mp3", True),
        (GUSCIO_SPA, ".mp3", False),
        (b"", ".png", False),
        (b"body { }", ".css", True),
    ],
)
def test_riconosce_i_file_validi(dati, suffisso, atteso):
    assert _contenuto_valido(dati, suffisso) is atteso


# ------------------------------------------------------------------ bot


def test_i_bot_registrati_si_costruiscono():
    assert "casuale" in DISPONIBILI
    assert isinstance(crea("casuale", seed=1), Bot)


def test_bot_sconosciuto_da_errore_utile():
    with pytest.raises(KeyError) as e:
        crea("inesistente")
    assert "casuale" in e.value.args[0]


def test_bot_casuale_e_riproducibile():
    stato = {"azioni": [{}] * 5, "passi": 0}
    a = crea("casuale", seed=7)
    b = crea("casuale", seed=7)
    a.inizio(7)
    b.inizio(7)
    assert [a.scegli(stato) for _ in range(20)] == [b.scegli(stato) for _ in range(20)]


def test_bot_casuale_resta_nel_range():
    stato = {"azioni": [{}] * 3, "passi": 0}
    b = crea("casuale", seed=1)
    b.inizio(1)
    assert all(0 <= b.scegli(stato) < 3 for _ in range(50))


def test_bot_astratto_non_si_istanzia():
    with pytest.raises(TypeError):
        Bot()


# --------------------------------------------------------------- render


STATO_ESEMPIO = {
    "schermata": "map-screen",
    "passi": 4,
    "run": {"mappa": 0, "medaglie": 1},
    "squadra": [
        {"nome": "Bulbasaur", "livello": 5, "hp": 19, "hp_max": 19,
         "tipi": ["Grass", "Poison"], "oggetto": None, "shiny": True},
        {"nome": "Charmander", "livello": 7, "hp": 0, "hp_max": 22,
         "tipi": ["Fire"], "oggetto": "Life Orb", "shiny": False},
    ],
    "zaino": ["Potion"],
    "mappa": {
        "nodi": [
            {"id": "n0_0", "tipo": "start", "livello": 0, "colonna": 0,
             "accessibile": False, "visitato": True, "rivelato": True},
            {"id": "n1_0", "tipo": "catch", "livello": 1, "colonna": 0,
             "accessibile": True, "visitato": False, "rivelato": True},
            {"id": "n1_1", "tipo": "battle", "livello": 1, "colonna": 1,
             "accessibile": True, "visitato": False, "rivelato": True},
            {"id": "n9_9", "tipo": "boss", "livello": 9, "colonna": 0,
             "accessibile": False, "visitato": False, "rivelato": False},
        ],
        "archi": [["n0_0", "n1_0"], ["n0_0", "n1_1"]],
        "attuale": "n0_0",
    },
    "azioni": [
        {"tipo": "nodo", "id": "n1_0", "nodo": "catch", "livello": 1, "colonna": 0},
        {"tipo": "nodo", "id": "n1_1", "nodo": "battle", "livello": 1, "colonna": 1},
    ],
    "finita": False,
}


def test_la_mappa_marca_posizione_e_mosse_legali():
    testo = render.mappa(STATO_ESEMPIO["mappa"])
    assert "[@]" in testo, "la posizione attuale non è marcata"
    assert "<o>" in testo and "<x>" in testo, "le mosse legali non sono marcate"
    assert "B" not in testo, "un nodo non rivelato non deve comparire"


def test_la_squadra_mostra_hp_e_shiny():
    testo = render.squadra(STATO_ESEMPIO["squadra"])
    assert "Bulbasaur" in testo and "19/19" in testo
    assert "Life Orb" in testo
    assert "*" in testo, "lo shiny non è marcato"


def test_le_azioni_sono_numerate_da_zero():
    testo = render.azioni(STATO_ESEMPIO["azioni"])
    assert "[0]" in testo and "[1]" in testo


def test_lo_schermo_regge_uno_stato_vuoto():
    """A caller should never get an exception just for rendering early state."""
    assert render.schermo({"azioni": []})


def test_lo_schermo_contiene_i_pezzi():
    testo = render.schermo(STATO_ESEMPIO)
    for pezzo in ("Bulbasaur", "n1_0", "[@]"):
        assert pezzo in testo


# ---------------------------------------------------------- statistiche


STATO_FINALE = {"schermata": "gameover-screen", "run": {"medaglie": 2}, "squadra": []}
STATO_VIVO = {"run": {"medaglie": 2}, "squadra": [{"nome": "Pikachu", "livello": 12,
                                                   "hp": 3, "hp_max": 30}]}
PUNTEGGIO = {
    "punti": 1005,
    "punti_senza_tempo": 25,
    "dettaglio": {"enemiesKO": 9, "faints": 4, "mapsCleared": 1,
                  "winBonus": 0, "legendaries": 0, "shinies": 0, "timeBonus": 980},
    "statistiche": {"catches": 3, "totalDamageDealt": 220, "highestLevel": 12},
}


def test_registra_e_rilegge(db_temporaneo):
    idx = registra(bot="prova", seed=1, stato=STATO_FINALE, punteggio=PUNTEGGIO,
                   passi=17, vivo=STATO_VIVO, percorso=db_temporaneo)
    assert idx > 0
    righe = ultime(5, percorso=db_temporaneo)
    assert len(righe) == 1
    assert righe[0]["bot"] == "prova"
    assert righe[0]["punti"] == 25, "deve salvare il punteggio senza bonus tempo"


def test_la_squadra_arriva_dallo_stato_vivo(db_temporaneo):
    """The regression that started this: at game over the final state is empty."""
    import json

    registra(bot="prova", seed=1, stato=STATO_FINALE, punteggio=PUNTEGGIO,
             passi=17, vivo=STATO_VIVO, percorso=db_temporaneo)
    import sqlite3

    conn = sqlite3.connect(db_temporaneo)
    (squadra,) = conn.execute("SELECT squadra FROM partite").fetchone()
    assert json.loads(squadra)[0]["nome"] == "Pikachu"


def test_riepilogo_aggrega_per_bot(db_temporaneo):
    for seed in (1, 2, 3):
        registra(bot="alfa", seed=seed, stato=STATO_FINALE, punteggio=PUNTEGGIO,
                 passi=10, vivo=STATO_VIVO, percorso=db_temporaneo)
    registra(bot="beta", seed=1, stato=STATO_FINALE, punteggio=PUNTEGGIO,
             passi=10, vivo=STATO_VIVO, percorso=db_temporaneo)

    righe = {r["bot"]: r for r in riepilogo(percorso=db_temporaneo)}
    assert righe["alfa"]["run"] == 3
    assert righe["beta"]["run"] == 1
    assert righe["alfa"]["medaglie_max"] == 2
    assert righe["alfa"]["punti_medi"] == 25


def test_riepilogo_vuoto_non_esplode(db_temporaneo):
    assert "nessuna" in formatta_riepilogo(riepilogo(percorso=db_temporaneo))


def test_i_dettagli_spiegano_le_colonne(db_temporaneo):
    registra(bot="alfa", seed=1, stato=STATO_FINALE, punteggio=PUNTEGGIO,
             passi=10, vivo=STATO_VIVO, percorso=db_temporaneo)
    righe = riepilogo(percorso=db_temporaneo)
    corto = formatta_riepilogo(righe)
    lungo = formatta_riepilogo(righe, dettagli=True)
    assert len(lungo) > len(corto)
