"""Starting and driving the headless browser that runs the game.

The game is JavaScript and needs a browser environment (`document`,
`localStorage`, SVG). Headless means that environment exists in full but is
never painted: no window, no pixels. We are not looking at a screen, we are
talking to objects in memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

BRIDGE = Path(__file__).with_name("bridge.js")

# Script that runs BEFORE the game bundle. It pins the game's two sources of
# randomness and collapses animation delays.
#
# The run seed is `Date.now() ^ (Math.random() * 2**32)` and everything a run
# generates (map layout, encounters, item offers) flows from the engine's PRNG
# seeded with it. Making a run reproducible therefore means pinning both.
INIT_SCRIPT = """
(() => {
  const cfg = %s;
  let s = (cfg.seed >>> 0) || 1;
  Math.random = function () {
    s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0;
    return s / 4294967296;
  };
  let clock = 1700000000000;
  Date.now = () => (clock += 16);
  const st = window.setTimeout.bind(window);
  window.setTimeout = (fn, d, ...a) => st(fn, Math.min(Number(d) || 0, cfg.max_delay), ...a);
  window.requestAnimationFrame = (fn) => st(() => fn(performance.now()), 0);
  try { localStorage.clear(); } catch (e) {}
})();
"""

# Screens that represent a real choice by the player.
DECISION_SCREENS = [
    "map-screen", "catch-screen", "item-screen", "passive-screen", "swap-screen",
    "starter-screen", "trainer-screen", "stat-buff-screen", "trade-screen", "shiny-screen",
]
TERMINAL_SCREENS = ["gameover-screen", "win-screen"]
# Modals that are genuine in-run choices. Purely informational ones (settings,
# Pokedex, patch notes) are excluded on purpose: a bot must never open them.
GAME_MODALS = [
    "item-equip-modal", "usable-item-modal", "item-discard-modal",
    "submap-pick-modal", "vitamin-apply-modal", "legend-voucher-modal", "shop-modal",
]

BLOCKED_HOSTS = (
    "fuseplatform", "googletagmanager", "googlesyndication", "doubleclick",
    "amazon-adsystem", "fonts.googleapis", "fonts.gstatic", "google-analytics",
    # Two of the game's own dependencies: pokeapi.co (used by the Pokedex, which
    # a bot never opens) and raw.githubusercontent (fallback for missing sprites,
    # which the game handles with an emoji). Blocking them is what makes the
    # environment genuinely offline.
    "raw.githubusercontent", "pokeapi.co",
)


@dataclass
class Session:
    """A live browser with a game page loaded."""

    url: str
    watch: bool = False
    max_delay: int = 1
    _pw: object | None = field(default=None, repr=False)
    browser: Browser | None = field(default=None, repr=False)
    page: Page | None = field(default=None, repr=False)
    external_requests: list[str] = field(default_factory=list, repr=False)
    page_errors: list[str] = field(default_factory=list, repr=False)

    def start(self) -> None:
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(
            headless=not self.watch, args=["--no-sandbox"]
        )

    def load(self, seed: int) -> Page:
        """Opens a fresh page with the seed pinned. One context per run."""
        if self.browser is None:
            raise RuntimeError("session not started: call start()")
        ctx = self.browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: self.page_errors.append(str(e)[:200]))
        page.route("**/*", self._filter)

        page.add_init_script(
            INIT_SCRIPT % json.dumps({"seed": seed, "max_delay": self.max_delay})
        )
        page.goto(self.url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        page.evaluate(
            "cfg => { window.__PK_CFG = cfg; }",
            {
                "decision": DECISION_SCREENS,
                "terminal": TERMINAL_SCREENS,
                "modals": GAME_MODALS,
            },
        )
        page.evaluate(BRIDGE.read_text(encoding="utf-8"))

        if self.page is not None:
            self.page.context.close()
        self.page = page
        return page

    def _filter(self, route) -> None:
        """Blocks ads and analytics, and records anything that left the machine.

        `external_requests` is how the mirror learns what it is still missing.
        """
        url = route.request.url
        if any(b in url for b in BLOCKED_HOSTS):
            route.abort()
            return
        if not url.startswith(("http://127.0.0.1", "http://localhost")):
            self.external_requests.append(url)
        route.continue_()

    def close(self) -> None:
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None
