# Chat Widget

AI chat widget injected into OpenEMR's main tab interface.

## Prerequisites

- Node >= 18 (unit tests only)
- Node >= 22 (integration tests, dev runner)
- OpenEMR submodule checked out at `openemr/` (integration/dev only)

## Unit Tests

No submodule required.

```bash
npm test
```

## Integration Tests

Requires the `openemr/` submodule. Gated behind `INTEGRATION_TEST=1`.

```bash
INTEGRATION_TEST=1 npm run test:integration
```

Tests verify:
1. Widget JS and CSS land at correct paths after injection
2. OpenEMR `npm run build` (gulp) succeeds after injection

## Inject

Apply patches and overlay into the OpenEMR submodule:

```bash
npm run inject
```

## Clean

Reset chat-widget dependencies:

```bash
rm -rf node_modules && npm install
```

Reset OpenEMR submodule to pristine state:

```bash
npm run clean
```

## Development

Local development uses Docker (via the `/dev-setup` skill) for the full
OpenEMR + AI Agent stack, and a file watcher for fast widget iteration.

### First-time setup

1. **Start the local environment** — from the repo root, run the
   `/dev-setup up` skill. This brings up OpenEMR, MySQL, and the
   AI Agent service. It also cleans the submodule and runs
   `openemr-customize.sh apply` + `npm run inject`, so patches and
   widget files are already in place when it finishes.

2. **Start the file watcher**:

   ```bash
   npm run dev
   ```

   This does an initial copy of `src/ai-chat-widget.js` and
   `src/ai-chat-widget.css` into the submodule, then watches `src/` for
   changes and re-copies automatically.

3. **Open the app** — navigate to `http://localhost:8300`, log in
   (admin / pass), and the blue chat button should appear in the
   bottom-right corner.

### Edit → refresh loop

With `npm run dev` running, any change you save in `src/` is copied into
the OpenEMR submodule within ~100 ms. Just refresh the browser to pick
up the new code — no rebuild or re-inject needed.

### Stopping

Stop the watcher with Ctrl-C. Stop the local environment with
`/dev-setup down`.

## OpenEMR Build Pipeline (why integration tests need a full install)

The chat widget itself has no build step — it's plain JS/CSS copied into the
submodule. But the integration test verifies that OpenEMR's gulp build still
succeeds after injection, and that build has a specific dependency chain:

1. `npm install` fetches regular npm packages (bootstrap, jquery, etc.)
2. The `postinstall` hook runs `napa && gulp -i`:
   - **napa** downloads packages not in npm (bootstrap-rtl, jquery-ui zips, etc.)
     and places them in `node_modules/`
   - **gulp -i** (the `install` task) copies dependencies from `node_modules/`
     into `public/assets/`, with special handling per package (bootstrap gets
     both `dist/` and `scss/`, fontawesome gets `css/`, `scss/`, and `webfonts/`)
3. `npm run build` (gulp default) compiles Sass themes that `@import` from
   `public/assets/bootstrap/scss/` and `public/assets/bootstrap-rtl/scss/`

Using `npm install --ignore-scripts` skips step 2. The Sass build then fails
because `public/assets/bootstrap/` never gets populated. The fix was dropping
`--ignore-scripts` so the full postinstall chain runs. `gulp -i` itself is
fast (~20ms, just file copies) — the cost is `napa` downloading a handful of
zip archives on first run.

## Injection Paths

| Source | Destination (inside `openemr/`) |
|--------|-------------------------------|
| `src/ai-chat-widget.js` | `interface/main/tabs/js/ai-chat-widget.js` |
| `src/ai-chat-widget.css` | `interface/main/tabs/css/ai-chat-widget.css` |
