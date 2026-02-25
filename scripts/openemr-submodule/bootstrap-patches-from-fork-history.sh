#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 [--author EMAIL] [--patch-dir PATH]

Creates the initial minimal patch queue from your fork history.
It diffs from the parent of your first authored commit up to HEAD.

Defaults:
  --author    git config user.email
  --patch-dir patches/openemr
USAGE
}

author_email="$(git config user.email || true)"
patch_dir="patches/openemr"

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

if [[ -z "$author_email" ]]; then
  echo "Unable to determine author email. Provide --author." >&2
  exit 1
fi

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
