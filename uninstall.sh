#!/usr/bin/env bash
set -euo pipefail
umask 077

HOME_DIR="${HOME:-/home/ubuntu}"
SERVICE="nanomaid.service"
UNIT="$HOME_DIR/.config/systemd/user/$SERVICE"
BIN="$HOME_DIR/.local/bin/nanomaid"

if [[ "${1:-}" != "--confirm" ]]; then
  echo "This stops/removes NanoMaid's user service and launcher only."
  echo "It preserves config/credentials, Colab OAuth, Node, project files, OpenCode data, and user lingering."
  echo "Review, then rerun as: $0 --confirm"
  exit 2
fi

systemctl --user disable --now "$SERVICE" 2>/dev/null || true
if [[ -f "$UNIT" ]]; then rm -- "$UNIT"; fi
if [[ -L "$BIN" && "$(readlink -f -- "$BIN" 2>/dev/null || true)" == "$HOME_DIR/nanomaid/bin/nanomaid" ]]; then
  rm -- "$BIN"
fi
systemctl --user daemon-reload
echo "NanoMaid service disabled. Config, credentials, runtime files, OpenCode data, and lingering were preserved."
