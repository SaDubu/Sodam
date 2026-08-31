/** Framework-independent state reducers for the desktop shell. */

import type { ProgressEvent } from "./progress-contract";

export type OutputMode = "summary" | "introduction" | "both";

export interface ProgressViewState {
  operationId: string | null;
  stage: string | null;
  stageLabel: string;
  stageProgress: number | null;
  overallProgress: number | null;
  elapsedSeconds: number;
  etaSeconds: number | null;
  message: string;
  canCancel: boolean;
  sequence: number;
  terminal: boolean;
}

export function createInitialProgressState(): ProgressViewState {
  return { operationId: null, stage: null, stageLabel: "대기 중", stageProgress: null, overallProgress: null, elapsedSeconds: 0, etaSeconds: null, message: "", canCancel: false, sequence: -1, terminal: false };
}

/** Apply a backend progress event while ignoring stale or terminal regressions. */
export function reduceProgressEvent(state: ProgressViewState, rawEvent: unknown): ProgressViewState {
  const event: ProgressEvent = normalizeProgressForState(rawEvent);
  if (state.terminal) return { ...state };
  if (state.operationId !== null && event.operationId !== state.operationId) return { ...state };
  if (event.sequence <= state.sequence) return { ...state };
  const terminal = ["completed", "failed", "cancelled"].includes(event.stage);
  return {
    operationId: event.operationId,
    stage: event.stage,
    stageLabel: event.stageLabel,
    stageProgress: event.stageProgress,
    overallProgress: event.overallProgress,
    elapsedSeconds: event.elapsedSeconds,
    etaSeconds: event.etaSeconds,
    message: event.message,
    canCancel: terminal ? false : event.canCancel,
    sequence: event.sequence,
    terminal,
  };
}

function normalizeProgressForState(value: unknown): ProgressEvent {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new TypeError("progress event must be an object");
  const event = value as Record<string, unknown>;
  const requiredStrings = ["operation_id", "stage", "stage_label", "message", "timestamp"];
  for (const key of requiredStrings) if (typeof event[key] !== "string" || (key !== "timestamp" && (event[key] as string).trim() === "")) throw new TypeError(`${key} is required`);
  if (event.scope !== "setup" && event.scope !== "job") throw new TypeError("invalid progress scope");
  if (!(event.stage as string) || !["environment_check", "dependency_install", "model_download", "source_validation", "source_acquisition", "audio_extraction", "transcription", "text_protection", "rule_normalization", "correction", "review_validation", "transcript_assembly", "summarization", "introduction", "persistence", "cleanup", "completed", "failed", "cancelled"].includes(event.stage as string)) throw new TypeError("invalid progress stage");
  if (typeof event.elapsed_seconds !== "number" || !Number.isFinite(event.elapsed_seconds) || event.elapsed_seconds < 0) throw new TypeError("elapsed_seconds is invalid");
  if (typeof event.sequence !== "number" || !Number.isInteger(event.sequence) || event.sequence < 0) throw new TypeError("sequence is invalid");
  if (typeof event.can_cancel !== "boolean") throw new TypeError("can_cancel is invalid");
  const numberOrNull = (value: unknown): number | null => value === null ? null : (typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : (() => { throw new TypeError("progress number is invalid"); })());
  return { operationId: event.operation_id as string, scope: event.scope as ProgressEvent["scope"], stage: event.stage as ProgressEvent["stage"], stageLabel: event.stage_label as string, stageProgress: numberOrNull(event.stage_progress), overallProgress: numberOrNull(event.overall_progress), completedUnits: numberOrNull(event.completed_units), totalUnits: numberOrNull(event.total_units), elapsedSeconds: event.elapsed_seconds as number, etaSeconds: numberOrNull(event.eta_seconds), message: event.message as string, canCancel: event.can_cancel, sequence: event.sequence as number, timestamp: event.timestamp as string };
}

export function assertOutputMode(value: unknown): asserts value is OutputMode {
  if (value !== "summary" && value !== "introduction" && value !== "both") throw new TypeError("unsupported output mode");
}

export type JobStatus =
  | "queued"
  | "acquiring"
  | "extracting"
  | "transcribing"
  | "normalizing"
  | "correcting"
  | "reviewing"
  | "summarizing"
  | "completed"
  | "cancelling"
  | "cancelled"
  | "failed"
  | "cleaning"
  | "archived";

export interface FailureViewModel {
  code: string;
  category?: string;
  message: string;
}

export interface ResilienceViewModel {
  correction_group_count: number;
  correction_attempt_count: number;
  identity_group_count: number;
  review_required_count: number;
  progress_event_count: number;
  last_stage: string | null;
  terminal_status: string;
}

