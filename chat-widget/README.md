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
