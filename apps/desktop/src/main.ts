import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import { assertOutputMode, createInitialDesktopState, createInitialProgressState, reduceProgressEvent, type OutputMode, type ProgressViewState } from "./state";
import type { BackendProgressEvent } from "./progress-contract";

const state = createInitialDesktopState();
const app = document.querySelector<HTMLElement>("#app");
if (app === null) throw new Error("desktop root element is missing");

app.innerHTML = `
  <main class="panel" aria-labelledby="title">
    <p class="eyebrow">Sodam · 영상 소개글 & 요약</p>
    <h1 id="title">로컬 영상 처리</h1>
    <p class="lede">전사부터 요약·소개글 생성까지, 현재 단계와 남은 시간을 확인할 수 있습니다.</p>
    <section aria-labelledby="input-title">
      <h2 id="input-title">입력과 출력</h2>
      <button id="select-source" type="button">로컬 미디어 선택</button>
      <span id="selected-source">선택되지 않음</span>
      <button id="preflight-source" type="button">파일 확인</button>
      <label for="output-mode">출력 모드</label>
      <select id="output-mode" name="output-mode">
        <option value="summary">요약</option><option value="introduction">소개글</option><option value="both">요약 + 소개글</option>
      </select>
      <button id="start-job" type="button" disabled>작업 시작</button>
      <button id="cancel-job" type="button" disabled>취소</button>
    </section>
    <section aria-labelledby="progress-title" class="progress-section">
      <h2 id="progress-title">진행 상황</h2>
      <p id="stage-label">대기 중</p>
      <progress id="overall-progress" max="100" value="0" aria-label="전체 진행률"></progress>
      <span id="progress-value" aria-live="polite">진행률 확인 중</span>
      <dl><dt>경과 시간</dt><dd id="elapsed">0초</dd><dt>예상 남은 시간</dt><dd id="eta">계산 중</dd></dl>
      <p id="progress-message" aria-live="polite"></p>
      <p id="resilience-summary" aria-live="polite"></p>
    </section>
    <p id="ipc-readiness" role="status">IPC 확인 중</p>
    <p id="doctor-readiness" role="status">환경 확인 중</p>
    <p id="preflight-result" role="status"></p>
    <section aria-labelledby="result-title" class="results">
      <h2 id="result-title">결과</h2>
      <div role="tablist" aria-label="결과 탭">
        <button role="tab" aria-selected="true" data-tab="transcript" type="button">전사</button>
        <button role="tab" aria-selected="false" data-tab="summary" type="button">요약</button>
        <button role="tab" aria-selected="false" data-tab="introduction" type="button">소개글</button>
        <button role="tab" aria-selected="false" data-tab="review" type="button">검토</button>
      </div>
      <article id="result-panel" role="tabpanel" tabindex="0">작업을 시작하면 결과가 표시됩니다.</article>
    </section>
  </main>
`;

const $ = <T extends HTMLElement>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (element === null) throw new Error(`missing UI element: ${selector}`);
  return element;
};

const readiness = $("#ipc-readiness");
const doctorReadiness = $("#doctor-readiness");
const selectedSource = $("#selected-source");
const sourceButton = $("#select-source") as HTMLButtonElement;
const preflightResult = $("#preflight-result");
const preflightButton = $("#preflight-source") as HTMLButtonElement;
const outputMode = $("#output-mode") as HTMLSelectElement;
const startButton = $("#start-job") as HTMLButtonElement;
const cancelButton = $("#cancel-job") as HTMLButtonElement;
const stageLabel = $("#stage-label");
const overallProgress = $("#overall-progress") as HTMLProgressElement;
const progressValue = $("#progress-value");
const elapsed = $("#elapsed");
const eta = $("#eta");
const progressMessage = $("#progress-message");
const resilienceSummary = $("#resilience-summary");
const resultPanel = $("#result-panel");

interface ShellReadiness { shell_version: string; backend_connected: boolean; message: string; }
interface DoctorReport { is_ready: boolean; required_actions: unknown[]; }
interface ResilienceReport {
  correction_group_count: number;
  correction_attempt_count: number;
  identity_group_count: number;
  review_required_count: number;
  progress_event_count: number;
  last_stage: string | null;
  terminal_status: string;
}
interface JobReport {
  transcript?: string | null;
  summary?: string | null;
  introduction?: { title?: string; body?: string; highlights?: string[] } | null;
  review_item_count?: number;
  result_path?: string;
  resilience?: ResilienceReport;
}
let selectedSourcePath: string | null = null;
let operationId: string | null = null;
let progress: ProgressViewState = createInitialProgressState();
let latestReport: JobReport | null = null;
let activeTab = "transcript";

function renderResultTab(tab: string): void {
  if (latestReport === null) {
    resultPanel.textContent = "작업을 시작하면 결과가 표시됩니다.";
    return;
  }
  if (tab === "transcript") resultPanel.textContent = latestReport.transcript ?? "전사 결과가 없습니다.";
  else if (tab === "summary") resultPanel.textContent = latestReport.summary ?? "요약 결과가 없습니다.";
  else if (tab === "introduction") {
    const introduction = latestReport.introduction;
    resultPanel.textContent = introduction === null || introduction === undefined
      ? "소개글 결과가 없습니다."
      : [introduction.title, introduction.body, ...(introduction.highlights ?? [])].filter(Boolean).join("\n\n");
  } else {
    resultPanel.textContent = `검토 항목 ${latestReport.review_item_count ?? 0}개\n결과 저장 완료: ${latestReport.result_path ?? "외부 결과 폴더"}`;
  }
}

