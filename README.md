# pokelike.xyz.bot

Gioca a [pokelike.xyz](https://pokelike.xyz/) — un roguelike Pokémon — da riga di
comando, da Python o via API HTTP. Senza finestre, senza internet, e con un
punteggio per confrontare i giocatori.

Nato per far giocare dei bot: ce ne sono due (uno casuale e uno guidato da un
LLM) e l'interfaccia per scriverne altri è di un metodo solo.

---

## Installazione

Serve [uv](https://docs.astral.sh/uv/) e nient'altro. Se non ce l'hai:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Poi:

```bash
git clone https://github.com/pierpierpy/pokelike.xyz.bot
cd pokelike.xyz.bot
uv sync            # crea l'ambiente e installa le dipendenze
uv run pokelike setup
```

`setup` fa due cose, una volta sola:

1. scarica il browser headless (~120 MB)
2. scarica il gioco in `site/` (~130 MB, qualche minuto)

Da qui in poi **non serve più internet**.

> Non hai bisogno di attivare nessun ambiente: `uv run` ci pensa da solo.
> Se preferisci, `source .venv/bin/activate` e poi `pokelike ...` senza `uv run`.

## Giochi tu

```bash
uv run pokelike gioca --seed 42
```

Ti compare la situazione e rispondi con un numero:

```
========================================================================
passo 2   schermata: map-screen   mappa 0   medaglie 0
========================================================================

SQUADRA
  0. Bulbasaur    Lv 5  ##########  19/19   Grass/Poison *

MAPPA   [qui]  <mossa legale>  x'=fatto
  liv  0 | [@]
  liv  1 | <o> <x>
  liv  2 |  T   x   T
  liv  3 |  o   o   i   o
  liv  8 |  B

AZIONI
  [0] vai al nodo n1_0   (catch)
  [1] vai al nodo n1_1   (battle)

> 1
```

La mappa si legge così: si scende dall'alto verso il basso, `[qui]` è dove sei,
`<così>` sono le mosse legali, `x'` è già fatto. In fondo c'è il boss.
**Scegliendo un nodo, gli altri dello stesso livello si chiudono per sempre.**

Al prompt: un **numero** per agire, `l` legenda dei simboli, `s` punteggio,
`j` stato grezzo in JSON, `n` nuova partita, `q` esci.

## Fai giocare un bot

```bash
uv run pokelike bot --partite 5              # bot casuale
uv run pokelike stats                        # com'è andata
```

Per il bot LLM servono le tue credenziali di un endpoint compatibile OpenAI
(qualunque: OpenAI, vLLM, Ollama, un endpoint aziendale):

```bash
export FW_ENDPOINT="https://il-tuo-endpoint"     # senza /v1 finale
export FW_TOKEN="la-tua-chiave"
export MODEL_ID="il-nome-del-modello"

uv run pokelike bot --bot llm --partite 3
POKELIKE_VERBOSO=1 uv run pokelike bot --bot llm --partite 1   # con le motivazioni
```

Le chiavi si leggono **solo** dall'ambiente: non finiscono mai nel codice né nel
registro delle partite.

## Vedere cosa succede

```bash
uv run pokelike gioca --seed 42                    # solo testo (il più veloce)
uv run pokelike gioca --seed 42 --foto /tmp/foto   # + un PNG a ogni schermata
uv run pokelike gioca --seed 42 --vedi             # + finestra vera del gioco
```

`--vedi` funziona anche su `bot`, con `--pausa` per i millisecondi fra le mosse.
Richiede il browser completo: `uv run playwright install chromium`.

---

## Come funziona

### Il gioco è tutto nel browser

Pokelike non ha un server: tutta la logica sta in un file JavaScript che gira nel
tuo browser. Quindi non c'è nessuna API remota da chiamare — il motore è già sul
tuo computer, e noi parliamo direttamente con le sue funzioni.

### "Headless" non vuol dire senza grafica

Vuol dire **senza finestra**. Il browser costruisce comunque tutto in memoria:
lo stato della partita, i bottoni, la mappa. Semplicemente non lo disegna.

Quindi non guardiamo pixel e non riconosciamo immagini. La mappa ASCII qui sopra
non è letta da uno screenshot: è ridisegnata da noi a partire dai nodi e dagli
archi che leggiamo dalla memoria del gioco.

### Le battaglie si giocano da sole

Il gioco decide le mosse di entrambi i lati. Quello che decide il giocatore è la
parte roguelike: dove andare sulla mappa, chi catturare, quale oggetto prendere e
a chi darlo, chi scambiare quando la squadra è piena.

### I pezzi

```
site/                 il gioco scaricato (non versionato)
   │
   ▼
assets/server.py      lo serve dal disco, senza toccare internet
   │
   ▼
browser headless      esegue il gioco
   │
core/bridge.js        legge lo stato, esegue le scelte
   │
core/game.py          classe Partita  ← LA LOGICA, una sola
   │
   ├─── cli/          il terminale
   ├─── api/          HTTP JSON
   └─── bot/          chi decide le mosse
```

`Partita` ha quattro metodi, e tutto il resto passa da lì:

```python
g.nuova(seed=42)   # comincia
g.stato()          # squadra, mappa, azioni legali
g.esegui(1)        # fai la mossa 1 -> nuovo stato
g.punteggio()      # quanto vale la partita
```

CLI, API e bot sono tre facce sopra questi quattro metodi. Nessuno dei tre
contiene logica di gioco.

### Le due interfacce

**Python**

```python
from pokelike import Partita
from pokelike.assets import ServerAsset

with ServerAsset("site") as s, Partita(url=s.url) as g:
    obs = g.nuova(seed=42)
    while not obs["finita"]:
        print(obs["azioni"])    # [{'tipo':'nodo','id':'n1_0','nodo':'catch'}, ...]
        obs = g.esegui(0)
    print(g.punteggio())
```

**HTTP** — `uv run pokelike api` (porta 8423). Il browser resta acceso fra una
chiamata e l'altra, per questo è un processo che deve restare vivo.

| Metodo | Rotta | Cosa fa |
|---|---|---|
| `POST` | `/nuova` `{"seed":42}` | comincia una partita |
| `GET` | `/stato` | stato completo + campo `vista` già formattato |
| `GET` | `/azioni` | solo le azioni legali |
| `POST` | `/azione` `{"indice":1}` | esegue → nuovo stato (409 se illegale) |
| `GET` | `/punteggio` | punteggio con la formula del gioco |

---

## Scrivere un bot

Un bot è una cosa sola: dato lo stato, dice **quale azione fare**.

```python
# src/pokelike/bot/mio.py
from .base import Bot

class MioBot(Bot):
    nome = "mio"

    def scegli(self, stato):
        # stato["azioni"] è la lista numerata che vedi giocando
        for i, a in enumerate(stato["azioni"]):
            if a.get("nodo") == "catch":
                return i          # cattura appena puoi
        return 0
```

Registralo in `DISPONIBILI` dentro [bot/\_\_init\_\_.py](src/pokelike/bot/__init__.py):

```python
DISPONIBILI = {
    "casuale": ("casuale", "BotCasuale"),
    "llm":     ("llm", "BotLLM"),
    "mio":     ("mio", "MioBot"),      # <-
}
```

e usalo: `uv run pokelike bot --bot mio`. I moduli si importano solo quando
servono, così un bot che tira dentro torch non rallenta gli altri.

Due agganci opzionali per chi ha bisogno di memoria fra i turni:
`inizio(seed)` e `fine(stato, punteggio)`.

### I due bot già pronti

**`casuale`** sceglie a caso fra le azioni legali. È la linea di base: muore in
12-17 mosse, zero medaglie, zero mappe completate, punteggio intorno a zero.
Chiunque deve batterlo.

**`llm`** ([bot/llm.py](src/pokelike/bot/llm.py)) sta tutto in un file: prompt,
strumenti, loop agentico e chiamata HTTP con `urllib`. Ogni turno il modello
riceve la situazione e le azioni numerate, può chiamare strumenti di sola lettura,
e chiude con `gioca(indice)`:

| strumento | cosa dà |
|---|---|
| `dettagli_squadra` | HP, livelli, tipi, oggetti tenuti |
| `cosa_c_e_avanti` | dove porta ogni azione al livello successivo |
| `gioca(indice, perche)` | esegue e chiude il turno |

`cosa_c_e_avanti` è quello che conta: la scelta chiude per sempre gli altri nodi
del livello, e senza guardare gli archi il modello non può saperlo.

Se il modello sbaglia indice, va in timeout o non chiama `gioca`, si ripiega su
una scelta di riserva e il ripiego viene contato. **Una partita non muore mai per
colpa del modello.**

---

## Il punteggio

È quello del gioco, non inventato da noi:

```
500 se completata + 5·nemici_sconfitti − 10·svenimenti + 50·mappe_completate
+ 20·leggendari + 20·shiny + bonus_tempo
```

Usa **`punti_senza_tempo`** per confrontare: il bonus tempo vale ~1000 su una
scala dove il resto sta nelle decine, quindi coprirebbe tutto.

## Le statistiche

Ogni partita di `pokelike bot` finisce in `stats/partite.db`, un SQLite
interrogabile con SQL normale. `--no-stats` la salta.

```bash
uv run pokelike stats                # riepilogo per bot
uv run pokelike stats --ultime 10    # + le ultime partite
```

```
bot          partite  vinte  punti medi    min    max   passi     KO  svenuti
-----------------------------------------------------------------------------
casuale            6      0        -6.7    -35     25    15.5    6.7      4.0
```

---

## Riproducibilità

Stesso seed + stesse azioni = stessa identica partita. Serve per confrontare due
bot sulle stesse partite invece che sulla fortuna.

## Comandi

| comando | cosa fa |
|---|---|
| `setup` | browser + copia offline. Una volta sola |
| `gioca` | partita interattiva nel terminale |
| `bot` | fa giocare un bot (`--bot`, `--partite`, `--seed`) |
| `api` | server HTTP JSON |
| `stats` | riepilogo delle partite |
| `mirror` | rifà la copia offline (dopo un aggiornamento del gioco) |

---

## Note

Il gioco è un progetto amatoriale di altri e chiede di non essere confuso con uno
ufficiale. Con la copia locale il traffico verso di loro è zero: si scarica una
volta e basta.

Il nome del file di gioco contiene l'hash del contenuto, quindi **cambia a ogni
aggiornamento**: se un giorno smette di funzionare, `uv run pokelike mirror`.

Dettagli tecnici, trappole e come è fatto dentro: [CLAUDE.md](CLAUDE.md).
