"""Main bot loop: perception -> planning -> input, in a worker thread. UEF only."""
from __future__ import annotations

import json
import threading
import time
from typing import Dict, List, Optional, Tuple

from . import config, layouts, report, uef, vision, win
from .camera import CalibrationError, Camera
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
from .ui import Panel

log = get("bot")

ACU_ITEMS = uef.ACU_BUILDS
ENGINEER_ITEMS = uef.T3_ENGINEER_BUILDS
FACTORY_ITEMS = sorted(set(uef.LAND_FACTORY_T3 + uef.AIR_FACTORY_T3 + ["ueb0201", "ueb0202", "ueb0301", "ueb0302"]))
UPGRADE_ITEMS = ["ueb1202", "ueb1302", "ueb0201", "ueb0202", "ueb0301", "ueb0302"]


class Bot(threading.Thread):
    def __init__(self, settings: dict, game: Game, map_info: MapInfo, advisor: Optional[OllamaAdvisor]) -> None:
        super().__init__(name="supcombot-loop", daemon=True)
        self.settings = settings
        self.game = game
        self.map = map_info
        self.advisor = advisor
        self.camera = Camera(game, map_info)
        self.eco = Economy(settings)
        self.state = BotState()
        slot = int(settings.get("start_slot", 0) or 0)
        if slot not in map_info.starts:
            slot = sorted(map_info.starts)[0] if map_info.starts else 1
        self.start_slot = slot
        self.ctx: MapContext = make_context(map_info, slot, [], list(settings.get("ally_slots", [])))
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
        self.last_acu_job = 0.0
        self.ui_missing_since = 0.0
        self.auto_strategy = "balanced"
        self.stream = FrameStream(game, fps=game.adv("capture_fps", 30), backend="auto")
        game.stream = self.stream
        self.perception = Perception(self.stream, game, self.camera, self.ctx, self.state,
                                     hz=game.adv("perception_hz", 8), base_radius=self.base_radius)
        self.new_game()

    # ------------------------------------------------------------------ lifecycle
    def new_game(self) -> None:
        with self.lock:
            self.state = BotState()
            self.perception.state = self.state
            sk0 = layouts.start_key(*self.ctx.start)
            self.auto_strategy = layouts.best_strategy(self.map.key, sk0, "balanced")
            self.state.strategy = self.auto_strategy if self.settings.get("strategy") == "auto" else self.settings.get("strategy", "balanced")
            self.state.strategy_auto = self.auto_strategy
            self.layout_used = set()
            self.layout = None
            self.tick_count = 0
            self.last_acu_job = 0.0
            self.ui_missing_since = 0.0
            self.layout = layouts.load(self.map.key, sk0)
            if self.layout:
                self.state.layout_slots = len(self.layout.get("entries", []))
                self.state.event(f"Layout geladen: {self.state.layout_slots} Slots, {self.layout.get('wins', 0)} Siege")
            self.state.event(f"Neues Spiel: {self.map.name}, Start-Slot {self.start_slot}, Gegner {len(self.ctx.enemies)}")
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

    def set_slots(self, start_slot: int, ally_slots) -> None:
        """Re-create the map context after the slot assignment changed (overlay)."""
        if start_slot not in self.map.starts:
            return
        self.start_slot = int(start_slot)
        self.settings["start_slot"] = int(start_slot)
        self.settings["ally_slots"] = list(ally_slots)
        self.ctx = make_context(self.map, int(start_slot), [], list(ally_slots))
        self.perception.ctx = self.ctx
        self.state.start_detected = True
        self.state.event(f"Start-Slot manuell: {start_slot}")

    def percepts(self) -> Percepts:
        return self.perception.percepts()

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
                    self._set_status("Spiel beendet: " + self.state.result + " (Ctrl+Alt+N = neues Spiel)")
                    p = self.percepts()
                    if self.state.result == "unknown" and p.ui_visible and time.time() - p.ts < 1.5:
                        if not self.ui_missing_since:
                            self.ui_missing_since = time.time()
                        elif time.time() - self.ui_missing_since > 8:
                            log.info("Spiel-UI wieder sichtbar: neues Spiel")
                            self.new_game()
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
                time.sleep(float(self.game.adv("loop_interval", 2.5)))
            except AbortedError:
                log.info("Aktion abgebrochen")
                self.game.inputs.release_all()
                time.sleep(0.3)
            except CalibrationError as exc:
                log.warning("%s", exc)
                self.state.event(str(exc))
                time.sleep(3.0)
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
        grace = float(self.game.adv("yield_to_user_seconds", 4) or 0)
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
        p = self.percepts()
        self.status.update({
            "phase": s.phase,
            "game_time": int(s.game_time()),
            "mass": s.mass_ratio, "energy": s.energy_ratio,
            "mass_income": s.mass_income, "energy_income": s.energy_income,
            "mass_stall": s.mass_stall, "energy_stall": s.energy_stall,
            "army": int(s.army_estimate), "army_seen": s.army_seen, "waves": len(s.waves),
            "threshold": attack_plan.threshold(s, self.settings),
            "strategy": s.strategy, "aggression": s.aggression, "focus": s.focus,
            "structures": len(s.structures), "mex": s.count_base("mex"), "factories": len(s.factories()),
            "engineers": s.engineers_ordered,
            "last_event": s.last_status,
            "advice": (s.advice or {}).get("note", ""),
            "ollama": (self.advisor.last_error or f"ok ({self.advisor.model})") if self.advisor else "aus",
            "layout_slots": s.layout_slots,
            "result": s.result,
            "map": self.map.name,
            "start": self.start_slot,
            "start_detected": s.start_detected,
            "vision_fps": round(self.stream.measured_fps, 1),
            "vision_backend": self.stream.backend,
            "ui_visible": p.ui_visible,
            "ui_scale": self.game.ui.scale,
            "ui_ok": s.ui_ok,
            "map_view_valid": p.map_view_valid,
            "enemies_near_base": p.enemies_near_base,
            "enemies_total": p.enemies_total,
            "analysis_ms": round(p.analysis_ms, 1),
            "allies": len(self.settings.get("ally_slots", [])),
            "enemies": len(self.ctx.enemies),
            "friendly_clusters": p.friendly_clusters,
            "enemy_clusters": p.enemy_clusters,
            "placements_rejected": s.placements_rejected,
            "factory_upgrades": s.factory_upgrades,
            "strategy_auto": self.auto_strategy,
            "debrief": s.debrief,
            "team_color": s.team_color,
            "factory_tech": max([f.tech for f in s.factories()] or [1]),
            "events": list(s.events[-6:]),
        })

    # ------------------------------------------------------------------ one tick
    def tick(self) -> None:
        s = self.state
        self.tick_count += 1
        p = self.percepts()
        live = time.time() - p.ts < 1.5
        if live and not p.ui_visible:
            # No economy panel: loading screen, menu, or the game is over.
            if not self.ui_missing_since:
                self.ui_missing_since = time.time()
            if s.opening_done and time.time() - self.ui_missing_since > 40:
                self.finish_game(None, "Spiel-UI verschwunden")
                return
            self._set_status("Warte auf Spielstart (Wirtschaftsanzeige nicht sichtbar)")
            return
        self.ui_missing_since = 0.0
        self._set_status("Aktiv")
        if live and p.mass is not None:
            self.eco.apply(p.mass, p.energy or 0.0, s, p.mass_income, p.energy_income)
        self.update_strategy()
        if not s.start_detected:
            if not self.setup_game():
                return
        self.camera.ensure_strategic(redetect=(self.tick_count % 5 == 1))
        if not s.opening_done:
            self.do_opening()
            self._after_tick()
            return
        if live and p.map_view_valid and p.army_seen is not None:
            s.army_seen = p.army_seen
        s.army_estimate = attack_plan.estimate_army(s)
        actions = 0
        if live and p.map_view_valid and p.enemies_near_base >= 6:
            actions += self.handle_acu_rescue(p)
        if live and p.map_view_valid and p.enemies_near_base > 0:
            actions += self.handle_defense(p)
        if live and p.map_view_valid and (p.friendly_clusters or p.enemy_clusters):
            actions += self.handle_waves(p)
        actions += self.handle_idle_engineers(max_jobs=2)
        actions += self.handle_factories()
        if actions < 2:
            actions += self.handle_acu()
        if actions < 2:
            self.handle_upgrades()
            self.handle_factory_upgrade()
        if self.settings.get("auto_attack") and attack_plan.should_launch(s, self.settings):
            self.launch_wave("auto")
        self._after_tick()

    def _after_tick(self) -> None:
        s = self.state
        t = s.game_time()
        if s.count_base("mex") < 4 and t < 300:
            s.phase = "opening"
        elif max([f.tech for f in s.factories()] or [1]) >= 2:
            s.phase = "tech2"
        else:
            s.phase = "expand"
        if time.time() - self.last_state_log > 15:
            self.last_state_log = time.time()
            log.info("STATE %s", json.dumps(s.snapshot(), ensure_ascii=False))
        self.maybe_ask_ollama()
        self._refresh_status()

    # ------------------------------------------------------------------ game setup (start slot, colours)
    def setup_game(self) -> bool:
        """Find our start position: select the ACU, zoom out, look for the selection brackets at a start marker."""
        s, g = self.state, self.game
        if g.dry_run and not g.hwnd:
            s.start_detected = True
            s.team_color = [255, 0, 0]
            return True
        manual = int(self.settings.get("start_slot", 0) or 0) in self.map.starts
        # Select the ACU: the game's own key when bound, else the view centre (the camera starts on the ACU).
        if not g.select_commander():
            g.click(*g.center())
        g.wait(0.3)
        self.camera.zoom_out_fully()
        frame = g.fresh_frame(0.3)
        if not self.camera.detect(frame, strict=False):
            self.state.event("Kartenrechteck nicht erkannt - bitte ganz herauszoomen")
            g.save_debug(frame, "setup_maprect")
            return False
        panel = g.panel(ACU_ITEMS, frame=g.fresh_frame(0.1))
        if panel.items:
            s.ui_ok = True
        best_slot, best_white = None, 0
        whites = {}
        for n, mk in self.map.start_positions():
            cx, cy = self.camera.world_to_client(mk.x, mk.z)
            w = g.selection_highlight(frame, cx, cy)
            whites[n] = w
            if w > best_white:
                best_slot, best_white = n, w
        min_white = max(6, int(10 * g.ui.s * g.ui.s))
        second = sorted(whites.values())[-2] if len(whites) > 1 else 0
        detected = best_slot is not None and best_white >= min_white and best_white >= 2 * second and panel.items
        log.info("Startsuche: Auswahl-Helligkeit je Slot %s, Baumenue %s", whites, "ja" if panel.items else "nein")
        if detected and not manual:
            if best_slot != self.start_slot:
                self.start_slot = best_slot
                self.ctx = make_context(self.map, best_slot, [], list(self.settings.get("ally_slots", [])))
                self.perception.ctx = self.ctx
            s.event(f"Startposition erkannt: Slot {best_slot}")
        elif manual:
            s.event(f"Start-Slot aus den Einstellungen: {self.start_slot}")
        else:
            s.event(f"Startposition nicht erkannt, nutze Slot {self.start_slot} (Overlay: Start-Slot)")
            g.save_debug(frame, "setup_start")
        # Colours: ours at our start (after deselecting), enemies at the other starts.
        g.deselect()
        frame = g.fresh_frame(0.25)
        sx, sy = self.camera.world_to_client(*self.ctx.start)
        col = g.icon_color(frame, sx, sy)
        if col:
            s.team_color = col
        enemy_cols: List[List[int]] = []
        for n, mk in self.map.start_positions():
            if n == self.start_slot or n in self.settings.get("ally_slots", []):
                continue
            cx, cy = self.camera.world_to_client(mk.x, mk.z)
            c = g.icon_color(frame, cx, cy)
            if c and (not col or sum(abs(a - b) for a, b in zip(c, col)) > 90) and all(sum(abs(a - b) for a, b in zip(c, e)) > 60 for e in enemy_cols):
                enemy_cols.append(c)
        s.enemy_colors = enemy_cols
        s.event(f"Teamfarbe {col}, {len(enemy_cols)} Gegnerfarben")
        s.start_detected = True
        s.started_at = time.time()
        return True

    # ------------------------------------------------------------------ strategy / advice
    def update_strategy(self) -> None:
        s = self.state
        fresh = s.advice and time.time() - s.advice_at < 180 and self.advisor is not None
        s.strategy = self.auto_strategy if self.settings.get("strategy") == "auto" else self.settings.get("strategy", "balanced")
        s.aggression = 2
        s.focus = "land"
        if fresh and s.advice:
            s.strategy = s.advice.get("strategy", s.strategy)
            s.aggression = int(s.advice.get("aggression", s.aggression))
            s.focus = s.advice.get("focus", s.focus)

    def maybe_ask_ollama(self) -> None:
        if not self.advisor:
            return
        interval = float(self.settings.get("ollama", {}).get("interval", 30))
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

    # ------------------------------------------------------------------ end of game
    def finish_game(self, won: Optional[bool], how: str) -> None:
        s = self.state
        if s.result:
            return
        s.result = "won" if won else ("lost" if won is False else "unknown")
        entries = [{"role": st.role, "dx": round(st.x - self.ctx.start[0], 1), "dz": round(st.z - self.ctx.start[1], 1)}
                   for st in s.structures if st.role not in ("mex", "hydro")]
        if won is not None:
            rec = layouts.store_result(self.map.key, layouts.start_key(*self.ctx.start), bool(won), entries,
                                       {"faction": uef.FACTION, "game_time": int(s.game_time()), "strategy": s.strategy})
            s.layout_slots = len(rec.get("entries", []))
        s.event(("SIEG" if won else "NIEDERLAGE" if won is False else "SPIELENDE") + f" ({how})")
        self.game.inputs.abort.set()
        self._refresh_status()
        try:
            path = report.write_report(s, self.settings, self.map.name, self.map.key, self.start_slot, s.result)
        except Exception as exc:
            log.warning("Bericht nicht geschrieben: %s", exc)
            return
        if self.advisor:
            def worker() -> None:
                text = report.debrief(self.advisor, path)
                if text:
                    s.debrief = text
                    s.event("Nachbesprechung von Ollama liegt vor")

            threading.Thread(target=worker, name="debrief", daemon=True).start()

    # ------------------------------------------------------------------ ACU
    def select_acu(self) -> Panel:
        """Select the ACU (game key or click on its icon at the start) and return the open build panel."""
        g = self.game
        if not g.select_commander():
            self.camera.click_world(*self.ctx.start)
            g.wait(0.3)
            self.camera.zoom_out_fully()
        else:
            self.camera.zoom_out_fully()
        return g.panel(ACU_ITEMS)

    def do_opening(self) -> None:
        s, g = self.state, self.game
        s.opening_attempts += 1
        panel = self.select_acu()
        if not panel.has("ueb1103"):
            g.deselect()
            s.event("ACU-Baumenue nicht gefunden (Versuch %d)" % s.opening_attempts)
            g.save_debug(g.screenshot(), "opening_nopanel")
            if s.opening_attempts >= 6:
                s.opening_done = True
                s.event("Eroeffnung uebersprungen - Ingenieure uebernehmen")
            return
        s.ui_ok = True
        sequence = (self.settings.get("openings") or {}).get(s.strategy)
        orders = opening_orders(s, self.ctx, self.layout, self.layout_used, sequence)
        placed = 0
        for w in orders:
            if self.place(w, w.pos, panel):
                placed += 1
            panel = None  # re-read after the first click (the panel may scroll/change)
        g.cancel_build_mode()
        g.deselect()
        s.opening_done = True
        self.last_acu_job = time.time()
        s.event(f"Eroeffnung: {placed}/{len(orders)} Bauauftraege fuer den ACU")

    def handle_acu(self) -> int:
        """Every ~75 s the ACU gets new build orders (energy, second factory, defence) or assists a factory."""
        s, g = self.state, self.game
        if time.time() - self.last_acu_job < 75 or s.game_time() > 1500:
            return 0
        self.last_acu_job = time.time()
        panel = self.select_acu()
        if not panel.has("ueb1103"):
            g.deselect()
            return 0
        wishes = [w for w in wishlist(s, self.ctx, self.settings, False) if w.role in ("pgen", "landFac", "mex", "pd", "aa")
                  and dist(w.pos or self.ctx.start, self.ctx.start) < 40]
        orders = 0
        for w in wishes[:2]:
            if s.mass_stall and w.role != "mex":
                continue
            pos = choose_spot(s, self.ctx, w, self.layout, self.layout_used, self.base_radius)
            if pos is None:
                continue
            if self.place(w, pos, panel):
                pos = w.pos or pos
                s.add_structure(w.role, pos[0], pos[1], builder="acu", marker=w.marker)
                orders += 1
                panel = None
        g.cancel_build_mode()
        if orders == 0:
            facs = s.factories()
            if facs:
                f = min(facs, key=lambda f: dist(f.pos(), self.ctx.start))
                self.camera.click_world(f.x, f.z, button="right", shift=True)
                s.event("ACU assistiert Fabrik")
        else:
            s.event(f"ACU: {orders} Bauauftraege")
        g.deselect()
        return 1

    # ------------------------------------------------------------------ placing structures
    def place(self, wish: Wish, pos: Tuple[float, float], panel: Optional[Panel] = None) -> bool:
        """Click the build icon, check the preview colour, then shift-click the world position."""
        g = self.game
        bp = uef.structure_id(wish.role)
        if bp is None:
            return False
        tier = uef.tier_of(wish.role)
        if panel is None or not panel.has(bp):
            g.select_tab(tier)   # no click when that tab is already active
            panel = g.panel(ENGINEER_ITEMS if tier > 1 else ACU_ITEMS + ["ueb1102", "ueb3101", "ueb1106", "ueb1105"])
        if not panel.has(bp):
            return False
        g.click_item(bp, panel)
        if g.adv("placement_check", True) and wish.role not in ("mex", "hydro") and not g.dry_run:
            checked = self.validate_spot(wish, pos)
            if checked is None:
                g.cancel_build_mode()
                return False
            pos = checked
        self.camera.click_world(pos[0], pos[1], shift=True)
        wish.pos = pos
        return True

    def validate_spot(self, wish: Wish, pos: Tuple[float, float], attempts: int = 4) -> Optional[Tuple[float, float]]:
        """Hover the template over the spot and read its colour; move on to another spot when it is red."""
        s = self.state
        upp = max(0.25, self.camera.units_per_pixel())
        radius = int(uef.FOOTPRINT.get(wish.role, 3.0) / upp / 2) + 3
        for _ in range(attempts):
            cx, cy = self.camera.world_to_client(pos[0], pos[1])
            self.game.hover(cx, cy)
            frame = self.game.fresh_frame(0.2)
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

    # ------------------------------------------------------------------ engineers
    def handle_idle_engineers(self, max_jobs: int = 2) -> int:
        s, g = self.state, self.game
        jobs = 0
        for _ in range(max_jobs):
            p = self.percepts()
            pos = p.idle_engineer if time.time() - p.ts < 1.0 else g.idle_engineer_button()
            if pos is None:
                break
            s.idle_engineers_seen += 1
            g.click(*pos)
            g.wait(0.3)
            self.camera.zoom_out_fully()
            panel = g.panel(ENGINEER_ITEMS)
            if not panel.items:
                g.deselect()
                s.panel_misses += 1
                if s.panel_misses in (3, 20):
                    s.event("Ingenieur ausgewaehlt, aber kein Baumenue erkannt (siehe doctor)")
                    g.save_debug(g.screenshot(), "eng_nopanel")
                break
            s.ui_ok = True
            if not self.assign_jobs(panel):
                self.assist_or_patrol()
            g.cancel_build_mode()
            g.deselect()
            jobs += 1
        return jobs

    def engineer_tier(self, panel: Panel) -> int:
        if panel.has("ueb1302") or panel.has("ueb1301"):
            return 3
        if panel.has("ueb1202") or panel.has("ueb1201") or panel.has("ueb0201"):
            return 2
        return 1

    def assign_jobs(self, panel: Panel, max_orders: int = 3) -> bool:
        s = self.state
        tier = self.engineer_tier(panel)
        if tier == 1 and self.game.ui.tab_state(self.game.screenshot(), 2) == "selected":
            tier = 2
        s.engineer_tier_seen = max(s.engineer_tier_seen, tier)
        wishes = wishlist(s, self.ctx, self.settings, tier >= 2, tier >= 3)
        budget = Economy.build_budget(s)
        now = time.time()
        in_progress = sum(1 for st in s.structures if now - st.ordered_at < 120 and st.role not in ("mex",))
        orders: List[str] = []
        for w in wishes:
            if len(orders) >= max_orders:
                break
            if in_progress >= budget and w.prio < 95:
                break
            if uef.tier_of(w.role) > tier:
                continue
            pos = choose_spot(s, self.ctx, w, self.layout, self.layout_used, self.base_radius)
            if pos is None:
                continue
            if self.place(w, pos, panel):
                pos = w.pos or pos   # place() may have moved it after a red preview
                s.add_structure(w.role, pos[0], pos[1], marker=w.marker)
                orders.append(w.role)
                in_progress += 1
                panel = None
        if orders:
            s.event(f"Ingenieur T{tier}: {', '.join(orders)}")
        return bool(orders)

    def assist_or_patrol(self) -> None:
        """Nothing to build: assist the newest factory (shift+right click on it) or patrol-reclaim around the base."""
        facs = self.state.factories()
        if facs:
            f = facs[-1]
            self.camera.click_world(f.x, f.z, button="right", shift=True)
            self.state.event("Ingenieur assistiert Fabrik")
        else:
            x, z = self.ctx.start
            if self.game.action("patrol"):
                for dx, dz in ((12, 12), (-12, 12), (-12, -12), (12, -12)):
                    self.camera.click_world(x + dx, z + dz, shift=True)
                self.state.event("Ingenieur patrouilliert (Reclaim)")

    # ------------------------------------------------------------------ factories
    def handle_factories(self) -> int:
        s, g = self.state, self.game
        now = time.time()
        p = self.percepts()
        pos = p.idle_factory if now - p.ts < 1.0 else None
        if pos is not None:
            g.click(*pos)
            g.wait(0.3)
            self.camera.zoom_out_fully()
            panel = g.panel(FACTORY_ITEMS)
            kind = panel.kind()
            if kind in ("land", "air"):
                s.ui_ok = True
                self.queue_units(kind, None, panel)
                return 1
            g.deselect()
        for fac in sorted(s.factories(), key=lambda f: f.last_queue_at):
            if now - fac.ordered_at < 70 or now - fac.last_queue_at < 100 or fac.upgrading_until > now:
                continue
            self.camera.click_world(fac.x, fac.z)
            panel = g.panel(FACTORY_ITEMS)
            kind = panel.kind()
            if kind in ("land", "air"):
                fac.confirmed = True
                self.queue_units(kind, fac, panel)
            else:
                fac.last_queue_at = now - 50  # not finished yet or mis-click: look again later
                g.deselect()
            return 1
        return 0

    def queue_units(self, kind: str, fac: Optional[Structure], panel: Panel) -> None:
        s, g = self.state, self.game
        n = Economy.factory_queue_size(s)
        if fac is None:
            cands = s.factories(kind)
            fac = min(cands, key=lambda f: f.last_queue_at) if cands else None
        avail_roles = [role for role, bp in uef.UNITS.items() if panel.has(bp)]
        if fac and panel.has("ueb0301" if kind == "land" else "ueb0302"):
            fac.tech = max(fac.tech, 2)
        if fac and any(uef.tier_of(r) == 3 for r in avail_roles):
            fac.tech = 3
        tech = fac.tech if fac else (3 if any(uef.tier_of(r) == 3 for r in avail_roles) else 2 if any(uef.tier_of(r) == 2 for r in avail_roles) else 1)
        if kind == "land":
            base = [r for r in avail_roles if uef.tier_of(r) == 1 and r in production.LAND_ROLES]
            roles = production.tier_roles(production.land_queue(s, self.settings, base, n), tech, avail_roles)
        else:
            base = [r for r in avail_roles if r in production.AIR_ROLES]
            roles = production.air_queue(s, base, n)
        queued: List[str] = []
        for r in roles:
            bp = uef.unit_id(r)
            if not bp:
                continue
            tier = uef.tier_of(r)
            if tier > 1 and not panel.has(bp):
                g.select_tab(tier)
                panel = g.panel(FACTORY_ITEMS)
            if not panel.has(bp):
                r1 = uef.base_role(r)
                bp = uef.unit_id(r1) or bp
                if not panel.has(bp):
                    continue
                r = r1
            g.click_item(bp, panel)
            queued.append(r)
            if r.startswith("eng"):
                s.engineer_tier_seen = max(s.engineer_tier_seen, uef.tier_of(r))
        if fac:
            fac.queued_units += len(queued)
            fac.last_queue_at = time.time()
            if not fac.rally_set:
                rally = self.ctx.rally
                if kind == "air" and self.ctx.nearest_enemy:
                    rally = (self.ctx.rally[0] + self.ctx.toward[0] * self.ctx.enemy_distance * 0.2,
                             self.ctx.rally[1] + self.ctx.toward[1] * self.ctx.enemy_distance * 0.2)
                elif kind == "land" and production.wants_home_guard(s) and len(s.factories("land")) >= 2 and fac is s.factories("land")[1]:
                    rally = (self.ctx.start[0] + self.ctx.toward[0] * 15, self.ctx.start[1] + self.ctx.toward[1] * 15)
                self.camera.click_world(rally[0], rally[1], button="right")
                fac.rally_set = True
        g.deselect()
        if queued:
            s.event(f"Fabrik ({kind} T{tech}): {', '.join(queued)}")

    def handle_factory_upgrade(self) -> None:
        """Upgrade land factories: the first one T1->T2->T3, further ones to T2 when mass floats."""
        s, g = self.state, self.game
        now = time.time()
        if now - self.last_factory_upgrade_check < 60:
            return
        self.last_factory_upgrade_check = now
        facs = [f for f in s.factories("land") if now - f.ordered_at > 120 and f.upgrading_until < now]
        if not facs or any(f.upgrading_until > now for f in s.factories("land")):
            return
        candidate, bp, new_tech = None, None, 0
        t2 = [f for f in facs if f.tech == 2]
        t1 = [f for f in facs if f.tech == 1]
        if t2 and Economy.can_upgrade_factory_t3(s) and not any(f.tech >= 3 for f in s.factories("land")):
            candidate, bp, new_tech = t2[0], "ueb0301", 3
        elif t1 and Economy.can_upgrade_factory(s):
            has_t2_already = any(f.tech >= 2 for f in s.factories("land"))
            if not has_t2_already or (s.mass_float and len(facs) >= 2):
                candidate, bp, new_tech = t1[0], "ueb0201", 2
        if candidate is None:
            return
        self.camera.click_world(candidate.x, candidate.z)
        panel = g.panel(UPGRADE_ITEMS + ["uel0105"])
        if panel.has(bp):
            g.click_item(bp, panel)
            candidate.tech = new_tech
            candidate.upgrading_until = now + (300 if new_tech == 3 else 200)
            s.factory_upgrades += 1
            s.event(f"Fabrik-Upgrade auf T{new_tech} gestartet")
        g.deselect()

    # ------------------------------------------------------------------ mex upgrades
    def handle_upgrades(self) -> None:
        s, g = self.state, self.game
        if not Economy.can_upgrade(s):
            return
        gap = {"rush": 150, "balanced": 70, "eco": 50, "turtle": 80}.get(s.strategy, 70)
        if time.time() - s.last_upgrade_at < gap or s.game_time() < 240:
            return
        now = time.time()
        mexes = [m for m in s.structures if m.role == "mex" and m.tech == 1 and now - m.ordered_at > 120]
        mexes.sort(key=lambda m: dist(m.pos(), self.ctx.start))
        bp, new_tech = "ueb1202", 2
        t2_mexes = [m for m in s.structures if m.role == "mex" and m.tech == 2 and now - m.ordered_at > 420]
        t2_mexes.sort(key=lambda m: dist(m.pos(), self.ctx.start))
        if (not mexes or s.count_base("mex") - len(mexes) >= 6) and t2_mexes and Economy.can_upgrade_mex_t3(s):
            mexes, bp, new_tech = t2_mexes, "ueb1302", 3
        if not mexes:
            return
        m = mexes[0]
        self.camera.click_world(m.x, m.z)
        panel = g.panel(["ueb1202", "ueb1302"])
        if panel.has(bp):
            g.click_item(bp, panel)
            m.tech = new_tech
            m.ordered_at = now
            s.last_upgrade_at = now
            s.event(f"Mex-Upgrade auf T{new_tech} bei ({int(m.x)},{int(m.z)})")
        else:
            m.ordered_at = now  # probably not built yet; look again later
        g.deselect()

    # ------------------------------------------------------------------ defence / waves / attacks
    def handle_defense(self, p: Percepts) -> int:
        """Enemy icons inside the base: send everything at the rally point against them (every 20 s)."""
        s = self.state
        now = time.time()
        if now - self.last_defense < 20 or p.enemy_world is None:
            return 0
        self.last_defense = now
        self.camera.box_select_world(self.ctx.rally[0], self.ctx.rally[1], 30)
        self.game.wait(0.3)
        self.game.attack_move(*self.camera.world_to_client(*p.enemy_world))
        self.game.deselect()
        s.event(f"Verteidigung: {p.enemies_near_base} Gegner-Symbole bei ({int(p.enemy_world[0])},{int(p.enemy_world[1])})")
        return 1

    def handle_acu_rescue(self, p: Percepts) -> int:
        """Many enemy icons in the base: pull the ACU back behind the base."""
        s = self.state
        if time.time() - s.last_acu_action < 30:
            return 0
        s.last_acu_action = time.time()
        safe = (self.ctx.start[0] + self.ctx.away[0] * 20, self.ctx.start[1] + self.ctx.away[1] * 20)
        if not self.game.select_commander():
            self.camera.click_world(*self.ctx.start)
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
        for kind, wave, target in actions[:2]:
            if wave.last_pos is None:
                continue
            self.camera.box_select_world(wave.last_pos[0], wave.last_pos[1], 22)
            self.game.wait(0.25)
            if kind == "retreat":
                self.camera.click_world(self.ctx.rally[0], self.ctx.rally[1], button="right")
            elif kind == "advance" and target:
                self.game.attack_move(*self.camera.world_to_client(*target))
            self.game.deselect()
            done += 1
        return done

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
        self.game.attack_move(*self.camera.world_to_client(*target))
        attack_plan.record_wave(s, size, target, reason, self.ctx.rally)
        self.game.deselect()
