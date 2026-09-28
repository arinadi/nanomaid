#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
HOME_DIR="${HOME:-/home/ubuntu}"
XDG_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME_DIR/.config}"
USER_NAME="$(id -un)"
OPENCODE_BIN="$(command -v opencode 2>/dev/null || echo "$HOME_DIR/.opencode/bin/opencode")"
MODE="${1:-install}"
source "$ROOT/versions.env"

NODE_DIR="$HOME_DIR/.local/opt/node-v${NODE_VERSION}"
NODE_BIN="$NODE_DIR/bin"
CACHE_DIR="$HOME_DIR/.cache/nanomaid"
STATE_DIR="$HOME_DIR/.local/share/nanomaid"
APP_DIR="$STATE_DIR/app"
COLAB_VENV="$STATE_DIR/colab-venv"
COLAB_HOME="$STATE_DIR/colab-home"
UV_DIR="$STATE_DIR/tools/uv-${UV_VERSION}"
BOT_HOME="$HOME_DIR/.config/opencode-telegram-bot"
LOCAL_BIN="$HOME_DIR/.local/bin"
SERVICE_DIR="$HOME_DIR/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/nanomaid.service"
OPENCODE_CONFIG_DIR="$XDG_CONFIG_DIR/opencode"

die() { printf 'NanoMaid installer: %s\n' "$*" >&2; exit 1; }
say() { printf 'NanoMaid installer: %s\n' "$*"; }

preflight() {
  [[ "$USER_NAME" != root ]] || die 'Run as the normal user, not root.'
  [[ -r /etc/os-release ]] || die 'Cannot read /etc/os-release.'
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 26.04 ]] || die 'Supported target is Ubuntu 26.04 only.'
  command -v opencode >/dev/null || die 'OpenCode V2 must already be installed.'
  opencode --version 2>&1 | grep -q 'v2\.' || die 'OpenCode V2 is required.'
  local endpoint
  endpoint="$(opencode service status 2>&1)" || die 'OpenCode service is not healthy.'
  [[ "$endpoint" == http://127.0.0.1:* ]] || die 'OpenCode must remain bound to 127.0.0.1.'
  [[ "$(loginctl show-user "$USER_NAME" -p Linger --value 2>/dev/null || true)" == yes ]] || die 'User lingering must already be enabled; the installer will not run sudo.'
  local available_kib
  available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
  [[ "$available_kib" =~ ^[0-9]+$ ]] || die 'Cannot read available memory.'
  (( available_kib >= 153600 )) || die "Only ${available_kib} KiB RAM available; minimum is 153600 KiB."
  for command_name in curl tar sha256sum python3 git systemctl; do
    command -v "$command_name" >/dev/null || die "Required command missing: $command_name"
  done
  python3 "$ROOT/scripts/merge_opencode_config.py" --check >/dev/null || die 'OpenCode config needs a safe manual merge; no files changed.'
}

case "$MODE" in
  --dry-run)
    preflight
    cat <<EOF
Dry run only; no changes made.
  Would install Node.js ${NODE_VERSION}, uv ${UV_VERSION}, Telegram wrapper ${TELEGRAM_WRAPPER_VERSION}, and Colab CLI ${COLAB_CLI_VERSION} under user-local paths.
  Would prepare bot config with mode 0600, global OpenCode shell/edit ask rules, Colab skill, NanoMaid AGENTS block, and nanomaid.service.
Would not enter credentials, authenticate Google, enable/start the service, change lingering, or open a port.
EOF
    exit 0
    ;;
  --check)
    exec "$ROOT/check.sh"
    ;;
  install)
    ;;
  *) die 'Usage: ./install.sh [--dry-run|--check]' ;;
esac

preflight
[[ -f "$ROOT/package-lock.json" ]] || die 'Pinned package-lock.json is missing.'
[[ -f "$ROOT/requirements-colab.lock" ]] || die 'Pinned requirements-colab.lock is missing.'

