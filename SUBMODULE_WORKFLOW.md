# OpenEMR Submodule Workflow

This repository now includes a minimal reinjection workflow so OpenEMR can be treated as an upstream dependency.

## Included Assets

- `patches/openemr/*.patch`: minimal core edits that must be reapplied
- `overlays/openemr/**`: additive files copied into OpenEMR after patching
- `scripts/openemr-submodule/update-openemr.sh`: fetch + pin + reapply patches/overlay
- `scripts/openemr-submodule/apply-openemr-overlay.sh`: apply overlay files only
- `scripts/openemr-submodule/refresh-openemr-patches.sh`: regenerate patch files from local OpenEMR diffs
- `scripts/openemr-submodule/bootstrap-patches-from-fork-history.sh`: generate initial patch queue from fork history

## Target Parent Repo Layout

```text
platform-repo/
  openemr/                      # git submodule
  ai-agent/                     # your standalone agent project
  patches/openemr/
    0001-ai-widget-main-tab.patch
    0002-user-repo-system-role.patch
    0003-dev-compose-ai-agent.patch
  overlays/openemr/
    interface/main/tabs/css/ai-chat-widget.css
    interface/main/tabs/js/ai-chat-widget.js
    tests/js/ai-chat-widget-sse.test.js
    tests/js/ai-chat-widget.test.js
  scripts/openemr-submodule/
    update-openemr.sh
    apply-openemr-overlay.sh
    refresh-openemr-patches.sh
    bootstrap-patches-from-fork-history.sh
```

## One-Time Setup In Parent Repo

```bash
# from platform-repo/
git submodule add https://github.com/openemr/openemr.git openemr
git submodule update --init --recursive

# copy directories from this repo:
#   patches/openemr
#   overlays/openemr
#   scripts/openemr-submodule
```

## Regular Upstream Update Flow

```bash
./scripts/openemr-submodule/update-openemr.sh \
  --submodule-path openemr \
  --remote origin \
  --branch master \
  --test-cmd "docker compose -f docker-compose.yml up -d --build"
```

If an upstream change conflicts with your customizations, patch application will fail fast and you can resolve the conflict in `openemr/`, then run:

```bash
./scripts/openemr-submodule/refresh-openemr-patches.sh --submodule-path openemr
```

## Using This Workflow In This Fork (Transition Mode)

While still in this forked repo (not yet parent+submodule), run against the current checkout:

```bash
./scripts/openemr-submodule/update-openemr.sh --submodule-path .
```

That lets you dry-run the reinjection process before final migration. The updater intentionally requires a clean checkout.

To regenerate the initial patch queue from your authored history in this fork:

```bash
./scripts/openemr-submodule/bootstrap-patches-from-fork-history.sh --author jakehemmerle@protonmail.com
```
