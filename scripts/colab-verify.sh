#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
case "${1:-}" in
  plan)
    shift
    exec python3 "$ROOT/scripts/prepare_colab_job.py" "$@"
    ;;
  run)
    shift
    exec python3 "$ROOT/scripts/run_colab_job.py" "$@"
    ;;
  *)
    cat >&2 <<'EOF'
Usage:
  nanomaid verify plan PROJECT_DIR COMMANDS.json
  nanomaid verify run JOB_ID ARCHIVE_SHA256 --free-confirmed

Plan prints an archive manifest; review it before approving a `run` shell request.
Only argv arrays are accepted; command strings are never run through a shell.
EOF
    exit 2
    ;;
esac
