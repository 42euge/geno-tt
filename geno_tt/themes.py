"""iTerm2 theme management — named color scheme presets with workspace assignment."""

import json
import subprocess
import sys
from pathlib import Path
from .config import TT_HOME

THEMES_DIR = TT_HOME / "themes"
PLIST = Path.home() / "Library" / "Preferences" / "com.googlecode.iterm2.plist"

COLOR_KEYS = [
    "Background Color",
    "Foreground Color",
    "Cursor Color",
    "Cursor Text Color",
    "Selection Color",
    "Selected Text Color",
    "Bold Color",
    "Badge Color",
] + [f"Ansi {i} Color" for i in range(16)]

SCALAR_KEYS = [
    "Normal Font",
    "Transparency",
    "Blur",
    "Blur Radius",
    "Cursor Type",
    "Blinking Cursor",
]


def _pb_read(key_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", f"Print '{key_path}'", str(PLIST)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _pb_read_color(key: str) -> dict | None:
    prefix = f":New Bookmarks:0:{key}"
    color = {}
    for component in ("Red Component", "Green Component", "Blue Component", "Alpha Component"):
        val = _pb_read(f"{prefix}:{component}")
        if val is not None:
            color[component] = float(val)
    if color:
        cs = _pb_read(f"{prefix}:Color Space")
        if cs:
            color["Color Space"] = cs
        return color
    return None


def _pb_write(key_path: str, value: str):
    subprocess.run(
        ["/usr/libexec/PlistBuddy", "-c", f"Set '{key_path}' {value}", str(PLIST)],
        capture_output=True,
    )


def _pb_write_color(key: str, color: dict):
    prefix = f":New Bookmarks:0:{key}"
    for component in ("Red Component", "Green Component", "Blue Component", "Alpha Component"):
        if component in color:
            _pb_write(f"{prefix}:{component}", str(color[component]))
    if "Color Space" in color:
        _pb_write(f"{prefix}:Color Space", color["Color Space"])


def _rgb_to_float(r: int, g: int, b: int) -> dict:
    return {
        "Red Component": r / 255.0,
        "Green Component": g / 255.0,
        "Blue Component": b / 255.0,
        "Alpha Component": 1.0,
        "Color Space": "sRGB",
    }


def list_themes() -> list[str]:
    """Return names of all saved themes."""
    if not THEMES_DIR.exists():
        return []
    return sorted(p.stem for p in THEMES_DIR.glob("*.json"))


def load_theme(name: str) -> dict | None:
    """Load a theme by name."""
    path = THEMES_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_theme(name: str, theme: dict):
    """Save a theme to disk."""
    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    path = THEMES_DIR / f"{name}.json"
    path.write_text(json.dumps(theme, indent=2) + "\n")


def capture_current() -> dict:
    """Capture the current iTerm2 color scheme as a theme dict."""
    if not PLIST.exists():
        print("iTerm2 plist not found.", file=sys.stderr)
        sys.exit(1)

    theme = {"colors": {}, "scalars": {}}
    for key in COLOR_KEYS:
        color = _pb_read_color(key)
        if color:
            theme["colors"][key] = color

    for key in SCALAR_KEYS:
        val = _pb_read(f":New Bookmarks:0:{key}")
        if val is not None:
            theme["scalars"][key] = val

    return theme


def apply_theme(theme: dict):
    """Apply a theme dict to iTerm2's default profile."""
    if not PLIST.exists():
        print("iTerm2 plist not found.", file=sys.stderr)
        sys.exit(1)

    for key, color in theme.get("colors", {}).items():
        _pb_write_color(key, color)

    for key, val in theme.get("scalars", {}).items():
        _pb_write(f":New Bookmarks:0:{key}", val)


def _color_to_applescript_rgb(color: dict) -> str:
    """Convert a color dict to iTerm2 AppleScript RGB {r, g, b} (0-65535 scale)."""
    r = int(color.get("Red Component", 0) * 65535)
    g = int(color.get("Green Component", 0) * 65535)
    b = int(color.get("Blue Component", 0) * 65535)
    return f"{{{r}, {g}, {b}}}"


def _color_to_osc_hex(color: dict) -> str:
    """Convert a color dict to hex format for OSC sequences: rr/gg/bb."""
    r = int(color.get("Red Component", 0) * 255)
    g = int(color.get("Green Component", 0) * 255)
    b = int(color.get("Blue Component", 0) * 255)
    return f"{r:02x}/{g:02x}/{b:02x}"


def apply_theme_live(theme: dict, preset_name: str | None = None):
    """Apply color changes to all iTerm2 sessions.

    If preset_name is provided and matches an iTerm2 color preset, use that directly.
    Otherwise, save as a temp preset and apply it.
    """
    if preset_name:
        # Try applying as an iTerm2 color preset name directly
        script = f'''
tell application "iTerm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                tell s to set color preset to "{preset_name}"
            end repeat
        end repeat
    end repeat
end tell
'''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if result.returncode == 0:
            return

    # Fallback: import theme as a temp .itermcolors file, then apply as preset
    import plistlib
    import tempfile

    colors = theme.get("colors", {})
    plist_dict = {}
    for key, color in colors.items():
        plist_dict[key] = {
            "Red Component": color.get("Red Component", 0),
            "Green Component": color.get("Green Component", 0),
            "Blue Component": color.get("Blue Component", 0),
            "Alpha Component": color.get("Alpha Component", 1.0),
            "Color Space": color.get("Color Space", "sRGB"),
        }

    with tempfile.NamedTemporaryFile(suffix=".itermcolors", delete=False) as f:
        plistlib.dump(plist_dict, f)
        tmp_path = f.name

    # Import and apply
    subprocess.run(["open", tmp_path], capture_output=True)
    import time
    time.sleep(1)

    # Apply the imported preset (filename without extension)
    import os
    preset = os.path.basename(tmp_path).replace(".itermcolors", "")
    script = f'''
tell application "iTerm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                tell s to set color preset to "{preset}"
            end repeat
        end repeat
    end repeat
end tell
'''
    subprocess.run(["osascript", "-e", script], capture_output=True)
    os.unlink(tmp_path)


# --- Built-in starter themes ---

BUILTIN_THEMES = {
    "dark": {
        "colors": {
            "Background Color": _rgb_to_float(30, 30, 30),
            "Foreground Color": _rgb_to_float(220, 220, 220),
            "Cursor Color": _rgb_to_float(220, 220, 220),
            "Cursor Text Color": _rgb_to_float(30, 30, 30),
            "Selection Color": _rgb_to_float(68, 68, 68),
            "Selected Text Color": _rgb_to_float(255, 255, 255),
            "Bold Color": _rgb_to_float(255, 255, 255),
            "Ansi 0 Color": _rgb_to_float(0, 0, 0),
            "Ansi 1 Color": _rgb_to_float(194, 54, 33),
            "Ansi 2 Color": _rgb_to_float(37, 188, 36),
            "Ansi 3 Color": _rgb_to_float(173, 173, 39),
            "Ansi 4 Color": _rgb_to_float(73, 46, 225),
            "Ansi 5 Color": _rgb_to_float(211, 56, 211),
            "Ansi 6 Color": _rgb_to_float(51, 187, 200),
            "Ansi 7 Color": _rgb_to_float(203, 204, 205),
            "Ansi 8 Color": _rgb_to_float(129, 131, 131),
            "Ansi 9 Color": _rgb_to_float(252, 57, 31),
            "Ansi 10 Color": _rgb_to_float(49, 231, 34),
            "Ansi 11 Color": _rgb_to_float(234, 236, 35),
            "Ansi 12 Color": _rgb_to_float(88, 51, 255),
            "Ansi 13 Color": _rgb_to_float(249, 53, 248),
            "Ansi 14 Color": _rgb_to_float(20, 240, 240),
            "Ansi 15 Color": _rgb_to_float(233, 235, 235),
        },
        "scalars": {},
    },
    "light": {
        "colors": {
            "Background Color": _rgb_to_float(255, 255, 255),
            "Foreground Color": _rgb_to_float(30, 30, 30),
            "Cursor Color": _rgb_to_float(30, 30, 30),
            "Cursor Text Color": _rgb_to_float(255, 255, 255),
            "Selection Color": _rgb_to_float(178, 215, 255),
            "Selected Text Color": _rgb_to_float(0, 0, 0),
            "Bold Color": _rgb_to_float(0, 0, 0),
            "Ansi 0 Color": _rgb_to_float(0, 0, 0),
            "Ansi 1 Color": _rgb_to_float(194, 54, 33),
            "Ansi 2 Color": _rgb_to_float(37, 138, 36),
            "Ansi 3 Color": _rgb_to_float(143, 120, 0),
            "Ansi 4 Color": _rgb_to_float(0, 32, 194),
            "Ansi 5 Color": _rgb_to_float(160, 40, 160),
            "Ansi 6 Color": _rgb_to_float(0, 150, 160),
            "Ansi 7 Color": _rgb_to_float(200, 200, 200),
            "Ansi 8 Color": _rgb_to_float(100, 100, 100),
            "Ansi 9 Color": _rgb_to_float(220, 50, 47),
            "Ansi 10 Color": _rgb_to_float(42, 161, 35),
            "Ansi 11 Color": _rgb_to_float(181, 137, 0),
            "Ansi 12 Color": _rgb_to_float(38, 139, 210),
            "Ansi 13 Color": _rgb_to_float(211, 54, 130),
            "Ansi 14 Color": _rgb_to_float(42, 161, 152),
            "Ansi 15 Color": _rgb_to_float(50, 50, 50),
        },
        "scalars": {},
    },
    "solarized-dark": {
        "colors": {
            "Background Color": _rgb_to_float(0, 43, 54),
            "Foreground Color": _rgb_to_float(131, 148, 150),
            "Cursor Color": _rgb_to_float(131, 148, 150),
            "Cursor Text Color": _rgb_to_float(0, 43, 54),
            "Selection Color": _rgb_to_float(7, 54, 66),
            "Selected Text Color": _rgb_to_float(147, 161, 161),
            "Bold Color": _rgb_to_float(147, 161, 161),
            "Ansi 0 Color": _rgb_to_float(7, 54, 66),
            "Ansi 1 Color": _rgb_to_float(220, 50, 47),
            "Ansi 2 Color": _rgb_to_float(133, 153, 0),
            "Ansi 3 Color": _rgb_to_float(181, 137, 0),
            "Ansi 4 Color": _rgb_to_float(38, 139, 210),
            "Ansi 5 Color": _rgb_to_float(211, 54, 130),
            "Ansi 6 Color": _rgb_to_float(42, 161, 152),
            "Ansi 7 Color": _rgb_to_float(238, 232, 213),
            "Ansi 8 Color": _rgb_to_float(0, 43, 54),
            "Ansi 9 Color": _rgb_to_float(203, 75, 22),
            "Ansi 10 Color": _rgb_to_float(88, 110, 117),
            "Ansi 11 Color": _rgb_to_float(101, 123, 131),
            "Ansi 12 Color": _rgb_to_float(131, 148, 150),
            "Ansi 13 Color": _rgb_to_float(108, 113, 196),
            "Ansi 14 Color": _rgb_to_float(147, 161, 161),
            "Ansi 15 Color": _rgb_to_float(253, 246, 227),
        },
        "scalars": {},
    },
    "monokai": {
        "colors": {
            "Background Color": _rgb_to_float(39, 40, 34),
            "Foreground Color": _rgb_to_float(248, 248, 242),
            "Cursor Color": _rgb_to_float(248, 248, 242),
            "Cursor Text Color": _rgb_to_float(39, 40, 34),
            "Selection Color": _rgb_to_float(73, 72, 62),
            "Selected Text Color": _rgb_to_float(248, 248, 242),
            "Bold Color": _rgb_to_float(255, 255, 255),
            "Ansi 0 Color": _rgb_to_float(39, 40, 34),
            "Ansi 1 Color": _rgb_to_float(249, 38, 114),
            "Ansi 2 Color": _rgb_to_float(166, 226, 46),
            "Ansi 3 Color": _rgb_to_float(244, 191, 117),
            "Ansi 4 Color": _rgb_to_float(102, 217, 239),
            "Ansi 5 Color": _rgb_to_float(174, 129, 255),
            "Ansi 6 Color": _rgb_to_float(161, 239, 228),
            "Ansi 7 Color": _rgb_to_float(248, 248, 242),
            "Ansi 8 Color": _rgb_to_float(117, 113, 94),
            "Ansi 9 Color": _rgb_to_float(249, 38, 114),
            "Ansi 10 Color": _rgb_to_float(166, 226, 46),
            "Ansi 11 Color": _rgb_to_float(244, 191, 117),
            "Ansi 12 Color": _rgb_to_float(102, 217, 239),
            "Ansi 13 Color": _rgb_to_float(174, 129, 255),
            "Ansi 14 Color": _rgb_to_float(161, 239, 228),
            "Ansi 15 Color": _rgb_to_float(249, 248, 245),
        },
        "scalars": {},
    },
}


# --- CLI commands ---

def cmd_theme_list():
    """List available themes."""
    saved = list_themes()
    builtins = sorted(BUILTIN_THEMES.keys())
    presets = sorted(ITERM2_PRESET_MAP.keys())

    if presets:
        print("iTerm2 presets:")
        for name in presets:
            print(f"  {name}")

    if builtins:
        print("\nCustom built-in themes:")
        for name in builtins:
            print(f"  {name}")

    if saved:
        print("\nSaved themes:")
        for name in saved:
            print(f"  {name}")

    if not builtins and not saved and not presets:
        print("No themes available. Create one with: tt theme create <name>")


def cmd_theme_show(name: str):
    """Show details of a theme."""
    theme = load_theme(name) or BUILTIN_THEMES.get(name)
    if not theme:
        print(f"Theme '{name}' not found.", file=sys.stderr)
        sys.exit(1)

    colors = theme.get("colors", {})
    scalars = theme.get("scalars", {})

    print(f"Theme: {name}")
    if scalars.get("Normal Font"):
        print(f"  Font: {scalars['Normal Font']}")

    for key in ("Background Color", "Foreground Color", "Cursor Color"):
        c = colors.get(key)
        if c:
            r = int(c.get("Red Component", 0) * 255)
            g = int(c.get("Green Component", 0) * 255)
            b = int(c.get("Blue Component", 0) * 255)
            label = key.replace(" Color", "")
            print(f"  {label}: rgb({r}, {g}, {b})")

    ansi_count = sum(1 for k in colors if k.startswith("Ansi"))
    if ansi_count:
        print(f"  ANSI colors: {ansi_count}/16")


def cmd_theme_create(name: str):
    """Capture current iTerm2 appearance as a named theme."""
    theme = capture_current()
    save_theme(name, theme)
    print(f"Theme '{name}' saved to {THEMES_DIR / f'{name}.json'}")
    print(f"  Colors: {len(theme['colors'])} captured")
    if theme['scalars'].get('Normal Font'):
        print(f"  Font: {theme['scalars']['Normal Font']}")


ITERM2_PRESET_MAP = {
    "tango-dark": "Builtin Tango Dark",
    "tango-light": "Builtin Tango Light",
    "solarized-dark": "Builtin Solarized Dark",
    "solarized-light": "Builtin Solarized Light",
    "dark-background": "Dark Background",
    "light-background": "Light Background",
    "pastel-dark": "Builtin Pastel Dark",
}


def cmd_theme_apply(name: str, live: bool = True):
    """Apply a theme by name."""
    # Check if it maps to an iTerm2 built-in preset
    preset_name = ITERM2_PRESET_MAP.get(name)

    theme = load_theme(name) or BUILTIN_THEMES.get(name)
    if not theme and not preset_name:
        print(f"Theme '{name}' not found. Run 'tt theme list' to see available themes.", file=sys.stderr)
        sys.exit(1)

    if preset_name:
        apply_theme_live(theme, preset_name=preset_name)
    elif theme:
        apply_theme(theme)
        if live:
            apply_theme_live(theme)
    print(f"Applied theme '{name}'.")


def cmd_theme_delete(name: str):
    """Delete a saved theme."""
    path = THEMES_DIR / f"{name}.json"
    if not path.exists():
        if name in BUILTIN_THEMES:
            print(f"Cannot delete built-in theme '{name}'.", file=sys.stderr)
        else:
            print(f"Theme '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    path.unlink()
    print(f"Deleted theme '{name}'.")


def apply_theme_to_tty(theme: dict):
    """Apply theme to the current terminal session only (via /dev/tty escape sequences)."""
    colors = theme.get("colors", {})

    try:
        tty = open("/dev/tty", "w")
    except OSError:
        tty = sys.stdout

    key_to_osc = {
        "Foreground Color": "10",
        "Background Color": "11",
        "Cursor Color": "12",
    }
    for key, code in key_to_osc.items():
        color = colors.get(key)
        if color:
            tty.write(f"\033]{code};rgb:{_color_to_osc_hex(color)}\a")

    for i in range(16):
        color = colors.get(f"Ansi {i} Color")
        if color:
            tty.write(f"\033]4;{i};rgb:{_color_to_osc_hex(color)}\a")

    tty.flush()
    if tty is not sys.stdout:
        tty.close()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--apply-live":
        name = sys.argv[2]
        theme = load_theme(name) or BUILTIN_THEMES.get(name)
        if theme:
            apply_theme_to_tty(theme)
