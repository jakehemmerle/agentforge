#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 [--submodule-path PATH] [--overlay-dir PATH]

Copies overlay files into the OpenEMR checkout.

Defaults:
  --submodule-path openemr
  --overlay-dir overlays/openemr
USAGE
}

submodule_path="openemr"
overlay_dir="overlays/openemr"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --submodule-path)
      submodule_path="$2"
      shift 2
      ;;
    --overlay-dir)
      overlay_dir="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel)"
submodule_abs="$repo_root/$submodule_path"
overlay_abs="$repo_root/$overlay_dir"

if [[ ! -d "$submodule_abs" ]]; then
  echo "Submodule path not found: $submodule_abs" >&2
  exit 1
fi

if [[ ! -d "$overlay_abs" ]]; then
  echo "Overlay directory not found, skipping: $overlay_abs"
  exit 0
fi

echo "Applying overlay from $overlay_dir -> $submodule_path"
if command -v rsync >/dev/null 2>&1; then
  rsync -a "$overlay_abs/" "$submodule_abs/"
else
  # Fallback for environments without rsync.
  cp -R "$overlay_abs/." "$submodule_abs/"
fi

echo "Overlay applied."
