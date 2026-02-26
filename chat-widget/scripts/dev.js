#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

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
  }, 100);
});