install -d -m 700 "$CACHE_DIR" "$HOME_DIR/.local/opt" "$STATE_DIR" "$APP_DIR" "$LOCAL_BIN" "$SERVICE_DIR" "$COLAB_HOME" "$BOT_HOME"

if [[ -x "$NODE_BIN/node" ]]; then
  [[ "$($NODE_BIN/node --version)" == "v${NODE_VERSION}" ]] || die "A different Node is already installed at $NODE_DIR; refusing to overwrite."
else
  archive="$CACHE_DIR/$NODE_ARCHIVE"
  if [[ ! -f "$archive" ]]; then
    say "Downloading official Node.js ${NODE_VERSION} archive."
    curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
      "https://nodejs.org/dist/v${NODE_VERSION}/${NODE_ARCHIVE}" -o "$archive"
  fi
  printf '%s  %s\n' "$NODE_SHA256" "$archive" | sha256sum --check --status || die 'Node archive checksum mismatch.'
  temp_dir="$HOME_DIR/.local/opt/.nanomaid-node-${NODE_VERSION}-$$"
  mkdir -m 700 "$temp_dir"
  tar -xJf "$archive" --strip-components=1 -C "$temp_dir"
  [[ -x "$temp_dir/bin/node" ]] || die 'Node archive did not contain the expected binary.'
  mv "$temp_dir" "$NODE_DIR"
fi

export PATH="$NODE_BIN:$LOCAL_BIN:$HOME_DIR/.opencode/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
"$NODE_BIN/node" --version | grep -q "^v${NODE_VERSION}$" || die 'Unexpected installed Node version.'

UV_WHEEL="$CACHE_DIR/$UV_WHEEL_FILE"
if [[ ! -f "$UV_DIR/uv" ]]; then
  if [[ ! -f "$UV_WHEEL" ]]; then
    say "Downloading pinned uv ${UV_VERSION} wheel."
    curl --fail --location --retry 3 --proto '=https' --tlsv1.2 "$UV_WHEEL_URL" -o "$UV_WHEEL"
  fi
  python3 "$ROOT/scripts/bootstrap_uv.py" "$UV_WHEEL" "$UV_VERSION" "$UV_WHEEL_SHA256" "$UV_DIR"
fi
"$UV_DIR/uv" --version | grep -q "${UV_VERSION}" || die 'Unexpected uv version.'

if [[ -f "$APP_DIR/package.json" ]] && ! cmp -s "$ROOT/package.json" "$APP_DIR/package.json"; then
  die "Existing app manifest differs at $APP_DIR; inspect before updating."
fi
install -m 644 "$ROOT/package.json" "$APP_DIR/package.json"
install -m 644 "$ROOT/package-lock.json" "$APP_DIR/package-lock.json"
if [[ -x "$APP_DIR/node_modules/.bin/opencode-telegram" ]] && \
   [[ "$("$NODE_BIN/node" -p "require('$APP_DIR/package.json').dependencies['@grinev/opencode-telegram-bot']" 2>/dev/null)" == "$TELEGRAM_WRAPPER_VERSION" ]]; then
  say "Telegram wrapper ${TELEGRAM_WRAPPER_VERSION} already installed; skipping npm ci."
else
  say "Installing Telegram wrapper ${TELEGRAM_WRAPPER_VERSION} from the pinned lockfile (lifecycle scripts disabled; bundled SQLite prebuild is used)."
  (cd "$APP_DIR" && NODE_OPTIONS=--max-old-space-size=256 "$NODE_BIN/npm" ci --omit=dev --ignore-scripts --no-audit --no-fund)
fi

if [[ ! -x "$COLAB_VENV/bin/python" ]]; then
  "$UV_DIR/uv" venv "$COLAB_VENV" --python "$(command -v python3)"
fi
"$UV_DIR/uv" pip sync --python "$COLAB_VENV/bin/python" "$ROOT/requirements-colab.lock"

