"""Ollama client: turns the bot's state into strategic advice (JSON) via the local HTTP API."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import List, Optional

from .log import get

log = get("ollama")

SYSTEM_PROMPT_DE = """Du bist der strategische Berater eines Bots, der Supreme Commander: Forged Alliance spielt.
Du bekommst den aktuellen Zustand als JSON (Wirtschaft, Gebaeude, Armee-Schaetzung, Zeit, Strategie) und die
letzten Ereignisse. Antworte NUR mit einem JSON-Objekt, keine Erklaerungen. Erlaubte Felder:
{
  "strategy": "balanced" | "eco" | "rush" | "turtle",
  "aggression": 1 | 2 | 3,
  "attackThreshold": Zahl 4..120,
  "maxEngineers": Zahl 3..40,
  "focus": "land" | "air" | "mixed",
  "armyMix": {"tank": 0..1, "arty": 0..1, "maa": 0..1, "scout": 0..1},
  "note": "max. 60 Zeichen Begruendung"
}
Regeln: Masse unter 10% und sinkend = Stall -> weniger Fabriken/Ingenieure, mehr Mex. Masse ueber 80% =
mehr Fabriken/Upgrades. Energie unter 20% = eco mit Fokus auf Generatoren. Frueh (< 6 min) keine grossen Umstellungen.
Verloren gegangene Angriffe -> Schwelle erhoehen. Gib nur Felder an, die du aendern willst."""

SYSTEM_PROMPT_EN = SYSTEM_PROMPT_DE  # The model answers JSON either way; German instructions work for most models.


class OllamaAdvisor:
    def __init__(self, url: str, model: str = "auto", timeout: int = 60, language: str = "de",
                 prefer: Optional[List[str]] = None, options: Optional[dict] = None) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.language = language
        self.prefer = prefer or ["llama3", "qwen", "mistral", "gemma", "phi"]
        self.options = {"temperature": 0.3}
        for k in ("num_ctx", "num_gpu", "num_thread"):
            v = (options or {}).get(k)
            if isinstance(v, int) and v > 0:
                self.options[k] = v
        self.available: Optional[bool] = None
        self.last_error = ""
        self.last_advice: Optional[dict] = None
        self.last_raw = ""
        self.history: List[dict] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ connection
    def list_models(self) -> List[str]:
        with urllib.request.urlopen(self.url + "/api/tags", timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]

    def check(self) -> bool:
        try:
            models = self.list_models()
        except Exception as exc:
            self.available = False
            self.last_error = f"Ollama nicht erreichbar unter {self.url}: {exc}"
            log.warning(self.last_error)
            return False
        if not models:
            self.available = False
            self.last_error = "Ollama laeuft, aber es ist kein Modell installiert (z.B. `ollama pull llama3.1`)."
            log.warning(self.last_error)
            return False
        if self.model == "auto" or self.model not in models:
            chosen = None
            for pref in self.prefer:           # ordered: biggest/best first (see settings ollama.prefer)
                hits = [m for m in models if m == pref or m.startswith(pref) or pref in m]
                if hits:
                    chosen = hits[0]
                    break
            chosen = chosen or models[0]
            if self.model != "auto":
                log.warning("Modell %s nicht gefunden, nutze %s", self.model, chosen)
            self.model = chosen
        self.available = True
        log.info("Ollama ok, Modell: %s", self.model)
        return True

    # ------------------------------------------------------------------ advice
    def ask(self, state: dict, events: List[str]) -> Optional[dict]:
        if self.available is False:
            return None
        prompt = SYSTEM_PROMPT_DE if self.language == "de" else SYSTEM_PROMPT_EN
        user = "ZUSTAND:\n" + json.dumps(state, ensure_ascii=False) + "\nEREIGNISSE:\n" + "\n".join(events[-25:] or ["-"])
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": self.options,
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
        }
        req = urllib.request.Request(self.url + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = f"Ollama-Anfrage fehlgeschlagen: {exc}"
            log.warning(self.last_error)
            return None
        content = (data.get("message") or {}).get("content", "")
        self.last_raw = content
        advice = parse_advice(content)
        if advice:
            advice["ts"] = time.time()
            with self._lock:
                self.last_advice = advice
                self.history.append(advice)
                self.history = self.history[-20:]
            log.info("Ollama-Rat: %s", json.dumps(advice, ensure_ascii=False))
        else:
            log.warning("Ollama-Antwort nicht verwertbar: %s", content[:200])
        return advice


def parse_advice(text: str) -> Optional[dict]:
    """Extract and validate the JSON object from a model answer."""
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        raw = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    if raw.get("strategy") in ("balanced", "eco", "rush", "turtle"):
        out["strategy"] = raw["strategy"]
    if isinstance(raw.get("aggression"), (int, float)):
        out["aggression"] = int(max(1, min(3, raw["aggression"])))
    if isinstance(raw.get("attackThreshold"), (int, float)):
        out["attackThreshold"] = int(max(4, min(120, raw["attackThreshold"])))
    if isinstance(raw.get("maxEngineers"), (int, float)):
        out["maxEngineers"] = int(max(3, min(40, raw["maxEngineers"])))
    if raw.get("focus") in ("land", "air", "mixed"):
        out["focus"] = raw["focus"]
    mix = raw.get("armyMix")
    if isinstance(mix, dict):
        clean = {k: float(v) for k, v in mix.items() if k in ("tank", "arty", "maa", "scout") and isinstance(v, (int, float)) and v >= 0}
        total = sum(clean.values())
        if total > 0:
            out["armyMix"] = {k: v / total for k, v in clean.items()}
    note = raw.get("note")
    out["note"] = str(note)[:80] if note is not None else ""
    return out
