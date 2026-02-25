#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 [--submodule-path PATH] [--patch-dir PATH]

Regenerates the minimal OpenEMR patch queue from the current OpenEMR checkout.

Defaults:
  --submodule-path openemr
  --patch-dir patches/openemr

Generated patches:
  0001-ai-widget-main-tab.patch
  0002-user-repo-system-role.patch
  0003-dev-compose-ai-agent.patch
USAGE
}

submodule_path="openemr"
patch_dir="patches/openemr"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --submodule-path)
      submodule_path="$2"
      shift 2
      ;;
    --patch-dir)
      patch_dir="$2"
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
patch_abs="$repo_root/$patch_dir"

if [[ ! -d "$submodule_abs" ]]; then
  echo "OpenEMR path not found: $submodule_abs" >&2
  exit 1
fi

mkdir -p "$patch_abs"

emit_patch() {
  local target_file="$1"
  local patch_file="$2"
  local tmp
  tmp="$(mktemp)"
  git -C "$submodule_abs" diff --no-color -- "$target_file" > "$tmp"
  if [[ ! -s "$tmp" ]]; then
    echo "No diff for $target_file; skipping $patch_file"
    rm -f "$tmp"
    return
  fi
  mv "$tmp" "$patch_abs/$patch_file"
  echo "Wrote $patch_dir/$patch_file"
}

emit_patch "interface/main/tabs/main.php" "0001-ai-widget-main-tab.patch"
emit_patch "src/Common/Auth/OpenIDConnect/Repositories/UserRepository.php" "0002-user-repo-system-role.patch"
emit_patch "docker/development-easy/docker-compose.yml" "0003-dev-compose-ai-agent.patch"

echo "Patch refresh complete."
