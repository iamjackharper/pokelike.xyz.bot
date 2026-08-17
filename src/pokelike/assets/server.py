"""Server statico che serve il gioco dal disco.

In funzionamento normale è completamente offline: legge solo da `site/` e non
tocca la rete. Se un file manca lo annota in `mancanti` e risponde 404 — è così
che lo strumento di mirror scopre cosa gli è sfuggito.

Con `origine` impostata (solo durante il mirror) scarica il file mancante,
lo salva e lo serve: la cache si riempie da sola giocando.
"""

from __future__ import annotations

import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

TIPI = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json",
    ".webmanifest": "application/manifest+json", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ico": "image/x-icon",
}


class ServerAsset:
    def __init__(
        self,
        radice: Path,
        porta: int = 8422,
        origine: str | None = None,
    ) -> None:
        self.radice = Path(radice)
        self.porta = porta
        self.origine = origine.rstrip("/") if origine else None
        self.mancanti: set[str] = set()
        self.scaricati: set[str] = set()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.porta}/"

    def _percorso(self, richiesta: str) -> Path:
        rel = unquote(urlparse(richiesta).path).lstrip("/")
        if not rel or rel.endswith("/"):
            rel += "index.html"
        # Nessuna risalita fuori dalla radice.
        p = (self.radice / rel).resolve()
        if not str(p).startswith(str(self.radice.resolve())):
            raise PermissionError(rel)
        return p

    def _scarica(self, richiesta: str, dest: Path) -> bytes | None:
        if not self.origine:
            return None
        url = self.origine + urlparse(richiesta).path
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status != 200:
                    return None
                dati = r.read()
        except Exception:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(dati)
        self.scaricati.add(urlparse(richiesta).path)
        return dati

    def avvia(self) -> None:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # silenzio
                pass

            def do_GET(self) -> None:  # noqa: N802 (nome imposto da BaseHTTPRequestHandler)
                try:
                    p = server._percorso(self.path)
                except PermissionError:
                    self.send_error(403)
                    return

                dati = p.read_bytes() if p.is_file() else server._scarica(self.path, p)
                if dati is None:
                    server.mancanti.add(urlparse(self.path).path)
                    self.send_error(404)
                    return

                self.send_response(200)
                self.send_header("Content-Type", TIPI.get(p.suffix.lower(), "application/octet-stream"))
                self.send_header("Content-Length", str(len(dati)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(dati)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.porta), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def ferma(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> "ServerAsset":
        self.avvia()
        return self

    def __exit__(self, *_exc) -> None:
        self.ferma()
