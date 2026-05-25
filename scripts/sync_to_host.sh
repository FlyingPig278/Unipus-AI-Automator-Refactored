#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/sync_to_host.sh /mnt/c/Users/you/Desktop/Unipus-AI-Automator

Environment:
  SYNC_INTERVAL_SECONDS  Poll interval, default: 2
  SYNC_DELETE            Mirror deletes to destination, default: 1

This is one-way: WSL project -> Windows host folder.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -ne 1 ]]; then
  usage
  exit 0
fi

src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest_dir="$1"
interval="${SYNC_INTERVAL_SECONDS:-2}"
delete_flag="${SYNC_DELETE:-1}"

if ! command -v rsync >/dev/null 2>&1; then
  echo "[sync] ERROR: rsync is required but was not found." >&2
  exit 1
fi

mkdir -p "$dest_dir"

rsync_args=(
  -a
  --human-readable
  --itemize-changes
  --exclude ".git/"
  --exclude ".venv/"
  --exclude "venv/"
  --exclude "__pycache__/"
  --exclude "*.pyc"
  --exclude ".logs/"
  --exclude ".diagnostics/"
  --exclude ".diagnose/"
  --exclude ".models/"
  --exclude ".runtime/"
  --exclude ".playwright-browsers/"
  --exclude ".temp_downloads/"
  --exclude "python-embed/"
  --exclude "*.zip"
)

if [[ "$delete_flag" == "1" || "$delete_flag" == "true" || "$delete_flag" == "True" ]]; then
  rsync_args+=(--delete)
fi

echo "[sync] Source:      $src_dir/"
echo "[sync] Destination: $dest_dir/"
echo "[sync] Interval:    ${interval}s"
echo "[sync] Delete:      $delete_flag"
echo "[sync] Press Ctrl+C to stop."

while true; do
  rsync "${rsync_args[@]}" "$src_dir/" "$dest_dir/"
  sleep "$interval"
done
