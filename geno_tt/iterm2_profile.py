"""iTerm2 profile export/apply via PlistBuddy."""

import json
import subprocess
import sys
from pathlib import Path
from .config import TT_HOME

PLIST = Path.home() / "Library" / "Preferences" / "com.googlecode.iterm2.plist"
PROFILE_PATH = TT_HOME / "iterm2-profile.json"

SCALAR_KEYS = [
    "Normal Font",
    "Non Ascii Font",
    "Use Non-ASCII Font",
    "Columns",
    "Rows",
    "Scrollback Lines",
    "Transparency",
    "Blur",
    "Blur Radius",
    "Blinking Cursor",
    "Cursor Type",
    "Option Key Sends",
    "Window Type",
    "Custom Directory",
]

COLOR_KEYS = [
    "Background Color",
    "Foreground Color",
    "Cursor Color",
    "Selection Color",
    "Selected Text Color",
    "Bold Color",
    "Badge Color",
] + [f"Ansi {i} Color" for i in range(16)]


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


def _pb_write(key_path: str, value: str, value_type: str = "string"):
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


def export_profile() -> dict:
    """Export current iTerm2 default profile to a dict."""
    profile = {"scalars": {}, "colors": {}}

    for key in SCALAR_KEYS:
        val = _pb_read(f":New Bookmarks:0:{key}")
        if val is not None:
            profile["scalars"][key] = val

    for key in COLOR_KEYS:
        color = _pb_read_color(key)
        if color:
            profile["colors"][key] = color

    return profile


def apply_profile(profile: dict):
    """Apply a saved profile dict to iTerm2's default profile."""
    if not PLIST.exists():
        print("iTerm2 plist not found. Is iTerm2 installed?", file=sys.stderr)
        sys.exit(1)

    applied = 0
    for key, val in profile.get("scalars", {}).items():
        _pb_write(f":New Bookmarks:0:{key}", val)
        applied += 1

    for key, color in profile.get("colors", {}).items():
        _pb_write_color(key, color)
        applied += 1

    return applied


def cmd_profile_export():
    """Export current profile to ~/.geno/tt/iterm2-profile.json."""
    if not PLIST.exists():
        print("iTerm2 plist not found.", file=sys.stderr)
        sys.exit(1)

    profile = export_profile()
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2) + "\n")
    print(f"Exported iTerm2 profile to {PROFILE_PATH}")
    print(f"  Font: {profile['scalars'].get('Normal Font', '?')}")
    print(f"  Window: {profile['scalars'].get('Columns', '?')}x{profile['scalars'].get('Rows', '?')}")
    print(f"  Scrollback: {profile['scalars'].get('Scrollback Lines', '?')}")
    print(f"  Colors: {len(profile['colors'])} saved")


def cmd_profile_apply():
    """Apply saved profile from ~/.geno/tt/iterm2-profile.json."""
    if not PROFILE_PATH.exists():
        print(f"No saved profile at {PROFILE_PATH}", file=sys.stderr)
        print("Run 'tt profile export' first on your configured machine.", file=sys.stderr)
        sys.exit(1)

    profile = json.loads(PROFILE_PATH.read_text())
    count = apply_profile(profile)
    print(f"Applied {count} settings to iTerm2 default profile.")
    print("Restart iTerm2 for changes to take effect.")


def cmd_profile_show():
    """Show current profile summary."""
    if PROFILE_PATH.exists():
        profile = json.loads(PROFILE_PATH.read_text())
        print(f"Saved profile ({PROFILE_PATH}):")
    elif PLIST.exists():
        profile = export_profile()
        print("Current iTerm2 profile (not yet exported):")
    else:
        print("No iTerm2 profile found.", file=sys.stderr)
        sys.exit(1)

    scalars = profile.get("scalars", {})
    print(f"  Font:        {scalars.get('Normal Font', '?')}")
    print(f"  Window:      {scalars.get('Columns', '?')} cols x {scalars.get('Rows', '?')} rows")
    print(f"  Scrollback:  {scalars.get('Scrollback Lines', '?')} lines")
    print(f"  Transparency:{scalars.get('Transparency', '0')}")
    print(f"  Blur:        {scalars.get('Blur', 'false')}")
    print(f"  Cursor type: {scalars.get('Cursor Type', '?')} (blink: {scalars.get('Blinking Cursor', '?')})")
    print(f"  Colors:      {len(profile.get('colors', {}))} defined")
