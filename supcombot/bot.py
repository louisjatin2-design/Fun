"""Main bot loop: perception -> planning -> input, in a worker thread."""
from __future__ import annotations

import json
import threading
import time
from typing import Dict, List, Optional, Tuple

from . import layouts, report, vision, win
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
from .planner.builder import FOOTPRINT, MapContext, Wish, choose_spot, dist, make_context, opening_orders, wishlist
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
        self.user_active_until = 0.0
        self.last_factory_upgrade_check = 0.0
        self.auto_strategy = "balanced"
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
            sk0 = layouts.start_key(*self.ctx.start)
            self.auto_strategy = layouts.best_strategy(self.map.key, sk0, "balanced")
            self.state.strategy = self.auto_strategy if self.settings.get("strategy") == "auto" else self.settings.get("strategy", "balanced")
            self.state.strategy_auto = self.auto_strategy
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
                if self.user_active():
                    self._set_status("Du bewegst die Maus - Bot wartet")
                    time.sleep(0.5)
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

    def user_active(self) -> bool:
        """True while the user moves the mouse (the bot yields for `yield_to_user_seconds`)."""
        grace = float(self.settings.get("input", {}).get("yield_to_user_seconds", 4) or 0)
        if grace <= 0 or self.game.dry_run or not win.IS_WINDOWS:
            return False
        now = time.time()
        inp = self.game.inputs
        try:
            cur = win.cursor_pos()
        except Exception:
            return False
        if inp.last_pos is not None and now - inp.last_move_time > 0.4:
            if abs(cur[0] - inp.last_pos[0]) + abs(cur[1] - inp.last_pos[1]) > 25:
                self.user_active_until = now + grace
                inp.last_pos = cur
        return now < self.user_active_until

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
            "friendly_clusters": self.percepts().friendly_clusters,
            "enemy_clusters": self.percepts().enemy_clusters,
            "placements_rejected": s.placements_rejected,
            "factory_upgrades": s.factory_upgrades,
            "strategy_auto": self.auto_strategy,
            "debrief": s.debrief,
            "faction": s.faction_detected or self.game.profile.faction,
            "factory_tech": max([f.tech for f in s.factories()] or [1]),
            "events": list(s.events[-int(self.settings.get("overlay", {}).get("log_lines", 5)):]),
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
        if live and p.map_view_valid and p.enemies_near_base >= int(self.settings.get("input", {}).get("acu_retreat_threshold", 6)):
            actions += self.handle_acu_rescue(p)
        if self.settings.get("auto_defense") and live and p.map_view_valid and p.enemies_near_base > 0:
            actions += self.handle_defense(p)
        if live and p.map_view_valid and (p.friendly_clusters or p.enemy_clusters):
            actions += self.handle_waves(p)
        if self.settings.get("build_manager"):
            actions += self.handle_idle_engineers(max_jobs=2)
        if self.settings.get("production_manager"):
            actions += self.handle_factories()
        if self.settings.get("eco_manager") and actions < 2:
            self.handle_upgrades()
            self.handle_factory_upgrade()
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
        s.strategy = self.auto_strategy if self.settings.get("strategy") == "auto" else self.settings.get("strategy", "balanced")
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
                                       {"faction": self.settings.get("faction"), "game_time": int(s.game_time()), "strategy": s.strategy})
            s.layout_slots = len(rec.get("entries", []))
        s.event(("SIEG" if won else "NIEDERLAGE") + f" ({how}), Layout " + ("gespeichert" if won else "bewertet"))
        self.game.inputs.abort.set()
        self._refresh_status()
        if self.settings.get("debrief", True):
            try:
                path = report.write_report(s, self.settings, self.map.name, self.map.key, int(self.settings.get("start_slot", 1)), s.result)
            except Exception as exc:
                log.warning("Bericht nicht geschrieben: %s", exc)
                return

            def worker() -> None:
                text = report.debrief(self.advisor, path) if self.settings.get("use_ollama") else None
                if text:
                    s.debrief = text
                    s.event("Nachbesprechung von Ollama liegt vor (siehe Overlay/Log)")

            threading.Thread(target=worker, name="debrief", daemon=True).start()

    # ------------------------------------------------------------------ opening
    def detect_faction(self) -> Optional[str]:
        """With faction "auto": compare the build menu on screen with every calibrated faction profile."""
        from .profile import Profile

        frame = self.game.screenshot()
        best, best_score = None, 0.0
        for faction, prof in Profile.available(self.game.profile.resolution):
            scores = []
            for key in ("ui.build.mex", "ui.build.landFac", "ui.build.pgen"):
                patch = prof.patch(key)
                if patch is not None and prof.has(key):
                    x, y = prof.point(key)
                    scores.append(vision.match_template_at(frame, patch, x, y, search=2))
            if scores:
                score = sum(scores) / len(scores)
                if score > best_score:
                    best, best_score = (faction, prof), score
        if best and best_score >= 0.7:
            faction, prof = best
            if faction != self.game.profile.faction:
                prof.map_rects.update({k: v for k, v in self.game.profile.map_rects.items() if k not in prof.map_rects})
                self.game.profile = prof
                self.eco = Economy(prof, self.settings)
            self.state.event(f"Fraktion erkannt: {faction} ({best_score:.2f})")
            return faction
        return None

    def do_opening(self) -> None:
        s = self.state
        g = self.game
        if not g.ui_visible("ui.build.mex"):
            self.select_acu()
            g.wait(0.4)
            if self.settings.get("faction") == "auto" and not s.faction_detected:
                detected = self.detect_faction()
                if detected:
                    s.faction_detected = detected
            if not g.ui_visible("ui.build.mex"):
                g.deselect()
                s.event("ACU nicht auswaehlbar - bitte ACU manuell anklicken")
                if s.game_time() > 90:
                    s.opening_done = True
                return
        sequence = (self.settings.get("openings") or {}).get(s.strategy)
        orders = opening_orders(s, self.ctx, self.layout, self.layout_used, sequence)
        for w in orders:
            if not self.place(w, w.pos):
                continue
        g.press("escape")
        g.deselect()
        s.opening_done = True
        s.event(f"Eroeffnung: {len(orders)} Bauauftraege fuer den ACU")

    def place(self, wish: Wish, pos: Tuple[float, float], builder: str = "eng") -> bool:
        """Click the build button, check the preview colour, then shift-click the world position."""
        key = "ui.build." + wish.role
        if not self.game.profile.has(key):
            return False
        tier = production.role_tier(wish.role) if wish.role not in ("mex", "hydro") else 1
        tab = {2: "ui.build.tab_t2", 3: "ui.build.tab_t3"}.get(tier)
        if tab:
            if not self.game.profile.has(tab):
                return False
            self.game.click_ui(tab)
            if not self.game.ui_visible(key):
                # This engineer cannot build that tier: back to T1 and give up on this wish for now.
                if self.game.profile.has("ui.build.tab_t1"):
                    self.game.click_ui("ui.build.tab_t1")
                return False
        self.game.click_ui(key)
        if self.settings.get("input", {}).get("placement_check", True) and wish.role not in ("mex", "hydro") and not self.game.dry_run:
            checked = self.validate_spot(wish, pos)
            if checked is None:
                self.game.press("escape")
                return False
            pos = checked
        self.camera.click_world(pos[0], pos[1], shift=True)
        wish.pos = pos
        return True

    def validate_spot(self, wish: Wish, pos: Tuple[float, float], attempts: int = 4) -> Optional[Tuple[float, float]]:
        """Hover the template over the spot and read its colour; move on to another spot when it is red."""
        s = self.state
        upp = max(0.25, self.camera.units_per_pixel())
        radius = int(FOOTPRINT.get(wish.role, 3.0) / upp / 2) + 3
        for _ in range(attempts):
            cx, cy = self.camera.world_to_client(pos[0], pos[1])
            self.game.hover(cx, cy)
            self.game.wait(0.2)
            frame = self.game.screenshot()
            verdict = vision.placement_verdict(frame, cx, cy, radius=radius, min_pixels=max(3, radius // 2))
            if verdict != "blocked":
                return pos
            s.blocked_spots.append(pos)
            s.placements_rejected += 1
            self.game.save_debug(frame, f"blocked_{wish.role}")
            alt = choose_spot(s, self.ctx, Wish(wish.role, wish.prio, toward_enemy=wish.toward_enemy, near_mex=wish.near_mex),
                              self.layout, self.layout_used, self.base_radius)
            if alt is None or alt == pos:
                s.event(f"Kein gueltiger Bauplatz fuer {wish.role}")
                return None
            pos = alt
        return pos

    def select_acu(self) -> None:
        key = (self.settings.get("input", {}).get("select_acu_key") or "").strip().lower()
        if key:
            self.game.press(key)
        else:
            self.camera.click_world(*self.ctx.start)

    def handle_acu_rescue(self, p: Percepts) -> int:
        """Many enemy icons in the base: pull the ACU back behind the base (needs input.select_acu_key)."""
        s = self.state
        key = (self.settings.get("input", {}).get("select_acu_key") or "").strip()
        if not key or time.time() - s.last_acu_action < 30:
            return 0
        s.last_acu_action = time.time()
        safe = (self.ctx.start[0] + self.ctx.away[0] * 20, self.ctx.start[1] + self.ctx.away[1] * 20)
        self.game.press(key)
        self.game.wait(0.2)
        self.camera.click_world(safe[0], safe[1], button="right")
        self.game.deselect()
        s.acu_retreats += 1
        s.event(f"ACU-Rueckzug: {p.enemies_near_base} Gegner-Symbole in der Basis")
        return 1

    def handle_waves(self, p: Percepts) -> int:
        """Closed loop for running waves: retreat when outnumbered, advance to the next target when done."""
        s = self.state
        actions = attack_plan.manage_waves(s, self.ctx, p.friendly_clusters, p.enemy_clusters, time.time(), self.base_radius)
        done = 0
        mod = self.settings.get("input", {}).get("attack_move_modifier", "alt") or None
        for kind, wave, target in actions[:2]:
            if wave.last_pos is None:
                continue
            self.camera.box_select_world(wave.last_pos[0], wave.last_pos[1], 22)
            self.game.wait(0.25)
            if kind == "retreat":
                self.camera.click_world(self.ctx.rally[0], self.ctx.rally[1], button="right")
            elif kind == "advance" and target:
                self.camera.click_world(target[0], target[1], button="right", modifier=mod)
            self.game.deselect()
            done += 1
        return done

    def handle_factory_upgrade(self) -> None:
        """Upgrade land factories: first one T1->T2->T3, the others to T2 when mass floats (vanilla: each factory upgrades itself)."""
        s, g = self.state, self.game
        now = time.time()
        if now - self.last_factory_upgrade_check < 60:
            return
        self.last_factory_upgrade_check = now
        facs = [f for f in s.factories("land") if now - f.ordered_at > 120 and f.upgrading_until < now]
        if not facs:
            return
        if any(f.upgrading_until > now for f in s.factories("land")):
            return
        candidate, key, new_tech = None, None, 0
        t2 = [f for f in facs if f.tech == 2]
        t1 = [f for f in facs if f.tech == 1]
        if t2 and g.profile.has("ui.factory.upgrade3") and Economy.can_upgrade_factory_t3(s) and not any(f.tech >= 3 for f in s.factories("land")):
            candidate, key, new_tech = t2[0], "ui.factory.upgrade3", 3
        elif t1 and g.profile.has("ui.factory.upgrade") and Economy.can_upgrade_factory(s):
            has_t2_already = any(f.tech >= 2 for f in s.factories("land"))
            if not has_t2_already or (s.mass_float and len(facs) >= 2):
                candidate, key, new_tech = t1[0], "ui.factory.upgrade", 2
        if candidate is None:
            return
        self.camera.click_world(candidate.x, candidate.z)
        g.wait(0.35)
        if g.ui_visible(key):
            g.click_ui(key)
            candidate.tech = new_tech
            candidate.upgrading_until = now + (300 if new_tech == 3 else 200)
            candidate.repeat_set = False
            s.factory_upgrades += 1
            s.event(f"Fabrik-Upgrade auf T{new_tech} gestartet")
        g.deselect()

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
        prof = self.game.profile
        has_t2 = prof.has("ui.build.tab_t2") and s.game_time() > 900 and s.engineer_tier_seen >= 2
        has_t3 = prof.has("ui.build.tab_t3") and prof.has("ui.build.pgen3") and s.engineer_tier_seen >= 3
        wishes = wishlist(s, self.ctx, self.settings, has_t2, has_t3)
        budget = Economy.build_budget(s)
        now = time.time()
        in_progress = sum(1 for st in s.structures if now - st.ordered_at < 120 and st.role not in ("mex",))
        orders: List[str] = []
        for w in wishes:
            if len(orders) >= max_orders:
                break
            if in_progress >= budget and w.prio < 95:
                break
            if not self.game.profile.has("ui.build." + w.role):
                continue
            pos = choose_spot(s, self.ctx, w, self.layout, self.layout_used, self.base_radius)
            if pos is None:
                continue
            if self.place(w, pos):
                pos = w.pos or pos   # place() may have moved it after a red preview
                s.add_structure(w.role, pos[0], pos[1], marker=w.marker)
                orders.append(w.role)
                in_progress += 1
        if orders:
            s.event(f"Ingenieur: {len(orders)} Auftraege ({', '.join(orders)})")
        return bool(orders)

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
        if fac is None:
            # Unknown which factory: assume the one queued least recently.
            cands = [f for f in s.factories(kind)]
            fac = min(cands, key=lambda f: f.last_queue_at) if cands else None
        if fac and fac.upgrading_until > time.time():
            g.deselect()
            return
        tech = fac.tech if fac else 1
        if kind == "land":
            avail = [r for r in LAND_ROLES + ("eng2", "tank2", "maa2", "eng3", "tank3", "arty3") if g.profile.has(f"ui.factory.land.{r}")]
            base = [r for r in avail if production.role_tier(r) == 1]
            roles = production.tier_roles(production.land_queue(s, self.settings, base, n), tech, avail)
        else:
            avail = [r for r in AIR_ROLES + ("inter3", "bomber3") if g.profile.has(f"ui.factory.air.{r}")]
            roles = production.tier_roles(production.air_queue(s, [r for r in avail if production.role_tier(r) == 1], n), tech, avail)
        # Group by tier so each tab is clicked once; a tier whose tab is missing falls back to T1.
        tabs = {2: "ui.factory.tab_t2", 3: "ui.factory.tab_t3"}
        ordered = sorted(roles, key=production.role_tier)
        current_tab = 1
        for r in ordered:
            tier = production.role_tier(r)
            if tier != current_tab:
                tab = tabs.get(tier)
                if tab and g.profile.has(tab):
                    g.click_ui(tab)
                    current_tab = tier
                else:
                    r = r.rstrip("23")
                    if current_tab != 1:
                        continue
            g.click_ui(f"ui.factory.{kind}.{r}")
            if r.startswith("eng"):
                s.engineer_tier_seen = max(s.engineer_tier_seen, production.role_tier(r))
        roles = ordered
        if fac:
            fac.queued_units += len(roles)
            fac.last_queue_at = time.time()
            if g.profile.has("ui.factory.repeat") and not fac.repeat_set:
                g.click_ui("ui.factory.repeat")
                fac.repeat_set = True
                fac.last_queue_at = time.time() + 240   # repeat build: re-queue much later
            if not fac.rally_set:
                rally = self.ctx.rally
                if kind == "air" and self.ctx.nearest_enemy:
                    # Forward rally for air: scouts and interceptors give vision over the lane.
                    rally = (self.ctx.rally[0] + self.ctx.toward[0] * self.ctx.enemy_distance * 0.2,
                             self.ctx.rally[1] + self.ctx.toward[1] * self.ctx.enemy_distance * 0.2)
                elif kind == "land" and production.wants_home_guard(s) and len(s.factories("land")) >= 2 and fac is s.factories("land")[1]:
                    rally = (self.ctx.start[0] + self.ctx.toward[0] * 15, self.ctx.start[1] + self.ctx.toward[1] * 15)
                    fac.home_guard = True
                self.camera.click_world(rally[0], rally[1], button="right")
                fac.rally_set = True
        g.deselect()
        s.event(f"Fabrik ({kind}{' T2' if tech >= 2 else ''}): {', '.join(roles)}")

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
        key, new_tech = "ui.upgrade", 2
        t2_mexes = [m for m in s.structures if m.role == "mex" and m.tech == 2 and now - m.ordered_at > 420]
        t2_mexes.sort(key=lambda m: dist(m.pos(), self.ctx.start))
        if (not mexes or s.count("mex") - len(mexes) >= 6) and t2_mexes and g.profile.has("ui.upgrade3") and Economy.can_upgrade_mex_t3(s):
            mexes, key, new_tech = t2_mexes, "ui.upgrade3", 3
        if not mexes:
            return
        m = mexes[0]
        self.camera.click_world(m.x, m.z)
        g.wait(0.35)
        if g.ui_visible(key):
            g.click_ui(key)
            m.tech = new_tech
            m.ordered_at = now
            s.last_upgrade_at = now
            s.event(f"Mex-Upgrade auf T{new_tech} bei ({int(m.x)},{int(m.z)})")
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
        attack_plan.record_wave(s, size, target, reason, self.ctx.rally)
        self.game.deselect()
