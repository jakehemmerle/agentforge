#!/usr/bin/env node
"use strict";

const esbuild = require("esbuild");
const path = require("path");

esbuild.buildSync({
  entryPoints: [path.join(__dirname, "..", "src", "ai-chat-widget.js")],
  bundle: true,
  format: "iife",
  outfile: path.join(__dirname, "..", "dist", "ai-chat-widget.js"),
  platform: "browser",
  target: ["es2015"],
  logLevel: "info",
});
