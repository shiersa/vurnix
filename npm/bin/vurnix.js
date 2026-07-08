#!/usr/bin/env node
const VERSION = "0.1.0";
const HOME = "https://github.com/shiersa/vurnix";

const cmd = process.argv[2];
if (cmd === "version" || cmd === "--version" || cmd === "-v") {
  console.log(`vurnix ${VERSION}`);
} else {
  console.log(
    `Vurnix v${VERSION} (alpha) — local-first software factory.\n` +
      `Deterministic multi-agent orchestration for small local models.\n\n` +
      `The Python package is the primary distribution: pip install vurnix\n` +
      `Home: ${HOME}`
  );
}
