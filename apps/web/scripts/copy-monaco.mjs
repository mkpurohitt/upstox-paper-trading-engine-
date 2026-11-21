// Copies Monaco's AMD build (monaco-editor/min/vs) into public/monaco/vs so the code editor is served by this app
// instead of a CDN (works offline / behind firewalls; same version as the installed package). Idempotent.
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

function packageRoot() {
  let dir = dirname(require.resolve("monaco-editor"));
  for (let i = 0; i < 8; i++) {
    const pj = join(dir, "package.json");
    if (existsSync(pj) && JSON.parse(readFileSync(pj, "utf8")).name === "monaco-editor") return dir;
    dir = dirname(dir);
  }
  throw new Error("monaco-editor package root not found");
}

const root = packageRoot();
const version = JSON.parse(readFileSync(join(root, "package.json"), "utf8")).version;
const src = join(root, "min", "vs");
const dest = resolve(here, "..", "public", "monaco", "vs");
const stamp = resolve(here, "..", "public", "monaco", ".version");
if (existsSync(stamp) && readFileSync(stamp, "utf8").trim() === version && existsSync(join(dest, "loader.js"))) process.exit(0);
rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true });
writeFileSync(stamp, version);
console.log(`[monaco] copied monaco-editor ${version} to public/monaco/vs`);
