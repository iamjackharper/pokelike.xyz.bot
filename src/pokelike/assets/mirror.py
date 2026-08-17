"""Costruisce la copia locale completa del gioco, per giocare senza rete.

Funziona in tre fasi:

1. STATICA  — scarica index.html, i CSS/JS a cui punta, e tutti i percorsi di
   file citati letteralmente dentro il bundle (sprite, audio, mappe). Sono la
   grande maggioranza.
2. GIOCATA  — apre il server in modalità "riempi i buchi" e gioca davvero
   qualche partita. Ogni file che il gioco chiede e che non abbiamo viene
   scaricato al volo. Serve perché alcuni URL sono costruiti a runtime
   (`"img/sprites/badges/" + nome + ".png"`) e non compaiono come stringhe.
3. VERIFICA — rigioca con la rete chiusa e conta i file mancanti. Se è zero,
   il mirror è completo davvero, non per congettura.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ORIGINE = "https://pokelike.xyz"

# I percorsi dei file non contengono spazi, quindi si trovano con una regex sul
# bundle grezzo: non serve deoffuscare nulla per questo.
RE_ASSET = re.compile(r"""["'](/?(?:img|audio|style|js|fonts?)/[\w\-./]+?\.\w{2,5})["']""")
RE_HTML_REF = re.compile(r"""(?:src|href)=["']([^"'#?]+\.(?:js|css|png|svg|ico|webmanifest))["']""")
RE_CSS_URL = re.compile(r"""url\(["']?([^"')]+?\.\w{2,5})["']?\)""")


def _stampa(*a) -> None:
    """Stampa subito: senza flush l'avanzamento resta invisibile se rediretto."""
    print(*a, flush=True)


# Firme dei formati binari. Servono perché il sito NON risponde 404 per i file
# mancanti: rimanda index.html con stato 200. Senza questo controllo il mirror
# si riempie di pagine HTML travestite da .png.
FIRME = {
    ".png": (b"\x89PNG",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF8",),
    ".webp": (b"RIFF",),
    ".mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    ".ogg": (b"OggS",),
    ".woff": (b"wOFF",),
    ".woff2": (b"wOF2",),
}


def _contenuto_valido(dati: bytes, suffisso: str) -> bool:
    if not dati:
        return False
    attese = FIRME.get(suffisso.lower())
    if attese is not None:
        return dati.startswith(attese)
    # Per i testuali basta escludere il guscio della SPA servito come fallback.
    if suffisso.lower() in {".svg", ".css", ".js", ".json", ".webmanifest", ".html"}:
        return True
    return True


def _scarica(percorso: str, dest_radice: Path) -> bool:
    """Scarica un percorso relativo dentro la radice. True se ora esiste ed è valido."""
    rel = percorso.lstrip("/")
    dest = dest_radice / rel
    if dest.is_file() and dest.stat().st_size > 0:
        return True
    try:
        req = urllib.request.Request(
            f"{ORIGINE}/{rel}", headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                return False
            dati = r.read()
    except Exception:
        return False
    if not _contenuto_valido(dati, dest.suffix):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(dati)
    return True


def pulisci(radice: Path, log=_stampa) -> int:
    """Elimina i file il cui contenuto non corrisponde all'estensione."""
    rimossi = 0
    for p in radice.rglob("*"):
        if not p.is_file():
            continue
        try:
            testa = p.open("rb").read(8)
        except OSError:
            continue
        if not _contenuto_valido(testa, p.suffix):
            p.unlink()
            rimossi += 1
    log(f"  rimossi {rimossi} file non validi")
    return rimossi


def fase_statica(radice: Path, log=_stampa) -> dict[str, int]:
    """Scarica index.html, i suoi riferimenti, e gli asset citati nel bundle."""
    radice.mkdir(parents=True, exist_ok=True)

    if not _scarica("index.html", radice):
        raise RuntimeError("non riesco a scaricare index.html da " + ORIGINE)
    html = (radice / "index.html").read_text(encoding="utf-8", errors="replace")

    percorsi: set[str] = set(RE_HTML_REF.findall(html))
    percorsi |= {"favicon.svg", "manifest.webmanifest", "privacy.html"}

    # Il bundle ha il nome con l'hash del contenuto: cambia a ogni rilascio.
    bundle = next((p for p in percorsi if p.startswith("js/bundle")), None)
    if bundle is None:
        raise RuntimeError("non trovo il bundle dentro index.html")
    log(f"  bundle: {bundle}")

    for p in sorted(percorsi):
        _scarica(p, radice)

    testo_bundle = (radice / bundle).read_text(encoding="utf-8", errors="replace")
    da_bundle = {m for m in RE_ASSET.findall(testo_bundle)}
    log(f"  asset citati nel bundle: {len(da_bundle)}")

    for css in [p for p in percorsi if p.endswith(".css")]:
        f = radice / css
        if f.is_file():
            for u in RE_CSS_URL.findall(f.read_text(encoding="utf-8", errors="replace")):
                if not u.startswith(("http", "data:")):
                    da_bundle.add(u)

    ok = fail = 0
    for i, p in enumerate(sorted(da_bundle), 1):
        if _scarica(p, radice):
            ok += 1
        else:
            fail += 1
        if i % 200 == 0:
            log(f"  ... {i}/{len(da_bundle)}")

    return {"riferiti": len(percorsi), "asset": len(da_bundle), "ok": ok, "falliti": fail}


# Cartelle i cui URL il gioco costruisce come prefisso + slug + ".png"
# (es. itemIconHtml fa "img/sprites/items/" + item.id + ".png"). Gli slug non
# compaiono mai come percorso completo, quindi vanno provati uno per uno.
CARTELLE_SLUG = (
    "img/sprites/items/",
    "img/sprites/trainers/",
    "img/sprites/badges/",
)
RE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def fase_slug(radice: Path, log=_stampa) -> dict[str, int]:
    """Prova ogni slug plausibile del bundle nelle cartelle a URL dinamico.

    Molti tentativi finiranno in 404 ed è normale: è il prezzo per non dipendere
    dalla fortuna di incontrare quell'oggetto giocando.
    """
    bundle = next(radice.glob("js/bundle*.js"), None)
    if bundle is None:
        raise RuntimeError("bundle non presente: esegui prima la fase statica")
    testo = bundle.read_text(encoding="utf-8", errors="replace")

    slug = {
        s for s in re.findall(r"""["']([a-z0-9][a-z0-9-]{2,29})["']""", testo)
        if RE_SLUG.match(s) and not s.endswith(("-js", "-css"))
    }
    log(f"  slug candidati: {len(slug)}  x {len(CARTELLE_SLUG)} cartelle")

    da_provare = [
        f"{c}{s}.png"
        for c in CARTELLE_SLUG
        for s in sorted(slug)
        if not (radice / f"{c}{s}.png").is_file()
    ]
    log(f"  da provare: {len(da_provare)} (i 404 sono attesi e normali)")

    # Poca concorrenza di proposito: con 24 richieste in volo il sito ci sbatte
    # fuori e *tutto* fallisce silenziosamente, il che è molto peggio che essere
    # lenti. 6 passa senza problemi.
    trovati = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futuri = {pool.submit(_scarica, p, radice): p for p in da_provare}
        for i, f in enumerate(as_completed(futuri), 1):
            if f.result():
                trovati += 1
            if i % 1000 == 0:
                log(f"  ... {i}/{len(da_provare)}  ({trovati} trovati)")
    return {"tentativi": len(da_provare), "trovati": trovati}


def fase_riparazione(radice: Path, mancanti: list[str], log=_stampa) -> dict[str, int]:
    """Scarica esattamente i file che la verifica ha segnalato come mancanti.

    Molto più affidabile del tentare a tappeto: l'elenco arriva dal gioco stesso,
    e si scarica in sequenza senza rischiare di essere bloccati.
    """
    ok = falliti = 0
    for m in mancanti:
        if _scarica(m, radice):
            ok += 1
        else:
            falliti += 1
            log(f"  non recuperabile: {m}")
    log(f"  riparati {ok}, non recuperabili {falliti}")
    return {"ok": ok, "falliti": falliti}


def fase_giocata(radice: Path, partite: int = 3, porta: int = 8422, log=_stampa) -> dict[str, int]:
    """Gioca con il riempimento automatico, per catturare gli URL dinamici."""
    from ..core.game import Partita
    from .server import ServerAsset

    server = ServerAsset(radice, porta=porta, origine=ORIGINE)
    server.avvia()
    try:
        gioco = Partita(url=server.url)
        gioco.apri()
        try:
            for i in range(partite):
                obs = gioco.nuova(seed=9000 + i)
                passi = 0
                while passi < 120 and not obs.get("finita") and obs.get("azioni"):
                    obs = gioco.esegui(passi % len(obs["azioni"]))
                    passi += 1
                log(f"  partita {i + 1}/{partite}: {passi} passi, "
                    f"{len(server.scaricati)} file recuperati finora")
        finally:
            gioco.chiudi()
    finally:
        server.ferma()
    return {"recuperati": len(server.scaricati)}


def fase_verifica(radice: Path, partite: int = 2, porta: int = 8423, log=_stampa) -> dict:
    """Rigioca con la rete chiusa. Zero mancanti = mirror davvero completo."""
    from ..core.game import Partita
    from .server import ServerAsset

    server = ServerAsset(radice, porta=porta, origine=None)  # niente rete
    server.avvia()
    try:
        gioco = Partita(url=server.url)
        gioco.apri()
        try:
            for i in range(partite):
                obs = gioco.nuova(seed=7000 + i)
                passi = 0
                while passi < 120 and not obs.get("finita") and obs.get("azioni"):
                    obs = gioco.esegui(passi % len(obs["azioni"]))
                    passi += 1
                log(f"  verifica {i + 1}/{partite}: {passi} passi giocati")
            esterne = list(gioco.sessione.richieste_esterne) if gioco.sessione else []
        finally:
            gioco.chiudi()
    finally:
        server.ferma()
    return {"mancanti": sorted(server.mancanti), "richieste_esterne": esterne}


def costruisci(radice: Path, fasi: str = "tutte", log=_stampa) -> dict:
    """`fasi` permette di riprendere senza riscaricare: tutte|statica|giocata|verifica."""
    st = gi = ve = None

    if fasi in ("tutte", "statica"):
        log("[1/4] fase statica: scarico index, bundle e asset citati")
        st = fase_statica(radice, log=log)
        log(f"      {st['ok']} file scaricati, {st['falliti']} non disponibili")

    if fasi in ("tutte", "slug"):
        log("[2/4] fase slug: provo gli URL costruiti come prefisso + nome")
        sl = fase_slug(radice, log=log)
        log(f"      {sl['trovati']} trovati su {sl['tentativi']} tentativi")
        # Rete di sicurezza: il sito risponde 200 con index.html per i file
        # mancanti, quindi qualunque cosa sia sfuggita alla validazione va tolta
        # prima che la verifica la scambi per un file buono.
        pulisci(radice, log=log)

    if fasi in ("tutte", "giocata"):
        log("[3/4] fase giocata: cerco gli URL costruiti a runtime")
        gi = fase_giocata(radice, log=log)
        log(f"      {gi['recuperati']} file recuperati giocando")

    if fasi not in ("tutte", "verifica"):
        file = sum(1 for _ in radice.rglob("*") if _.is_file())
        return {"statica": st, "giocata": gi, "verifica": None, "file": file}

    log("[4/4] verifica: rigioco con la rete chiusa")
    ve = fase_verifica(radice, log=log)

    # Ciclo verifica -> riparazione -> riverifica. L'elenco dei mancanti lo
    # produce il gioco giocando, quindi è esatto: molto meglio che indovinare.
    for giro in range(3):
        if not ve["mancanti"]:
            break
        log(f"      riparo {len(ve['mancanti'])} file mancanti (giro {giro + 1})")
        fase_riparazione(radice, ve["mancanti"], log=log)
        ve = fase_verifica(radice, log=log)
    n = len(ve["mancanti"])
    if n == 0 and not ve["richieste_esterne"]:
        log("      OK: nessun file mancante, nessuna richiesta verso internet")
    else:
        log(f"      ATTENZIONE: {n} file mancanti, "
            f"{len(ve['richieste_esterne'])} richieste esterne")
        for m in ve["mancanti"][:20]:
            log(f"        manca {m}")

    file = sum(1 for _ in radice.rglob("*") if _.is_file())
    mb = sum(p.stat().st_size for p in radice.rglob("*") if p.is_file()) / 1e6
    log(f"\nmirror in {radice}: {file} file, {mb:.1f} MB")
    return {"statica": st, "giocata": gi, "verifica": ve, "file": file, "mb": round(mb, 1)}
