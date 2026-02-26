#!/usr/bin/env bash
set -euo pipefail

repo_root() {
  git rev-parse --show-toplevel
}

usage_main() {
  cat <<USAGE
Usage: $0 <command> [options]

Commands:
  update             Fetch/pin OpenEMR, then run apply
  apply              Idempotent: apply patches + overlay without fetch/pin
  apply-patches      Idempotent: apply patch files only
  apply-overlay      Copy additive overlay files into OpenEMR
  clean              Reset submodule to parent-pinned commit and remove all local changes
  refresh-patches    Regenerate patch files from current OpenEMR diffs
  bootstrap-patches  Build initial patch files from fork commit history
  help               Show this help

Run '$0 <command> --help' for command-specific options.
USAGE
}

usage_update() {
  cat <<USAGE
Usage: $0 update [options]

Fetches latest OpenEMR upstream into a submodule path, then reapplies customizations.

Options:
  --submodule-path PATH   OpenEMR checkout path (default: openemr)
  --remote NAME           Remote to fetch (default: origin)
  --branch NAME           Branch to fetch (default: master)
  --patch-dir PATH        Patch dir (default: injectables/patches)
  --overlay-dir PATH      Overlay dir (default: injectables/overlay)
  --test-cmd CMD          Optional command to validate after update
  --skip-patches          Do not apply patch files
  --skip-overlay          Do not apply overlay files
  -h, --help              Show help
USAGE
}

usage_apply() {
  cat <<USAGE
Usage: $0 apply [options]

Idempotently reapplies local customizations without fetching upstream.

Options:
  --submodule-path PATH   OpenEMR checkout path (default: openemr)
  --patch-dir PATH        Patch dir (default: injectables/patches)
  --overlay-dir PATH      Overlay dir (default: injectables/overlay)
  --skip-patches          Do not apply patch files
  --skip-overlay          Do not apply overlay files
  -h, --help              Show help
USAGE
}

usage_apply_patches() {
  cat <<USAGE
Usage: $0 apply-patches [--submodule-path PATH] [--patch-dir PATH]

Idempotently applies patch files into the OpenEMR checkout.

Defaults:
  --submodule-path openemr
  --patch-dir injectables/patches
USAGE
}

usage_apply_overlay() {
  cat <<USAGE
Usage: $0 apply-overlay [--submodule-path PATH] [--overlay-dir PATH]

Copies overlay files into the OpenEMR checkout.

Defaults:
  --submodule-path openemr
  --overlay-dir injectables/overlay
USAGE
}

usage_clean() {
  cat <<USAGE
Usage: $0 clean [--submodule-path PATH]

Resets the OpenEMR submodule to the commit pinned by the parent repository,
then removes tracked/untracked modifications inside the submodule.

Defaults:
  --submodule-path openemr
USAGE
}

usage_refresh_patches() {
  cat <<USAGE
Usage: $0 refresh-patches [--submodule-path PATH] [--patch-dir PATH]

Regenerates the minimal OpenEMR patch queue from the current OpenEMR checkout.

Defaults:
  --submodule-path openemr
  --patch-dir injectables/patches

Generated patches:
  0001-ai-widget-main-tab.patch
  0002-user-repo-system-role.patch
  0003-dev-compose-ai-agent.patch
USAGE
}

usage_bootstrap_patches() {
  cat <<USAGE
Usage: $0 bootstrap-patches [--author EMAIL] [--patch-dir PATH]

Creates the initial minimal patch queue from your fork history.
It diffs from the parent of your first authored commit up to HEAD.

Defaults:
  --author    git config user.email
  --patch-dir injectables/patches
USAGE
}

