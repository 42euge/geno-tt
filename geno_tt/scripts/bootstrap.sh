#!/usr/bin/env bash
# Bootstrap geno-tt at coding-agent session start. Idempotent and quiet
# (output goes to ~/.geno/tt/bootstrap.log, never the agent's stderr).
#
#   1. Self-install the `tt` CLI onto PATH via pipx (falling back to
#      pip --user) if it isn't already there.
#   2. Install the interactive shell layer (the `tt` function + iTerm hooks):
#      refresh ~/.geno/tt/init.sh and add one source line to the user's rc.
#
# Plugin root: Claude Code exports ${CLAUDE_PLUGIN_ROOT}; otherwise resolve from
# this script's own location (geno_tt/scripts/ sits two levels under the root).
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_root="${CLAUDE_PLUGIN_ROOT:-${script_dir%/geno_tt/scripts}}"

state_dir="${HOME}/.geno/tt"
log_file="${state_dir}/bootstrap.log"
mkdir -p "${state_dir}"

# 1. Install the `tt` CLI if absent.
if ! command -v tt >/dev/null 2>&1; then
  if [[ -f "${plugin_root}/pyproject.toml" ]]; then
    {
      echo "[$(date -u +%FT%TZ)] tt not on PATH; installing from ${plugin_root}"
      if command -v pipx >/dev/null 2>&1; then
        pipx install --force "${plugin_root}"
      elif command -v python3 >/dev/null 2>&1; then
        python3 -m pip install --user --quiet "${plugin_root}"
      else
        echo "no pipx or python3 found; cannot self-install the tt CLI"
      fi
    } >>"${log_file}" 2>&1 || true
  fi
fi

# 2. Install the interactive shell layer (stable copy + one rc source line).
tt_shell_src="${plugin_root}/geno_tt/shell/tt.sh"
if [[ -f "${tt_shell_src}" ]]; then
  cp "${tt_shell_src}" "${state_dir}/init.sh" 2>>"${log_file}" || true
  _marker="# geno-tt shell layer"
  for _rc in "${HOME}/.zshrc" "${HOME}/.bashrc"; do
    [[ -f "${_rc}" ]] || continue
    if ! grep -qF "${_marker}" "${_rc}" 2>/dev/null; then
      printf '\n%s\n[ -f "$HOME/.geno/tt/init.sh" ] && source "$HOME/.geno/tt/init.sh"\n' \
        "${_marker}" >> "${_rc}"
    fi
  done
fi

# 3. Keep the workspace-scheme docs current in the global CLAUDE.md.
#    Idempotently (re)writes a marker-delimited "Workspaces" section so every
#    agent session knows the code-org scheme and that geno-ws is deprecated.
#    Fully owned by this hook; user notes outside the markers are preserved.
inject_py="${plugin_root}/geno_tt/scripts/inject_claude_md.py"
if [[ -f "${inject_py}" ]] && command -v python3 >/dev/null 2>&1; then
  python3 "${inject_py}" "${HOME}/.claude/CLAUDE.md" >>"${log_file}" 2>&1 || true
fi