export interface JobViewModel {
  jobId: string;
  sourceLabel: string;
  status: JobStatus;
  progressPercent: number | null;
  summary: string | null;
  resultPath: string | null;
  error: FailureViewModel | null;
}

export interface ReviewItemViewModel {
  segmentId: string;
  startSeconds: number;
  rawText: string;
  proposedText: string;
  reason: string;
}

export interface DesktopState {
  job: JobViewModel;
  reviewItems: readonly ReviewItemViewModel[];
  resilience: ResilienceViewModel | null;
}

export type JobEvent =
  | { type: "created"; jobId: string; sourceLabel: string }
  | { type: "progress"; jobId: string; status: JobStatus; progressPercent: number }
  | { type: "review-ready"; jobId: string; items: readonly ReviewItemViewModel[] }
  | { type: "completed"; jobId: string; summary: string; resultPath: string; resilience?: unknown }
  | { type: "failed"; jobId: string; error: FailureViewModel }
  | { type: "cancelled"; jobId: string };

const STATUSES = new Set<JobStatus>([
  "queued", "acquiring", "extracting", "transcribing", "normalizing",
  "correcting", "reviewing", "summarizing", "completed", "cancelling",
  "cancelled", "failed", "cleaning", "archived",
]);
const TERMINAL_STATUSES = new Set<JobStatus>(["archived", "cancelled", "failed"]);

function assertRecord(value: unknown, name: string): asserts value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
}

function assertNonBlank(value: unknown, name: string): asserts value is string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new TypeError(`${name} must be a non-blank string`);
  }
}

function assertStatus(value: unknown): asserts value is JobStatus {
  if (typeof value !== "string" || !STATUSES.has(value as JobStatus)) {
    throw new TypeError("status must be a supported backend status");
  }
}

function assertProgress(value: unknown): asserts value is number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError("progressPercent must be a finite number");
  }
  if (value < 0 || value > 100) {
    throw new RangeError("progressPercent must be between 0 and 100");
  }
}

function cloneReviewItem(value: unknown): ReviewItemViewModel {
  assertRecord(value, "review item");
  assertNonBlank(value.segmentId, "review item segmentId");
  if (typeof value.startSeconds !== "number" || !Number.isFinite(value.startSeconds)) {
    throw new TypeError("review item startSeconds must be a finite number");
  }
  if (value.startSeconds < 0) {
    throw new RangeError("review item startSeconds must be non-negative");
  }
  assertNonBlank(value.rawText, "review item rawText");
  assertNonBlank(value.proposedText, "review item proposedText");
  assertNonBlank(value.reason, "review item reason");
  return {
    segmentId: value.segmentId,
    startSeconds: value.startSeconds,
    rawText: value.rawText,
    proposedText: value.proposedText,
    reason: value.reason,
  };
}

function cloneResilience(value: unknown): ResilienceViewModel {
  assertRecord(value, "resilience");
  const numberKeys = [
    "correction_group_count",
    "correction_attempt_count",
    "identity_group_count",
    "review_required_count",
    "progress_event_count",
  ];
  for (const key of numberKeys) {
    if (typeof value[key] !== "number" || !Number.isInteger(value[key]) || value[key] < 0) {
      throw new TypeError("resilience " + key + " must be a non-negative integer");
    }
  }
  if (value.last_stage !== null && typeof value.last_stage !== "string") {
    throw new TypeError("resilience last_stage must be a string or null");
  }
  assertNonBlank(value.terminal_status, "resilience terminal_status");
  return {
    correction_group_count: value.correction_group_count as number,
    correction_attempt_count: value.correction_attempt_count as number,
    identity_group_count: value.identity_group_count as number,
    review_required_count: value.review_required_count as number,
    progress_event_count: value.progress_event_count as number,
    last_stage: value.last_stage,
    terminal_status: value.terminal_status,
  };
}

function cloneJob(value: unknown): JobViewModel {
  assertRecord(value, "job");
  if (typeof value.jobId !== "string" || typeof value.sourceLabel !== "string") {
    throw new TypeError("jobId and sourceLabel must be strings");
  }
  assertStatus(value.status);
  if (value.progressPercent !== null) {
    assertProgress(value.progressPercent);
  }
  if (value.summary !== null && typeof value.summary !== "string") {
    throw new TypeError("summary must be a string or null");
  }
  if (value.resultPath !== null && typeof value.resultPath !== "string") {
    throw new TypeError("resultPath must be a string or null");
  }
  let error: FailureViewModel | null = null;
  if (value.error !== null) {
    assertRecord(value.error, "error");
    assertNonBlank(value.error.code, "error code");
    assertNonBlank(value.error.message, "error message");
    if (value.error.category !== undefined) assertNonBlank(value.error.category, "error category");
    error = value.error.category === undefined
      ? { code: value.error.code, message: value.error.message }
      : { code: value.error.code, category: value.error.category, message: value.error.message };
  }
  return {
    jobId: value.jobId,
    sourceLabel: value.sourceLabel,
    status: value.status,
    progressPercent: value.progressPercent,
    summary: value.summary,
    resultPath: value.resultPath,
    error,
  };
}