if [[ -e "$LOCAL_BIN/nanomaid" && ! -L "$LOCAL_BIN/nanomaid" ]]; then
  die "$LOCAL_BIN/nanomaid exists and is not a symlink; refusing to overwrite."
fi
ln -sfn "$ROOT/bin/nanomaid" "$LOCAL_BIN/nanomaid"
chmod 755 "$ROOT/bin/nanomaid" "$ROOT/install.sh" "$ROOT/check.sh" "$ROOT/uninstall.sh" "$ROOT/scripts/colab-verify.sh"

install -d -m 700 "$BOT_HOME"
if [[ ! -e "$BOT_HOME/.env" ]]; then
  install -m 600 "$ROOT/templates/model.env" "$BOT_HOME/.env"
else
  chmod 600 "$BOT_HOME/.env"
fi

python3 "$ROOT/scripts/merge_opencode_config.py"
[[ -x "$OPENCODE_BIN" ]] || die "OpenCode binary not found at $OPENCODE_BIN."
"$OPENCODE_BIN" api post /api/location/reload >/dev/null
python3 "$ROOT/scripts/merge_opencode_config.py" --verify
skill_dir="$OPENCODE_CONFIG_DIR/skills/colab"
install -d -m 700 "$skill_dir"
skill_target="$skill_dir/SKILL.md"
if [[ -e "$skill_target" ]] && ! cmp -s "$ROOT/skills/colab/SKILL.md" "$skill_target"; then
  installed_skill_sha256="$(sha256sum "$skill_target" | awk '{print $1}')"
  case "$installed_skill_sha256" in
    e2454ca59cc3462fd450257694c9806e80f54134f9a487ca6d58c992abf4ea5a|\
    1cdb4672d66c5eb1fe694822debae3cc7ea667e11a9a00b473458fd8253b655e|\
    c807e23f50ba3f9956cc3d8e269c2f34701587b5e8ca7c398595e7a050bbef20)
      ;;
    *)
    die "An existing Colab skill differs at $skill_target and is not the known prior NanoMaid version; refusing to overwrite."
      ;;
  esac
fi
install -m 600 "$ROOT/skills/colab/SKILL.md" "$skill_target"
python3 "$ROOT/scripts/merge_agents.py" install \
  --target "$OPENCODE_CONFIG_DIR/AGENTS.md" \
  --template "$ROOT/templates/AGENTS.nanomaid.md"
"$OPENCODE_BIN" api post /api/location/reload >/dev/null

python3 - "$ROOT/templates/nanomaid.service.in" "$SERVICE_FILE" "$USER_NAME" "$HOME_DIR" "$NODE_BIN" "$LOCAL_BIN" <<'PY'
import os
import sys
from pathlib import Path

source, target, user, home, node_bin, local_bin = sys.argv[1:]
template = Path(source).read_text(encoding="utf-8")
rendered = (template.replace("@USER@", user).replace("@HOME@", home)
            .replace("@NODE_BIN@", node_bin).replace("@LOCAL_BIN@", local_bin)
            .replace("@NANOMAID_BIN@", f"{local_bin}/nanomaid")
            .replace("@BOT_HOME@", f"{home}/.config/opencode-telegram-bot"))
target_path = Path(target)
target_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
if target_path.exists() and target_path.read_text(encoding="utf-8") != rendered:
    raise SystemExit(f"Existing service unit differs: {target_path}; refusing to overwrite.")
target_path.write_text(rendered, encoding="utf-8")
os.chmod(target_path, 0o600)
PY

systemctl --user daemon-reload
say 'Installation files prepared. Service remains disabled until credentials are entered and foreground tests pass.'
say 'In a local terminal, run: ~/.local/bin/nanomaid configure'
say 'Then test with: ~/.local/bin/nanomaid start'
say 'After memory and Telegram checks, enable with: ~/.local/bin/nanomaid enable'
