#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 [options]

Fetches latest OpenEMR upstream into a submodule path, reapplies custom patches,
and reapplies overlay files.

Options:
  --submodule-path PATH   OpenEMR checkout path (default: openemr)
  --remote NAME           Remote to fetch (default: origin)
  --branch NAME           Branch to fetch (default: master)
  --patch-dir PATH        Patch dir (default: patches/openemr)
  --overlay-dir PATH      Overlay dir (default: overlays/openemr)
  --test-cmd CMD          Optional command to validate after update
  --skip-patches          Do not apply patch files
  --skip-overlay          Do not apply overlay files
  -h, --help              Show help
USAGE
}

submodule_path="openemr"
remote_name="origin"
branch_name="master"
patch_dir="patches/openemr"
overlay_dir="overlays/openemr"
test_cmd=""
skip_patches="false"
skip_overlay="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --submodule-path)
      submodule_path="$2"
      shift 2
      ;;
    --remote)
      remote_name="$2"
      shift 2
      ;;
    --branch)
      branch_name="$2"
      shift 2
      ;;
    --patch-dir)
      patch_dir="$2"
      shift 2
      ;;
    --overlay-dir)
      overlay_dir="$2"
      shift 2
      ;;
    --test-cmd)
      test_cmd="$2"
      shift 2
      ;;
    --skip-patches)
      skip_patches="true"
      shift
      ;;
    --skip-overlay)
      skip_overlay="true"
      shift
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

if [[ ! -d "$submodule_abs/.git" && ! -f "$submodule_abs/.git" ]]; then
  echo "OpenEMR checkout not found: $submodule_abs" >&2
  exit 1
fi

if [[ -n "$(git -C "$submodule_abs" status --porcelain)" ]]; then
  echo "OpenEMR checkout is dirty: $submodule_path" >&2
  echo "Commit/stash/reset submodule changes before running update." >&2
  exit 1
fi

echo "Updating OpenEMR at $submodule_path from $remote_name/$branch_name"

if [[ "$submodule_path" != "." ]]; then
  # Keep this non-recursive: some upstream nested submodules are optional
  # and may not always be accessible.
  git submodule update --init "$submodule_path"
fi

git -C "$submodule_abs" fetch "$remote_name" "$branch_name"
new_rev="$(git -C "$submodule_abs" rev-parse FETCH_HEAD)"

git -C "$submodule_abs" checkout --detach "$new_rev"

if [[ "$submodule_path" != "." ]]; then
  git add "$submodule_path"
fi

echo "OpenEMR pinned at: $new_rev"

if [[ "$skip_patches" != "true" ]]; then
  if compgen -G "$patch_abs/*.patch" >/dev/null; then
    echo "Applying patches from $patch_dir"
    while IFS= read -r patch_file; do
      echo "  -> $(basename "$patch_file")"
      git -C "$submodule_abs" apply --3way --whitespace=nowarn "$patch_file"
    done < <(ls -1 "$patch_abs"/*.patch | sort)
  else
    echo "No patch files found in $patch_dir"
  fi
else
  echo "Skipping patch application"
fi

if [[ "$skip_overlay" != "true" ]]; then
  "$repo_root/scripts/openemr-submodule/apply-openemr-overlay.sh" \
    --submodule-path "$submodule_path" \
    --overlay-dir "$overlay_dir"
else
  echo "Skipping overlay application"
fi

echo "OpenEMR status summary:"
git -C "$submodule_abs" status --short

if [[ -n "$test_cmd" ]]; then
  echo "Running validation command: $test_cmd"
  bash -lc "$test_cmd"
fi

echo "Update complete."