function cloneState(value: unknown): DesktopState {
  assertRecord(value, "state");
  if (!Array.isArray(value.reviewItems)) {
    throw new TypeError("reviewItems must be an array");
  }
  return {
    job: cloneJob(value.job),
    reviewItems: value.reviewItems.map(cloneReviewItem),
    resilience: value.resilience === undefined || value.resilience === null
      ? null
      : cloneResilience(value.resilience),
  };
}

function isInitial(job: JobViewModel): boolean {
  return job.jobId === "" && job.sourceLabel === "" && job.status === "queued";
}

function isTerminal(job: JobViewModel): boolean {
  return TERMINAL_STATUSES.has(job.status);
}

/** Return a fresh initial job view model for components that need it directly. */
export function createInitialJobViewModel(): JobViewModel {
  return {
    jobId: "",
    sourceLabel: "",
    status: "queued",
    progressPercent: null,
    summary: null,
    resultPath: null,
    error: null,
  };
}

/** Return a detached, empty desktop state before the first backend job event. */
export function createInitialDesktopState(): DesktopState {
  return { job: createInitialJobViewModel(), reviewItems: [], resilience: null };
}

/** Apply one validated backend event without mutating either input value. */
export function reduceJobEvent(state: DesktopState, event: JobEvent): DesktopState {
  const current = cloneState(state);
  assertRecord(event, "event");
  if (typeof event.type !== "string") {
    throw new TypeError("event type must be a string");
  }

  if (event.type === "created") {
    assertNonBlank(event.jobId, "event jobId");
    assertNonBlank(event.sourceLabel, "event sourceLabel");
    if (!isInitial(current.job) && !isTerminal(current.job)) {
      throw new Error("cannot replace an active job");
    }
    return {
      job: {
        jobId: event.jobId,
        sourceLabel: event.sourceLabel,
        status: "queued",
        progressPercent: null,
        summary: null,
        resultPath: null,
        error: null,
      },
      reviewItems: [],
      resilience: null,
    };
  }

  assertNonBlank(event.jobId, "event jobId");
  if (event.jobId !== current.job.jobId || isTerminal(current.job)) {
    return current;
  }

  if (event.type === "progress") {
    assertStatus(event.status);
    if (TERMINAL_STATUSES.has(event.status)) {
      throw new TypeError("progress status must be non-terminal");
    }
    assertProgress(event.progressPercent);
    return {
      job: { ...current.job, status: event.status, progressPercent: event.progressPercent, error: null },
      reviewItems: current.reviewItems,
      resilience: current.resilience,
    };
  }
  if (event.type === "review-ready") {
    if (!Array.isArray(event.items)) {
      throw new TypeError("review-ready items must be an array");
    }
    return {
      job: { ...current.job, status: "reviewing", progressPercent: null, error: null },
      reviewItems: event.items.map(cloneReviewItem),
      resilience: current.resilience,
    };
  }
  if (event.type === "completed") {
    assertNonBlank(event.summary, "completed summary");
    assertNonBlank(event.resultPath, "completed resultPath");
    return {
      job: {
        ...current.job,
        status: "archived",
        progressPercent: null,
        summary: event.summary,
        resultPath: event.resultPath,
        error: null,
      },
      reviewItems: current.reviewItems,
      resilience: event.resilience === undefined || event.resilience === null ? null : cloneResilience(event.resilience),
    };
  }
  if (event.type === "failed") {
    const error = cloneJob({ ...current.job, error: event.error }).error;
    if (error === null) {
      throw new TypeError("failed event error is required");
    }
    return {
      job: { ...current.job, status: "failed", progressPercent: null, error },
      reviewItems: current.reviewItems,
      resilience: current.resilience,
    };
  }
  if (event.type === "cancelled") {
    return {
      job: { ...current.job, status: "cancelled", progressPercent: null },
      reviewItems: current.reviewItems,
      resilience: current.resilience,
    };
  }
  throw new TypeError("unsupported event type");
}
