"""Bot guidato da un LLM, con loop agentico e strumenti.

Tutto quello che serve sta in questo file: configurazione, prompt, strumenti,
chiamata HTTP. Nessuna dipendenza esterna — parla con un endpoint compatibile
OpenAI usando `urllib` della libreria standard.

Configurazione, solo da variabili d'ambiente (mai chiavi nel codice):

    export FW_ENDPOINT="https://..."
    export FW_TOKEN="..."
    export MODEL_ID="glm-5.2-nvfp4"     # opzionale
    pokelike bot --bot llm --partite 3

Come funziona un turno: al modello arriva la situazione in testo e la lista delle
azioni numerate. Può chiamare strumenti di sola lettura per approfondire, e
chiude chiamando `gioca(indice)`. Se non lo fa entro `max_giri`, o se qualcosa
va storto, si ripiega su una scelta di riserva: **una partita non deve mai
morire per colpa del modello**.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..core import render
from .base import Bot

# --------------------------------------------------------------------- prompt

SISTEMA = """Stai giocando a Pokelike, un roguelike Pokémon. Giochi per fare punti.

COME FUNZIONA
- La mappa è un grafo a livelli, dall'alto verso il basso. In fondo c'è il boss.
- A ogni turno scegli un nodo fra quelli legali. Appena ne scegli uno, gli altri
  nodi dello stesso livello si CHIUDONO PER SEMPRE: è una scelta irreversibile.
- Le battaglie si risolvono da sole: non scegli le mosse. Quello che decidi è
  dove andare, chi catturare, quale oggetto prendere e a chi darlo.
- La squadra arriva a 6 Pokémon. Se muoiono tutti la partita finisce.

TIPI DI NODO
  o cattura      aggiunge un Pokémon alla squadra
  x lotta        un Pokémon selvatico, dà esperienza
  T allenatore   1 Pokémon sulla mappa 0, 2 sulle mappe 1-2, 3 dalla mappa 3
  i oggetto      un oggetto da equipaggiare o tenere nello zaino
  + centro cure  ripristina gli HP
  ? ignoto       si rivela solo quando ci entri
  $ scambio      M tutor mosse    S negozio    B boss

COME SI FANNO PUNTI
  +5 per nemico sconfitto, +50 per mappa completata, +20 per shiny o leggendario
  -10 per ogni Pokémon che sviene, +500 se completi la partita
Quindi: perdere Pokémon costa caro, e avanzare vale molto più che accumulare.

CONSIGLI CHE VALGONO
- All'inizio hai 1 solo Pokémon: se sviene hai perso. Prima si allarga la squadra.
- Un Pokémon con pochi HP che entra in battaglia rischia di svenire: -10 punti.
- Le debolezze di tipo decidono le battaglie: controlla la squadra prima di
  scegliere una lotta.

