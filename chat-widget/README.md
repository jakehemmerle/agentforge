# Chat Widget

AI chat widget injected into OpenEMR's main tab interface.

## Prerequisites

- Node >= 18 (unit tests only)
- Node >= 22 (integration tests, dev runner)
- OpenEMR submodule checked out at `openemr/` (integration/dev only)

## Build

The widget uses esbuild to bundle `src/ai-chat-widget.js` + `marked`
(markdown renderer) into a single browser-ready file at `dist/ai-chat-widget.js`.

```bash
npm run build
```

`dist/` is gitignored — the build runs automatically during `npm run dev`
and `openemr-customize.sh apply`.

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

   This runs esbuild to produce `dist/ai-chat-widget.js`, copies it
   along with `src/ai-chat-widget.css` and `src/dev-reload.js` into
   the submodule, then watches `src/` for changes and rebuilds/copies
   automatically.

3. **Open the app** — navigate to `http://localhost:8300`, log in
   (admin / pass), and the blue chat button should appear in the
   bottom-right corner.

### Hot-reload (no page refresh)

With `npm run dev` running, changes auto-apply without a page refresh:

- **CSS changes** swap the stylesheet in-place (~1.5s). No DOM rebuild,
  no lost chat state.
- **JS changes** trigger esbuild, then save widget state (messages,
  open/closed, panel size) to `sessionStorage`, tear down the widget,
  and re-execute the script. Chat history and panel state are restored
  automatically.

The dev server on port 8351 serves a `/version` endpoint. The
`dev-reload.js` client (loaded only when the `AI_CHAT_DEV_RELOAD` env
var is set) polls it every 1.5s. Console shows `[dev-reload] connected`,
`[dev-reload] CSS reloaded`, `[dev-reload] JS reloaded` as appropriate.

If the dev server is not running, the client silently falls back to
manual refresh.

### Stopping

Stop the watcher with Ctrl-C. Stop the local environment with
`/dev-setup down`.

## OpenEMR Build Pipeline (why integration tests need a full install)

The chat widget has a lightweight esbuild step (bundles `marked` into an IIFE),
then JS/CSS are copied into the submodule. The integration test verifies that OpenEMR's gulp build still
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
| `dist/ai-chat-widget.js` | `interface/main/tabs/js/ai-chat-widget.js` |
| `src/ai-chat-widget.css` | `interface/main/tabs/css/ai-chat-widget.css` |
| `src/dev-reload.js` | `interface/main/tabs/js/dev-reload.js` |
