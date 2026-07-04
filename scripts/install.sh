#!/usr/bin/env bash
# install.sh — set up toolbox-web as a persistent user service on Fedora
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# This script lives in toolbox-web/scripts/ — the project root is one level up.
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: 'uv' is not installed or not on PATH." >&2
    echo "       Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

echo "==> Syncing Python environment (uv, pinned to Python 3.14)..."
# Creates/updates $PROJECT_DIR/.venv from pyproject.toml + uv.lock.
( cd "$PROJECT_DIR" && uv sync )

# Seed a local .env from the template on first install (host/port etc. live here).
if [ ! -f "$PROJECT_DIR/.env" ] && [ -f "$PROJECT_DIR/.env.example" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "==> Created .env from .env.example — edit it to change host/port/token."
fi

# Seed the live config from the sanitized *.example files (paths/keys/model list
# live here and are git-ignored). Never clobber a file the user already has.
for example in "$PROJECT_DIR"/config/*.example; do
    [ -e "$example" ] || continue          # no examples present → skip
    target="${example%.example}"
    if [ ! -f "$target" ]; then
        cp "$example" "$target"
        echo "==> Created ${target#"$PROJECT_DIR"/} from $(basename "$example") — edit it before use."
    fi
done

echo "==> Installing systemd user service..."
mkdir -p "$HOME/.config/systemd/user"
cp "$PROJECT_DIR/toolbox-web.service" "$HOME/.config/systemd/user/toolbox-web.service"

# Fix the WorkingDirectory in case toolbox-web is not in ~/toolbox-web
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$PROJECT_DIR|" \
    "$HOME/.config/systemd/user/toolbox-web.service"

echo "==> Installing file-watch auto-restart units..."
cp "$PROJECT_DIR/toolbox-web-watch.path"    "$HOME/.config/systemd/user/toolbox-web-watch.path"
cp "$PROJECT_DIR/toolbox-web-watch.service" "$HOME/.config/systemd/user/toolbox-web-watch.service"
# Substitute placeholder paths with the actual install location
sed -i "s|TOOLBOX_WEB_TEMPLATES_DIR|$PROJECT_DIR/templates|g" \
    "$HOME/.config/systemd/user/toolbox-web-watch.path"
sed -i "s|TOOLBOX_WEB_DIR|$PROJECT_DIR|g" \
    "$HOME/.config/systemd/user/toolbox-web-watch.path"

systemctl --user daemon-reload
systemctl --user enable --now toolbox-web.service
systemctl --user enable --now toolbox-web-watch.path

# Allow the service to survive after you log out (linger)
loginctl enable-linger "$USER" 2>/dev/null && \
    echo "==> Linger enabled (service survives logout)" || \
    echo "    (Could not enable linger — run: sudo loginctl enable-linger $USER)"

echo ""
echo "==> Done! Service status:"
systemctl --user status toolbox-web.service --no-pager

IP=$(hostname -I | awk '{print $1}')
echo ""
echo "  Open: http://${IP}:5000"
echo ""
echo "Useful commands:"
echo "  systemctl --user status  toolbox-web"
echo "  systemctl --user restart toolbox-web"
echo "  systemctl --user stop    toolbox-web"
echo "  journalctl --user -u toolbox-web -f"

# Firewall hint
if command -v firewall-cmd &>/dev/null; then
    if ! firewall-cmd --list-ports --quiet 2>/dev/null | grep -q "5000/tcp"; then
        echo ""
        echo "  NOTE: To allow access from other machines:"
        echo "  sudo firewall-cmd --add-port=5000/tcp --permanent && sudo firewall-cmd --reload"
    fi
fi
