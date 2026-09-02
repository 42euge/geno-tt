---
name: geno-tt-windows-settings
description: >-
  Use when the user explicitly asks to enable, disable, inspect, or configure
  TT's local macOS window arrangement through Rectangle.
allowed-tools: "Bash(tt windows *)"
metadata:
  author: 42euge
  version: "0.9.0"
---

# Manage window arrangement settings

Start with `tt windows status --json`. Only run `tt windows enable` or
`tt windows disable` when the user explicitly requested that state change.

- Enabling verifies that the host is macOS and Rectangle is installed, then
  persists the policy in the settings file reported by `status`.
- Disabling blocks arrangement but does not quit Rectangle or disable its own
  keyboard shortcuts.
- Missing settings use the built-in `coding` profile without writing a file.
  Enabling or disabling creates the file atomically.

Layout profiles contain named `zones` whose values are validated Rectangle
actions and ordered `rules` with `node`, `surface`, and `zone` fields. Preserve
version `1`, keep the active profile valid, and preview configuration changes
with `tt windows arrange --dry-run --json` before applying a layout.
