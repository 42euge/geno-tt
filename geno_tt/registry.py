"""Shared object-notation registry — geno-tt's side (writes the 'iterm' key).

Same file/contract as geno-surf: ~/.geno/workspace.json, nodes keyed by object
path. geno-tt owns each node's `iterm` attachment; geno-surf owns `chrome`.
Neither clobbers the other.
"""

import json
from pathlib import Path

PATH = Path.home() / ".geno" / "workspace.json"


def load() -> dict:
    if PATH.exists():
        try:
            data = json.loads(PATH.read_text())
            data.setdefault("nodes", {})
            return data
        except (ValueError, OSError):
            pass
    return {"nodes": {}}


def save(reg: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n")


def node(reg: dict, path: str) -> dict:
    return reg.setdefault("nodes", {}).setdefault(path, {})
