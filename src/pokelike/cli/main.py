"""Interfaccia a riga di comando.

È una faccia sottile sopra `core.game.Partita`: la stessa classe che usa l'API.
Nessuna logica di gioco vive qui dentro.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..assets.mirror import costruisci
from ..assets.server import ServerAsset
from ..core import render
from ..core.game import ErroreAzione, Partita
from ..statistiche import formatta_riepilogo, registra, riepilogo, ultime

RADICE_SITO = Path(__file__).resolve().parents[3] / "site"

AIUTO_REPL = """
comandi:
  <numero>   esegui l'azione con quel numero
  s          mostra il punteggio
  j          mostra lo stato grezzo in JSON
  l          mostra la legenda dei simboli della mappa
  n          nuova partita
  q          esci
"""


def _server_e_partita(args) -> tuple[ServerAsset, Partita]:
    if not RADICE_SITO.is_dir() or not (RADICE_SITO / "index.html").is_file():
        print(
            f"copia offline assente in {RADICE_SITO}\n"
            "eseguila una volta con:  pokelike mirror",
            file=sys.stderr,
        )
        raise SystemExit(2)
    server = ServerAsset(RADICE_SITO, porta=args.porta)
    server.avvia()

    vedi = getattr(args, "vedi", False)
    # A finestra aperta le animazioni vanno lasciate correre alla loro velocità,
    # altrimenti passa tutto in un lampo e non si vede niente. Headless invece le
    # schiaccia a 1 ms perché nessuno le guarda.
    gioco = Partita(url=server.url, visibile=vedi, attesa_max=100_000 if vedi else 1)
    try:
        gioco.apri()
    except Exception as e:  # noqa: BLE001
        server.ferma()
        if vedi:
            print(
                f"non riesco ad aprire la finestra: {e}\n\n"
                "La modalità --vedi richiede il browser completo, non solo il guscio "
                "headless:\n    .venv/bin/python -m playwright install chromium",
                file=sys.stderr,
            )
            raise SystemExit(3) from e
        raise
    return server, gioco


# --------------------------------------------------------------------- comandi


def cmd_setup(args) -> int:
    """Prepara tutto: browser + copia offline del gioco. Da fare una volta sola."""
    import subprocess

    print("[1/2] scarico il browser headless (~120 MB)")
    r = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"]
    )
    if r.returncode != 0:
        print("installazione del browser fallita", file=sys.stderr)
        return r.returncode

    if (RADICE_SITO / "index.html").is_file() and not args.riscarica:
        print(f"[2/2] copia offline già presente in {RADICE_SITO} — salto")
        print("      (usa --riscarica per rifarla)")
    else:
        print("[2/2] scarico il gioco per l'uso offline (~130 MB, qualche minuto)")
        costruisci(RADICE_SITO)

    print("\nPronto. Prova:  pokelike gioca")
    return 0


def cmd_mirror(args) -> int:
    costruisci(RADICE_SITO, fasi=args.fasi)
    return 0


def cmd_gioca(args) -> int:
    server, gioco = _server_e_partita(args)
    try:
        obs = gioco.nuova(seed=args.seed)
        print(f"\nnuova partita — seed {args.seed}")
        if args.foto:
            print(f"immagini in {args.foto}/")
        print(AIUTO_REPL)
        while True:
            print()
            print(render.schermo(obs))
            if args.foto:
                f = gioco.foto(Path(args.foto) / f"{gioco.passi:03d}-{obs['schermata']}.png")
                print(f"\n[immagine: {f}]")
            if obs.get("finita"):
                print()
                print(render.punteggio(gioco.punteggio()))
                print("\n('n' per un'altra partita, 'q' per uscire)")

            try:
                riga = input("\n> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0

            if riga in {"q", "quit", "esci"}:
                return 0
            if riga == "n":
                args.seed += 1
                obs = gioco.nuova(seed=args.seed)
                print(f"\nnuova partita — seed {args.seed}")
                continue
            if riga == "s":
                print()
                print(render.punteggio(gioco.punteggio()))
                continue
            if riga == "j":
                print(json.dumps(gioco.stato(), indent=1, ensure_ascii=False))
                continue
            if riga == "l":
                print()
                print(render.LEGENDA)
                continue
            if riga in {"?", "h", "help"}:
                print(AIUTO_REPL)
                continue
            if not riga.isdigit():
                print("non ho capito — scrivi un numero, oppure '?' per l'aiuto")
                continue

            try:
                obs = gioco.esegui(int(riga))
            except ErroreAzione as e:
                print(f"azione rifiutata: {e}")
    finally:
        gioco.chiudi()
        server.ferma()


def cmd_bot(args) -> int:
    """Fa giocare un bot. Il bot decide le mosse, qui si gestisce solo il giro."""
    from ..bot import crea

    try:
        bot = crea(args.bot, seed=args.seed)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        raise SystemExit(2) from e

    server, gioco = _server_e_partita(args)
    try:
        for i in range(args.partite):
            seed = args.seed + i
            obs = gioco.nuova(seed=seed)
            bot.inizio(seed)
            while not obs.get("finita") and obs.get("azioni") and gioco.passi < args.max_passi:
                if args.foto:
                    gioco.foto(Path(args.foto) / f"{i:02d}-{gioco.passi:03d}-{obs['schermata']}.png")
                obs = gioco.esegui(bot.scegli(obs))
                if args.vedi:
                    gioco.sessione.page.wait_for_timeout(args.pausa)
            p = gioco.punteggio() or {}
            bot.fine(obs, p)
            if not args.no_stats:
                registra(bot=args.bot, seed=seed, stato=obs, punteggio=p,
                         passi=gioco.passi, vivo=gioco.ultimo_vivo,
                         extra=bot.note() if hasattr(bot, "note") else None)
            d = p.get("dettaglio") or {}
            # Si stampa `punti_senza_tempo` perché è l'unico confrontabile: il
            # bonus tempo vale ~1000 su una scala dove il resto sta nelle decine,
            # quindi `punti` fa sembrare buona anche una partita disastrosa.
            print(
                f"partita {i + 1}/{args.partite}  seed {seed}  "
                f"passi {gioco.passi:>3}  fine {obs.get('schermata'):<16} "
                f"medaglie {(obs.get('run') or {}).get('medaglie', 0)}  "
                f"punti {p.get('punti_senza_tempo')}  "
                f"(KO {d.get('enemiesKO', 0)}, svenuti {d.get('faints', 0)}, "
                f"mappe {d.get('mapsCleared', 0)})"
            )
        return 0
    finally:
        gioco.chiudi()
        server.ferma()


def cmd_stats(args) -> int:
    print(formatta_riepilogo(riepilogo()))
    if args.ultime:
        print()
        for r in ultime(args.ultime, bot=args.bot):
            print(f"  #{r['id']:<5} {r['quando']}  {r['bot']:<10} seed {r['seed']:<5}"
                  f" passi {r['passi']:>3}  {r['fine']:<16} punti {r['punti']}")
    return 0


def cmd_api(args) -> int:
    from ..api.server import avvia_api

    server, gioco = _server_e_partita(args)
    try:
        # Una partita è già pronta all'avvio, così GET /stato risponde subito
        # senza dover per forza chiamare POST /nuova.
        gioco.nuova(seed=args.seed)
        print(f"API su http://127.0.0.1:{args.porta_api}/   (ctrl-c per fermare)")
        print(f"partita pronta con seed {args.seed} — prova: curl 127.0.0.1:{args.porta_api}/stato")
        avvia_api(gioco, porta=args.porta_api)
        return 0
    finally:
        gioco.chiudi()
        server.ferma()


# ------------------------------------------------------------------ argomenti


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="pokelike",
        description="Gioca a pokelike.xyz headless, da riga di comando o via API.",
    )
    p.add_argument("--porta", type=int, default=8422, help="porta del server dei file di gioco")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("setup", help="prepara tutto: browser + copia offline (una volta sola)")
    s.add_argument("--riscarica", action="store_true", help="rifà la copia anche se c'è già")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("mirror", help="rifà solo la copia offline del gioco")
    s.add_argument("--fasi", choices=["tutte", "statica", "numeri", "slug", "giocata", "verifica"],
                   default="tutte", help="riprendi da una fase senza riscaricare")
    s.set_defaults(func=cmd_mirror)

    s = sub.add_parser("gioca", help="partita interattiva nel terminale")
    s.add_argument("--seed", type=int, default=1, help="seed della partita")
    s.add_argument("--vedi", action="store_true", help="apri una finestra vera e guarda")
    s.add_argument("--foto", metavar="CARTELLA", help="salva un'immagine a ogni schermata")
    s.set_defaults(func=cmd_gioca)

    s = sub.add_parser("bot", help="fai giocare un bot")
    s.add_argument("--bot", default="casuale", help="quale bot usare (vedi bot/DISPONIBILI)")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--partite", type=int, default=3)
    s.add_argument("--max-passi", type=int, default=300)
    s.add_argument("--vedi", action="store_true", help="apri una finestra vera e guarda")
    s.add_argument("--foto", metavar="CARTELLA", help="salva un'immagine a ogni passo")
    s.add_argument("--pausa", type=int, default=800, help="ms di pausa fra le mosse con --vedi")
    s.add_argument("--no-stats", action="store_true", help="non registrare le partite")
    s.set_defaults(func=cmd_bot)

    s = sub.add_parser("api", help="avvia l'API HTTP")
    s.add_argument("--porta-api", type=int, default=8423)
    s.add_argument("--seed", type=int, default=1, help="seed della partita iniziale")
    s.set_defaults(func=cmd_api)

    s = sub.add_parser("stats", help="riepilogo delle partite registrate")
    s.add_argument("--ultime", type=int, default=0, help="mostra anche le ultime N partite")
    s.add_argument("--bot", default=None, help="filtra le ultime per bot")
    s.set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
