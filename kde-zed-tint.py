#!/usr/bin/env python3
"""
kde-zed-tint: Generate a Zed editor theme tinted with KDE Plasma's accent color.
Watches kdeglobals for changes and rewrites the theme JSON automatically.

Requirements: python3, inotify-tools (inotifywait) OR watchdog pip package
              python3-watchdog  (pip install watchdog)
"""

import json
import os
import sys
import time
import colorsys
import argparse
import subprocess
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
KDEGLOBALS      = Path.home() / ".config" / "kdeglobals"
ZED_THEMES_DIR  = Path.home() / ".config" / "zed" / "themes"
OUTPUT_THEME    = ZED_THEMES_DIR / "kde-tint.json"

# ── Base dark palette (neutral — Adwaita / Material-ish, all in hex) ──────────
# Surfaces are pure neutral greys (r == g == b) so the accent tint lands on a
# clean base instead of muddying an already blue-tinted One Dark background.
# These are the "fixed" values that won't be tinted.
BASE = {
    "bg":           "#1e1e1e",   # Adwaita view background
    "bg_alt":       "#242424",   # Adwaita window background
    "bg_elevated":  "#2b2b2b",
    "surface":      "#303030",   # Adwaita headerbar / sidebar
    "overlay":      "#3a3a3a",
    "fg":           "#b4b4b4",
    "fg_muted":     "#787878",
    "fg_subtle":    "#565656",
    # syntax
    "red":          "#e06c75",
    "orange":       "#d19a66",
    "yellow":       "#e5c07b",
    "green":        "#98c379",
    "cyan":         "#56b6c2",
    "blue":         "#61afef",
    "purple":       "#c678dd",
    "comment":      "#666666",
}

TINT_STRENGTH = 0.075   # 7.5 % — same ratio used by adw-tint-kde


# ── Color helpers ──────────────────────────────────────────────────────────────

def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        int(r * 255), int(g * 255), int(b * 255)
    )


def mix(base_hex: str, tint_hex: str, amount: float) -> str:
    """Linear mix: result = base * (1 - amount) + tint * amount"""
    br, bg, bb = hex_to_rgb(base_hex)
    tr, tg, tb = hex_to_rgb(tint_hex)
    r = br + (tr - br) * amount
    g = bg + (tg - bg) * amount
    b = bb + (tb - bb) * amount
    return rgb_to_hex(r, g, b)


def lighten(hex_color: str, amount: float) -> str:
    r, g, b = hex_to_rgb(hex_color)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    v = min(1.0, v + amount)
    return rgb_to_hex(*colorsys.hsv_to_rgb(h, s, v))


def darken(hex_color: str, amount: float) -> str:
    r, g, b = hex_to_rgb(hex_color)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    v = max(0.0, v - amount)
    return rgb_to_hex(*colorsys.hsv_to_rgb(h, s, v))


def with_alpha(hex_color: str, alpha: float) -> str:
    """Return #rrggbbaa"""
    r, g, b = hex_to_rgb(hex_color)
    a = int(alpha * 255)
    return "#{:02x}{:02x}{:02x}{:02x}".format(
        int(r * 255), int(g * 255), int(b * 255), a
    )


# ── KDE accent reader ──────────────────────────────────────────────────────────

def read_kde_accent() -> str | None:
    """
    Read the current KDE accent color.

    KDE Plasma 6 stores it in kdeglobals under [General] AccentColor as "r,g,b".
    Falls back to DecorationFocus from [Colors:Button] if AccentColor is absent.
    Returns a hex string like #61afef, or None if unreadable.
    """
    if not KDEGLOBALS.exists():
        return None

    text = KDEGLOBALS.read_text(errors="replace")
    section = None
    accent_rgb = None
    decoration_focus = None

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
            continue
        if section == "[General]" and line.startswith("AccentColor="):
            val = line.split("=", 1)[1].strip()
            parts = val.split(",")
            if len(parts) == 3:
                try:
                    r, g, b = (int(p.strip()) / 255.0 for p in parts)
                    accent_rgb = (r, g, b)
                except ValueError:
                    pass
        if section == "[Colors:Button]" and line.startswith("DecorationFocus="):
            val = line.split("=", 1)[1].strip()
            parts = val.split(",")
            if len(parts) == 3:
                try:
                    r, g, b = (int(p.strip()) / 255.0 for p in parts)
                    decoration_focus = (r, g, b)
                except ValueError:
                    pass

    if accent_rgb:
        return rgb_to_hex(*accent_rgb)
    if decoration_focus:
        return rgb_to_hex(*decoration_focus)
    return None


