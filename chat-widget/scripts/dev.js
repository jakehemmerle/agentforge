#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const http = require("http");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(ROOT, "chat-widget", "src");
const DIST = path.join(ROOT, "chat-widget", "dist");

const JS_DEST = path.join(ROOT, "openemr", "interface", "main", "tabs", "js");
const CSS_DEST = path.join(ROOT, "openemr", "interface", "main", "tabs", "css");

const TARGETS = [
  {
    src: path.join(DIST, "ai-chat-widget.js"),
    dest: path.join(JS_DEST, "ai-chat-widget.js"),
    label: "dist/ai-chat-widget.js",
  },
  {
    src: path.join(SRC, "ai-chat-widget.css"),
    dest: path.join(CSS_DEST, "ai-chat-widget.css"),
    label: "src/ai-chat-widget.css",
  },
  {
    src: path.join(SRC, "dev-reload.js"),
    dest: path.join(JS_DEST, "dev-reload.js"),
    label: "src/dev-reload.js",
  },
];

// Preflight checks
const openemrDir = path.join(ROOT, "openemr");
if (!fs.existsSync(openemrDir)) {
  console.error(
    "Error: openemr/ submodule not found. Run:\n  git submodule update --init"
  );
  process.exit(1);
}

for (const t of TARGETS) {
  const destDir = path.dirname(t.dest);
  if (!fs.existsSync(destDir)) {
    console.error(
      `Error: ${path.relative(ROOT, destDir)} does not exist.\n` +
        "Run  ./injectables/openemr-customize.sh apply  first to set up the overlay directories."
    );
    process.exit(1);
  }
}

function runBuild() {
  console.log("  running esbuild…");
  execFileSync(process.execPath, [path.join(__dirname, "build.js")], {
    stdio: "inherit",
  });
}

function copyAll() {
  for (const t of TARGETS) {
    fs.copyFileSync(t.src, t.dest);
    console.log(`  copied ${t.label} → ${path.relative(ROOT, t.dest)}`);
  }
}

// Initial build + copy
console.log("chat-widget dev: initial build + copy…");
runBuild();
copyAll();

// Version tracking for hot-reload
let jsVersion = 0;
let cssVersion = 0;

// Watch for changes
console.log("chat-widget dev: watching src/ for changes…");
let debounce = null;
fs.watch(SRC, (_event, filename) => {
  if (!filename) return;
  if (debounce) clearTimeout(debounce);
  debounce = setTimeout(() => {
    debounce = null;
    console.log(`\nchange detected: ${filename}`);
    if (filename.endsWith(".js") && filename !== "dev-reload.js") {
      runBuild();
    }
    copyAll();
    if (filename.endsWith(".css")) {
      cssVersion++;
      console.log(`  css version → ${cssVersion}`);
    } else if (filename.endsWith(".js")) {
      jsVersion++;
      console.log(`  js version → ${jsVersion}`);
    }
  }, 100);
});

// Hot-reload version server
const DEV_PORT = 8351;
const server = http.createServer((_req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({ js: jsVersion, css: cssVersion }));
});
server.listen(DEV_PORT, () => {
  console.log(`chat-widget dev: version server on http://localhost:${DEV_PORT}/version`);
  console.log("open http://localhost:8300");
});
server.on("error", (err) => {
  console.warn(`warning: version server failed to start (${err.code}) — hot-reload disabled, file watcher still active`);
});