cmd_apply_patches() {
  local submodule_path="openemr"
  local patch_dir="injectables/patches"

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
        usage_apply_patches
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage_apply_patches >&2
        exit 1
        ;;
    esac
  done

  local root submodule_abs patch_abs
  root="$(repo_root)"
  submodule_abs="$root/$submodule_path"
  patch_abs="$root/$patch_dir"

  if [[ ! -d "$submodule_abs/.git" && ! -f "$submodule_abs/.git" ]]; then
    echo "OpenEMR checkout not found: $submodule_abs" >&2
    exit 1
  fi

  if ! compgen -G "$patch_abs/*.patch" >/dev/null; then
    echo "No patch files found in $patch_dir"
    return 0
  fi

  local applied_count=0
  local already_count=0

  echo "Applying patches from $patch_dir (idempotent)"
  while IFS= read -r patch_file; do
    local patch_name
    patch_name="$(basename "$patch_file")"

    if git -C "$submodule_abs" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
      echo "  -> $patch_name (already applied)"
      already_count=$((already_count + 1))
      continue
    fi

    if git -C "$submodule_abs" apply --check "$patch_file" >/dev/null 2>&1; then
      git -C "$submodule_abs" apply --whitespace=nowarn "$patch_file"
      echo "  -> $patch_name (applied cleanly)"
      applied_count=$((applied_count + 1))
      continue
    fi

    git -C "$submodule_abs" apply --3way --whitespace=nowarn "$patch_file"
    echo "  -> $patch_name (applied with 3-way merge)"
    applied_count=$((applied_count + 1))
  done < <(ls -1 "$patch_abs"/*.patch | sort)

  echo "Patch apply summary: applied=$applied_count already_applied=$already_count"
}

cmd_apply_overlay() {
  local submodule_path="openemr"
  local overlay_dir="injectables/overlay"

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
        usage_apply_overlay
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage_apply_overlay >&2
        exit 1
        ;;
    esac
  done

  local root submodule_abs overlay_abs
  root="$(repo_root)"
  submodule_abs="$root/$submodule_path"
  overlay_abs="$root/$overlay_dir"

  if [[ ! -d "$submodule_abs" ]]; then
    echo "Submodule path not found: $submodule_abs" >&2
    exit 1
  fi

  if [[ ! -d "$overlay_abs" ]]; then
    echo "Overlay directory not found, skipping: $overlay_abs"
    return 0
  fi

  echo "Applying overlay from $overlay_dir -> $submodule_path"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "$overlay_abs/" "$submodule_abs/"
  else
    cp -R "$overlay_abs/." "$submodule_abs/"
  fi

  # Copy chat-widget source into OpenEMR paths
  local widget_dir="$root/chat-widget/src"
  if [[ -d "$widget_dir" ]]; then
    echo "Copying chat-widget sources into $submodule_path"
    mkdir -p "$submodule_abs/interface/main/tabs/js"
    mkdir -p "$submodule_abs/interface/main/tabs/css"
    cp "$widget_dir/ai-chat-widget.js" "$submodule_abs/interface/main/tabs/js/"
    cp "$widget_dir/ai-chat-widget.css" "$submodule_abs/interface/main/tabs/css/"
    cp "$widget_dir/dev-reload.js" "$submodule_abs/interface/main/tabs/js/"
  fi

  echo "Overlay applied."
}

cmd_apply() {
  local submodule_path="openemr"
  local patch_dir="injectables/patches"
  local overlay_dir="injectables/overlay"
  local skip_patches="false"
  local skip_overlay="false"

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
      --overlay-dir)
        overlay_dir="$2"
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
        usage_apply
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage_apply >&2
        exit 1
        ;;
    esac
  done

  if [[ "$skip_patches" != "true" ]]; then
    cmd_apply_patches --submodule-path "$submodule_path" --patch-dir "$patch_dir"
  else
    echo "Skipping patch application"
  fi

  if [[ "$skip_overlay" != "true" ]]; then
    cmd_apply_overlay --submodule-path "$submodule_path" --overlay-dir "$overlay_dir"
  else
    echo "Skipping overlay application"
  fi

  local root
  root="$(repo_root)"
  echo "OpenEMR status summary:"
  git -C "$root/$submodule_path" status --short
}

cmd_clean() {
  local submodule_path="openemr"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --submodule-path)
        submodule_path="$2"
        shift 2
        ;;
      -h|--help)
        usage_clean
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage_clean >&2
        exit 1
        ;;
    esac
  done

  local root submodule_abs
  root="$(repo_root)"
  submodule_abs="$root/$submodule_path"

  if [[ ! -d "$submodule_abs/.git" && ! -f "$submodule_abs/.git" ]]; then
    echo "OpenEMR checkout not found: $submodule_abs" >&2
    exit 1
  fi

  if [[ "$submodule_path" != "." ]]; then
    git submodule update --init "$submodule_path"
  fi

  git -C "$submodule_abs" reset --hard HEAD
  # git clean may warn about Docker-mounted volumes it cannot remove; tolerate that.
  git -C "$submodule_abs" clean -fdx || true

  echo "Submodule cleaned: $submodule_path"
  git -C "$submodule_abs" status --short --branch
}

cmd_refresh_patches() {
  local submodule_path="openemr"
  local patch_dir="injectables/patches"

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
        usage_refresh_patches
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage_refresh_patches >&2
        exit 1
        ;;
    esac
  done

  local root submodule_abs patch_abs
  root="$(repo_root)"
  submodule_abs="$root/$submodule_path"
  patch_abs="$root/$patch_dir"

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
}

cmd_bootstrap_patches() {
  local author_email patch_dir
  author_email="$(git config user.email || true)"
  patch_dir="injectables/patches"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --author)
        author_email="$2"
        shift 2
        ;;
      --patch-dir)
        patch_dir="$2"
        shift 2
        ;;
      -h|--help)
        usage_bootstrap_patches
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage_bootstrap_patches >&2
        exit 1
        ;;
    esac
  done

  if [[ -z "$author_email" ]]; then
    echo "Unable to determine author email. Provide --author." >&2
    exit 1
  fi

  local first_commit base_commit
  first_commit="$(git log --reverse --author="$author_email" --format='%H' | head -n1)"
  if [[ -z "$first_commit" ]]; then
    echo "No commits found for author: $author_email" >&2
    exit 1
  fi

  base_commit="$(git rev-parse "${first_commit}^")"
  mkdir -p "$patch_dir"

  git diff --no-color "${base_commit}"..HEAD -- interface/main/tabs/main.php \
    > "$patch_dir/0001-ai-widget-main-tab.patch"
  git diff --no-color "${base_commit}"..HEAD -- src/Common/Auth/OpenIDConnect/Repositories/UserRepository.php \
    > "$patch_dir/0002-user-repo-system-role.patch"
  git diff --no-color "${base_commit}"..HEAD -- docker/development-easy/docker-compose.yml \
    > "$patch_dir/0003-dev-compose-ai-agent.patch"

  echo "Author: $author_email"
  echo "First commit: $first_commit"
  echo "Base commit: $base_commit"
  echo "Wrote patch files to: $patch_dir"
}

cmd_update() {
  local submodule_path="openemr"
  local remote_name="origin"
  local branch_name="master"
  local patch_dir="injectables/patches"
  local overlay_dir="injectables/overlay"
  local test_cmd=""
  local skip_patches="false"
  local skip_overlay="false"

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
        usage_update
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage_update >&2
        exit 1
        ;;
    esac
  done

  local root submodule_abs
  root="$(repo_root)"
  submodule_abs="$root/$submodule_path"

  if [[ ! -d "$submodule_abs/.git" && ! -f "$submodule_abs/.git" ]]; then
    echo "OpenEMR checkout not found: $submodule_abs" >&2
    exit 1
  fi

  if [[ -n "$(git -C "$submodule_abs" status --porcelain)" ]]; then
    echo "OpenEMR checkout is dirty: $submodule_path" >&2
    echo "Run '$0 clean --submodule-path $submodule_path' or commit/stash/reset first." >&2
    exit 1
  fi

  echo "Updating OpenEMR at $submodule_path from $remote_name/$branch_name"

  if [[ "$submodule_path" != "." ]]; then
    git submodule update --init "$submodule_path"
  fi

  git -C "$submodule_abs" fetch "$remote_name" "$branch_name"
  local new_rev
  new_rev="$(git -C "$submodule_abs" rev-parse FETCH_HEAD)"

  git -C "$submodule_abs" checkout --detach "$new_rev"

  if [[ "$submodule_path" != "." ]]; then
    git add "$submodule_path"
  fi

  echo "OpenEMR pinned at: $new_rev"

  local -a apply_args
  apply_args=(
    --submodule-path "$submodule_path"
    --patch-dir "$patch_dir"
    --overlay-dir "$overlay_dir"
  )
  if [[ "$skip_patches" == "true" ]]; then
    apply_args+=(--skip-patches)
  fi
  if [[ "$skip_overlay" == "true" ]]; then
    apply_args+=(--skip-overlay)
  fi

  cmd_apply "${apply_args[@]}"

  if [[ -n "$test_cmd" ]]; then
    echo "Running validation command: $test_cmd"
    bash -lc "$test_cmd"
  fi

  echo "Update complete."
}

main() {
  local command="${1:-help}"
  if [[ $# -gt 0 ]]; then
    shift
  fi

  case "$command" in
    update)
      cmd_update "$@"
      ;;
    apply)
      cmd_apply "$@"
      ;;
    apply-patches|patches)
      cmd_apply_patches "$@"
      ;;
    apply-overlay|overlay)
      cmd_apply_overlay "$@"
      ;;
    clean)
      cmd_clean "$@"
      ;;
    refresh-patches|refresh)
      cmd_refresh_patches "$@"
      ;;
    bootstrap-patches|bootstrap)
      cmd_bootstrap_patches "$@"
      ;;
    help|-h|--help)
      usage_main
      ;;
    *)
      echo "Unknown command: $command" >&2
      usage_main >&2
      exit 1
      ;;
  esac
}

main "$@"
