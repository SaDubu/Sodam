import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const main = fs.readFileSync(path.join(root, "src", "main.ts"), "utf8");
const style = fs.readFileSync(path.join(root, "src", "style.css"), "utf8");

test("UI exposes output modes, progress/ETA, cancel, and result tabs", () => {
  assert.match(main, /id="output-mode"/);
  assert.match(main, /value="summary"/);
  assert.match(main, /value="introduction"/);
  assert.match(main, /value="both"/);
  assert.match(main, /id="overall-progress"/);
  assert.match(main, /id="eta"/);
  assert.match(main, /id="resilience-summary"/);
  assert.match(main, /identity_group_count/);
  assert.match(main, /correction_attempt_count/);
  assert.match(main, /완료\(검토 필요\)/);
  assert.match(main, /category/);
  assert.match(main, /id="cancel-job"/);
  assert.match(main, /data-tab="summary"/);
  assert.match(main, /data-tab="introduction"/);
  assert.match(main, /aria-live="polite"/);
  assert.match(main, /listen<BackendProgressEvent>\("progress"/);
  assert.match(style, /progress/);
});
