# OpenEMR Injectable Workflow

This repo treats OpenEMR as an upstream submodule and reapplies local changes from `injectables/`.

## Injectable Layout

- `injectables/openemr-customize.sh`: single CLI
- `injectables/patches/*.patch`: edits to existing OpenEMR files
- `injectables/overlay/**`: additive files copied into OpenEMR

## Main Commands

- Update OpenEMR and reapply customizations:

```bash
./injectables/openemr-customize.sh update --remote origin --branch master
```

- Idempotent local reapply (no fetch/pin):

```bash
./injectables/openemr-customize.sh apply
```

- Clean submodule completely to parent-pinned state:

```bash
./injectables/openemr-customize.sh clean
```

## Maintenance Commands

- Rebuild patch files from current OpenEMR diffs:

```bash
./injectables/openemr-customize.sh refresh-patches
```

- Rebuild initial patch queue from fork history:

```bash
./injectables/openemr-customize.sh bootstrap-patches --author jakehemmerle@protonmail.com
```

## Notes

- `apply` is idempotent: already-applied patches are skipped, overlays are safely recopied.
- `clean` removes all tracked/untracked submodule modifications (`reset --hard` + `clean -fdx`).
