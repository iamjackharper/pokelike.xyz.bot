"""Bot che sceglie a caso fra le azioni legali.

Non guarda nulla dello stato: né HP, né tipi, né cosa c'è più avanti sulla mappa.
Serve come linea di base — muore quasi sempre entro una ventina di mosse senza
mai completare la prima mappa, quindi qualunque giocatore vero deve battere
questo.

È riproducibile: con lo stesso seed rifà la stessa identica partita.
"""

from __future__ import annotations

import random
from typing import Any

from .base import Bot


class BotCasuale(Bot):
    nome = "casuale"

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self._rnd = random.Random(seed)

    def inizio(self, seed: int) -> None:
        # Riparte dal seed della partita, così la sequenza di scelte è legata
        # alla partita e non a quante ne sono state giocate prima.
        self._rnd = random.Random(seed)

    def scegli(self, stato: dict[str, Any]) -> int:
        return self._rnd.randrange(len(stato["azioni"]))
