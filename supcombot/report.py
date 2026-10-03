"""After-action report: JSON per game plus an optional short Ollama debrief."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from . import config
from .log import get

log = get("report")

GAMES_DIR = config.APP_DIR / "games"

DEBRIEF_PROMPT_DE = """Du bist Coach fuer Supreme Commander: Forged Alliance. Unten steht der Bericht eines Spiels,
das ein Bot gespielt hat (Zustand, Gebaeude, Angriffswellen, Ereignisse, Ergebnis). Schreibe auf Deutsch eine
Nachbesprechung mit genau 5 kurzen Stichpunkten: was gut lief, was schlecht lief, und drei konkrete Aenderungen
fuer das naechste Spiel (Strategie, Angriffsschwelle, Ingenieurzahl, Bauprioritaeten). Keine Einleitung."""


def write_report(state, settings: dict, map_name: str, map_key: str, start_slot: int, result: str) -> Path:
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "map": map_name,
        "map_key": map_key,
        "start_slot": start_slot,
        "faction": settings.get("faction"),
        "result": result,
        "game_seconds": int(state.game_time()),
        "strategy": state.strategy,
        "aggression": state.aggression,
        "snapshot": state.snapshot(),
        "structures": [{"role": s.role, "x": s.x, "z": s.z, "tech": s.tech} for s in state.structures],
        "waves": [{"started": int(w.started - state.started_at), "size": w.size, "seen": w.seen, "target": list(w.target),
                   "retreated": w.retreating, "reason": w.reason} for w in state.waves],
        "events": list(state.events),
        "advice_history": [],
    }
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in map_key)
    path = GAMES_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe}_{result}.json"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("Spielbericht: %s", path)
    return path


def debrief(advisor, report_path: Path) -> Optional[str]:
    """Ask Ollama for a short review of the saved report; stores the answer next to the report."""
    if advisor is None or advisor.available is False:
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        data["events"] = data["events"][-40:]
        import urllib.request

        body = {
            "model": advisor.model,
            "stream": False,
            "options": advisor.options,
            "messages": [{"role": "system", "content": DEBRIEF_PROMPT_DE},
                         {"role": "user", "content": json.dumps(data, ensure_ascii=False)[:12000]}],
        }
        req = urllib.request.Request(advisor.url + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=max(60, advisor.timeout)) as r:
            answer = json.loads(r.read().decode("utf-8")).get("message", {}).get("content", "").strip()
        if answer:
            data["debrief"] = answer
            report_path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            (report_path.with_suffix(".debrief.txt")).write_text(answer, encoding="utf-8")
            log.info("Nachbesprechung:\n%s", answer)
        return answer or None
    except Exception as exc:
        log.warning("Nachbesprechung fehlgeschlagen: %s", exc)
        return None


def list_reports(limit: int = 20):
    if not GAMES_DIR.exists():
        return []
    return sorted(GAMES_DIR.glob("*.json"), reverse=True)[:limit]
