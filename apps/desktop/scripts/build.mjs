import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { build } from "esbuild";

const root = path.resolve(import.meta.dirname, "..");
const dist = path.join(root, "dist");
fs.rmSync(dist, { recursive: true, force: true });
fs.mkdirSync(dist, { recursive: true });
const result = spawnSync(process.execPath, [path.join(root, "node_modules", "typescript", "bin", "tsc"), "--noEmit"], { cwd: root, stdio: "inherit" });
if (result.status !== 0) process.exit(result.status ?? 1);
await build({
  entryPoints: [path.join(root, "src", "main.ts")],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  outfile: path.join(dist, "main.js"),
  sourcemap: false,
});
for (const name of ["index.html", "src/style.css"]) {
  fs.copyFileSync(path.join(root, name), path.join(dist, path.basename(name)));
}
