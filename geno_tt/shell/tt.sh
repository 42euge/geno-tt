# geno-tt shell layer — the interactive `tt` function + iTerm hooks.
#
# Source this from your shell profile (geno_tt/scripts/bootstrap.sh adds the
# line for you). It provides the interactive `tt` function — the only piece of
# tt that must live in the shell, because a Python process can't change its
# parent shell's directory or install chpwd hooks:
#
#   1. `cd` into a session/workspace/worktree — `tt` writes the cd
#      command to $TT_EXEC_FILE; this function sources it.
#   2. iTerm2 tab-tinting by track + CWD reporting — chpwd / PROMPT_COMMAND hooks.
#
# Everything else works without this file: just call the `tt` binary directly.

# Config home.
_TT_CONFIG="${HOME}/.geno/tt/config.toml"

_TT_PYTHON=python3
for _v in python3.13 python3.12 python3.11; do
    if command -v "$_v" &>/dev/null; then _TT_PYTHON="$_v"; break; fi
done

tt() {
    local TT_EXEC_FILE="/tmp/.tt_exec_$$"

    TT_EXEC_FILE="$TT_EXEC_FILE" command tt "$@"
    local tt_exit=$?

    if [[ -f "$TT_EXEC_FILE" ]]; then
        source "$TT_EXEC_FILE"
        rm -f "$TT_EXEC_FILE"
        # Reset iTerm2 tab metadata after a session ends
        if [[ "$TERM_PROGRAM" == "iTerm.app" ]]; then
            printf '\e]6;1;bg;*;default\a'
            printf '\e]1337;SetBadgeFormat=\a'
            printf '\e]1337;SetUserVar=ttTitle\a'
        fi
    fi

    return $tt_exit
}

ttui() { tt tui "$@"; }
tti()  { tt repos -i "$@"; }

# iTerm2 integration: CWD reporting + workspace tab colors by track.
if [[ "$TERM_PROGRAM" == "iTerm.app" ]]; then
    _tt_iterm2_report_cwd() { printf '\e]1337;CurrentDir=%s\a' "$PWD"; }

    _tt_iterm2_set_tab_color() {
        printf '\e]6;1;bg;red;brightness;%d\a' "$1"
        printf '\e]6;1;bg;green;brightness;%d\a' "$2"
        printf '\e]6;1;bg;blue;brightness;%d\a' "$3"
    }

    _tt_iterm2_clear_tab_color() { printf '\e]6;1;bg;*;default\a'; }

    # Load base theme, tab colors, workspace themes, and track colors from config.
    eval "$("$_TT_PYTHON" -c "
import tomllib, sys
from pathlib import Path
cfg = Path('${_TT_CONFIG}')
if not cfg.exists(): sys.exit(0)
with open(cfg, 'rb') as f: c = tomllib.load(f)
bt = c.get('base_theme', '')
if bt: print(f'_TT_BASE_THEME={chr(34)}{bt}{chr(34)}')
colors = [f'{n}={r[0]},{r[1]},{r[2]}' for n, r in c.get('tab_colors', {}).items()]
print(f'_TT_TAB_COLORS={chr(34)}{chr(10).join(colors)}{chr(34)}')
themes = [f'{n}={t}' for n, t in c.get('workspace_themes', {}).items()]
print(f'_TT_WORKSPACE_THEMES={chr(34)}{chr(10).join(themes)}{chr(34)}')
tcolors = [f'{n}={r[0]},{r[1]},{r[2]}' for n, r in c.get('track_colors', {}).items()]
print(f'_TT_TRACK_COLORS={chr(34)}{chr(10).join(tcolors)}{chr(34)}')
" 2>/dev/null)"

    _tt_iterm2_apply_theme_live() {
        "$_TT_PYTHON" -m geno_tt.themes --apply-live "$1" 2>/dev/null
    }

    _tt_iterm2_workspace_theme() {
        local _matched=0
        local _name _val _r _g _b

        # New scheme: tint by track segment in ~/code/<track>/...
        if [[ -n "$_TT_TRACK_COLORS" && "$PWD" == *"/code/"* ]]; then
            local _track="${PWD##*/code/}"
            _track="${_track%%/*}"
            while IFS='=' read -r _name _val; do
                [[ -z "$_name" ]] && continue
                if [[ "$_track" == "$_name" ]]; then
                    IFS=',' read -r _r _g _b <<< "$_val"
                    _tt_iterm2_set_tab_color "$_r" "$_g" "$_b"
                    _matched=1
                    break
                fi
            done <<< "$_TT_TRACK_COLORS"
        fi

        # Workspace theme assignments (full color scheme)
        if [[ $_matched -eq 0 && -n "$_TT_WORKSPACE_THEMES" ]]; then
            while IFS='=' read -r _name _val; do
                [[ -z "$_name" ]] && continue
                if [[ "$PWD" == *"/code/$_name/"* || "$PWD" == *"/code/$_name" ]]; then
                    _tt_iterm2_apply_theme_live "$_val"
                    _matched=1
                    break
                fi
            done <<< "$_TT_WORKSPACE_THEMES"
        fi

        # Fall back to tab colors (just tint)
        if [[ $_matched -eq 0 && -n "$_TT_TAB_COLORS" ]]; then
            while IFS='=' read -r _name _val; do
                [[ -z "$_name" ]] && continue
                if [[ "$PWD" == *"/code/$_name/"* || "$PWD" == *"/code/$_name" ]]; then
                    IFS=',' read -r _r _g _b <<< "$_val"
                    _tt_iterm2_set_tab_color "$_r" "$_g" "$_b"
                    _matched=1
                    break
                fi
            done <<< "$_TT_TAB_COLORS"
        fi

        # Revert to base theme when outside any workspace
        if [[ $_matched -eq 0 ]]; then
            [[ -n "$_TT_BASE_THEME" ]] && _tt_iterm2_apply_theme_live "$_TT_BASE_THEME"
            _tt_iterm2_clear_tab_color
        fi
    }

    _tt_iterm2_hook() {
        _tt_iterm2_report_cwd
        _tt_iterm2_workspace_theme
    }

    if [[ -n "$ZSH_VERSION" ]]; then
        chpwd_functions+=(_tt_iterm2_hook)
    else
        _tt_orig_prompt_command="${PROMPT_COMMAND}"
        PROMPT_COMMAND="_tt_iterm2_hook${_tt_orig_prompt_command:+;$_tt_orig_prompt_command}"
    fi

    [[ -n "$_TT_BASE_THEME" ]] && _tt_iterm2_apply_theme_live "$_TT_BASE_THEME"
    _tt_iterm2_hook
fi
