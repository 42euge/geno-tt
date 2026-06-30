"""iTerm2 integration: detection, escape sequences, AppleScript tab control."""

import base64
import os
import shlex
import subprocess
import sys


def is_iterm2() -> bool:
    """Detect if running inside iTerm2."""
    return bool(
        os.environ.get("ITERM_SESSION_ID")
        or os.environ.get("TERM_PROGRAM") == "iTerm.app"
    )


def get_iterm2_config(config: dict) -> dict:
    """Extract [iterm2] config section with defaults."""
    defaults = {
        "control_mode": False,
        "new_tab": "flag",
        "host_colors": {},
        "badge_format": "",
        "title_format": "{host}: {ws}",
    }
    iterm_cfg = config.get("iterm2", {})
    return {**defaults, **iterm_cfg}


def should_use_control_mode(config: dict, cli_flag: bool | None = None) -> bool:
    """Determine if tmux -CC should be used.

    Priority: CLI flag (--cc/--no-cc) > config > default (False).
    """
    if cli_flag is not None:
        return cli_flag
    iterm_cfg = get_iterm2_config(config)
    return iterm_cfg.get("control_mode", False)


def should_open_new_tab(config: dict, cli_flag: bool = False) -> bool:
    """Determine if a new iTerm2 tab should be opened."""
    if not is_iterm2():
        return False
    iterm_cfg = get_iterm2_config(config)
    mode = iterm_cfg.get("new_tab", "flag")
    if mode == "always":
        return True
    if mode == "flag":
        return cli_flag
    return False


def emit_pre_connect_sequences(
    config: dict,
    host_alias: str,
    session_name: str,
    folder: str,
) -> list[str]:
    """Return shell printf lines for iTerm2 tab title, badge, and color.

    These are meant to be written into TT_EXEC_FILE before the ssh command.
    """
    if not is_iterm2():
        return []

    iterm_cfg = get_iterm2_config(config)
    context = {"host": host_alias, "session": session_name, "folder": folder, "ws": folder}
    lines = []

    title_fmt = iterm_cfg.get("title_format", "")
    if title_fmt:
        title = title_fmt.format(**context)
        b64_title = base64.b64encode(title.encode()).decode()
        lines.append(f'printf "\\033]1337;SetUserVar=ttTitle={b64_title}\\007"')

    badge_fmt = iterm_cfg.get("badge_format", "")
    if badge_fmt:
        badge = badge_fmt.format(**context)
        b64 = base64.b64encode(badge.encode()).decode()
        lines.append(f'printf "\\033]1337;SetBadgeFormat={b64}\\007"')

    tab_colors = iterm_cfg.get("host_colors", {})
    if host_alias in tab_colors:
        c = tab_colors[host_alias]
        r, g, b = c.get("r", 0), c.get("g", 0), c.get("b", 0)
        lines.append(f'printf "\\033]6;1;bg;red;brightness;{r}\\007"')
        lines.append(f'printf "\\033]6;1;bg;green;brightness;{g}\\007"')
        lines.append(f'printf "\\033]6;1;bg;blue;brightness;{b}\\007"')

    return lines


def open_iterm2_tab(cmd: list[str], local_dir: str | None = None):
    """Open a new iTerm2 tab and execute the command via AppleScript."""
    shell_cmd_parts = []
    if local_dir:
        shell_cmd_parts.append(f"cd {shlex.quote(local_dir)}")
    shell_cmd_parts.append(" ".join(shlex.quote(c) for c in cmd))
    shell_cmd = " && ".join(shell_cmd_parts)

    as_cmd = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')

    applescript = f'''
    tell application "iTerm2"
        tell current window
            create tab with default profile
            tell current session
                write text "{as_cmd}"
            end tell
        end tell
    end tell
    '''
    subprocess.run(["osascript", "-e", applescript], capture_output=True)
