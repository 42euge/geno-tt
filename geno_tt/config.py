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
