"""Config loading from ~/.geno/tt/config.toml."""

import tomllib
from pathlib import Path

TT_HOME = Path.home() / ".geno" / "tt"
CONFIG_PATH = TT_HOME / "config.toml"
SESSIONS_DIR = TT_HOME / "sessions"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"default_host": None, "hosts": {}}
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


# --- Workspace tracks -------------------------------------------------------
# A track is the first path segment of the scheme:
#   ~/code/<track>/<domain>/<workspace>.<born>/<repo>
# Tracks are object-notation entries: a name plus its display colors. The
# builtin set below can be extended or overridden from config.toml, e.g.:
#
#   [[tracks]]
#   name = "main"
#   ansi = "green"                 # key into the base ANSI palette
#   hex = { bar = "#14281a", fg = "#a0e0b0" }   # optional; TUI/overlay accent
#
# Any config track with a new name is appended; a config track reusing a
# builtin name overrides that builtin's colors. Order = builtins first, then
# new config tracks in file order (drives display ordering).
DEFAULT_TRACKS = [
    {"name": "main",    "ansi": "green",  "hex": {"bar": "#14281a", "fg": "#a0e0b0"}},
    {"name": "crit",    "ansi": "red",    "hex": {"bar": "#2e1414", "fg": "#e0a0a0"}},
    {"name": "explore", "ansi": "blue",   "hex": {"bar": "#14202e", "fg": "#a0c0e0"}},
    {"name": "chore",   "ansi": "yellow", "hex": {"bar": "#222214", "fg": "#d0d080"}},
    {"name": "side",    "ansi": "purp",   "hex": {"bar": "#141428", "fg": "#a0a0e0"}},
]


def load_tracks(config: dict | None = None) -> list[dict]:
    """Return the ordered list of track objects (builtins merged with config).

    Each entry: {"name": str, "ansi": str, "hex": {"bar": str, "fg": str}}.
    Config `[[tracks]]` entries override a builtin of the same name (merged
    field-wise) or append as new tracks in file order.
    """
    if config is None:
        config = load_config()
    merged: dict[str, dict] = {t["name"]: dict(t) for t in DEFAULT_TRACKS}
    order: list[str] = [t["name"] for t in DEFAULT_TRACKS]
    for entry in config.get("tracks", []) or []:
        name = entry.get("name")
        if not name:
            continue
        if name in merged:
            merged[name] = {**merged[name], **{k: v for k, v in entry.items() if k != "name"}, "name": name}
        else:
            merged[name] = {"name": name, "ansi": entry.get("ansi", "indigo"),
                            "hex": entry.get("hex", {"bar": "#14141e", "fg": "#a0a0c0"})}
            order.append(name)
    return [merged[n] for n in order]


def set_default_host(alias: str):
    """Update default_host in the config file."""
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config file not found: {CONFIG_PATH}")
    text = CONFIG_PATH.read_text()
    import re
    new_text = re.sub(
        r'^default_host\s*=\s*"[^"]*"',
        f'default_host = "{alias}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if new_text == text:
        raise SystemExit(f"Could not find default_host line in {CONFIG_PATH}")
    CONFIG_PATH.write_text(new_text)


def add_host(alias: str, hostname: str):
    """Add a new host to the config file."""
    if not CONFIG_PATH.exists():
        # Create a minimal config
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            f'default_host = "{alias}"\n\n[hosts]\n{alias} = "{hostname}"\n'
        )
        return
    text = CONFIG_PATH.read_text()
    # Check if alias already exists
    import re
    if re.search(rf'^{re.escape(alias)}\s*=', text, flags=re.MULTILINE):
        raise SystemExit(f"Host '{alias}' already exists in config. Edit {CONFIG_PATH} to update it.")
    # Append under [hosts]
    if "[hosts]" in text:
        text = text.rstrip("\n") + f'\n{alias} = "{hostname}"\n'
    else:
        text = text.rstrip("\n") + f'\n\n[hosts]\n{alias} = "{hostname}"\n'
    CONFIG_PATH.write_text(text)


def resolve_host(config: dict, alias: str | None = None) -> tuple[str, str]:
    """Return (alias, hostname). If alias is None, use default."""
    hosts = config.get("hosts", {})
    if alias is None:
        alias = config.get("default_host")
        if alias is None:
            raise SystemExit("No default_host in config and no host specified")
    hostname = hosts.get(alias, alias)
    return alias, hostname
