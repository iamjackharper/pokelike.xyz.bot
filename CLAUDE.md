# CLAUDE.md — pokelike.xyz.bot

Note per agenti che lavorano su questa repo. Il README è per chi la usa; questo è
per chi ci mette le mani.

## Cos'è

Un ambiente per far giocare bot a [pokelike.xyz](https://pokelike.xyz/), un
roguelike Pokémon che gira interamente nel browser. Il gioco non ha un backend:
tutta la logica sta in un bundle JavaScript offuscato. Noi lo eseguiamo in un
Chromium headless e parliamo con le sue funzioni globali.

Il codice, i commenti e i nomi delle variabili sono **in italiano**. Mantieni
quella lingua quando aggiungi roba.

## Comandi

```bash
uv sync                         # ambiente
uv run pokelike setup           # browser + copia offline (una volta sola)
uv run pokelike gioca --seed 42 # partita interattiva
uv run pokelike bot --partite 5 # bot casuale
uv run pokelike stats           # riepilogo
```

Non c'è una suite di test. Il collaudo di fatto è `pokelike bot --partite 3`: se
tre partite finiscono senza eccezioni e con punteggi sensati, la catena regge.

## Architettura

```
site/                    il gioco scaricato (gitignored, ~130 MB)
src/pokelike/
├── core/                LOGICA COMUNE — l'unica che sa giocare
│   ├── bridge.js          iniettato nella pagina: osserva ed esegue
│   ├── browser.py         Playwright headless, seed fissato, animazioni azzerate
│   ├── game.py            classe Partita: nuova/stato/esegui/punteggio
│   └── render.py          mappa ASCII, squadra, azioni
├── bot/                 CHI DECIDE LE MOSSE
│   ├── base.py            classe Bot astratta: solo scegli() è obbligatorio
│   ├── casuale.py         linea di base
│   └── llm.py             autosufficiente: prompt + strumenti + HTTP
├── assets/
│   ├── mirror.py          costruisce site/ in quattro fasi
│   └── server.py          serve site/ dal disco
├── statistiche/registro.py  SQLite in stats/partite.db
├── cli/main.py          interfaccia terminale
└── api/server.py        interfaccia HTTP
tools/deobfuscate.py     rende leggibile il bundle (richiede node)
```

`cli`, `api` e `bot` non contengono logica di gioco: passano tutti per i quattro
metodi di `Partita`. Se ti viene voglia di mettere una regola di gioco in `cli`,
va in `core`.

## Come si parla col gioco

Il motore espone tutto come globali della pagina. Le più utili:

| globale | uso |
|---|---|
| `state` | stato completo: squadra, zaino, mappa (DAG), medaglie, `runSeed` |
| `getAccessibleNodes(state.map)` | mosse legali sulla mappa |
| `onNodeClick(nodo)` | esegue una mossa |
| `runBattle(...)` | simulatore di battaglia puro, senza DOM |
| `getBestMove`, `calcDamage` | l'AI e la formula del danno del gioco |
| `finalizeRunScore`, `foldBattleIntoRunStats`, `newRunStats` | punteggio |
| `seedRng`, `getRngSeed` | PRNG interno |

Non si guardano pixel. Gli screenshot esistono (`Partita.foto`) ma sono solo per
gli umani.

Le azioni sono di due tipi: le mosse sulla mappa passano da `onNodeClick(nodo)`
(chiamata diretta), le altre scelte attivano un elemento del DOM perché il gioco
ci lega sopra il gestore.

Per esplorare il bundle: `python3 tools/deobfuscate.py site/js/bundle.*.js`.
Ricava da solo i nomi interni dell'offuscatore, che cambiano a ogni rilascio.

## Trappole vere

Tutte incontrate sul campo. Rileggerle prima di mettere mano:

- **Il sito non risponde 404 ai file mancanti**: rimanda `index.html` con stato
  200. Senza controllare i byte iniziali il mirror si riempie di HTML travestito
  da `.png` (successe: 6612 file). Vedi `FIRME` in `assets/mirror.py`.
- **Poca concorrenza in download.** Con 24 richieste in volo il sito blocca tutto
  in silenzio, peggio che essere lenti. Il mirror sta a 6 e ripara i mancanti in
  sequenza, dall'elenco esatto che produce la verifica giocando.
- **A game over il motore azzera `state`**: squadra vuota, medaglie assenti. Per
  il riepilogo di fine partita serve `Partita.ultimo_vivo`, l'ultima istantanea
  con la partita viva.
- **Mai dichiarare una variabile locale con lo stesso nome di un globale che vuoi
  sostituire** in `bridge.js`: la oscuri e riscrivi la copia sbagliata. Sintomo:
  `Assignment to constant variable` che non c'entra niente con `const`.
- **`maxTeamSize` è un massimo storico, non un limite.** Il limite vero è 6.
- **Gli oggetti non usabili aprono un modale di equipaggiamento** che non è un
  `.screen`. Chi guarda solo i `.screen` resta bloccato lì per sempre.
- **La mappa è SVG**: i nodi non hanno `.click()`.
- **Il nome del bundle contiene l'hash del contenuto** e cambia a ogni rilascio
  del gioco. Se qualcosa si rompe di colpo, prima cosa: `pokelike mirror`.

## Punteggio

Il gioco sa già calcolarlo (`finalizeRunScore`) e sa già contare
(`foldBattleIntoRunStats`), ma collega le due cose **solo in modalità Challenge**:
il punto di chiamata è `state.challengeId && state.runStats && fold(...)`.

Forzare `challengeId` sarebbe la scorciatoia ovvia ed è **sbagliata**: quel campo
cambia le regole, fra l'altro alza i livelli della Superquattro
(`challengeId ? Math.max(0, 10 + challengeEliteLevelMod) : 0`). Quindi
`bridge.js` avvolge `runBattle` e passa il risultato alla funzione di conteggio
del gioco: regole intatte, contatori nativi.

Confronta sempre con `punti_senza_tempo`. Il bonus tempo dipende da `Date.now()`,
che congeliamo per il determinismo, quindi resta fisso vicino a 1000 e coprirebbe
tutto il resto.

## Riproducibilità

Il seed di partita è `Date.now() ^ (Math.random() * 2**32)` e tutto discende dal
PRNG del motore inizializzato con quello. `browser.py` fissa **entrambi** in uno
script che gira prima del bundle, e cappa i `setTimeout` a 1 ms per azzerare le
animazioni. Stesso seed + stesse azioni = stessa partita, punteggio incluso.

Un contesto browser nuovo per ogni partita: riusando la stessa pagina si
impilerebbe un altro init script, e un altro reseed, a ogni reset.

## Prestazioni

~1,5 decisioni al secondo, ~14 s per partita con policy veloce. Le partite sono
indipendenti: per andare più forte si lanciano più processi, non più thread.

Il bot LLM è molto più lento (una o più chiamate HTTP per decisione) e consuma
~30k token a partita.

## Segreti

Le credenziali dell'LLM si leggono **solo** da `FW_ENDPOINT`, `FW_TOKEN`,
`MODEL_ID`. Non scriverle nel codice, nei commenti, nel README o nel registro
partite. `stats/` è gitignored.