def try_dbus_accent() -> str | None:
    """
    Try the XDG Settings Portal (works on both X11 and Wayland, Plasma 6+).
    Returns hex string or None.
    """
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.freedesktop.portal.Desktop",
                "--object-path", "/org/freedesktop/portal/desktop",
                "--method", "org.freedesktop.portal.Settings.Read",
                "org.freedesktop.appearance", "accent-color",
            ],
            capture_output=True, text=True, timeout=2
        )
        # output looks like: (<<(0.38, 0.686, 0.937)>>,)
        out = result.stdout.strip()
        import re
        m = re.search(r"\(([\d.]+),\s*([\d.]+),\s*([\d.]+)\)", out)
        if m:
            r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return rgb_to_hex(r, g, b)
    except Exception:
        pass
    return None


def get_accent_color() -> str:
    """Best-effort accent color, falling back through sources."""
    # 1. XDG portal (most authoritative on Plasma 6 Wayland)
    color = try_dbus_accent()
    if color:
        return color
    # 2. kdeglobals file direct parse
    color = read_kde_accent()
    if color:
        return color
    # 3. Hard-coded default (Zed blue)
    print("[kde-zed-tint] Could not read KDE accent — using default #61afef", file=sys.stderr)
    return "#61afef"


# ── Theme builder ──────────────────────────────────────────────────────────────

