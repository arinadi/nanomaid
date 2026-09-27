#!/usr/bin/env bash
set -euo pipefail

HOME_DIR="${HOME:-/home/ubuntu}"
NODE_BIN="$HOME_DIR/.local/opt/node-v24.21.0/bin/node"
APP_DIR="$HOME_DIR/.local/share/nanomaid/app"
COLAB_BIN="$HOME_DIR/.local/share/nanomaid/colab-venv/bin/colab"
UV_BIN="$HOME_DIR/.local/share/nanomaid/tools/uv-0.12.19/uv"
BOT_ENV="$HOME_DIR/.config/opencode-telegram-bot/.env"
SERVICE="nanomaid.service"
MODE="${1:-all}"
failed=0

pass() { printf 'PASS: %s\n' "$1"; }
warn() { printf 'WAIT: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; failed=1; }

if [[ -r /etc/os-release ]] && grep -q '^VERSION_ID="26.04"$' /etc/os-release; then
  pass 'Ubuntu 26.04'
else
  fail 'Requires Ubuntu 26.04'
fi

if command -v opencode >/dev/null 2>&1 && opencode --version 2>&1 | grep -q 'v2\.'; then
  pass 'OpenCode V2 installed'
else
  fail 'OpenCode V2 not found'
fi

if [[ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || true)" == yes ]]; then
  pass 'systemd user lingering enabled'
else
  fail 'systemd user lingering is disabled'
fi

available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
if [[ "$available_kib" =~ ^[0-9]+$ ]] && (( available_kib >= 153600 )); then
  pass "RAM headroom ${available_kib} KiB (minimum 153600 KiB)"
else
  fail "RAM headroom ${available_kib:-unknown} KiB is below 150 MiB"
fi

if opencode service status 2>&1 | grep -q '^http://127\.0\.0\.1:'; then
  pass 'OpenCode service is loopback-only'
else
  fail 'OpenCode service is not reporting a loopback endpoint'
fi

if [[ -x "$NODE_BIN" ]] && [[ "$($NODE_BIN --version)" == v24.21.0 ]]; then
  pass 'pinned Node 24.21.0 installed'
else
  fail 'pinned Node 24.21.0 missing'
fi

if [[ -x "$APP_DIR/node_modules/.bin/opencode-telegram" ]]; then
  pass 'Telegram wrapper installed'
else
  fail 'Telegram wrapper missing'
fi

if [[ -x "$COLAB_BIN" ]] && "$COLAB_BIN" version 2>/dev/null | grep -q '0.7.4'; then
  pass 'pinned Colab CLI 0.7.4 installed'
else
  fail 'Colab CLI 0.7.4 missing'
fi

if [[ -x "$UV_BIN" ]] && "$UV_BIN" --version | grep -q '0.12.19'; then
  pass 'pinned uv 0.12.19 installed'
else
  fail 'pinned uv 0.12.19 missing'
fi

if [[ -e "$BOT_ENV" ]]; then
  mode="$(stat -c '%a' "$BOT_ENV")"
  [[ "$mode" == 600 ]] && pass 'bot config permissions are 0600' || fail "bot config permissions are $mode, expected 600"
  if [[ "$MODE" == --require-config ]]; then
    for key in TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USER_ID OPENCODE_SERVER_PASSWORD; do
      if grep -Eq "^${key}=.+$" "$BOT_ENV"; then
        pass "$key configured (value hidden)"
      else
        fail "$key missing (value hidden)"
      fi
    done
  fi
else
  warn 'bot credentials not configured; run nanomaid configure in a local terminal'
  [[ "$MODE" == --require-config ]] && failed=1
fi

local_commands="$HOME_DIR/.config/opencode-telegram-bot/local-commands"
if [[ -d "$local_commands" ]] && find "$local_commands" -maxdepth 1 -type f -name '*.json' -print -quit | grep -q .; then
  fail 'custom host-shell local commands exist; inspect them before enabling NanoMaid'
else
  pass 'no custom host-shell local commands configured'
fi

if ! python3 "$(dirname -- "${BASH_SOURCE[0]}")/scripts/merge_opencode_config.py" --verify >/dev/null; then
  fail 'global OpenCode shell/edit ask policy missing or config requires manual merge'
else
  pass 'global OpenCode shell/edit ask policy verified'
fi

if systemctl --user is-active --quiet "$SERVICE"; then
  pass 'nanomaid.service active'
else
  warn 'nanomaid.service not active'
fi

(( failed == 0 ))
