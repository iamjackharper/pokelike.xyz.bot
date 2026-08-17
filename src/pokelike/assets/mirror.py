"""Builds the complete local copy of the game, so it can be played offline.

It works in five phases:

1. STATIC   — downloads index.html, the CSS/JS it points at, and every file path
   quoted literally inside the game bundle (sprites, audio, maps). That is the
   vast majority of them.
2. NUMBERED — badges and map backgrounds are addressed by number
   ("badges/2.png"), which no name-based search will ever produce.
3. SLUG     — some URLs are built at runtime ("items/" + id + ".png") and never
   appear as a whole string, so plausible names are tried one by one.
4. PLAYED   — opens the server in fill-the-gaps mode and actually plays a few
   runs, downloading whatever the game asks for and we do not have.
5. VERIFY   — replays with the network closed and counts what is missing, then
   repairs exactly that list and checks again. Zero missing means the copy is
   genuinely complete, not complete by assumption.
"""

from __future__ import annotations

import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

UPSTREAM = "https://pokelike.xyz"

# File paths contain no spaces, so they can be found with a regex over the raw
# bundle: nothing needs de-obfuscating for this.
RE_ASSET = re.compile(r"""["'](/?(?:img|audio|style|js|fonts?)/[\w\-./]+?\.\w{2,5})["']""")
RE_HTML_REF = re.compile(r"""(?:src|href)=["']([^"'#?]+\.(?:js|css|png|svg|ico|webmanifest))["']""")
RE_CSS_URL = re.compile(r"""url\(["']?([^"')]+?\.\w{2,5})["']?\)""")


def _log(*a) -> None:
    """Print immediately: without a flush, progress is invisible when redirected."""
    print(*a, flush=True)


