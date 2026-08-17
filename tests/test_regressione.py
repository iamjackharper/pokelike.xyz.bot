"""The regression net: recorded games must replay identically.

If any of these fail after a refactor, behaviour changed. The fingerprint holds
only engine data, so a rename or a translation of our own strings cannot make it
fail — only a real change in how the game is played.
"""

from __future__ import annotations

import pytest
from impronta import CASI, carica_golden, impronta


@pytest.mark.slow
@pytest.mark.parametrize("seed,politica", CASI, ids=lambda v: str(v))
def test_partita_riproduce_il_golden(partita, seed, politica):
    atteso = carica_golden()[f"{seed}-{politica}"]
    ottenuto = impronta(partita, seed, politica)

    # Compared field by field so a failure says *what* moved, not just "differs".
    assert ottenuto["passi"] == atteso["passi"], "numero di decisioni diverso"
    assert ottenuto["schermata_finale"] == atteso["schermata_finale"], "finale diverso"
    assert ottenuto["punti"] == atteso["punti"], "punteggio diverso"
    assert ottenuto["dettaglio"] == atteso["dettaglio"], "voci del punteggio diverse"
    assert ottenuto["squadra"] == atteso["squadra"], "squadra finale diversa"
    assert ottenuto["traccia"] == atteso["traccia"], "sequenza di decisioni diversa"


@pytest.mark.slow
def test_stesso_seed_stessa_partita(partita):
    """Determinism: replaying a seed with the same policy gives the same game."""
    a = impronta(partita, 5, "fissa")
    b = impronta(partita, 5, "fissa")
    assert a == b


@pytest.mark.slow
def test_seed_diversi_partite_diverse(partita):
    """Sanity check on the other side: the seed must actually matter."""
    a = impronta(partita, 11, "ciclica")
    b = impronta(partita, 12, "ciclica")
    assert a["traccia"] != b["traccia"]
