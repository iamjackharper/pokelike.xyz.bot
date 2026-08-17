"""API HTTP JSON. Seconda faccia sopra la stessa `core.game.Partita`.

Endpoint:

    GET  /stato                 stato corrente (+ vista testuale)
    GET  /azioni                solo le azioni legali
    POST /nuova   {"seed": 42}  comincia una partita
    POST /azione  {"indice": 1} esegue un'azione
    GET  /punteggio             punteggio con la formula del gioco

Il browser resta acceso fra una chiamata e l'altra: è il motivo per cui serve
un processo vivo invece di un comando che parte e muore ogni volta.

Volutamente a thread singolo: una partita, un giocatore per volta.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from ..core import render
from ..core.game import ErroreAzione, Partita


def _handler(gioco: Partita):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        # ------------------------------------------------------------ utilità

        def _json(self, dati, codice: int = 200) -> None:
            corpo = json.dumps(dati, ensure_ascii=False).encode("utf-8")
            self.send_response(codice)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def _corpo(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return {}

        def _con_vista(self, obs: dict) -> dict:
            obs = dict(obs)
            obs["vista"] = render.schermo(obs)
            return obs

        # ------------------------------------------------------------ percorsi

        def do_GET(self) -> None:  # noqa: N802
            rotta = self.path.split("?")[0].rstrip("/") or "/"
            if rotta == "/":
                self._json({
                    "servizio": "pokelike",
                    "endpoint": ["/stato", "/azioni", "/nuova", "/azione", "/punteggio"],
                })
            elif rotta == "/stato":
                self._json(self._con_vista(gioco.stato()))
            elif rotta == "/azioni":
                self._json({"azioni": gioco.azioni()})
            elif rotta == "/punteggio":
                self._json(gioco.punteggio() or {"errore": "punteggio non disponibile"})
            else:
                self._json({"errore": "percorso sconosciuto"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            rotta = self.path.split("?")[0].rstrip("/") or "/"
            corpo = self._corpo()
            if rotta == "/nuova":
                obs = gioco.nuova(seed=int(corpo.get("seed", 1)))
                self._json(self._con_vista(obs))
            elif rotta == "/azione":
                if "indice" not in corpo:
                    self._json({"errore": "manca il campo 'indice'"}, 400)
                    return
                try:
                    obs = gioco.esegui(int(corpo["indice"]))
                except ErroreAzione as e:
                    self._json({"errore": str(e)}, 409)
                    return
                self._json(self._con_vista(obs))
            else:
                self._json({"errore": "percorso sconosciuto"}, 404)

    return Handler


def crea_api(gioco: Partita, porta: int = 8423) -> HTTPServer:
    """Costruisce il server senza avviarlo.

    Serve per poterlo fermare da codice: `httpd.shutdown()` si può chiamare da un
    altro thread, mentre `serve_forever()` va lasciato sul thread che possiede la
    partita (vedi la nota qui sotto).
    """
    return HTTPServer(("127.0.0.1", porta), _handler(gioco))


def avvia_api(gioco: Partita, porta: int = 8423) -> None:
    """Serve le richieste finché non arriva un ctrl-c.

    A thread singolo per necessità, non per pigrizia: l'API sincrona di
    Playwright è legata al thread che l'ha creata, quindi i gestori devono girare
    sullo stesso thread della partita. Servire da un thread diverso fallisce con
    `greenlet.error: Cannot switch to a different thread`.
    """
    httpd = crea_api(gioco, porta)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
