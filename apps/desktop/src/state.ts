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

/**
 * Declare the future initial-state factory.
 * It will validate only UI state once B13 exposes a local backend contract.
 */
export function createInitialJobViewModel(): JobViewModel {
  throw new Error("U01: createInitialJobViewModel has not been implemented");
}
