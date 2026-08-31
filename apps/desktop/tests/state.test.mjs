import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const root = path.resolve(import.meta.dirname, "..");
const source = fs.readFileSync(path.join(root, "src", "state.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const module = { exports: {} };
const loadModule = vm.runInThisContext(`(module, exports) => {${compiled.outputText}\n}`);
loadModule(module, module.exports);
const state = module.exports;

const item = {
  segmentId: "segment-0001",
  startSeconds: 1.5,
  rawText: "원문",
  proposedText: "제안",
  reason: "meaning change",
};

test("initial state is detached and exposes every backend status in the source contract", () => {
  const first = state.createInitialDesktopState();
  const second = state.createInitialDesktopState();
  first.reviewItems.push(item);
  assert.equal(second.reviewItems.length, 0);
  for (const status of ["queued", "acquiring", "extracting", "transcribing", "normalizing", "correcting", "reviewing", "summarizing", "completed", "cancelling", "cancelled", "failed", "cleaning", "archived"]) {
    assert.match(source, new RegExp(`"${status}"`));
  }
});

test("created, progress, review, and completed events create a detached result", () => {
  const created = state.reduceJobEvent(state.createInitialDesktopState(), { type: "created", jobId: "job-1", sourceLabel: "한국어.mp3" });
  const progressing = state.reduceJobEvent(created, { type: "progress", jobId: "job-1", status: "transcribing", progressPercent: 45 });
  const reviewing = state.reduceJobEvent(progressing, { type: "review-ready", jobId: "job-1", items: [item] });
  const done = state.reduceJobEvent(reviewing, { type: "completed", jobId: "job-1", summary: "요약", resultPath: "D:/results/job-1" });
  assert.equal(created.job.status, "queued");
  assert.equal(progressing.job.progressPercent, 45);
  assert.equal(done.job.status, "archived");
  assert.equal(done.job.summary, "요약");
  assert.equal(done.reviewItems[0].rawText, "원문");
  item.rawText = "mutated input";
  assert.equal(done.reviewItems[0].rawText, "원문");
});

test("stale and terminal events are ignored without retaining aliases", () => {
  const active = state.reduceJobEvent(state.createInitialDesktopState(), { type: "created", jobId: "job-1", sourceLabel: "source" });
  const stale = state.reduceJobEvent(active, { type: "progress", jobId: "job-2", status: "extracting", progressPercent: 10 });
  assert.deepEqual(stale, active);
  assert.notEqual(stale, active);
  const terminal = state.reduceJobEvent(active, { type: "cancelled", jobId: "job-1" });
  const ignored = state.reduceJobEvent(terminal, { type: "review-ready", jobId: "job-1", items: [item] });
  assert.equal(ignored.job.status, "cancelled");
  assert.equal(ignored.reviewItems.length, 0);
});

test("failure and cancellation produce terminal user-facing state", () => {
  const active = state.reduceJobEvent(state.createInitialDesktopState(), { type: "created", jobId: "job-1", sourceLabel: "source" });
  const failed = state.reduceJobEvent(active, { type: "failed", jobId: "job-1", error: { code: "STT_UNAVAILABLE", message: "STT를 시작할 수 없습니다." } });
  assert.deepEqual(failed.job.error, { code: "STT_UNAVAILABLE", message: "STT를 시작할 수 없습니다." });
  const cancelled = state.reduceJobEvent(state.reduceJobEvent(state.createInitialDesktopState(), { type: "created", jobId: "job-2", sourceLabel: "source" }), { type: "cancelled", jobId: "job-2" });
  assert.equal(cancelled.job.status, "cancelled");
  assert.equal(cancelled.job.progressPercent, null);
});

test("completed resilience metadata is detached and identity is review-visible", () => {
  const active = state.reduceJobEvent(state.createInitialDesktopState(), { type: "created", jobId: "job-3", sourceLabel: "source" });
  const resilience = {
    correction_group_count: 2,
    correction_attempt_count: 4,
    identity_group_count: 1,
    review_required_count: 1,
    progress_event_count: 9,
    last_stage: "completed",
    terminal_status: "archived",
  };
  const done = state.reduceJobEvent(active, {
    type: "completed",
    jobId: "job-3",
    summary: "요약",
    resultPath: "D:/results/job-3",
    resilience,
  });
  assert.equal(done.resilience.identity_group_count, 1);
  resilience.identity_group_count = 99;
  assert.equal(done.resilience.identity_group_count, 1);
});

test("malformed public values are rejected", () => {
  const active = state.reduceJobEvent(state.createInitialDesktopState(), { type: "created", jobId: "job-1", sourceLabel: "source" });
  assert.throws(() => state.reduceJobEvent(active, { type: "progress", jobId: "job-1", status: "transcribing", progressPercent: 101 }), RangeError);
  assert.throws(() => state.reduceJobEvent(active, { type: "review-ready", jobId: "job-1", items: [{ ...item, startSeconds: -1 }] }), RangeError);
  assert.throws(() => state.reduceJobEvent(active, { type: "failed", jobId: "job-1", error: { code: "", message: "no" } }), TypeError);
  assert.throws(() => state.reduceJobEvent(active, { type: "progress", jobId: "job-1", status: "archived", progressPercent: 1 }), TypeError);
});

test("progress reducer keeps monotonic events and terminal state", () => {
  const initial = state.createInitialProgressState();
  const first = state.reduceProgressEvent(initial, {
    operation_id: "op-1", scope: "job", stage: "transcription", stage_label: "전사",
    stage_progress: 0.5, overall_progress: 0.2, completed_units: 1, total_units: 2,
    elapsed_seconds: 3, eta_seconds: 5, message: "진행", can_cancel: true, sequence: 1, timestamp: "now",
  });
  assert.equal(first.overallProgress, 0.2);
  const stale = state.reduceProgressEvent(first, {
    operation_id: "op-1", scope: "job", stage: "transcription", stage_label: "전사",
    stage_progress: 0.4, overall_progress: 0.1, completed_units: 0, total_units: 2,
    elapsed_seconds: 2, eta_seconds: 6, message: "stale", can_cancel: true, sequence: 1, timestamp: "now",
  });
  assert.notEqual(stale, first);
  assert.equal(stale.sequence, 1);
  const done = state.reduceProgressEvent(first, {
    operation_id: "op-1", scope: "job", stage: "completed", stage_label: "완료",
    stage_progress: 1, overall_progress: 1, completed_units: 2, total_units: 2,
    elapsed_seconds: 4, eta_seconds: 0, message: "완료", can_cancel: true, sequence: 2, timestamp: "now",
  });
  assert.equal(done.terminal, true);
  assert.equal(done.canCancel, false);
  assert.throws(() => state.reduceProgressEvent(initial, { operation_id: "op", scope: "job", stage: "x", stage_label: "", message: "", can_cancel: false, sequence: 0, elapsed_seconds: -1 }), TypeError);
});

test("output mode selector accepts only the three public values", () => {
  assert.doesNotThrow(() => state.assertOutputMode("summary"));
  assert.doesNotThrow(() => state.assertOutputMode("introduction"));
  assert.doesNotThrow(() => state.assertOutputMode("both"));
  assert.throws(() => state.assertOutputMode("unknown"), TypeError);
});
