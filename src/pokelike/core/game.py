"""Logica di gioco comune. CLI e API sono due facce sottili sopra questa classe.

Il modello è quello di un ambiente a turni:

    g = Partita()
    g.nuova(seed=42)
    g.stato()        -> dizionario con squadra, mappa, azioni legali
    g.esegui(1)      -> applica l'azione 1 e restituisce il nuovo stato
    g.punteggio()    -> punteggio calcolato con la formula del gioco

Fra una decisione e l'altra il motore fa un sacco di cose da solo (riproduce la
battaglia, mostra i passaggi di livello, i banner). Non sono scelte del
giocatore, quindi `_assesta()` le fa scorrere e restituisce il controllo solo
quando c'è davvero più di un'opzione, o la partita è finita.
"""

from __future__ import annotations

import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .browser import Sessione


class ErroreAzione(RuntimeError):
    """Azione non valida nello stato corrente."""


@dataclass
class Partita:
    url: str = "http://127.0.0.1:8422/"
    visibile: bool = False
    attesa_max: int = 1
    punteggio_attivo: bool = True

    sessione: Sessione | None = field(default=None, repr=False)
    seed: int | None = None
    passi: int = 0
    aggancio_punteggio: dict[str, Any] | None = field(default=None, repr=False)
    ultimo_vivo: dict[str, Any] | None = field(default=None, repr=False)
    _ultimo: dict[str, Any] | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ avvio

    def apri(self) -> None:
        self.sessione = Sessione(
            url=self.url, visibile=self.visibile, attesa_max=self.attesa_max
        )
        self.sessione.avvia()

    def chiudi(self) -> None:
        if self.sessione is not None:
            self.sessione.chiudi()
            self.sessione = None

    def __enter__(self) -> "Partita":
        self.apri()
        return self

    def __exit__(self, *_exc) -> None:
        self.chiudi()

    # ----------------------------------------------------------------- partita

    def nuova(self, seed: int = 0) -> dict[str, Any]:
        """Comincia una partita in modalità Storia, regione Kanto, regole classiche.

        La scelta dell'allenatore e dello starter NON viene fatta qui: restano
        decisioni del giocatore e compaiono come primi due turni.
        """
        if self.sessione is None:
            self.apri()
        assert self.sessione is not None

        self.seed = seed
        self.passi = 0
        self.ultimo_vivo = None
        page = self.sessione.carica(seed)

        page.evaluate("() => { const b = document.getElementById('btn-history-run'); if (b) b.click(); }")
        page.wait_for_timeout(300)
        page.evaluate(
            "() => { const b = document.querySelector('.history-region-btn');"
            " if (b) b.dispatchEvent(new MouseEvent('click', {bubbles: true})); }"
        )
        page.wait_for_timeout(300)

        if self.punteggio_attivo:
            # Il punteggio è un extra: se l'aggancio fallisce la partita deve
            # comunque andare avanti.
            try:
                self.aggancio_punteggio = page.evaluate(
                    "() => window.__pk_aggancia_punteggio()"
                )
            except Exception as e:  # noqa: BLE001
                self.aggancio_punteggio = {"ok": False, "motivo": str(e)[:200]}

        return self._assesta()

    # ------------------------------------------------------------ osservazione

    def stato(self) -> dict[str, Any]:
        """Lo stato corrente. Sola lettura: non fa avanzare il gioco."""
        if self.sessione is None or self.sessione.page is None:
            raise RuntimeError("nessuna partita aperta: chiama nuova()")
        obs = self.sessione.page.evaluate("() => window.__pk_obs()")
        obs["passi"] = self.passi
        obs["seed"] = self.seed
        obs["finita"] = self._e_finale()
        self._ultimo = obs
        # Sulla schermata di game over il motore azzera `state`: squadra vuota e
        # medaglie assenti. Teniamo da parte l'ultima istantanea con la partita
        # ancora viva, altrimenti il riepilogo di fine partita non ha nulla da
        # raccontare.
        if obs.get("squadra"):
            self.ultimo_vivo = obs
        return obs

    def azioni(self) -> list[dict[str, Any]]:
        return self.stato().get("azioni", [])

    # ----------------------------------------------------------------- azione

    def esegui(self, indice: int) -> dict[str, Any]:
        """Applica l'azione `indice` fra quelle legali e restituisce il nuovo stato."""
        assert self.sessione is not None and self.sessione.page is not None
        azioni = (self._ultimo or self.stato()).get("azioni", [])
        if not 0 <= indice < len(azioni):
            raise ErroreAzione(
                f"indice {indice} fuori range: ci sono {len(azioni)} azioni legali"
            )
        scelta = azioni[indice]
        ok = self.sessione.page.evaluate("c => window.__pk_apply(c)", scelta)
        if not ok:
            raise ErroreAzione(f"il motore ha rifiutato l'azione: {scelta}")
        self.passi += 1
        self.sessione.page.wait_for_timeout(70)
        return self._assesta()

    # -------------------------------------------------------------- punteggio

    def punteggio(self) -> dict[str, Any] | None:
        """Punteggio secondo la formula del gioco.

            500 se completata + 5·KO − 10·svenimenti + 50·mappe
            + 20·leggendari + 20·shiny + bonus tempo

        Restituisce None se l'aggancio alle statistiche non è attivo.
        """
        if self.sessione is None or self.sessione.page is None:
            return None
        completata = (self._ultimo or {}).get("schermata") == "win-screen"
        return self.sessione.page.evaluate("c => window.__pk_punteggio(c)", completata)

    # ---------------------------------------------------------------- interni

    def foto(self, percorso: str | Path) -> Path:
        """Salva un'immagine della schermata attuale.

        Non è una cattura dello schermo: non c'è nessuno schermo. È il motore di
        rendering del browser che disegna in memoria su richiesta e ci consegna
        i byte del PNG. Funziona identico anche in headless.
        """
        if self.sessione is None or self.sessione.page is None:
            raise RuntimeError("nessuna partita aperta")
        p = Path(percorso)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.sessione.page.screenshot(path=str(p))
        return p

    def _e_finale(self) -> bool:
        assert self.sessione is not None and self.sessione.page is not None
        return self.sessione.page.evaluate("() => window.__pk_stato_punto()") == "finale"

    def _assesta(self, timeout_s: float = 90.0) -> dict[str, Any]:
        """Fa scorrere tutto ciò che non è una scelta, poi restituisce lo stato."""
        assert self.sessione is not None and self.sessione.page is not None
        page = self.sessione.page
        inizio = time.monotonic()
        fermi = 0

        while time.monotonic() - inizio < timeout_s:
            punto = page.evaluate("() => window.__pk_stato_punto()")
            if punto == "finale":
                return self.stato()
            if punto == "decisione":
                n = page.evaluate("() => window.__pk_choices().length")
                if n > 1:
                    return self.stato()
                if n == 1:
                    # Scelta obbligata: non è una decisione, la prendiamo noi.
                    page.evaluate("() => window.__pk_apply(window.__pk_choices()[0])")
                    page.wait_for_timeout(100)
                    continue
            avanzato = page.evaluate("() => window.__pk_avanza()")
            if not avanzato:
                fermi += 1
                if fermi > 200:
                    break
            else:
                fermi = 0
            page.wait_for_timeout(50 if avanzato else 100)

        stato = self.stato()
        stato["bloccata"] = True
        return stato
