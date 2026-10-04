"""Always-on-top overlay window (tkinter) with status, a few toggles and global hotkeys."""
from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, Dict, Optional

from . import config
from .log import get

log = get("overlay")

try:
    import keyboard  # type: ignore
except Exception:  # pragma: no cover
    keyboard = None

BG, FG, DIM, PANEL = "#0b1220", "#e6edf7", "#9fb0c8", "#24324f"


class Overlay:
    def __init__(self, settings: dict, bot, on_quit: Callable[[], None]) -> None:
        self.settings = settings
        self.bot = bot
        self.on_quit = on_quit
        self.root = tk.Tk()
        self.root.title("SupComBot")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", float(settings.get("overlay", {}).get("alpha", 0.9)))
        except tk.TclError:
            pass
        self.root.configure(bg=BG)
        ov = settings.get("overlay", {})
        self.root.geometry(f"+{int(ov.get('x', 20))}+{int(ov.get('y', 140))}")
        self.vars: Dict[str, tk.StringVar] = {}
        self.buttons: Dict[str, tk.Button] = {}
        self.preview: Optional[tk.Toplevel] = None
        self._preview_label: Optional[tk.Label] = None
        self._preview_photo = None
        self._build()
        self._bind_hotkeys()
        self.root.after(500, self._poll)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        title = tk.Frame(self.root, bg="#1c2b4a")
        title.pack(fill="x")
        tk.Label(title, text="  SupComBot (UEF)", bg="#1c2b4a", fg=FG, font=("Segoe UI", 10, "bold")).pack(side="left", pady=2)
        tk.Button(title, text="x", command=self.on_quit, bg="#6b2b2b", fg=FG, bd=0, padx=8).pack(side="right")
        tk.Button(title, text="_", command=self.toggle_visible, bg=PANEL, fg=FG, bd=0, padx=8).pack(side="right")
        title.bind("<ButtonPress-1>", self._drag_start)
        title.bind("<B1-Motion>", self._drag_move)
        title.bind("<ButtonRelease-1>", self._drag_end)

        body = tk.Frame(self.root, bg=BG, padx=8, pady=4)
        body.pack(fill="both")
        for key in ("status", "map", "eco", "army", "vision", "event"):
            v = tk.StringVar(value="-")
            self.vars[key] = v
            tk.Label(body, textvariable=v, bg=BG, fg=FG if key == "status" else DIM, anchor="w",
                     font=("Segoe UI", 9), justify="left", wraplength=360).pack(fill="x")

        mid = tk.Frame(self.root, bg=BG, padx=8)
        mid.pack(fill="x")
        self.log_text = tk.Text(mid, height=6, width=44, bg="#0f1830", fg=DIM, bd=0, font=("Consolas", 8), state="disabled", wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True, pady=2)
        self.minimap = tk.Canvas(mid, width=180, height=180, bg="#06090f", highlightthickness=1, highlightbackground=PANEL)
        self.minimap.pack(side="right", padx=(6, 0), pady=2)

        grid = tk.Frame(self.root, bg=BG, padx=8, pady=4)
        grid.pack(fill="x")
        self.buttons["bot_enabled"] = tk.Button(grid, text="Bot", width=18, bd=0, command=lambda: self.toggle("bot_enabled"), font=("Segoe UI", 9, "bold"))
        self.buttons["bot_enabled"].grid(row=0, column=0, padx=3, pady=2, sticky="ew")
        self.buttons["auto_attack"] = tk.Button(grid, text="Auto-Angriff", width=18, bd=0, command=lambda: self.toggle("auto_attack"), font=("Segoe UI", 9))
        self.buttons["auto_attack"].grid(row=0, column=1, padx=3, pady=2, sticky="ew")
        self.buttons["strategy"] = tk.Button(grid, text="Strategie", width=18, bd=0, command=self.cycle_strategy, font=("Segoe UI", 9))
        self.buttons["strategy"].grid(row=1, column=0, padx=3, pady=2, sticky="ew")
        self.buttons["start"] = tk.Button(grid, text="Start-Slot", width=18, bd=0, command=self.next_start, font=("Segoe UI", 9))
        self.buttons["start"].grid(row=1, column=1, padx=3, pady=2, sticky="ew")
        actions = [("JETZT ANGREIFEN", lambda: self.bot.request("attack_now")), ("Neues Spiel", lambda: self.bot.request("new_game")),
                   ("Sieg melden", lambda: self.bot.request("report_win")), ("Niederlage melden", lambda: self.bot.request("report_loss")),
                   ("Bot-Sicht", self.toggle_preview), ("Nachbesprechung", self.show_debrief)]
        for i, (label, cmd) in enumerate(actions):
            b = tk.Button(grid, text=label, width=18, bd=0, command=cmd, bg=PANEL, fg=FG, font=("Segoe UI", 9))
            b.grid(row=2 + i // 2, column=i % 2, padx=3, pady=2, sticky="ew")
        slots = tk.Frame(self.root, bg=BG, padx=8, pady=2)
        slots.pack(fill="x")
        tk.Label(slots, text="Slots (klicken: Gegner -> Verbuendet):", bg=BG, fg=DIM, font=("Segoe UI", 8)).grid(row=0, column=0, columnspan=6, sticky="w")
        self.slot_buttons: Dict[int, tk.Button] = {}
        for i, n in enumerate(sorted(self.bot.map.starts)):
            b = tk.Button(slots, text=str(n), width=7, bd=0, font=("Segoe UI", 8), command=lambda k=n: self.cycle_slot(k))
            b.grid(row=1 + i // 6, column=i % 6, padx=2, pady=1)
            self.slot_buttons[n] = b
        hk = self.settings.get("hotkeys", {})
        hint = f"Hotkeys: Bot {hk.get('toggle_bot')} | Angriff {hk.get('toggle_attack')} | Jetzt {hk.get('attack_now')} | Overlay {hk.get('toggle_overlay')} | Ende {hk.get('quit')}"
        tk.Label(self.root, text=hint, bg=BG, fg="#7f8fa8", font=("Segoe UI", 8), wraplength=380, justify="left").pack(fill="x", padx=8, pady=(0, 6))
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        for key in ("bot_enabled", "auto_attack"):
            on = bool(self.settings.get(key))
            self.buttons[key].configure(bg="#2e7d32" if on else "#6b2b2b", fg=FG,
                                        text=("Bot" if key == "bot_enabled" else "Auto-Angriff") + (": AN" if on else ": AUS"))
        strat = self.settings.get("strategy")
        if strat == "auto":
            strat = f"auto ({getattr(self.bot, 'auto_strategy', '?')})"
        self.buttons["strategy"].configure(text=f"Strategie: {strat}", bg=PANEL, fg=FG)
        det = "erkannt" if self.bot.state.start_detected and not int(self.settings.get("start_slot", 0) or 0) else "manuell"
        self.buttons["start"].configure(text=f"Start-Slot: {self.bot.start_slot} ({det})", bg=PANEL, fg=FG)
        self._refresh_slots()

    # ------------------------------------------------------------------ actions
    def toggle(self, key: str) -> None:
        self.settings[key] = not self.settings.get(key, False)
        if key == "bot_enabled":
            self.bot.set_enabled(self.settings[key])
        config.save_settings(self.settings)
        self._refresh_buttons()

    def cycle_strategy(self) -> None:
        cur = self.settings.get("strategy", "balanced")
        i = (config.STRATEGIES.index(cur) + 1) % len(config.STRATEGIES) if cur in config.STRATEGIES else 0
        self.settings["strategy"] = config.STRATEGIES[i]
        config.save_settings(self.settings)
        self._refresh_buttons()

    def _refresh_slots(self) -> None:
        allies = self.settings.get("ally_slots", [])
        for n, b in self.slot_buttons.items():
            if n == self.bot.start_slot:
                text, color = "Ich", "#2e7d32"
            elif n in allies:
                text, color = "Ally", "#1f5f8b"
            else:
                text, color = "Gegner", "#6b2b2b"
            b.configure(text=f"{n}: {text}", bg=color, fg=FG)

    def cycle_slot(self, n: int) -> None:
        """Gegner -> Verbuendet -> Gegner for every slot that is not ours."""
        if n == self.bot.start_slot:
            return
        allies = set(self.settings.get("ally_slots", []))
        if n in allies:
            allies.discard(n)
        else:
            allies.add(n)
        self.settings["ally_slots"] = sorted(allies)
        config.save_settings(self.settings)
        self.bot.set_slots(self.bot.start_slot, sorted(allies))
        self._refresh_buttons()

    def next_start(self) -> None:
        slots = sorted(self.bot.map.starts)
        cur = self.bot.start_slot
        nxt = slots[(slots.index(cur) + 1) % len(slots)] if cur in slots else slots[0]
        allies = [k for k in self.settings.get("ally_slots", []) if k != nxt]
        self.settings["ally_slots"] = allies
        self.settings["start_slot"] = nxt
        config.save_settings(self.settings)
        self.bot.set_slots(nxt, allies)
        self._refresh_buttons()

    def show_debrief(self) -> None:
        text = self.bot.state.debrief or "Noch keine Nachbesprechung. Sie entsteht nach Spielende (Sieg/Niederlage gemeldet) mit Ollama."
        win = tk.Toplevel(self.root)
        win.title("SupComBot - Nachbesprechung")
        win.attributes("-topmost", True)
        win.configure(bg=BG)
        t = tk.Text(win, width=70, height=16, bg="#0f1830", fg=FG, font=("Segoe UI", 10), wrap="word", bd=0)
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(padx=8, pady=8)

    def _draw_minimap(self, st: Dict[str, object]) -> None:
        c = self.minimap
        c.delete("all")
        info = self.bot.map
        size = 180
        scale = size / max(info.size)
        w, h = info.size[0] * scale, info.size[1] * scale
        c.create_rectangle(0, 0, w, h, outline=PANEL, fill="#0d1526")

        def pt(x, z):
            return x * scale, z * scale

        for m in info.mass:
            x, y = pt(m.x, m.z)
            c.create_oval(x - 1.5, y - 1.5, x + 1.5, y + 1.5, fill="#4c6a3c", outline="")
        ctx = self.bot.ctx
        colors = {"mex": "#7ee07e", "landFac": "#ffffff", "airFac": "#c8c8ff", "pgen": "#ffc850", "pd": "#ff9c9c", "aa": "#9cd3ff", "radar": "#d0a0ff"}
        for stc in list(self.bot.state.structures):
            x, y = pt(stc.x, stc.z)
            c.create_rectangle(x - 2, y - 2, x + 2, y + 2, outline=colors.get(stc.role.rstrip("23"), "#b0b0b0"))
        for e in ctx.enemies:
            x, y = pt(*e)
            c.create_line(x - 4, y - 4, x + 4, y + 4, fill="#ff4040", width=2)
            c.create_line(x - 4, y + 4, x + 4, y - 4, fill="#ff4040", width=2)
        for n in self.settings.get("ally_slots", []):
            mk = info.starts.get(n)
            if mk:
                x, y = pt(mk.x, mk.z)
                c.create_oval(x - 4, y - 4, x + 4, y + 4, outline="#4aa3ff", width=2)
        x, y = pt(*ctx.start)
        c.create_oval(x - 4, y - 4, x + 4, y + 4, outline="#40ff40", width=2)
        x, y = pt(*ctx.rally)
        c.create_oval(x - 3, y - 3, x + 3, y + 3, outline="#ffe600", width=2)
        for cx, cz, n in (st.get("enemy_clusters") or [])[:60]:
            x, y = pt(cx, cz)
            r = 2 + min(8, n ** 0.5)
            c.create_oval(x - r, y - r, x + r, y + r, outline="#ff3030")
        for cx, cz, n in (st.get("friendly_clusters") or [])[:60]:
            x, y = pt(cx, cz)
            r = 2 + min(8, n ** 0.5)
            c.create_oval(x - r, y - r, x + r, y + r, outline="#30ff60")
        for wv in self.bot.state.waves:
            if wv.done:
                continue
            x1, y1 = pt(*(wv.last_pos or ctx.rally))
            x2, y2 = pt(*wv.target)
            c.create_line(x1, y1, x2, y2, fill="#ff8080" if not wv.retreating else "#ffd080", dash=(3, 2))
        c.create_text(4, h - 4, anchor="sw", text=info.name[:26], fill="#7f8fa8", font=("Segoe UI", 7))

    def _update_log(self, events) -> None:
        text = "\n".join(events or [])
        if getattr(self, "_last_log", None) == text:
            return
        self._last_log = text
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", text)
        self.log_text.configure(state="disabled")

    def toggle_visible(self) -> None:
        if self.root.state() == "withdrawn":
            self.root.deiconify()
        else:
            self.root.withdraw()

    # ------------------------------------------------------------------ drag
    def _drag_start(self, e) -> None:
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e) -> None:
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _drag_end(self, e) -> None:
        self.settings.setdefault("overlay", {})["x"] = self.root.winfo_x()
        self.settings["overlay"]["y"] = self.root.winfo_y()
        config.save_settings(self.settings)

    # ------------------------------------------------------------------ hotkeys
    def _bind_hotkeys(self) -> None:
        if not keyboard:
            log.warning("Modul 'keyboard' fehlt: keine globalen Hotkeys (pip install keyboard)")
            return
        hk = self.settings.get("hotkeys", {})
        mapping = {
            "toggle_bot": lambda: self.toggle("bot_enabled"),
            "toggle_attack": lambda: self.toggle("auto_attack"),
            "attack_now": lambda: self.bot.request("attack_now"),
            "toggle_overlay": self.toggle_visible,
            "report_win": lambda: self.bot.request("report_win"),
            "report_loss": lambda: self.bot.request("report_loss"),
            "new_game": lambda: self.bot.request("new_game"),
            "quit": self.on_quit,
        }
        for name, fn in mapping.items():
            combo = hk.get(name)
            if not combo:
                continue
            try:
                keyboard.add_hotkey(combo, lambda f=fn: self.root.after(0, f), suppress=False)
            except Exception as exc:
                log.warning("Hotkey %s (%s) nicht registrierbar: %s", name, combo, exc)

    # ------------------------------------------------------------------ polling
    def _poll(self) -> None:
        st = self.bot.status
        s = st.get("status", "-")
        gt = int(st.get("game_time", 0) or 0)
        self.vars["status"].set(f"Status: {s}   Phase: {st.get('phase', '-')}   Zeit {gt // 60:02d}:{gt % 60:02d}")
        self.vars["map"].set(f"Karte: {st.get('map', '-')}   Start {st.get('start', '-')}   Strategie {st.get('strategy', '-')}   Layout {st.get('layout_slots', 0)}")
        m, e = float(st.get("mass", 0) or 0), float(st.get("energy", 0) or 0)
        sign = lambda v: "+" if (v or 0) > 0.3 else ("-" if (v or 0) < -0.3 else "~")
        flags = (" MASS-STALL" if st.get("mass_stall") else "") + (" ENERGIE-STALL" if st.get("energy_stall") else "")
        self.vars["eco"].set(f"Masse {m * 100:3.0f}% ({sign(st.get('mass_income'))})   Energie {e * 100:3.0f}% ({sign(st.get('energy_income'))}){flags}")
        seen = st.get("army_seen")
        self.vars["army"].set(f"Armee ~{st.get('army', 0)}" + (f" (gesehen {seen})" if seen is not None else "") +
                              f"   Wellen {st.get('waves', 0)}   Schwelle {st.get('threshold', 0)}   Gebaeude {st.get('structures', 0)} (Mex {st.get('mex', 0)}, Fab {st.get('factories', 0)})   Ing {st.get('engineers', 0)}")
        ui = "ok" if st.get("ui_ok") else ("gesucht" if st.get("ui_visible") else "kein Spiel")
        valid = "ja" if st.get("map_view_valid") else "nein"
        self.vars["vision"].set(f"Sicht: {st.get('vision_fps', 0)} fps ({st.get('vision_backend', '-')})   Baumenue: {ui}   Skalierung {st.get('ui_scale') or '-'}   "
                                f"Karte: {valid}   Gegner gesehen {st.get('enemies_total', 0)} / Basis {st.get('enemies_near_base', 0)}   Ollama: {st.get('ollama', '-')}")
        self.vars["event"].set(f"Letztes: {st.get('last_event', '-')}")
        try:
            self._update_log(st.get("events"))
            self._draw_minimap(st)
        except Exception as exc:  # cosmetic widgets must not break the overlay
            log.debug("Minikarte/Log: %s", exc)
        self._refresh_buttons()
        self.root.after(500, self._poll)

    # ------------------------------------------------------------------ live preview ("Bot-Sicht")
    def toggle_preview(self) -> None:
        if self.preview is not None:
            self.preview.destroy()
            self.preview = None
            self._preview_label = None
            return
        self.preview = tk.Toplevel(self.root)
        self.preview.title("SupComBot - Bot-Sicht")
        self.preview.attributes("-topmost", True)
        self.preview.configure(bg="#000000")
        self.preview.protocol("WM_DELETE_WINDOW", self.toggle_preview)
        self._preview_label = tk.Label(self.preview, bg="#000000")
        self._preview_label.pack()
        self.root.after(50, self._poll_preview)

    def _poll_preview(self) -> None:
        if self.preview is None or self._preview_label is None:
            return
        try:
            self._render_preview()
        except Exception as exc:  # preview is a convenience, never fatal
            log.debug("Vorschau: %s", exc)
        self.root.after(150, self._poll_preview)

    def _render_preview(self) -> None:
        from PIL import Image, ImageDraw, ImageTk

        frame, ts = self.bot.stream.latest(max_age=3.0)
        width = 640
        if frame is None:
            img = Image.new("RGB", (width, int(width * 9 / 16)), (10, 10, 20))
            d = ImageDraw.Draw(img)
            d.text((10, 10), "kein Bild (Spielfenster?)", fill=(230, 230, 230))
        else:
            h, w = frame.shape[:2]
            scale = width / max(1, w)
            img = Image.fromarray(frame).resize((width, max(1, int(h * scale))), Image.BILINEAR)
            d = ImageDraw.Draw(img)
            cam = self.bot.camera
            p = self.bot.percepts()
            ui = self.bot.game.ui
            if ui.last_panel:
                for bp, (x, y) in ui.last_panel.items.items():
                    r = ui.slot * scale / 2
                    d.rectangle([x * scale - r, y * scale - r, x * scale + r, y * scale + r], outline=(0, 255, 120))
            if cam.rect:
                x, y, rw, rh = cam.rect
                d.rectangle([x * scale, y * scale, (x + rw) * scale, (y + rh) * scale],
                            outline=(0, 200, 255) if p.map_view_valid else (255, 120, 0), width=2)

                def wp(wx, wz):
                    cx, cy = cam.world_to_client(wx, wz)
                    return cx * scale, cy * scale

                ctx = self.bot.ctx
                sx, sy = wp(*ctx.start)
                d.ellipse([sx - 6, sy - 6, sx + 6, sy + 6], outline=(0, 255, 0), width=2)
                rx, ry = wp(*ctx.rally)
                d.ellipse([rx - 5, ry - 5, rx + 5, ry + 5], outline=(255, 230, 0), width=2)
                for e in ctx.enemies:
                    ex, ey = wp(*e)
                    d.line([ex - 5, ey - 5, ex + 5, ey + 5], fill=(255, 60, 60), width=2)
                    d.line([ex - 5, ey + 5, ex + 5, ey - 5], fill=(255, 60, 60), width=2)
                for st in list(self.bot.state.structures):
                    bx, by = wp(st.x, st.z)
                    d.rectangle([bx - 2, by - 2, bx + 2, by + 2], outline=(180, 180, 180))
                for (ex, ey) in p.enemy_points[:80]:
                    d.point((ex * scale, ey * scale), fill=(255, 0, 0))
            if p.idle_engineer:
                x, y = p.idle_engineer
                d.ellipse([x * scale - 8, y * scale - 8, x * scale + 8, y * scale + 8], outline=(255, 255, 0), width=2)
            age = time.time() - ts
            d.text((6, 4), f"{p.backend} {p.fps:.0f} fps  Alter {age * 1000:.0f} ms  Masse {int((p.mass or 0) * 100)}%  Energie {int((p.energy or 0) * 100)}%  Armee {p.army_seen if p.army_seen is not None else '-'}",
                   fill=(255, 255, 255))
        self._preview_photo = ImageTk.PhotoImage(img)
        self._preview_label.configure(image=self._preview_photo)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        try:
            if keyboard:
                keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