# Magic numbers for binary formats. These matter because the site does NOT answer
# 404 for missing files: it returns index.html with status 200. Without this
# check the mirror fills up with HTML pages wearing a .png extension.
SIGNATURES = {
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


def _valid_content(data: bytes, suffix: str) -> bool:
    if not data:
        return False
    expected = SIGNATURES.get(suffix.lower())
    if expected is not None:
        return data.startswith(expected)
    return True


def _fetch(path: str, root: Path) -> bool:
    """Downloads a relative path into the root. True if it now exists and is valid."""
    rel = path.lstrip("/")
    dest = root / rel
    if dest.is_file() and dest.stat().st_size > 0:
        return True
    try:
        req = urllib.request.Request(
            f"{UPSTREAM}/{rel}", headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                return False
            data = r.read()
    except Exception:
        return False
    if not _valid_content(data, dest.suffix):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def clean(root: Path, log=_log) -> int:
    """Deletes files whose content does not match their extension."""
    removed = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            head = p.open("rb").read(8)
        except OSError:
            continue
        if not _valid_content(head, p.suffix):
            p.unlink()
            removed += 1
    log(f"  removed {removed} invalid files")
    return removed


def phase_static(root: Path, log=_log) -> dict[str, int]:
    """Downloads index.html, what it references, and the assets named in the bundle."""
    root.mkdir(parents=True, exist_ok=True)

    if not _fetch("index.html", root):
        raise RuntimeError("cannot download index.html from " + UPSTREAM)
    html = (root / "index.html").read_text(encoding="utf-8", errors="replace")

    paths: set[str] = set(RE_HTML_REF.findall(html))
    paths |= {"favicon.svg", "manifest.webmanifest", "privacy.html"}

    # The bundle filename carries a content hash: it changes with every release.
    bundle = next((p for p in paths if p.startswith("js/bundle")), None)
    if bundle is None:
        raise RuntimeError("cannot find the bundle inside index.html")
    log(f"  bundle: {bundle}")

    for p in sorted(paths):
        _fetch(p, root)

    bundle_text = (root / bundle).read_text(encoding="utf-8", errors="replace")
    from_bundle = set(RE_ASSET.findall(bundle_text))
    log(f"  assets named in the bundle: {len(from_bundle)}")

    for css in [p for p in paths if p.endswith(".css")]:
        f = root / css
        if f.is_file():
            for u in RE_CSS_URL.findall(f.read_text(encoding="utf-8", errors="replace")):
                if not u.startswith(("http", "data:")):
                    from_bundle.add(u)

    ok = failed = 0
    for i, p in enumerate(sorted(from_bundle), 1):
        if _fetch(p, root):
            ok += 1
        else:
            failed += 1
        if i % 200 == 0:
            log(f"  ... {i}/{len(from_bundle)}")

    return {"referenced": len(paths), "assets": len(from_bundle), "ok": ok, "failed": failed}


# Folders whose URLs the game builds as prefix + slug + ".png"
# (itemIconHtml does "img/sprites/items/" + item.id + ".png"). The slugs never
# appear as a complete path, so they have to be tried one at a time.
SLUG_FOLDERS = (
    "img/sprites/items/",
    "img/sprites/trainers/",
    "img/sprites/badges/",
    "img/sprites/g1/", "img/sprites/g2/", "img/sprites/g3/", "img/sprites/g4/",
)
RE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Folders whose URLs are prefix + NUMBER + ".png" (badges, map backgrounds).
# These need their own pass: the slug search looks for word-shaped names and
# would never produce "2.png", which is how every badge past the first went
# missing.
NUMBERED_FOLDERS = (
    "img/sprites/badges/",
    "img/maps/g1/", "img/maps/g2/", "img/maps/g3/", "img/maps/g4/",
)
MAX_NUMBER = 60


def phase_numbered(root: Path, log=_log) -> dict[str, int]:
    """Tries the numbered paths until they run out."""
    found = 0
    for folder in NUMBERED_FOLDERS:
        n = 0
        for i in range(1, MAX_NUMBER + 1):
            path = f"{folder}{i}.png"
            if (root / path).is_file() or _fetch(path, root):
                n += 1
        found += n
        log(f"  {folder}: {n}")
    return {"found": found}


def phase_slug(root: Path, log=_log) -> dict[str, int]:
    """Tries every plausible slug from the bundle in the dynamic-URL folders.

    Most attempts will 404 and that is fine: it is the price of not depending on
    the luck of running into that item while playing.
    """
    bundle = next(root.glob("js/bundle*.js"), None)
    if bundle is None:
        raise RuntimeError("bundle missing: run the static phase first")
    text = bundle.read_text(encoding="utf-8", errors="replace")

    slugs = {
        s for s in re.findall(r"""["']([a-z0-9][a-z0-9-]{2,29})["']""", text)
        if RE_SLUG.match(s) and not s.endswith(("-js", "-css"))
    }
    log(f"  candidate slugs: {len(slugs)}  x {len(SLUG_FOLDERS)} folders")

    to_try = [
        f"{c}{s}.png"
        for c in SLUG_FOLDERS
        for s in sorted(slugs)
        if not (root / f"{c}{s}.png").is_file()
    ]
    log(f"  to try: {len(to_try)} (404s are expected and normal)")

    # Deliberately low concurrency: with 24 requests in flight the site cuts us
    # off and *everything* fails silently, which is far worse than being slow.
    found = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch, p, root): p for p in to_try}
        for i, f in enumerate(as_completed(futures), 1):
            if f.result():
                found += 1
            if i % 1000 == 0:
                log(f"  ... {i}/{len(to_try)}  ({found} found)")
    return {"tried": len(to_try), "found": found}


def phase_repair(root: Path, missing: list[str], log=_log) -> dict[str, int]:
    """Downloads exactly the files the verification reported as missing.

    Far more reliable than guessing wholesale: the list comes from the game
    itself, and it downloads sequentially without risking a block.
    """
    ok = failed = 0
    for m in missing:
        if _fetch(m, root):
            ok += 1
        else:
            failed += 1
            log(f"  unrecoverable: {m}")
    log(f"  repaired {ok}, unrecoverable {failed}")
    return {"ok": ok, "failed": failed}


