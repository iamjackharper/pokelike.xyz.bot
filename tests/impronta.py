"""Builds the fingerprint of a played game.

This is the heart of the regression suite. The fingerprint contains only data
that comes **from the game engine** — screen ids, node types, Pokemon names,
scores — never text we write ourselves. That is deliberate: our own wording can
be translated or reworded, the engine's data cannot change without a real
behavioural regression.

So the same fingerprint file stays valid across a full translation of this
codebase, and any difference in it is a genuine bug.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).parent / "golden" / "partite.json"


def politica_fissa(stato: dict[str, Any]) -> int:
    """Always the first legal action. Fully deterministic, no RNG involved."""
    return 0


def politica_ciclica(stato: dict[str, Any]) -> int:
    """Cycles through the options, so the run does not always hug one branch."""
    return stato["passi"] % len(stato["azioni"])


POLITICHE = {"fissa": politica_fissa, "ciclica": politica_ciclica}


def _azione_stabile(a: dict[str, Any]) -> str:
    """A label that survives translation: it comes from the game, not from us."""
    if a.get("tipo") == "nodo":
        return f"{a['id']}:{a['nodo']}"
    # `etichetta` is the button text rendered by the game itself (English).
    return f"el{a['idx']}:{(a.get('etichetta') or '')[:40]}"


def impronta(gioco, seed: int, politica: str, max_passi: int = 120) -> dict[str, Any]:
    """Plays one game and returns its fingerprint."""
    scegli = POLITICHE[politica]
    obs = gioco.nuova(seed=seed)
    passi: list[str] = []

    while not obs.get("finita") and obs.get("azioni") and gioco.passi < max_passi:
        i = scegli(obs)
        passi.append(f"{obs['schermata']}|{len(obs['azioni'])}|{_azione_stabile(obs['azioni'][i])}")
        obs = gioco.esegui(i)

    p = gioco.punteggio() or {}
    vivo = gioco.ultimo_vivo or obs
    return {
        "seed": seed,
        "politica": politica,
        "passi": gioco.passi,
        "schermata_finale": obs.get("schermata"),
        "punti": p.get("punti_senza_tempo"),
        "dettaglio": p.get("dettaglio"),
        "squadra": [
            {"nome": m["nome"], "livello": m["livello"], "hp": m["hp"], "hp_max": m["hp_max"]}
            for m in (vivo.get("squadra") or [])
        ],
        "traccia": passi,
    }


def carica_golden() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def salva_golden(dati: dict[str, Any]) -> None:
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(dati, indent=1, ensure_ascii=False), encoding="utf-8")


# Games recorded in the golden file. Kept small on purpose: each one costs about
# ten seconds of wall clock.
CASI = [(1, "fissa"), (2, "fissa"), (3, "ciclica"), (7, "ciclica")]