COME RISPONDI
Puoi chiamare gli strumenti di sola lettura per capire meglio la situazione.
Quando hai deciso, chiama `gioca` con l'indice dell'azione. Chiama SEMPRE `gioca`
per chiudere il turno. Ragiona in breve."""

STRUMENTI = [
    {
        "type": "function",
        "function": {
            "name": "dettagli_squadra",
            "description": "Statistiche complete della squadra: HP, livelli, tipi, oggetti tenuti.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cosa_c_e_avanti",
            "description": (
                "Per ogni azione legale, dice a quali nodi porta al livello successivo. "
                "Utile per non chiudersi strade: la scelta di adesso decide cosa potrai fare dopo."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gioca",
            "description": "Esegue l'azione scelta e chiude il turno.",
            "parameters": {
                "type": "object",
                "properties": {
                    "indice": {"type": "integer", "description": "indice dell'azione legale"},
                    "perche": {"type": "string", "description": "una frase sul motivo"},
                },
                "required": ["indice", "perche"],
            },
        },
    },
]


class ErroreLLM(RuntimeError):
    pass


# ------------------------------------------------------------------------ bot


class BotLLM(Bot):
    nome = "llm"

    def __init__(
        self,
        seed: int = 0,
        endpoint: str | None = None,
        token: str | None = None,
        modello: str | None = None,
        max_giri: int = 4,
        max_token: int = 1500,
        temperatura: float = 0.6,
        memoria: int = 6,
        verboso: bool = False,
    ) -> None:
        self.endpoint = (endpoint or os.environ.get("FW_ENDPOINT", "")).rstrip("/")
        self.token = token or os.environ.get("FW_TOKEN", "")
        self.modello = modello or os.environ.get("MODEL_ID", "glm-5.2-nvfp4")
        if not self.endpoint or not self.token:
            raise ErroreLLM(
                "servono le variabili d'ambiente FW_ENDPOINT e FW_TOKEN\n"
                '  export FW_ENDPOINT="https://..."\n  export FW_TOKEN="..."'
            )
        self.max_giri = max_giri
        self.max_token = max_token
        self.temperatura = temperatura
        self.memoria = memoria
        self.verboso = verboso or bool(os.environ.get("POKELIKE_VERBOSO"))

        # contatori per il registro statistiche
        self.chiamate = 0
        self.token_usati = 0
        self.ripieghi = 0
        self.diario: list[str] = []

    # --------------------------------------------------------------- agganci

    def inizio(self, seed: int) -> None:
        self.diario = []
        self.chiamate = 0
        self.token_usati = 0
        self.ripieghi = 0

    def note(self) -> dict[str, Any]:
        """Finisce nella colonna `extra` del registro partite."""
        return {
            "modello": self.modello,
            "chiamate": self.chiamate,
            "token": self.token_usati,
            "ripieghi": self.ripieghi,
        }

    # ------------------------------------------------------------ decisione

    def scegli(self, stato: dict[str, Any]) -> int:
        n = len(stato["azioni"])
        try:
            indice, perche = self._giro_agentico(stato)
        except Exception as e:  # noqa: BLE001 — nessun errore deve fermare la partita
            self.ripieghi += 1
            if self.verboso:
                print(f"   [llm] ripiego: {type(e).__name__}: {e}")
            return self._riserva(stato)

        if not isinstance(indice, int) or not 0 <= indice < n:
            self.ripieghi += 1
            if self.verboso:
                print(f"   [llm] indice non valido ({indice}), ripiego")
            return self._riserva(stato)

        self.diario.append(f"passo {stato.get('passi')}: [{indice}] {perche[:90]}")
        self.diario = self.diario[-self.memoria:]
        if self.verboso:
            print(f"   [llm] -> [{indice}] {perche[:100]}")
        return indice

    def _riserva(self, stato: dict[str, Any]) -> int:
        """Scelta di riserva quando il modello non risponde o sbaglia.

        Non casuale: preferisce ciò che tiene in vita la squadra — prima curarsi
        se qualcuno sta male, poi allargare la squadra.
        """
        azioni = stato["azioni"]
        squadra = stato.get("squadra") or []
        malmessi = [p for p in squadra if p["hp_max"] and p["hp"] / p["hp_max"] < 0.4]

        ordine = ["pokecenter", "catch", "item"] if malmessi else ["catch", "item", "pokecenter"]
        for tipo in ordine:
            for i, a in enumerate(azioni):
                if a.get("nodo") == tipo:
                    return i
        return 0

    # ------------------------------------------------------- loop agentico

    def _giro_agentico(self, stato: dict[str, Any]) -> tuple[int, str]:
        messaggi: list[dict[str, Any]] = [
            {"role": "system", "content": SISTEMA},
            {"role": "user", "content": self._situazione(stato)},
        ]

        for _ in range(self.max_giri):
            msg = self._chiama(messaggi)
            chiamate = msg.get("tool_calls") or []
            if not chiamate:
                # Nessuno strumento: forse ha scritto l'indice a parole.
                indice = self._indice_dal_testo(msg.get("content") or "", len(stato["azioni"]))
                if indice is not None:
                    return indice, "(dedotto dal testo)"
                raise ErroreLLM("il modello non ha chiamato nessuno strumento")

            messaggi.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": chiamate,
            })

            for c in chiamate:
                nome = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                if nome == "gioca":
                    return args.get("indice"), str(args.get("perche", ""))

                messaggi.append({
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "content": self._esegui_strumento(nome, stato),
                })

        raise ErroreLLM(f"nessuna chiamata a gioca() in {self.max_giri} giri")

    def _esegui_strumento(self, nome: str, stato: dict[str, Any]) -> str:
        if nome == "dettagli_squadra":
            return render.squadra(stato.get("squadra")) or "(squadra vuota)"
        if nome == "cosa_c_e_avanti":
            return self._sbocchi(stato)
        return f"strumento sconosciuto: {nome}"

    # ------------------------------------------------------------- contesto

    def _situazione(self, stato: dict[str, Any]) -> str:
        parti = [render.schermo(stato)]
        if self.diario:
            parti += ["", "LE TUE ULTIME MOSSE:", *(f"  {r}" for r in self.diario)]
        parti += [
            "",
            f"Scegli un indice fra 0 e {len(stato['azioni']) - 1} e chiama gioca().",
        ]
        return "\n".join(parti)

    def _sbocchi(self, stato: dict[str, Any]) -> str:
        """Dove porta ogni azione legale, guardando gli archi della mappa."""
        mappa = stato.get("mappa")
        if not mappa:
            return "Non sei sulla mappa: questa scelta non apre o chiude percorsi."
        per_id = {n["id"]: n for n in mappa["nodi"]}
        righe = []
        for i, a in enumerate(stato["azioni"]):
            if a.get("tipo") != "nodo":
                righe.append(f"  [{i}] {a.get('etichetta', '')[:60]}")
                continue
            dopo = [per_id[t]["tipo"] for f, t in mappa["archi"] if f == a["id"] and t in per_id]
            seguito = ", ".join(sorted(dopo)) if dopo else "niente (fine mappa)"
            righe.append(f"  [{i}] {a['nodo']:<12} -> porta a: {seguito}")
        return "Sbocchi al livello successivo:\n" + "\n".join(righe)

    # ------------------------------------------------------------------ HTTP

    def _chiama(self, messaggi: list[dict[str, Any]]) -> dict[str, Any]:
        corpo = json.dumps({
            "model": self.modello,
            "messages": messaggi,
            "tools": STRUMENTI,
            "tool_choice": "auto",
            "max_tokens": self.max_token,
            "temperature": self.temperatura,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.endpoint}/v1/chat/completions",
            data=corpo,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                risposta = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ErroreLLM(f"HTTP {e.code}: {e.read()[:200]!r}") from e
        except Exception as e:  # rete, timeout, JSON malformato
            raise ErroreLLM(f"{type(e).__name__}: {e}") from e

        self.chiamate += 1
        self.token_usati += (risposta.get("usage") or {}).get("total_tokens", 0)
        scelte = risposta.get("choices") or []
        if not scelte:
            raise ErroreLLM("risposta senza choices")
        return scelte[0].get("message") or {}

    @staticmethod
    def _indice_dal_testo(testo: str, n: int) -> int | None:
        """Ultima spiaggia: pesca un indice valido da una risposta a parole."""
        import re

        for m in re.finditer(r"\[?(\d+)\]?", testo):
            v = int(m.group(1))
            if 0 <= v < n:
                return v
        return None