def phase_played(root: Path, runs: int = 3, port: int = 8422, log=_log) -> dict[str, int]:
    """Plays with auto-fill on, to capture the URLs built at runtime."""
    from ..core.game import Game
    from .server import AssetServer

    server = AssetServer(root, port=port, upstream=UPSTREAM)
    server.start()
    try:
        game = Game(url=server.url)
        game.open()
        try:
            for i in range(runs):
                obs = game.reset(seed=9000 + i)
                steps = 0
                while steps < 120 and not obs.get("done") and obs.get("actions"):
                    obs = game.step(steps % len(obs["actions"]))
                    steps += 1
                log(f"  run {i + 1}/{runs}: {steps} steps, "
                    f"{len(server.fetched)} files recovered so far")
        finally:
            game.close()
    finally:
        server.stop()
    return {"recovered": len(server.fetched)}


def phase_verify(root: Path, runs: int = 2, port: int = 8423, log=_log) -> dict:
    """Replays with the network closed. Zero missing means genuinely complete."""
    from ..core.game import Game
    from .server import AssetServer

    server = AssetServer(root, port=port, upstream=None)  # no network
    server.start()
    try:
        game = Game(url=server.url)
        game.open()
        try:
            for i in range(runs):
                obs = game.reset(seed=7000 + i)
                steps = 0
                while steps < 120 and not obs.get("done") and obs.get("actions"):
                    obs = game.step(steps % len(obs["actions"]))
                    steps += 1
                log(f"  check {i + 1}/{runs}: {steps} steps played")
            external = list(game.session.external_requests) if game.session else []
        finally:
            game.close()
    finally:
        server.stop()
    return {"missing": sorted(server.missing), "external_requests": external}


PHASES = ("all", "static", "numbered", "slug", "played", "verify")


def build(root: Path, phases: str = "all", log=_log) -> dict:
    """`phases` allows resuming without downloading everything again."""
    st = nu = sl = pl = ve = None

    if phases in ("all", "static"):
        log("[1/5] static phase: index, bundle and the assets they name")
        st = phase_static(root, log=log)
        log(f"      {st['ok']} files downloaded, {st['failed']} unavailable")

    if phases in ("all", "numbered"):
        log("[2/5] numbered phase: badges and map backgrounds")
        nu = phase_numbered(root, log=log)
        log(f"      {nu['found']} numbered files")

    if phases in ("all", "slug"):
        log("[3/5] slug phase: URLs built as prefix + name")
        sl = phase_slug(root, log=log)
        log(f"      {sl['found']} found out of {sl['tried']} attempts")
        # Safety net: the site answers 200 with index.html for missing files, so
        # anything that slipped past validation must go before the verification
        # mistakes it for a good file.
        clean(root, log=log)

    if phases in ("all", "played"):
        log("[4/5] played phase: hunting the URLs built at runtime")
        pl = phase_played(root, log=log)
        log(f"      {pl['recovered']} files recovered by playing")

    if phases not in ("all", "verify"):
        files = sum(1 for _ in root.rglob("*") if _.is_file())
        return {"static": st, "numbered": nu, "slug": sl, "played": pl,
                "verify": None, "files": files}

    log("[5/5] verify: replaying with the network closed")
    ve = phase_verify(root, log=log)

    # verify -> repair -> re-verify. The missing list is produced by the game as
    # it plays, so it is exact: much better than guessing.
    for round_ in range(3):
        if not ve["missing"]:
            break
        log(f"      repairing {len(ve['missing'])} missing files (round {round_ + 1})")
        phase_repair(root, ve["missing"], log=log)
        ve = phase_verify(root, log=log)

    n = len(ve["missing"])
    if n == 0 and not ve["external_requests"]:
        log("      OK: nothing missing, no requests to the internet")
    else:
        log(f"      WARNING: {n} files missing, "
            f"{len(ve['external_requests'])} external requests")
        for m in ve["missing"][:20]:
            log(f"        missing {m}")

    files = sum(1 for _ in root.rglob("*") if _.is_file())
    mb = sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) / 1e6
    log(f"\ncopy in {root}: {files} files, {mb:.1f} MB")
    return {"static": st, "numbered": nu, "slug": sl, "played": pl, "verify": ve,
            "files": files, "mb": round(mb, 1)}
