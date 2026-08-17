"""Avvio e controllo del browser headless che fa da runtime al gioco.

Il gioco è JavaScript e ha bisogno di un ambiente browser (`document`,
`localStorage`, canvas SVG). Headless significa che quell'ambiente esiste per
intero ma non viene disegnato: nessuna finestra, nessun pixel. Non stiamo
"guardando lo schermo", stiamo parlando con gli oggetti in memoria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

BRIDGE = Path(__file__).with_name("bridge.js")

# Lo script che gira PRIMA del bundle. Fissa le due sorgenti di casualità del
# gioco e azzera le attese delle animazioni.
#
# Il seed di partita è `Date.now() ^ (Math.random() * 2**32)` e tutto quello che
# la partita genera (mappa, incontri, offerte di oggetti) discende dal PRNG del
# motore inizializzato con quel valore. Per rendere una partita riproducibile
# vanno quindi fissati entrambi.
INIT_SCRIPT = """
(() => {
  const cfg = %s;
  let s = (cfg.seed >>> 0) || 1;
  Math.random = function () {
    s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0;
    return s / 4294967296;
  };
  let orologio = 1700000000000;
  Date.now = () => (orologio += 16);
  const st = window.setTimeout.bind(window);
  window.setTimeout = (fn, d, ...a) => st(fn, Math.min(Number(d) || 0, cfg.attesa_max), ...a);
  window.requestAnimationFrame = (fn) => st(() => fn(performance.now()), 0);
  try { localStorage.clear(); } catch (e) {}
})();
"""

# Schermate che rappresentano una scelta reale del giocatore.
SCHERMATE_DECISIONE = [
    "map-screen", "catch-screen", "item-screen", "passive-screen", "swap-screen",
    "starter-screen", "trainer-screen", "stat-buff-screen", "trade-screen", "shiny-screen",
]
SCHERMATE_FINALI = ["gameover-screen", "win-screen"]
# Modali che sono scelte di gioco. Quelli informativi (impostazioni, Pokédex,
# note di rilascio) sono esclusi apposta: l'agente non deve poterli aprire.
MODALI_GIOCO = [
    "item-equip-modal", "usable-item-modal", "item-discard-modal",
    "submap-pick-modal", "vitamin-apply-modal", "legend-voucher-modal", "shop-modal",
]

# Tutto ciò che uscirebbe da casa. Oltre a pubblicità e analytics ci sono due
# dipendenze del gioco stesso: pokeapi.co (usata dal Pokédex, che l'agente non
# apre mai) e raw.githubusercontent (ripiego per gli sprite mancanti, gestito dal
# gioco con un'emoji). Bloccarle è ciò che rende l'ambiente davvero offline.
BLOCCO_ESTERNO = (
    "fuseplatform", "googletagmanager", "googlesyndication", "doubleclick",
    "amazon-adsystem", "fonts.googleapis", "fonts.gstatic", "google-analytics",
    "raw.githubusercontent", "pokeapi.co",
)


@dataclass
class Sessione:
    """Un browser vivo con una pagina di gioco caricata."""

    url: str
    visibile: bool = False
    attesa_max: int = 1
    _pw: object | None = field(default=None, repr=False)
    browser: Browser | None = field(default=None, repr=False)
    page: Page | None = field(default=None, repr=False)
    richieste_esterne: list[str] = field(default_factory=list, repr=False)
    errori_pagina: list[str] = field(default_factory=list, repr=False)

    def avvia(self) -> None:
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(
            headless=not self.visibile, args=["--no-sandbox"]
        )

    def carica(self, seed: int) -> Page:
        """Apre una pagina nuova con il seed fissato. Un contesto per partita."""
        if self.browser is None:
            raise RuntimeError("sessione non avviata: chiama avvia()")
        ctx = self.browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: self.errori_pagina.append(str(e)[:200]))
        page.route("**/*", self._filtra)

        import json

        page.add_init_script(
            INIT_SCRIPT % json.dumps({"seed": seed, "attesa_max": self.attesa_max})
        )
        page.goto(self.url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        page.evaluate(
            "cfg => { window.__PK_CFG = cfg; }",
            {
                "decisionali": SCHERMATE_DECISIONE,
                "terminali": SCHERMATE_FINALI,
                "modali": MODALI_GIOCO,
            },
        )
        page.evaluate(BRIDGE.read_text(encoding="utf-8"))

        if self.page is not None:
            self.page.context.close()
        self.page = page
        return page

    def _filtra(self, route) -> None:
        """Blocca pubblicità e analytics, e annota ogni richiesta uscita di casa.

        `richieste_esterne` è ciò che il mirror usa per sapere cosa gli manca.
        """
        url = route.request.url
        if any(b in url for b in BLOCCO_ESTERNO):
            route.abort()
            return
        if not url.startswith(("http://127.0.0.1", "http://localhost")):
            self.richieste_esterne.append(url)
        route.continue_()

    def chiudi(self) -> None:
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None