def build_theme(accent: str) -> dict:
    """Generate a complete Zed theme JSON structure tinted with accent."""
    t = TINT_STRENGTH

    # Tinted surfaces
    bg           = mix(BASE["bg"],          accent, t)
    bg_alt       = mix(BASE["bg_alt"],      accent, t)
    bg_elevated  = mix(BASE["bg_elevated"], accent, t)
    surface      = mix(BASE["surface"],     accent, t)
    overlay      = mix(BASE["overlay"],     accent, t)

    # Accent variants
    acc_dim      = darken(accent, 0.15)
    acc_muted    = with_alpha(accent, 0.20)
    acc_subtle   = with_alpha(accent, 0.12)
    acc_border   = with_alpha(accent, 0.50)

    # Status colors (untinted — keep semantic clarity)
    red    = BASE["red"]
    orange = BASE["orange"]
    yellow = BASE["yellow"]
    green  = BASE["green"]
    cyan   = BASE["cyan"]
    blue   = BASE["blue"]
    purple = BASE["purple"]

    theme = {
        "$schema": "https://zed.dev/schema/themes/v0.2.0.json",
        "name": "KDE Tint",
        "author": "kde-zed-tint",
        "themes": [
            {
                "name": "KDE Tint Dark",
                "appearance": "dark",
                "style": {
                    # ── Backgrounds ────────────────────────────────────────
                    "background":                    bg,
                    "background.appearance":         "opaque",
                    "elevated_surface.background":   bg_elevated,
                    "surface.background":            surface,
                    "panel.background":              bg_alt,
                    "pane.background":               bg,
                    "element.background":            overlay,
                    "element.hover":                 with_alpha(accent, 0.08),
                    "element.active":                with_alpha(accent, 0.15),
                    "element.selected":              with_alpha(accent, 0.20),
                    "element.disabled":              with_alpha(BASE["fg_subtle"], 0.40),
                    "drop_target.background":        with_alpha(accent, 0.18),

                    # ── Borders ────────────────────────────────────────────
                    "border":                        with_alpha(BASE["fg_subtle"], 0.30),
                    "border.variant":                with_alpha(BASE["fg_subtle"], 0.20),
                    "border.focused":                acc_border,
                    "border.selected":               accent,
                    "border.transparent":            "#00000000",
                    "border.disabled":               with_alpha(BASE["fg_subtle"], 0.15),

                    # ── Text ───────────────────────────────────────────────
                    "text":                          BASE["fg"],
                    "text.muted":                    BASE["fg_muted"],
                    "text.placeholder":              BASE["fg_subtle"],
                    "text.disabled":                 with_alpha(BASE["fg_muted"], 0.50),
                    "text.accent":                   accent,

                    # ── Icons ──────────────────────────────────────────────
                    "icon":                          BASE["fg_muted"],
                    "icon.muted":                    BASE["fg_subtle"],
                    "icon.disabled":                 with_alpha(BASE["fg_subtle"], 0.40),
                    "icon.placeholder":              BASE["fg_subtle"],
                    "icon.accent":                   accent,

                    # ── Status ─────────────────────────────────────────────
                    "status_bar.background":         bg_alt,

                    # ── Title bar ──────────────────────────────────────────
                    "title_bar.background":          bg_alt,
                    "title_bar.inactive_background": bg,

                    # ── Toolbar ────────────────────────────────────────────
                    "toolbar.background":            bg_elevated,

                    # ── Tab bar ────────────────────────────────────────────
                    "tab_bar.background":            bg_alt,
                    "tab.inactive_background":       bg_alt,
                    "tab.active_background":         bg,

                    # ── Search / Match ─────────────────────────────────────
                    "search.match_background":       with_alpha(accent, 0.25),

                    # ── Panels ─────────────────────────────────────────────
                    "panel.focused_border":          acc_border,

                    # ── Pane ──────────────────────────────────────────────
                    "pane.focused_border":           accent,

                    # ── Scrollbar ──────────────────────────────────────────
                    "scrollbar.thumb.background":    with_alpha(BASE["fg_subtle"], 0.35),
                    "scrollbar.thumb.hover_background": with_alpha(BASE["fg_muted"], 0.55),
                    "scrollbar.thumb.border":        with_alpha(BASE["fg_subtle"], 0.10),
                    "scrollbar.track.background":    "#00000000",
                    "scrollbar.track.border":        with_alpha(BASE["fg_subtle"], 0.08),

                    # ── Editor ─────────────────────────────────────────────
                    "editor.background":             bg,
                    "editor.gutter.background":      bg,
                    "editor.subheader.background":   bg_alt,
                    "editor.active_line.background": with_alpha(accent, 0.06),
                    "editor.highlighted_line.background": with_alpha(accent, 0.09),
                    "editor.line_number":            BASE["fg_subtle"],
                    "editor.active_line_number":     accent,
                    "editor.invisible":              with_alpha(BASE["fg_subtle"], 0.25),
                    "editor.wrap_guide":             with_alpha(BASE["fg_subtle"], 0.12),
                    "editor.active_wrap_guide":      with_alpha(accent, 0.25),
                    "editor.document_highlight.read_background":  with_alpha(accent, 0.12),
                    "editor.document_highlight.write_background": with_alpha(accent, 0.20),

                    # ── Terminal ────────────────────────────────────────────
                    "terminal.background":           bg,
                    "terminal.foreground":           BASE["fg"],
                    "terminal.bright_foreground":    BASE["fg"],
                    "terminal.dim_foreground":       BASE["fg_muted"],
                    "terminal.ansi.black":           surface,
                    "terminal.ansi.bright_black":    overlay,
                    "terminal.ansi.white":           BASE["fg"],
                    "terminal.ansi.bright_white":    "#ffffff",
                    "terminal.ansi.red":             red,
                    "terminal.ansi.bright_red":      lighten(red, 0.1),
                    "terminal.ansi.green":           green,
                    "terminal.ansi.bright_green":    lighten(green, 0.1),
                    "terminal.ansi.yellow":          yellow,
                    "terminal.ansi.bright_yellow":   lighten(yellow, 0.1),
                    "terminal.ansi.blue":            blue,
                    "terminal.ansi.bright_blue":     lighten(blue, 0.1),
                    "terminal.ansi.magenta":         purple,
                    "terminal.ansi.bright_magenta":  lighten(purple, 0.1),
                    "terminal.ansi.cyan":            cyan,
                    "terminal.ansi.bright_cyan":     lighten(cyan, 0.1),

                    # ── Git diff ────────────────────────────────────────────
                    "created":                       green,
                    "created.background":            with_alpha(green, 0.15),
                    "created.border":                with_alpha(green, 0.40),
                    "modified":                      yellow,
                    "modified.background":           with_alpha(yellow, 0.15),
                    "modified.border":               with_alpha(yellow, 0.40),
                    "deleted":                       red,
                    "deleted.background":            with_alpha(red, 0.15),
                    "deleted.border":                with_alpha(red, 0.40),

                    # ── Diagnostics ─────────────────────────────────────────
                    "error":                         red,
                    "error.background":              with_alpha(red, 0.15),
                    "error.border":                  with_alpha(red, 0.40),
                    "warning":                       yellow,
                    "warning.background":            with_alpha(yellow, 0.12),
                    "warning.border":                with_alpha(yellow, 0.35),
                    "info":                          blue,
                    "info.background":               with_alpha(blue, 0.12),
                    "info.border":                   with_alpha(blue, 0.35),
                    "hint":                          BASE["fg_muted"],
                    "hint.background":               with_alpha(BASE["fg_muted"], 0.10),
                    "hint.border":                   with_alpha(BASE["fg_muted"], 0.25),
                    "predictive":                    BASE["fg_subtle"],
                    "predictive.background":         with_alpha(BASE["fg_subtle"], 0.10),
                    "predictive.border":             with_alpha(BASE["fg_subtle"], 0.20),

                    # ── Players / Selections ────────────────────────────────
                    "players": [
                        {
                            "cursor":     accent,
                            "background": with_alpha(accent, 0.22),
                            "selection":  with_alpha(accent, 0.22),
                        },
                        {
                            "cursor":     green,
                            "background": with_alpha(green, 0.22),
                            "selection":  with_alpha(green, 0.22),
                        },
                        {
                            "cursor":     red,
                            "background": with_alpha(red, 0.22),
                            "selection":  with_alpha(red, 0.22),
                        },
                        {
                            "cursor":     yellow,
                            "background": with_alpha(yellow, 0.22),
                            "selection":  with_alpha(yellow, 0.22),
                        },
                    ],

                    # ── Link ───────────────────────────────────────────────
                    "link_text.hover":               lighten(accent, 0.1),

                    # ── Syntax ─────────────────────────────────────────────
                    "syntax": {
                        "attribute":     {"color": orange,                "font_style": None, "font_weight": None},
                        "boolean":       {"color": orange,                "font_style": None, "font_weight": None},
                        "comment":       {"color": BASE["comment"],       "font_style": "italic", "font_weight": None},
                        "comment.doc":   {"color": lighten(BASE["comment"], 0.08), "font_style": "italic", "font_weight": None},
                        "constant":      {"color": orange,                "font_style": None, "font_weight": None},
                        "constructor":   {"color": blue,                  "font_style": None, "font_weight": None},
                        "embedded":      {"color": BASE["fg"],            "font_style": None, "font_weight": None},
                        "emphasis":      {"color": BASE["fg"],            "font_style": "italic", "font_weight": None},
                        "emphasis.strong": {"color": BASE["fg"],          "font_style": None, "font_weight": 700},
                        "enum":          {"color": yellow,                "font_style": None, "font_weight": None},
                        "function":      {"color": blue,                  "font_style": None, "font_weight": None},
                        "function.builtin": {"color": cyan,               "font_style": None, "font_weight": None},
                        "function.definition": {"color": blue,            "font_style": None, "font_weight": None},
                        "hint":          {"color": BASE["fg_muted"],      "font_style": None, "font_weight": None},
                        "keyword":       {"color": purple,                "font_style": None, "font_weight": None},
                        "label":         {"color": red,                   "font_style": None, "font_weight": None},
                        "link_text":     {"color": accent,                "font_style": None, "font_weight": None},
                        "link_uri":      {"color": green,                 "font_style": None, "font_weight": None},
                        "number":        {"color": orange,                "font_style": None, "font_weight": None},
                        "operator":      {"color": BASE["fg"],            "font_style": None, "font_weight": None},
                        "predictive":    {"color": BASE["fg_subtle"],     "font_style": "italic", "font_weight": None},
                        "preproc":       {"color": purple,                "font_style": None, "font_weight": None},
                        "primary":       {"color": BASE["fg"],            "font_style": None, "font_weight": None},
                        "property":      {"color": red,                   "font_style": None, "font_weight": None},
                        "punctuation":   {"color": BASE["fg_muted"],      "font_style": None, "font_weight": None},
                        "punctuation.bracket": {"color": BASE["fg_muted"],"font_style": None, "font_weight": None},
                        "punctuation.delimiter": {"color": BASE["fg_muted"],"font_style": None, "font_weight": None},
                        "punctuation.list_marker": {"color": accent,      "font_style": None, "font_weight": None},
                        "punctuation.special": {"color": cyan,            "font_style": None, "font_weight": None},
                        "string":        {"color": green,                 "font_style": None, "font_weight": None},
                        "string.escape": {"color": cyan,                  "font_style": None, "font_weight": None},
                        "string.regex":  {"color": cyan,                  "font_style": None, "font_weight": None},
                        "string.special": {"color": cyan,                 "font_style": None, "font_weight": None},
                        "string.special.symbol": {"color": green,         "font_style": None, "font_weight": None},
                        "tag":           {"color": red,                   "font_style": None, "font_weight": None},
                        "text.literal":  {"color": green,                 "font_style": None, "font_weight": None},
                        "title":         {"color": accent,                "font_style": None, "font_weight": 700},
                        "type":          {"color": yellow,                "font_style": None, "font_weight": None},
                        "type.builtin":  {"color": yellow,                "font_style": None, "font_weight": None},
                        "type.interface": {"color": yellow,               "font_style": "italic", "font_weight": None},
                        "type.super":    {"color": yellow,                "font_style": None, "font_weight": None},
                        "variable":      {"color": red,                   "font_style": None, "font_weight": None},
                        "variable.special": {"color": orange,             "font_style": "italic", "font_weight": None},
                        "variant":       {"color": accent,                "font_style": None, "font_weight": None},
                    },
                },
            }
        ],
    }
    return theme


