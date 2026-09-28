#!/usr/bin/env bash
set -euo pipefail

HOME_DIR="${HOME:-/home/ubuntu}"
XDG_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME_DIR/.config}"
ROOT="${NANOMAID_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}"
OPENCODE_CONFIG_DIR="$XDG_CONFIG_DIR/opencode"
NODE_BIN="$HOME_DIR/.local/opt/node-v24.21.0/bin/node"
APP_DIR="$HOME_DIR/.local/share/nanomaid/app"
COLAB_BIN="$HOME_DIR/.local/share/nanomaid/colab-venv/bin/colab"
UV_BIN="$HOME_DIR/.local/share/nanomaid/tools/uv-0.12.19/uv"
BOT_HOME="$HOME_DIR/.config/opencode-telegram-bot"
BOT_ENV="$BOT_HOME/.env"
SERVICE="nanomaid.service"
SERVICE_FILE="$HOME_DIR/.config/systemd/user/$SERVICE"
COLAB_SKILL_SOURCE="$ROOT/skills/colab/SKILL.md"
COLAB_SKILL_TARGET="$OPENCODE_CONFIG_DIR/skills/colab/SKILL.md"
AGENTS_TARGET="$OPENCODE_CONFIG_DIR/AGENTS.md"
OPENCODE_CONFIG="$OPENCODE_CONFIG_DIR/opencode.json"
MODE="${1:-all}"
failed=0
needs_installer=0
repair_blocked=0
installer_reasons=()

usage() {
  cat <<'EOF'
NanoMaid doctor [--require-config]

Checks prerequisites and safe config state, repairs bot config permissions,
and asks before running the installer for pinned-tool or global-config repairs.
It never uses sudo or starts/enables nanomaid.service.
EOF
}

case "$MODE" in
  all|--require-config) ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

pass() { printf 'PASS: %s\n' "$1"; }
warn() { printf 'WAIT: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; failed=1; }
request_installer() {
  needs_installer=1
  installer_reasons+=("$1")
}

if [[ ! -x "$NODE_BIN" ]] || [[ "$("$NODE_BIN" --version 2>/dev/null || true)" != v24.21.0 ]]; then
  request_installer 'pinned Node.js 24.21.0 is missing or differs'
fi
if [[ ! -x "$APP_DIR/node_modules/.bin/opencode-telegram" ]]; then
  request_installer 'Telegram wrapper is missing'
fi
if [[ ! -x "$COLAB_BIN" ]] || ! "$COLAB_BIN" version 2>/dev/null | grep -q '0.7.4'; then
  request_installer 'pinned Colab CLI 0.7.4 is missing or differs'
fi
if [[ ! -x "$UV_BIN" ]] || [[ "$("$UV_BIN" --version 2>/dev/null || true)" != 'uv 0.12.19 (x86_64-unknown-linux-gnu)' ]]; then
  request_installer 'pinned uv 0.12.19 is missing or differs'
fi
if [[ ! -f "$COLAB_SKILL_SOURCE" || ! -f "$COLAB_SKILL_TARGET" ]] || ! cmp -s "$COLAB_SKILL_SOURCE" "$COLAB_SKILL_TARGET"; then
  if [[ -L "$COLAB_SKILL_TARGET" ]]; then
    repair_blocked=1
  else
    request_installer 'global Colab skill is missing or differs'
  fi
fi
if [[ -L "$AGENTS_TARGET" || -L "$OPENCODE_CONFIG" || -L "$BOT_ENV" || -L "$SERVICE_FILE" ]]; then
  repair_blocked=1
fi
if [[ -e "$BOT_ENV" && ! -f "$BOT_ENV" ]]; then
  repair_blocked=1
fi
if [[ ! -L "$AGENTS_TARGET" ]] && ! python3 "$ROOT/scripts/merge_agents.py" check \
    --target "$AGENTS_TARGET" --template "$ROOT/templates/AGENTS.nanomaid.md" >/dev/null 2>&1; then
  request_installer 'global NanoMaid AGENTS block is missing or differs'
fi
if [[ ! -L "$OPENCODE_CONFIG" ]] && ! python3 "$ROOT/scripts/merge_opencode_config.py" --verify >/dev/null 2>&1; then
  request_installer 'global OpenCode shell/edit ask policy is missing or differs'
fi
if [[ ! -e "$BOT_ENV" && ! -L "$BOT_ENV" ]]; then
  request_installer 'bot config template is missing'
fi
if [[ ! -e "$SERVICE_FILE" && ! -L "$SERVICE_FILE" ]]; then
  request_installer 'user service unit is missing'
fi

if (( needs_installer )); then
  printf 'Doctor found installer repairs:\n'
  printf '  - %s\n' "${installer_reasons[@]}"
  if (( repair_blocked )); then
    fail 'installer repair blocked by a symlinked config target; inspect it manually'
  elif [[ -t 0 && -t 1 ]]; then
    cat <<'EOF'
Running the installer may download/synchronize pinned tools, update global
OpenCode shell/edit permissions and Colab skill/AGENTS files (with backups),
reload OpenCode config, and prepare/reload the disabled user service. It will
not use sudo or start/enable the bot service.
EOF
    read -r -p 'Run ./install.sh now? [y/N] ' answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      if ! "$ROOT/install.sh"; then
        fail 'installer stopped; review its output and resolve the reported issue'
      fi
    else
      warn 'installer repair skipped; run ./install.sh after reviewing the changes'
      failed=1
    fi
  else
    warn 'installer repair needs interactive confirmation; run ./install.sh after reviewing the changes'
    failed=1
  fi
fi

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

if [[ -f "$COLAB_SKILL_SOURCE" && -f "$COLAB_SKILL_TARGET" ]] && cmp -s "$COLAB_SKILL_SOURCE" "$COLAB_SKILL_TARGET"; then
  pass 'global Colab skill matches NanoMaid source'
else
  fail 'global Colab skill missing or differs from NanoMaid source'
fi

if python3 "$ROOT/scripts/merge_agents.py" check \
    --target "$AGENTS_TARGET" \
    --template "$ROOT/templates/AGENTS.nanomaid.md" >/dev/null; then
  pass 'global AGENTS.md contains the NanoMaid managed block'
else
  fail 'global AGENTS.md NanoMaid managed block missing or differs'
fi

if [[ -x "$UV_BIN" ]] && "$UV_BIN" --version | grep -q '0.12.19'; then
  pass 'pinned uv 0.12.19 installed'
else
  fail 'pinned uv 0.12.19 missing'
fi

if [[ -L "$BOT_ENV" ]]; then
  fail 'bot config is a symlink; refusing to inspect or change its target'
elif [[ -e "$BOT_ENV" ]]; then
  if [[ ! -f "$BOT_ENV" ]]; then
    fail 'bot config is not a regular file; refusing to change it'
  else
    mode="$(stat -c '%a' "$BOT_ENV")"
    if [[ "$mode" != 600 ]]; then
      if chmod 600 "$BOT_ENV"; then
        printf 'FIX: bot config permissions changed from %s to 0600\n' "$mode"
        mode=600
      else
        fail 'could not set bot config permissions to 0600'
      fi
    fi
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
  fi
else
  warn 'bot credentials not configured; run nanomaid configure in a local terminal'
  [[ "$MODE" == --require-config ]] && failed=1
fi

local_commands="$BOT_HOME/local-commands"
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
  warn 'nanomaid.service not active; after foreground test run nanomaid enable'
fi

if (( failed == 0 )); then
  exit 0
fi
exit 1
