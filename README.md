# 🌊 Abyssal — Tiefsee-Förderung

Ein Idle-Tycoon-Spiel als **einzelne, einbettbare HTML-Datei**. Keine Dependencies,
kein Build-Step, kein npm — einfach `index.html` öffnen oder per `<iframe>` einbetten.

Dunkler Tiefsee-Look (Navy/Tiefseeblau) mit Biolumineszenz-Akzenten in Cyan & Magenta.

## Spielprinzip

- **Credits** ticken automatisch — manuell fördern per Tap als Einstieg.
- **6 Generatoren** als Kette mit exponentiell steigenden Kosten:
  Gezeitenbecken → Kelpfarm → Riff → Tiefseegraben → Hydrothermalquelle → Abyssalkern
- Pro Generator: **Kauf ×1/×10/×100**, ein **Upgrade-Track** (×2 Produktion je Stufe)
  und ein **Manager**, der den Generator automatisiert.

### Der Twist: Druck

Tiefere Generatoren erzeugen **Druck**. Übersteigt der Druck die Kapazität deiner
Hülle, droht eine **Implosion** und die Produktion bricht drastisch ein (bis −85 %).
Kaufe **Verstärkungen**, um die Kapazität zu erhöhen — das erzwingt echte
Kaufentscheidungen zwischen mehr Produktion und mehr Stabilität.

### Prestige: Tauchgang zurücksetzen

Setze Credits, Generatoren und Verstärkungen zurück und erhalte permanente
**Perlen**, die als globaler Produktions-Multiplikator über alle künftigen
Tauchgänge wirken (`Perlen = floor(√(verdiente Credits / 1e6))`).

## Features

- 📱 **Mobile-first**: Touch-Events, große Tap-Targets, responsive bis 320 px,
  Canvas auf `devicePixelRatio` skaliert.
- 💾 **Autosave** alle 5 s in `localStorage` + **Offline-Progress** (gedeckelt auf 8 h).
  Fällt in Sandboxes ohne Storage sauber auf In-Memory zurück.
- ♿ **Barrierefrei**: sichtbarer Keyboard-Fokus, `prefers-reduced-motion` respektiert.
- 🔢 Zahl-Formatierung mit Abkürzungen (1.2K, 3.4M, 5.6B, …).
- 📤 Export/Import des Spielstands als Base64-String.

## Einbetten

```html
<iframe src="index.html"
        width="420" height="800"
        style="border:0;border-radius:12px"
        title="Abyssal — Tiefsee-Förderung"></iframe>
```

Oder direkt `index.html` im Browser öffnen.

## Balancing (Kurzfassung)

- Kostenfaktor pro Kauf: **1.15** (klassische Idle-Kurve).
- Erster Generator kostet 12 Credits, Tap gibt ≥1 → erster Kauf in <30 s.
- Pro Tiefenstufe grob ×8 Produktion / ×11 Kosten → tiefere Generatoren sind
  teuer, aber stark.
- Druck nur bei den tieferen Generatoren (ab „Riff"). Kapazität über Verstärkungen.

Details als Kommentare in `index.html`.
