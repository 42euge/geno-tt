---
name: geno-tt-windows-control
description: >-
  Use when listing, previewing, or arranging categorized local macOS windows
  for a TT area or workspace node through Rectangle.
allowed-tools: "Bash(tt windows *), Bash(tt code --sync)"
metadata:
  author: 42euge
  version: "0.9.0"
---

# Arrange categorized windows

TT categorizes live VS Code windows, iTerm tabs, and browser groups by their
dot-notation registry node. The first segment is the logical area: `geno` is
the area for nodes such as `geno.geno-tt`.

1. Run `tt windows status --json`. If control is disabled, stop and tell the
   user to enable it; this skill must not enable itself.
2. Run `tt windows ls [area-or-node] --json`. If expected VS Code windows are
   absent, refresh them once with `tt code --sync`, then list again.
3. Preview with
   `tt windows arrange [area-or-node] --dry-run --json`. Surface any skipped or
   ambiguous target instead of moving a different window.
4. When the user asked to arrange the windows, run the same command without
   `--dry-run`.

Rectangle acts on the frontmost window after TT activates each registered
surface. Treat `dispatched` as acceptance of the Rectangle URL, not proof of
final geometry. Remote surfaces and multiple VS Code windows with the same
workspace locator are intentionally not arranged.
