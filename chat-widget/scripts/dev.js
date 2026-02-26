#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const http = require("http");

const ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(ROOT, "chat-widget", "src");

const TARGETS = [
  {
    src: "ai-chat-widget.js",
    dest: path.join(ROOT, "openemr", "interface", "main", "tabs", "js"),
  },
  {
    src: "ai-chat-widget.css",
    dest: path.join(ROOT, "openemr", "interface", "main", "tabs", "css"),
  },
  {
    src: "dev-reload.js",
    dest: path.join(ROOT, "openemr", "interface", "main", "tabs", "js"),
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
  if (!fs.existsSync(t.dest)) {
    console.error(
      `Error: ${path.relative(ROOT, t.dest)} does not exist.\n` +
        "Run  ./injectables/openemr-customize.sh apply  first to set up the overlay directories."
    );
    process.exit(1);
  }
}

function copyAll() {
  for (const t of TARGETS) {
    const srcPath = path.join(SRC, t.src);
    const destPath = path.join(t.dest, t.src);
    fs.copyFileSync(srcPath, destPath);
    console.log(`copied ${t.src} → ${path.relative(ROOT, destPath)}`);
  }
}

// Initial copy
console.log("chat-widget dev: initial copy…");
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