# ── Write ──────────────────────────────────────────────────────────────────────

def apply_theme(verbose: bool = True):
    accent = get_accent_color()
    theme  = build_theme(accent)

    ZED_THEMES_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_THEME.write_text(json.dumps(theme, indent=2))

    if verbose:
        print(f"[kde-zed-tint] Wrote theme with accent {accent} → {OUTPUT_THEME}")


# ── Watcher ────────────────────────────────────────────────────────────────────

def watch():
    """Watch kdeglobals for changes using inotifywait (no extra Python deps)."""
    print(f"[kde-zed-tint] Watching {KDEGLOBALS} for accent color changes…")
    apply_theme()

    # Try inotifywait first (usually available as inotify-tools)
    try:
        subprocess.run(["which", "inotifywait"], check=True,
                       capture_output=True)
        _watch_inotify()
    except subprocess.CalledProcessError:
        # Fall back to polling every 2 seconds
        print("[kde-zed-tint] inotifywait not found — falling back to polling every 2s")
        _watch_poll()


def _watch_inotify():
    import subprocess
    last_accent = None
    while True:
        subprocess.run(
            ["inotifywait", "-e", "close_write,modify",
             "-q", str(KDEGLOBALS)],
            check=False
        )
        accent = get_accent_color()
        if accent != last_accent:
            last_accent = accent
            apply_theme()


def _watch_poll():
    last_mtime  = None
    last_accent = None
    while True:
        try:
            mtime = KDEGLOBALS.stat().st_mtime
        except FileNotFoundError:
            time.sleep(2)
            continue
        if mtime != last_mtime:
            last_mtime = mtime
            accent = get_accent_color()
            if accent != last_accent:
                last_accent = accent
                apply_theme()
        time.sleep(2)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a Zed theme tinted with KDE Plasma's accent color."
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Keep running and regenerate on accent color change"
    )
    parser.add_argument(
        "--accent", metavar="HEX",
        help="Override accent color (e.g. #ff6600) instead of reading from KDE"
    )
    args = parser.parse_args()

    if args.accent:
        # Manual override
        theme = build_theme(args.accent)
        ZED_THEMES_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_THEME.write_text(json.dumps(theme, indent=2))
        print(f"Written with override accent {args.accent} → {OUTPUT_THEME}")
        return

    if args.watch:
        watch()
    else:
        apply_theme()


if __name__ == "__main__":
    main()
