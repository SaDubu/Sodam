/**
 * UI-only state contracts for the eventual Tauri desktop shell.
 *
 * This module intentionally has no framework imports, command invocations, or
 * file/URL actions.  Those integrations require their own approved tasks.
 */

export type JobStatus =
  | "queued"
  | "running"
  | "reviewing"
  | "completed"
  | "failed"
  | "cancelled";

export interface JobViewModel {
  jobId: string;
  sourceLabel: string;
  status: JobStatus;
  progressPercent: number | null;
  summary: string | null;
}

export interface ReviewItemViewModel {
  segmentId: string;
  startSeconds: number;
  rawText: string;
  proposedText: string;
  reason: string;
}

/** Return a fresh UI state before any job has been created. */
export function createInitialJobViewModel(): JobViewModel {
  return {
    jobId: "",
    sourceLabel: "",
    status: "queued",
    progressPercent: null,
    summary: null,
  };
}
