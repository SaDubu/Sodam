/** Shared desktop declarations and boundary normalization for progress. */

export type OutputMode = "summary" | "introduction" | "both";

export type ProgressScope = "setup" | "job";

export type ProgressStage =
  | "environment_check"
  | "dependency_install"
  | "model_download"
  | "source_validation"
  | "source_acquisition"
  | "audio_extraction"
  | "transcription"
  | "text_protection"
  | "rule_normalization"
  | "correction"
  | "review_validation"
  | "transcript_assembly"
  | "summarization"
  | "introduction"
  | "persistence"
  | "cleanup"
  | "completed"
  | "failed"
  | "cancelled";

const PROGRESS_STAGES = new Set<ProgressStage>([
  "environment_check", "dependency_install", "model_download", "source_validation", "source_acquisition",
  "audio_extraction", "transcription", "text_protection", "rule_normalization", "correction",
  "review_validation", "transcript_assembly", "summarization", "introduction", "persistence", "cleanup",
  "completed", "failed", "cancelled",
]);

export interface ProgressEvent {
  readonly operationId: string;
  readonly scope: ProgressScope;
  readonly stage: ProgressStage;
  readonly stageLabel: string;
  readonly stageProgress: number | null;
  readonly overallProgress: number | null;
  readonly completedUnits: number | null;
  readonly totalUnits: number | null;
  readonly elapsedSeconds: number;
  readonly etaSeconds: number | null;
  readonly message: string;
  readonly canCancel: boolean;
  readonly sequence: number;
  readonly timestamp: string;
}

export interface VideoIntroductionViewModel {
  readonly titleHook: string;
  readonly body: string;
  readonly highlights: readonly string[];
  readonly evidenceSegmentIds: readonly string[];
  readonly callToAction: string;
}

export interface StartJobRequest {
  readonly source: string;
  readonly outputMode: OutputMode;
  readonly runtimeProfileName: string;
}

export interface BackendProgressEvent {
  operation_id: string;
  scope: ProgressScope;
  stage: ProgressStage;
  stage_label: string;
  stage_progress: number | null;
  overall_progress: number | null;
  completed_units: number | null;
  total_units: number | null;
  elapsed_seconds: number;
  eta_seconds: number | null;
  message: string;
  can_cancel: boolean;
  sequence: number;
  timestamp: string;
}

function finiteOrNull(value: unknown, name: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new TypeError(`${name} must be a finite non-negative number or null`);
  }
  return value;
}

/** Normalize and validate snake_case backend events at the IPC boundary. */
export function normalizeProgressEvent(value: unknown): ProgressEvent {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("progress event must be an object");
  }
  const event = value as Record<string, unknown>;
  if (typeof event.operation_id !== "string" || event.operation_id.trim() === "") throw new TypeError("operation_id is required");
  if (typeof event.scope !== "string" || !["setup", "job"].includes(event.scope)) throw new TypeError("invalid progress scope");
  if (typeof event.stage !== "string" || !PROGRESS_STAGES.has(event.stage as ProgressStage)) throw new TypeError("invalid progress stage");
  if (typeof event.stage_label !== "string" || typeof event.message !== "string") throw new TypeError("progress text is required");
  if (typeof event.elapsed_seconds !== "number" || !Number.isFinite(event.elapsed_seconds) || event.elapsed_seconds < 0) throw new TypeError("elapsed_seconds is invalid");
  if (typeof event.sequence !== "number" || !Number.isInteger(event.sequence) || event.sequence < 0) throw new TypeError("sequence is invalid");
  if (typeof event.can_cancel !== "boolean") throw new TypeError("can_cancel is invalid");
  return {
    operationId: event.operation_id,
    scope: event.scope as ProgressScope,
    stage: event.stage as ProgressStage,
    stageLabel: event.stage_label,
    stageProgress: finiteOrNull(event.stage_progress, "stage_progress"),
    overallProgress: finiteOrNull(event.overall_progress, "overall_progress"),
    completedUnits: finiteOrNull(event.completed_units, "completed_units"),
    totalUnits: finiteOrNull(event.total_units, "total_units"),
    elapsedSeconds: event.elapsed_seconds,
    etaSeconds: finiteOrNull(event.eta_seconds, "eta_seconds"),
    message: event.message,
    canCancel: event.can_cancel,
    sequence: event.sequence,
    timestamp: typeof event.timestamp === "string" ? event.timestamp : "",
  };
}