function renderProgress(): void {
  stageLabel.textContent = progress.stageLabel;
  progressMessage.textContent = progress.message;
  elapsed.textContent = `${Math.round(progress.elapsedSeconds)}초`;
  eta.textContent = progress.etaSeconds === null ? "계산 중" : `${Math.round(progress.etaSeconds)}초`;
  if (progress.overallProgress === null) {
    overallProgress.removeAttribute("value");
    progressValue.textContent = "진행률 계산 중";
  } else {
    overallProgress.value = progress.overallProgress;
    progressValue.textContent = `${Math.round(progress.overallProgress)}%`;
  }
  const resilience = latestReport?.resilience;
  resilienceSummary.textContent = resilience === undefined
    ? ""
    : "재시도 " + resilience.correction_attempt_count + "회 · 원문 유지 "
      + resilience.identity_group_count + "개 · 검토 필요 "
      + resilience.review_required_count + "개";
  cancelButton.disabled = !progress.canCancel || progress.terminal;
}

void invoke<ShellReadiness>("shell_readiness").then((report) => {
  readiness.textContent = `${report.message} (shell ${report.shell_version})`;
}).catch(() => { readiness.textContent = "IPC 준비 상태를 확인할 수 없습니다."; });
void invoke<DoctorReport>("doctor_report").then((report) => {
  doctorReadiness.textContent = report.is_ready ? "환경 준비됨" : `준비 필요: ${report.required_actions.length}개 항목`;
}).catch(() => { doctorReadiness.textContent = "환경 진단을 확인할 수 없습니다."; });

sourceButton.addEventListener("click", () => {
  void open({ multiple: false, directory: false, filters: [{ name: "Media", extensions: ["mp3", "m4a", "wav", "flac", "mp4", "mkv", "mov", "webm"] }] }).then((value) => {
    if (typeof value !== "string" || value.trim() === "") return;
    selectedSourcePath = value;
    selectedSource.textContent = value.split(/[\\/]/).at(-1) ?? "선택됨";
    startButton.disabled = false;
  });
});

preflightButton.addEventListener("click", () => {
  if (selectedSourcePath === null) { preflightResult.textContent = "먼저 미디어 파일을 선택하세요."; return; }
  void invoke<{ file_name: string; byte_length: number }>("preflight_source", { path: selectedSourcePath }).then((report) => {
    preflightResult.textContent = `${report.file_name}: ${report.byte_length} bytes, 실행 준비됨`;
  }).catch(() => { preflightResult.textContent = "선택한 파일을 사용할 수 없습니다."; });
});

startButton.addEventListener("click", () => {
  if (selectedSourcePath === null) return;
  try { assertOutputMode(outputMode.value); } catch { preflightResult.textContent = "출력 모드를 확인할 수 없습니다."; return; }
  const selectedMode = outputMode.value as OutputMode;
  void invoke<{ operation_id: string }>("start_job", { request: { source: selectedSourcePath, output_mode: selectedMode, runtime_profile_name: "quality" } }).then((accepted) => {
    operationId = accepted.operation_id;
    latestReport = null;
    progress = createInitialProgressState();
    renderProgress();
    startButton.disabled = true;
  }).catch(() => { preflightResult.textContent = "작업을 시작할 수 없습니다."; });
});

cancelButton.addEventListener("click", () => {
  if (operationId === null) return;
  void invoke("cancel_job", { operationId }).then(() => { progress = { ...progress, canCancel: false, terminal: true, stageLabel: "취소됨" }; renderProgress(); });
});

for (const tab of document.querySelectorAll<HTMLButtonElement>("[data-tab]")) {
  tab.addEventListener("click", () => {
    for (const candidate of document.querySelectorAll<HTMLButtonElement>("[data-tab]")) candidate.setAttribute("aria-selected", String(candidate === tab));
    activeTab = tab.dataset.tab ?? "transcript";
    renderResultTab(activeTab);
  });
}

void listen<BackendProgressEvent>("progress", (event) => {
  try { progress = reduceProgressEvent(progress, event.payload); renderProgress(); } catch { progressMessage.textContent = "잘못된 진행 이벤트를 무시했습니다."; }
});

void listen<{ operation_id: string; report: JobReport }>("job_result", (event) => {
  if (operationId !== null && event.payload.operation_id !== operationId) return;
  latestReport = event.payload.report;
  operationId = null;
  const identityCount = latestReport.resilience?.identity_group_count ?? 0;
  progress = {
    ...progress,
    canCancel: false,
    terminal: true,
    stageLabel: identityCount > 0 ? "완료(검토 필요)" : "완료",
    message: identityCount > 0 ? "원문 유지 항목이 있어 검토가 필요합니다." : "작업이 완료되었습니다.",
  };
  startButton.disabled = selectedSourcePath === null;
  renderProgress();
  renderResultTab(activeTab);
});

void listen<{ operation_id: string; error?: { code?: string; category?: string; message?: string } }>("job_failed", (event) => {
  if (operationId !== null && event.payload.operation_id !== operationId) return;
  operationId = null;
  const error = event.payload.error;
  const category = error?.category ?? error?.code ?? "runtime_error";
  progress = {
    ...progress,
    canCancel: false,
    terminal: true,
    stageLabel: "실패",
    message: category + ": " + (error?.message ?? "backend 작업이 실패했습니다."),
  };
  startButton.disabled = selectedSourcePath === null;
  renderProgress();
});

void listen<{ operation_id: string }>("job_cancelled", (event) => {
  if (operationId !== null && event.payload.operation_id !== operationId) return;
  operationId = null;
  progress = { ...progress, canCancel: false, terminal: true, stageLabel: "취소됨", message: "작업이 취소되었습니다." };
  startButton.disabled = selectedSourcePath === null;
  renderProgress();
});

renderProgress();
