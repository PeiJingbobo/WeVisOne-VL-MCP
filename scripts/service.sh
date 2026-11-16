#!/usr/bin/env bash
# Register the WeVisOne-VL MCP server as a systemd service so it starts with the OS.
#
#   ./scripts/service.sh install            # per-user unit (no root) + enable-linger
#   ./scripts/service.sh install --system   # system-wide unit (needs root)
#   ./scripts/service.sh status
#   ./scripts/service.sh uninstall
#
# Environment overrides (all optional):
#   WEVISONE_PYTHON   interpreter (default: <project>/.venv/bin/python, else python3)
#   WEVISONE_PROJECT  project directory (default: parent of this script's folder)
#   WEVISONE_HOST     bind host        (default: 0.0.0.0)
#   WEVISONE_PORT     bind port        (default: 8000)
#   WEVISONE_TOKEN_FILE  token file    (default: <project>/.token)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${WEVISONE_PROJECT:-$(dirname "$SCRIPT_DIR")}"
HOST="${WEVISONE_HOST:-0.0.0.0}"
PORT="${WEVISONE_PORT:-8000}"
TOKEN_FILE="${WEVISONE_TOKEN_FILE:-$PROJECT/.token}"
UNIT_NAME="wevisone-mcp"

die() { echo "error: $*" >&2; exit 1; }

resolve_python() {
    if [[ -n "${WEVISONE_PYTHON:-}" ]]; then
        echo "$WEVISONE_PYTHON"
    elif [[ -x "$PROJECT/.venv/bin/python" ]]; then
        echo "$PROJECT/.venv/bin/python"
    else
        command -v python3 || die "no python3 found; set WEVISONE_PYTHON"
    fi
}

require_systemd() {
    command -v systemctl >/dev/null 2>&1 || die "systemctl not found: this host has no systemd"
}

# Writes the env file shared by both unit flavours (mode 0600 — it may hold a path
# to a secret, and the file itself is never readable by others).
write_env_file() {
    local target="$1"
    mkdir -p "$(dirname "$target")"
    if [[ -f "$TOKEN_FILE" ]]; then
        cat >"$target" <<EOF
WEVISONE_MCP_HOST=$HOST
WEVISONE_MCP_PORT=$PORT
WEVISONE_MCP_TOKEN_FILE=$TOKEN_FILE
EOF
    else
        cat >"$target" <<EOF
WEVISONE_MCP_HOST=$HOST
WEVISONE_MCP_PORT=$PORT
EOF
    fi
    chmod 600 "$target"
}

unit_body() {
    local python="$1"
    cat <<EOF
[Unit]
Description=WeVisOne-VL perception MCP server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT
EnvironmentFile=$2
ExecStart=$python -u -m wevisone_mcp.server
Restart=always
RestartSec=5
# the model preload happens before the port binds; do not time out too early
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
EOF
}

install_user() {
    local python unit_dir env_file
    python="$(resolve_python)"
    unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    env_file="${XDG_CONFIG_HOME:-$HOME/.config}/$UNIT_NAME.env"
    mkdir -p "$unit_dir"
    write_env_file "$env_file"
    unit_body "$python" "$env_file" >"$unit_dir/$UNIT_NAME.service"
    systemctl --user daemon-reload
    systemctl --user enable --now "$UNIT_NAME.service"
    # without linger the user manager stops at logout and the service dies with it
    if command -v loginctl >/dev/null 2>&1; then
        loginctl enable-linger "$(id -un)" 2>/dev/null \
            || echo "warning: could not enable-linger; the service stops when you log out"
    fi
    echo "installed user unit: $unit_dir/$UNIT_NAME.service"
    echo "autostart: on (starts at boot via linger, restarts on failure)"
}

install_system() {
    [[ "$(id -u)" -eq 0 ]] || die "--system needs root; re-run with sudo"
    local python env_file="/etc/$UNIT_NAME.env"
    python="$(resolve_python)"
    write_env_file "$env_file"
    unit_body "$python" "$env_file" >"/etc/systemd/system/$UNIT_NAME.service"
    systemctl daemon-reload
    systemctl enable --now "$UNIT_NAME.service"
    echo "installed system unit: /etc/systemd/system/$UNIT_NAME.service"
    echo "autostart: on (starts at boot, runs as root)"
}

uninstall() {
    local scope=user
    if [[ "$1" == "--system" ]]; then
        [[ "$(id -u)" -eq 0 ]] || die "--system needs root; re-run with sudo"
        scope=system
    fi
    systemctl "$scope" disable --now "$UNIT_NAME.service" 2>/dev/null || true
    if [[ "$scope" == system ]]; then
        rm -f "/etc/systemd/system/$UNIT_NAME.service" "/etc/$UNIT_NAME.env"
        systemctl daemon-reload
    else
        rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$UNIT_NAME.service" \
              "${XDG_CONFIG_HOME:-$HOME/.config}/$UNIT_NAME.env"
        systemctl --user daemon-reload
    fi
    echo "uninstalled $scope unit; autostart: off"
}

status() {
    local scope=user
    [[ "$1" == "--system" ]] && scope=system
    require_systemd
    systemctl "$scope" status "$UNIT_NAME.service" --no-pager || true
    echo "---"
    systemctl "$scope" is-enabled "$UNIT_NAME.service" 2>/dev/null \
        | sed 's/^/enabled: /' || echo "enabled: no"
}

main() {
    local action="${1:-}"; shift || true
    require_systemd
    case "$action" in
        install)
            if [[ "${1:-}" == "--system" ]]; then install_system; else install_user; fi
            ;;
        uninstall) uninstall "${1:-}" ;;
        status) status "${1:-}" ;;
        *) echo "usage: $0 {install [--system]|uninstall [--system]|status [--system]}" >&2; exit 2 ;;
    esac
}

main "$@"
