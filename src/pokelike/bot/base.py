"""Interfaccia comune a tutti i bot.

Un bot è una cosa sola: qualcosa che, dato lo stato, dice **quale azione fare**.
Tutto il resto (avviare il browser, applicare la mossa, calcolare il punteggio)
non lo riguarda.

    class MioBot(Bot):
        def scegli(self, stato):
            return 0          # indice dentro stato["azioni"]

L'indice è la posizione dentro `stato["azioni"]`, la stessa lista numerata che
vedi giocando da CLI. Restituire un indice fuori range fa fallire la mossa, quindi
un bot deve sempre stare dentro `len(stato["azioni"])`.

I due agganci `inizio` e `fine` servono ai bot che hanno bisogno di memoria fra
un turno e l'altro:

- un **LLM** azzera la conversazione in `inizio` e la chiude in `fine`;
- un algoritmo **RL** accumula la traiettoria e in `fine` riceve il punteggio
  finale, che è il segnale di ricompensa;
- un bot a **mosse prefissate** rimette a zero il contatore in `inizio`.

Chi non ne ha bisogno li ignora: hanno già un'implementazione vuota.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Bot(ABC):
    """Base di ogni bot. L'unico metodo obbligatorio è `scegli`."""

    nome = "bot"

    @abstractmethod
    def scegli(self, stato: dict[str, Any]) -> int:
        """Indice dell'azione scelta dentro `stato["azioni"]`.

        `stato` è il dizionario completo: `squadra`, `zaino`, `mappa`, `run`,
        `azioni`, `passi`, `schermata`. Vedi `core/render.py` per come si legge.
        """

    def inizio(self, seed: int) -> None:
        """Chiamato prima del primo turno di ogni partita."""

    def fine(self, stato: dict[str, Any], punteggio: dict[str, Any] | None) -> None:
        """Chiamato a partita conclusa, con lo stato finale e il punteggio."""
