# kde-zed-tint

A Zed editor theme that **tints its surfaces with your KDE Plasma accent color** — and regenerates automatically when the wallpaper changes your accent.

Inspired by [adw-tint-kde](https://github.com/n3thshan/adw-tint-kde), which does the same for libadwaita GTK4 apps.

---

## How it works

KDE Plasma 6 writes the current accent color to `~/.config/kdeglobals` under
`[General] AccentColor = r,g,b` whenever you change wallpaper (with *Accent color from wallpaper* on) or pick a custom color.

`kde-zed-tint.py` reads that value, mixes a 7.5% tint into all surface/background colors — the same ratio used by adw-tint-kde — and writes a valid Zed theme JSON to `~/.config/zed/themes/kde-tint.json`.

In `--watch` mode it listens for `kdeglobals` changes via `inotifywait` (or polls every 2 s) and rewrites the theme file on every accent change.

> **Zed limitation:** unlike GTK4 which can inject CSS variables at runtime, Zed themes are static JSON. The workaround is regenerating the file — Zed hot-reloads themes from disk, so the change is nearly instant.

---

## Requirements

- Python 3.10+
- Zed editor
- KDE Plasma 6 (works on Plasma 5 too, via the kdeglobals fallback)
- `inotify-tools` for instant file-change detection (optional, falls back to polling)

```bash
# Arch
sudo pacman -S inotify-tools

# Fedora
sudo dnf install inotify-tools

# Ubuntu/Debian
sudo apt install inotify-tools
```

---

## Install

```bash
git clone https://github.com/yourname/kde-zed-tint
cd kde-zed-tint
chmod +x install.sh
./install.sh
```

Then in Zed: **Cmd/Ctrl+Shift+P → Theme Selector → KDE Tint Dark**.

---

## Manual use

```bash
# Generate once with your current KDE accent
~/.local/bin/kde-zed-tint.py

# Watch for changes (run in background / via autostart)
~/.local/bin/kde-zed-tint.py --watch

# Override with a specific hex color (no KDE needed)
~/.local/bin/kde-zed-tint.py --accent "#e06c75"
```

---

## What gets tinted

| Color role | Treatment |
|---|---|
| All background/surface/panel colors | 7.5% accent tint (linear mix) |
| Active line highlight | 6% accent alpha overlay |
| Cursor | Full accent color |
| Selection | 22% accent alpha |
| Active line number | Full accent color |
| Borders (focused, selected) | 50% accent alpha |
| Syntax colors (keywords, strings, etc.) | Untouched — keeps readability |
| Status/diagnostic colors (red/yellow/green) | Untouched — keeps semantics |

---

## Uninstall

```bash
# Remove theme
rm ~/.config/zed/themes/kde-tint.json

# Stop and remove service
systemctl --user disable --now kde-zed-tint.service
rm ~/.config/systemd/user/kde-zed-tint.service

# Or remove autostart entry
rm ~/.config/autostart/kde-zed-tint-autostart.desktop

# Remove script
rm ~/.local/bin/kde-zed-tint.py
```

---

## Customization

Edit `TINT_STRENGTH` at the top of `kde-zed-tint.py` (default `0.075`).
Higher = more colorful surfaces, lower = subtler tint.

```python
TINT_STRENGTH = 0.075   # 7.5% — same as adw-tint-kde
TINT_STRENGTH = 0.12    # slightly more visible
TINT_STRENGTH = 0.05    # very subtle
```
