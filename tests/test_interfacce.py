"""CLI and HTTP API: both must stay thin faces over the same game."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request

import pytest

from pokelike.cli.main import main


def _attendi(porta: int, secondi: float = 15.0) -> None:
    """Waits for the API to bind: the thread needs a moment before answering."""
    import socket
    import time

    scadenza = time.monotonic() + secondi
    while time.monotonic() < scadenza:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                return
        time.sleep(0.1)
    raise TimeoutError(f"l'API non risponde sulla porta {porta}")


def _cli(*argv) -> tuple[int, str]:
    """Runs the CLI in a subprocess and returns (exit code, output)."""
    r = subprocess.run(
        [sys.executable, "-m", "pokelike.cli.main", *argv],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode, r.stdout + r.stderr


def test_aiuto_elenca_tutti_i_comandi():
    codice, testo = _cli("--help")
    assert codice == 0
    for comando in ("setup", "mirror", "gioca", "bot", "api", "stats"):
        assert comando in testo, f"il comando {comando} non compare nell'aiuto"


@pytest.mark.parametrize("comando", ["setup", "mirror", "gioca", "bot", "api", "stats"])
def test_ogni_comando_ha_il_suo_aiuto(comando):
    codice, _ = _cli(comando, "--help")
    assert codice == 0


def test_senza_comando_esce_con_errore():
    codice, _ = _cli()
    assert codice != 0


def test_bot_sconosciuto_esce_con_errore_leggibile():
    codice, testo = _cli("bot", "--bot", "inesistente")
    assert codice != 0
    assert "casuale" in testo


def test_main_e_richiamabile_da_python():
    """`main` must not assume it owns the process."""
    with pytest.raises(SystemExit):
        main(["--help"])


# --------------------------------------------------------------------- API
#
# Il server gira sul THREAD PRINCIPALE e le richieste partono da un thread di
# lavoro, non il contrario: l'API sincrona di Playwright è legata al thread che
# ha creato la partita, quindi i gestori devono girare lì.


def _client_api(porta, passi, esiti):
    """Esegue le chiamate HTTP e poi ferma il server, così serve_forever esce."""
    import time

    scadenza = time.monotonic() + 15
    while time.monotonic() < scadenza:
        import socket

        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                break
        time.sleep(0.1)

    base = f"http://127.0.0.1:{porta}"

    def get(rotta):
        with urllib.request.urlopen(f"{base}{rotta}", timeout=60) as r:
            return json.loads(r.read())

    def post(rotta, corpo):
        req = urllib.request.Request(
            f"{base}{rotta}", data=json.dumps(corpo).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())

    try:
        esiti.update(passi(get, post))
    except Exception as e:  # noqa: BLE001
        esiti["errore"] = f"{type(e).__name__}: {e}"


def _con_api(server, seed, passi):
    """Avvia partita + API, lascia fare al client, restituisce i suoi esiti."""
    import threading

    from pokelike.api.server import crea_api
    from pokelike.core.game import Partita

    porta = 8553
    gioco = Partita(url=server.url)
    gioco.apri()
    try:
        gioco.nuova(seed=seed)
        httpd = crea_api(gioco, porta)
        esiti: dict = {}
        t = threading.Thread(target=lambda: (_client_api(porta, passi, esiti),
                                             httpd.shutdown()), daemon=True)
        t.start()
        httpd.serve_forever()          # sul thread principale, come in produzione
        httpd.server_close()
        t.join(timeout=10)
        return esiti
    finally:
        gioco.chiudi()


@pytest.mark.slow
def test_api_espone_il_giro_completo(server):
    """Comincia, leggi, agisci, calcola il punteggio — tutto via HTTP."""

    def passi(get, post):
        stato = post("/nuova", {"seed": 21})
        azioni = get("/azioni")["azioni"]
        dopo = post("/azione", {"indice": 0})
        return {
            "seed": stato["seed"],
            "ha_vista": "vista" in stato,
            "n_azioni": len(azioni),
            "passi_prima": stato["passi"],
            "passi_dopo": dopo["passi"],
            "stato_allineato": get("/stato")["passi"] == dopo["passi"],
            "ha_punti": "punti" in get("/punteggio"),
        }

    e = _con_api(server, 21, passi)
    assert "errore" not in e, e.get("errore")
    assert e["seed"] == 21
    assert e["ha_vista"], "la vista pronta da stampare deve esserci"
    assert e["n_azioni"] >= 2
    assert e["passi_dopo"] == e["passi_prima"] + 1
    assert e["stato_allineato"]
    assert e["ha_punti"]


@pytest.mark.slow
def test_api_rifiuta_azione_illegale(server):
    def passi(get, post):
        try:
            post("/azione", {"indice": 99})
            return {"codice": None}
        except urllib.error.HTTPError as e:
            return {"codice": e.code}

    e = _con_api(server, 22, passi)
    assert e.get("codice") == 409, "un'azione illegale è un conflitto, non un errore interno"
