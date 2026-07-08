"""geno-tt — terminal/session + workspace manager for the geno ecosystem.

Standalone CLI (`tt`) + skills. The interactive `tt` shell function (cd + iTerm
hooks) lives in geno_tt/shell/tt.sh and is installed by the bootstrap."""

__version__ = "0.7.0"

from .cli import main

__all__ = ["main", "__version__"]
