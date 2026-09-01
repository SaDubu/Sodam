import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..", "..", "..");
const config = JSON.parse(fs.readFileSync(path.join(root, "apps", "desktop", "src-tauri", "tauri.conf.json"), "utf8"));
const packageConfig = JSON.parse(fs.readFileSync(path.join(root, "apps", "desktop", "package.json"), "utf8"));
const workflow = fs.readFileSync(path.join(root, ".github", "workflows", "desktop-build.yml"), "utf8");

test("bundle targets and CI matrix are explicit and unsigned", () => {
  assert.equal(config.bundle.active, true);
  assert.deepEqual(config.bundle.targets, ["nsis", "msi", "dmg", "appimage", "deb"]);
  assert.equal(config.bundle.createUpdaterArtifacts, false);
  assert.deepEqual(config.bundle.icon, [
    "icons/32x32.png",
    "icons/128x128.png",
    "icons/128x128@2x.png",
    "icons/icon.icns",
    "icons/icon.ico",
  ]);
  assert.equal(packageConfig.scripts.test, "node --test");
  for (const icon of config.bundle.icon) {
    const iconPath = path.join(root, "apps", "desktop", "src-tauri", icon);
    assert.ok(fs.statSync(iconPath).size > 0, `${icon} must be present`);
  }
  assert.ok(
    fs.statSync(path.join(root, "apps", "desktop", "src-tauri", "icons", "icon.png")).size > 0,
    "Tauri generate_context default icon must be present",
  );
  for (const os of ["windows-latest", "macos-latest", "ubuntu-latest"]) assert.match(workflow, new RegExp(os));
  for (const command of ["npm ci", "npm run check", "npm test", "npm run build", "npx tauri build"]) assert.match(workflow, new RegExp(command.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(workflow, /actions\/upload-artifact@v4/);
  assert.doesNotMatch(workflow, /Qwen|qwen3|\.gguf|OLLAMA_HOST|SIGNING_KEY/i);
});
