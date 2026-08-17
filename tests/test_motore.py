"""The contract of `Partita`: what callers are allowed to rely on."""

from __future__ import annotations

import pytest

from pokelike.core.game import ErroreAzione


@pytest.mark.slow
def test_stato_ha_le_chiavi_attese(partita):
    obs = partita.nuova(seed=3)
    for chiave in ("schermata", "azioni", "passi", "seed", "finita"):
        assert chiave in obs, f"manca {chiave}"
    assert obs["seed"] == 3
    assert obs["passi"] == 0
    assert obs["finita"] is False


@pytest.mark.slow
def test_ogni_decisione_offre_almeno_due_scelte(partita):
    """`_assesta` must never hand back a turn with nothing to decide."""
    obs = partita.nuova(seed=4)
    for _ in range(8):
        if obs["finita"]:
            break
        assert len(obs["azioni"]) >= 2, f"turno senza scelta su {obs['schermata']}"
        obs = partita.esegui(0)


@pytest.mark.slow
def test_stato_non_fa_avanzare_il_gioco(partita):
    partita.nuova(seed=6)
    prima = partita.stato()
    dopo = partita.stato()
    assert prima["passi"] == dopo["passi"]
    assert prima["azioni"] == dopo["azioni"]


@pytest.mark.slow
@pytest.mark.parametrize("indice", [-1, 99])
def test_azione_illegale_viene_rifiutata(partita, indice):
    partita.nuova(seed=8)
    with pytest.raises(ErroreAzione):
        partita.esegui(indice)


@pytest.mark.slow
def test_i_passi_avanzano_di_uno(partita):
    obs = partita.nuova(seed=9)
    prima = obs["passi"]
    obs = partita.esegui(0)
    assert obs["passi"] == prima + 1


@pytest.mark.slow
def test_aggancio_punteggio_attivo(partita):
    """The score hook must attach, otherwise every score would be None."""
    partita.nuova(seed=10)
    assert partita.aggancio_punteggio is not None
    assert partita.aggancio_punteggio.get("ok") is True


@pytest.mark.slow
def test_le_statistiche_arrivano_a_ogni_passo(partita):
    """Per-step counters are what an RL reward would be built from."""
    obs = partita.nuova(seed=13)
    for _ in range(6):
        if obs["finita"] or not obs["azioni"]:
            break
        obs = partita.esegui(0)
    assert "statistiche" in obs
    assert "enemiesKO" in obs["statistiche"]


@pytest.mark.slow
def test_ultimo_vivo_sopravvive_al_game_over(partita):
    """At game over the engine wipes `state`; the snapshot must keep the team."""
    obs = partita.nuova(seed=1)
    while not obs["finita"] and obs["azioni"] and partita.passi < 60:
        obs = partita.esegui(0)
    assert obs["finita"]
    assert not obs.get("squadra")
    assert partita.ultimo_vivo is not None
    assert partita.ultimo_vivo["squadra"], "la squadra è andata persa"


@pytest.mark.slow
def test_la_mappa_e_un_grafo_coerente(partita):
    obs = partita.nuova(seed=14)
    while not obs["finita"] and obs["schermata"] != "map-screen":
        obs = partita.esegui(0)
    mappa = obs["mappa"]
    ids = {n["id"] for n in mappa["nodi"]}
    for da, a in mappa["archi"]:
        assert da in ids and a in ids, f"arco verso un nodo inesistente: {da}->{a}"
    legali = {a["id"] for a in obs["azioni"] if a["tipo"] == "nodo"}
    accessibili = {n["id"] for n in mappa["nodi"] if n["accessibile"] and not n["visitato"]}
    assert legali == accessibili
