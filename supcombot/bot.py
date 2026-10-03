"""Main bot loop: perception -> planning -> input, in a worker thread."""
from __future__ import annotations

import json
import threading
import time
from typing import Dict, List, Optional, Tuple

from . import layouts, vision
from .camera import CalibrationError, Camera
from .capture import crop
from .game import Game
from .inputs import AbortedError
from .livevision import FrameStream, Perception, Percepts
from .log import get
from .maps import MapInfo
from .ollama import OllamaAdvisor
from .planner import attack as attack_plan
from .planner import production
from .planner.builder import MapContext, Wish, choose_spot, dist, make_context, opening_orders, wishlist
from .planner.economy import Economy
from .state import BotState, Structure

log = get("bot")
LAND_ROLES = ("eng", "tank", "arty", "maa", "scout")
AIR_ROLES = ("scout", "inter", "bomber")


class Bot(threading.Thread):
    def __init__(self, settings: dict, game: Game, map_info: MapInfo, advisor: Optional[OllamaAdvisor]) -> None:
        super().__init__(name="supcombot-loop", daemon=True)
        self.settings = settings
        self.game = game
        self.map = map_info
        self.advisor = advisor
        self.camera = Camera(game, map_info)
        self.eco = Economy(game.profile, settings)
        self.state = BotState()
        self.ctx: MapContext = make_context(map_info, int(settings.get("start_slot", 1)), list(settings.get("enemy_slots", [])),
                                            list(settings.get("ally_slots", [])))
        self.layout: Optional[dict] = None
        self.layout_used: set = set()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.status: Dict[str, object] = {"status": "Bereit", "map": map_info.name}
        self.tick_count = 0
        self.last_state_log = 0.0
        self.last_ollama = 0.0
        self.base_radius = 60.0
        self._pending_actions: List[str] = []
        self.last_defense = 0.0
        vis = settings.get("vision", {})
        self.stream = FrameStream(game, fps=vis.get("fps", 20), backend=vis.get("backend", "auto"))
        game.stream = self.stream
        self.perception = Perception(self.stream, game, self.camera, self.ctx, hz=vis.get("perception_hz", 5),
                                     base_radius=self.base_radius, scan_whole_map=bool(vis.get("scan_whole_map", True)))
        self.new_game()

    # ------------------------------------------------------------------ lifecycle
    def new_game(self) -> None:
        with self.lock:
            self.state = BotState()
            self.state.strategy = self.settings.get("strategy", "balanced")
            self.state.aggression = int(self.settings.get("aggression", 2))
            self.layout_used = set()
            self.layout = None
            self.tick_count = 0
            if self.settings.get("use_layout_memory"):
                sk = layouts.start_key(*self.ctx.start)
                self.layout = layouts.load(self.map.key, sk)
                if self.layout:
                    self.state.layout_slots = len(self.layout.get("entries", []))
                    self.state.event(f"Layout geladen: {self.state.layout_slots} Slots, {self.layout.get('wins', 0)} Siege")
            self.state.event(f"Neues Spiel: {self.map.name}, Start {self.settings.get('start_slot')}, Gegner {len(self.ctx.enemies)}")
            self.camera.detect_failures = 0
            self.perception.ctx = self.ctx
        log.info("Neues Spiel vorbereitet: %s (%dx%d), %d Mass-Marker", self.map.name, *self.map.size, len(self.map.mass))

    def request(self, action: str) -> None:
        """Thread-safe request from overlay / hotkeys (attack_now, report_win, report_loss, new_game)."""
        with self.lock:
            self._pending_actions.append(action)

    def stop(self) -> None:
        self.stop_event.set()
        self.game.inputs.abort.set()

    def set_enabled(self, enabled: bool) -> None:
        self.settings["bot_enabled"] = enabled
        if not enabled:
            self.game.inputs.abort.set()
        else:
            self.game.inputs.abort.clear()
        self.state.event("Bot " + ("aktiviert" if enabled else "pausiert"))

    # ------------------------------------------------------------------ main loop
    def run(self) -> None:
        log.info("Bot-Thread gestartet")
        if not self.stream.is_alive():
            self.stream.start()
        if not self.perception.is_alive():
            self.perception.start()
        while not self.stop_event.is_set():
            try:
                self._process_requests()
                if not self.settings.get("bot_enabled"):
                    self._set_status("Pausiert (" + self.settings["hotkeys"]["toggle_bot"] + ")")
                    time.sleep(0.4)
                    continue
                if self.state.result:
                    self._set_status("Spiel beendet: " + self.state.result)
                    time.sleep(0.5)
                    continue
                if not self.game.hwnd and not self.game.attach():
                    self._set_status("Spielfenster nicht gefunden")
                    time.sleep(1.0)
                    continue
                if not self.game.focused():
                    self._set_status("Spiel nicht im Vordergrund - warte")
                    time.sleep(0.8)
                    continue
                self.game.inputs.abort.clear()
                self.tick()
                time.sleep(float(self.settings.get("loop_interval", 3.0)))
            except AbortedError:
                log.info("Aktion abgebrochen")
                self.game.inputs.release_all()
                time.sleep(0.3)
            except CalibrationError as exc:
                log.error("%s", exc)
                self.state.event(str(exc))
                self.settings["bot_enabled"] = False
            except Exception:  # keep the loop alive, report in the log
                log.exception("Fehler im Bot-Tick")
                self.game.inputs.release_all()
                time.sleep(1.0)
        self.game.inputs.release_all()
        self.perception.stop()
        self.stream.stop()
        log.info("Bot-Thread beendet")

    def _process_requests(self) -> None:
        with self.lock:
            actions, self._pending_actions = self._pending_actions, []
        for a in actions:
            if a == "attack_now":
                if self.settings.get("bot_enabled") and self.game.focused():
                    try:
                        self.camera.ensure_strategic(redetect=False)
                        self.launch_wave("hotkey")
                    except (AbortedError, CalibrationError) as exc:
                        self.state.event(f"Angriff nicht moeglich: {exc}")
                else:
                    self.state.event("Angriff: Bot ist aus oder Spiel nicht im Vordergrund")
            elif a == "report_win":
                self.finish_game(True, "manuell")
            elif a == "report_loss":
                self.finish_game(False, "manuell")
            elif a == "new_game":
                self.new_game()

    def _set_status(self, text: str) -> None:
        self.status["status"] = text
        self._refresh_status()

    def _refresh_status(self) -> None:
        s = self.state
        self.status.update({
            "phase": s.phase,
            "game_time": int(s.game_time()),
            "mass": s.mass_ratio, "energy": s.energy_ratio,
            "mass_stall": s.mass_stall, "energy_stall": s.energy_stall,
            "army": int(s.army_estimate), "army_seen": s.army_seen, "waves": len(s.waves),
            "threshold": attack_plan.threshold(s, self.settings),
            "strategy": s.strategy, "aggression": s.aggression, "focus": s.focus,
            "structures": len(s.structures), "mex": s.count("mex"), "factories": len(s.factories()),
            "engineers": s.engineers_ordered,
            "last_event": s.last_status,
            "advice": (s.advice or {}).get("note", ""),
            "ollama": (self.advisor.last_error or f"ok ({self.advisor.model})") if self.advisor else "aus",
            "layout_slots": s.layout_slots,
            "result": s.result,
            "map": self.map.name,
            "start": self.settings.get("start_slot"),
            "vision_fps": round(self.stream.measured_fps, 1),
            "vision_backend": self.stream.backend,
            "map_view_valid": self.percepts().map_view_valid,
            "enemies_near_base": self.percepts().enemies_near_base,
            "enemies_total": self.percepts().enemies_total,
            "analysis_ms": round(self.percepts().analysis_ms, 1),
            "allies": len(self.settings.get("ally_slots", [])),
            "enemies": len(self.ctx.enemies),
        })

    def set_slots(self, start_slot: int, enemy_slots, ally_slots) -> None:
        """Re-create the map context after the slot assignment changed (multiplayer lobbies)."""
        self.settings["start_slot"] = int(start_slot)
        self.settings["enemy_slots"] = list(enemy_slots)
        self.settings["ally_slots"] = list(ally_slots)
        self.ctx = make_context(self.map, int(start_slot), list(enemy_slots), list(ally_slots))
        self.perception.ctx = self.ctx
        self.request("new_game")

    def percepts(self) -> Percepts:
        return self.perception.percepts()

    # ------------------------------------------------------------------ one tick
    def tick(self) -> None:
        s = self.state
        self.tick_count += 1
        self._set_status("Aktiv")
        self.camera.ensure_strategic(redetect=(self.tick_count % 5 == 1))
        img = self.game.screenshot()
        p = self.percepts()
        live = time.time() - p.ts < 1.5
        if live and p.mass is not None:
            self.eco.apply(p.mass, p.energy or 0.0, s)
        else:
            self.eco.read(img, s)
        self.update_strategy()
        if (live and p.end_result and self._finish_from_percept(p.end_result)) or self.detect_end(img):
            return
        if not s.opening_done:
            self.do_opening()
            self._after_tick()
            return
        if live and p.map_view_valid and p.army_seen is not None:
            s.army_seen = p.army_seen
            s.army_estimate = attack_plan.estimate_army(s)
        else:
            self.update_army_estimate(img)
        actions = 0
        if self.settings.get("auto_defense") and live and p.map_view_valid and p.enemies_near_base > 0:
            actions += self.handle_defense(p)
        if self.settings.get("build_manager"):
            actions += self.handle_idle_engineers(max_jobs=2)
        if self.settings.get("production_manager"):
            actions += self.handle_factories()
        if self.settings.get("eco_manager") and actions < 2:
            self.handle_upgrades()
        if self.settings.get("auto_attack") and attack_plan.should_launch(s, self.settings):
            self.launch_wave("auto")
        self._after_tick()

    def _after_tick(self) -> None:
        s = self.state
        t = s.game_time()
        if s.count("mex") < 4 and t < 300:
            s.phase = "opening"
        elif t > 1200 and s.count("mex") >= 8:
            s.phase = "tech2"
        else:
            s.phase = "expand"
        if time.time() - self.last_state_log > 15:
            self.last_state_log = time.time()
            log.info("STATE %s", json.dumps(s.snapshot(), ensure_ascii=False))
        self.maybe_ask_ollama()
        self._refresh_status()

    # ------------------------------------------------------------------ strategy / advice
    def update_strategy(self) -> None:
        s = self.state
        fresh = s.advice and time.time() - s.advice_at < 180 and self.settings.get("use_ollama")
        s.strategy = self.settings.get("strategy", "balanced")
        s.aggression = int(self.settings.get("aggression", 2))
        s.focus = "land"
        if fresh and s.advice:
            s.strategy = s.advice.get("strategy", s.strategy)
            s.aggression = int(s.advice.get("aggression", s.aggression))
            s.focus = s.advice.get("focus", s.focus)

    def maybe_ask_ollama(self) -> None:
        if not (self.advisor and self.settings.get("use_ollama")):
            return
        interval = float(self.settings.get("ollama", {}).get("interval", 45))
        if time.time() - self.last_ollama < interval or self.state.game_time() < 90:
            return
        self.last_ollama = time.time()
        snapshot, events = self.state.snapshot(), list(self.state.events)

        def worker() -> None:
            adv = self.advisor.ask(snapshot, events)
            if adv:
                self.state.advice = adv
                self.state.advice_at = time.time()
                self.state.event("Ollama: " + adv.get("note", "")[:60])

        threading.Thread(target=worker, name="ollama", daemon=True).start()

    # ------------------------------------------------------------------ perception
    def update_army_estimate(self, img) -> None:
        s = self.state
        color = self.game.profile.team_color
        if color and self.camera.rect:
            rect = self.camera.world_rect_to_client(self.ctx.rally[0], self.ctx.rally[1], 28)
            region = crop(img, rect)
            mask = vision.color_mask(region, color, tol=60)
            s.army_seen = vision.count_blobs(mask, min_pixels=2, max_blobs=300)
        s.army_estimate = attack_plan.estimate_army(s)

    def detect_end(self, img) -> bool:
        for name, won in (("victory", True), ("defeat", False)):
            tpl = self.game.profile.template(name)
            if not tpl:
                continue
            patch, x, y = tpl
            if vision.match_template_at(img, patch, x, y, search=4) > 0.86:
                self.finish_game(won, "erkannt")
                return True
        return False

    def _finish_from_percept(self, result: str) -> bool:
        self.finish_game(result == "won", "live erkannt")
        return True

    def handle_defense(self, p: Percepts) -> int:
        """Enemy icons inside the base: send everything at the rally point against them (every 20 s)."""
        s = self.state
        now = time.time()
        if now - self.last_defense < 20 or p.enemy_world is None:
            return 0
        self.last_defense = now
        self.camera.box_select_world(self.ctx.rally[0], self.ctx.rally[1], 30)
        self.game.wait(0.3)
        mod = self.settings.get("input", {}).get("attack_move_modifier", "alt") or None
        self.camera.click_world(p.enemy_world[0], p.enemy_world[1], button="right", modifier=mod)
        self.game.deselect()
        s.event(f"Verteidigung: {p.enemies_near_base} Gegner-Symbole bei ({int(p.enemy_world[0])},{int(p.enemy_world[1])})")
        return 1

    def finish_game(self, won: bool, how: str) -> None:
        s = self.state
        if s.result:
            return
        s.result = "won" if won else "lost"
        entries = [{"role": st.role, "dx": round(st.x - self.ctx.start[0], 1), "dz": round(st.z - self.ctx.start[1], 1)}
                   for st in s.structures if st.role not in ("mex", "hydro")]
        if self.settings.get("use_layout_memory"):
            rec = layouts.store_result(self.map.key, layouts.start_key(*self.ctx.start), won, entries,
                                       {"faction": self.settings.get("faction"), "game_time": int(s.game_time())})
            s.layout_slots = len(rec.get("entries", []))
        s.event(("SIEG" if won else "NIEDERLAGE") + f" ({how}), Layout " + ("gespeichert" if won else "bewertet"))
        self.game.inputs.abort.set()
        self._refresh_status()

    # ------------------------------------------------------------------ opening
    def do_opening(self) -> None:
        s = self.state
        g = self.game
        if not g.ui_visible("ui.build.mex"):
            self.camera.click_world(*self.ctx.start)
            g.wait(0.4)
            if not g.ui_visible("ui.build.mex"):
                g.deselect()
                s.event("ACU nicht auswaehlbar - bitte ACU manuell anklicken")
                if s.game_time() > 90:
                    s.opening_done = True
                return
        orders = opening_orders(s, self.ctx, self.layout, self.layout_used)
        for w in orders:
            if not self.place(w, w.pos):
                continue
        g.press("escape")
        g.deselect()
        s.opening_done = True
        s.event(f"Eroeffnung: {len(orders)} Bauauftraege fuer den ACU")

    def place(self, wish: Wish, pos: Tuple[float, float], builder: str = "eng") -> bool:
        """Click the build button, then shift-click the world position. Returns False if not calibrated."""
        key = "ui.build." + wish.role
        if not self.game.profile.has(key):
            return False
        if wish.role in ("pgen2", "pd2", "aa2", "shield2") and self.game.profile.has("ui.build.tab_t2"):
            self.game.click_ui("ui.build.tab_t2")
        self.game.click_ui(key)
        self.camera.click_world(pos[0], pos[1], shift=True)
        return True

    # ------------------------------------------------------------------ engineers
    def handle_idle_engineers(self, max_jobs: int = 2) -> int:
        s, g = self.state, self.game
        if not g.profile.has("ui.idle_engineer"):
            return 0
        jobs = 0
        for _ in range(max_jobs):
            if not g.ui_visible("ui.idle_engineer"):
                break
            s.idle_engineers_seen += 1
            g.click_ui("ui.idle_engineer")
            g.wait(0.35)
            self.camera.zoom_out_fully()
            if not g.ui_visible("ui.build.mex"):
                g.deselect()
                break
            if not self.assign_jobs():
                self.assist_or_patrol()
            g.press("escape")
            g.deselect()
            jobs += 1
        return jobs

    def assign_jobs(self, max_orders: int = 3) -> bool:
        s = self.state
        has_t2 = self.game.profile.has("ui.build.tab_t2") and s.game_time() > 900
        wishes = wishlist(s, self.ctx, self.settings, has_t2)
        budget = Economy.build_budget(s)
        now = time.time()
        in_progress = sum(1 for st in s.structures if now - st.ordered_at < 120 and st.role not in ("mex",))
        orders = 0
        for w in wishes:
            if orders >= max_orders:
                break
            if in_progress >= budget and w.prio < 95:
                break
            if not self.game.profile.has("ui.build." + w.role):
                continue
            pos = choose_spot(s, self.ctx, w, self.layout, self.layout_used, self.base_radius)
            if pos is None:
                continue
            if self.place(w, pos):
                s.add_structure(w.role, pos[0], pos[1], marker=w.marker)
                orders += 1
                in_progress += 1
        if orders:
            s.event(f"Ingenieur: {orders} Auftraege ({', '.join(w.role for w in wishes[:orders])})")
        return orders > 0

    def assist_or_patrol(self) -> None:
        """Nothing to build: assist the newest factory (right click on it) or patrol-reclaim around the base."""
        facs = self.state.factories()
        if facs:
            f = facs[-1]
            self.camera.click_world(f.x, f.z, button="right")
            self.state.event("Ingenieur assistiert Fabrik")
        else:
            x, z = self.ctx.start
            self.game.press("p")
            for dx, dz in ((12, 12), (-12, 12), (-12, -12), (12, -12)):
                self.camera.click_world(x + dx, z + dz, shift=True)
            self.state.event("Ingenieur patrouilliert (Reclaim)")

    # ------------------------------------------------------------------ factories
    def handle_factories(self) -> int:
        s, g = self.state, self.game
        now = time.time()
        if g.profile.has("ui.idle_factory") and g.ui_visible("ui.idle_factory"):
            g.click_ui("ui.idle_factory")
            g.wait(0.35)
            self.camera.zoom_out_fully()
            kind = self.selected_factory_kind()
            if kind:
                self.queue_units(kind, None)
                return 1
            g.deselect()
        for fac in sorted(s.factories(), key=lambda f: f.last_queue_at):
            if now - fac.ordered_at < 75 or now - fac.last_queue_at < 90:
                continue
            self.camera.click_world(fac.x, fac.z)
            g.wait(0.35)
            kind = self.selected_factory_kind()
            if kind:
                self.queue_units(kind, fac)
            else:
                fac.last_queue_at = now - 45  # try again a bit later; maybe not finished yet
                g.deselect()
            return 1
        return 0

    def selected_factory_kind(self) -> Optional[str]:
        g = self.game
        if g.ui_visible("ui.factory.land.eng") or g.ui_visible("ui.factory.land.tank"):
            return "land"
        if g.ui_visible("ui.factory.air.inter") or g.ui_visible("ui.factory.air.scout"):
            return "air"
        return None

    def queue_units(self, kind: str, fac: Optional[Structure]) -> None:
        s, g = self.state, self.game
        n = Economy.factory_queue_size(s)
        if kind == "land":
            avail = [r for r in LAND_ROLES if g.profile.has(f"ui.factory.land.{r}")]
            roles = production.land_queue(s, self.settings, avail, n)
        else:
            avail = [r for r in AIR_ROLES if g.profile.has(f"ui.factory.air.{r}")]
            roles = production.air_queue(s, avail, n)
        for r in roles:
            g.click_ui(f"ui.factory.{kind}.{r}")
        if fac is None:
            # Unknown which factory: assume the one queued least recently.
            cands = [f for f in s.factories(kind)]
            fac = min(cands, key=lambda f: f.last_queue_at) if cands else None
        if fac:
            fac.queued_units += len(roles)
            fac.last_queue_at = time.time()
            if not fac.rally_set:
                self.camera.click_world(self.ctx.rally[0], self.ctx.rally[1], button="right")
                fac.rally_set = True
        g.deselect()
        s.event(f"Fabrik ({kind}): {', '.join(roles)}")

    # ------------------------------------------------------------------ upgrades
    def handle_upgrades(self) -> None:
        s, g = self.state, self.game
        if not g.profile.has("ui.upgrade") or not Economy.can_upgrade(s):
            return
        gap = {"rush": 150, "balanced": 75, "eco": 55, "turtle": 80}.get(s.strategy, 75)
        if time.time() - s.last_upgrade_at < gap or s.game_time() < 240:
            return
        now = time.time()
        mexes = [m for m in s.structures if m.role == "mex" and m.tech == 1 and now - m.ordered_at > 120]
        mexes.sort(key=lambda m: dist(m.pos(), self.ctx.start))
        if not mexes:
            return
        m = mexes[0]
        self.camera.click_world(m.x, m.z)
        g.wait(0.35)
        if g.ui_visible("ui.upgrade"):
            g.click_ui("ui.upgrade")
            m.tech = 2
            s.last_upgrade_at = now
            s.event(f"Mex-Upgrade bei ({int(m.x)},{int(m.z)})")
        else:
            m.ordered_at = now  # probably not built yet; look again later
        g.deselect()

    # ------------------------------------------------------------------ attacks
    def launch_wave(self, reason: str) -> None:
        s = self.state
        p = self.percepts()
        clusters = p.enemy_clusters if (time.time() - p.ts < 1.5 and p.map_view_valid) else None
        target = attack_plan.pick_target(s, self.ctx, self.ctx.rally, clusters, self.base_radius)
        if target is None:
            s.event("Kein Angriffsziel (keine Gegnerposition bekannt)")
            return
        size = int(max(1, attack_plan.estimate_army(s)))
        self.camera.box_select_world(self.ctx.rally[0], self.ctx.rally[1], 30)
        self.game.wait(0.3)
        mod = self.settings.get("input", {}).get("attack_move_modifier", "alt") or None
        self.camera.click_world(target[0], target[1], button="right", modifier=mod)
        attack_plan.record_wave(s, size, target, reason)
        self.game.deselect()
