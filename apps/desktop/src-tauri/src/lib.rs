use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Read};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock, mpsc};
use std::thread;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter};

const DEFAULT_QWEN_MODEL: &str = "qwen3.6:35b-a3b-agent-64k";
const DEFAULT_MODEL_PATH: &str = r"D:\AI-Legion\Sodam-models\faster-whisper\turbo-0a363e9";
const DEFAULT_FFMPEG_PATH: &str = r"D:\AI-Legion\Sodam-data\tools\ffmpeg-9.0.1\bin\ffmpeg.exe";
const DEFAULT_PYTHON_PATH: &str = r"D:\AI-Legion\Sodam-runtime\Scripts\python.exe";
const WINDOWS_HIDE_CONSOLE: u32 = 0x0800_0000;
const MAX_STDERR_LINES: usize = 2;
const MAX_STDERR_CHARS: usize = 240;

#[derive(serde::Serialize)]
struct ShellReadiness {
    shell_version: &'static str,
    backend_connected: bool,
    message: String,
}

#[derive(serde::Deserialize)]
struct StartJobRequest {
    source: String,
    output_mode: String,
    runtime_profile_name: String,
}

#[derive(serde::Deserialize)]
struct StartSetupRequest {
    runtime_profile_name: String,
}

#[derive(serde::Serialize)]
struct OperationAccepted {
    operation_id: String,
}

#[derive(serde::Serialize)]
struct CancelResponse {
    operation_id: String,
    cancelled: bool,
}

#[derive(serde::Serialize)]
struct SourcePreflight {
    file_name: String,
    byte_length: u64,
}

#[derive(Clone)]
struct OperationHandle {
    cancel: Arc<AtomicBool>,
    child: Arc<Mutex<Option<Child>>>,
}

static OPERATIONS: OnceLock<Mutex<HashMap<String, OperationHandle>>> = OnceLock::new();
static NEXT_OPERATION_ID: AtomicU64 = AtomicU64::new(1);

fn operations() -> &'static Mutex<HashMap<String, OperationHandle>> {
    OPERATIONS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn require_non_blank(value: &str, field: &str) -> Result<(), String> {
    if value.trim().is_empty() {
        return Err(format!("{}는 비어 있을 수 없습니다.", field));
    }
    Ok(())
}

fn repository_root() -> Result<PathBuf, String> {
    if let Ok(value) = std::env::var("SODAM_REPOSITORY_ROOT") {
        let candidate = PathBuf::from(value);
        if candidate.join("tools").join("run_local.py").is_file() {
            return Ok(candidate);
        }
        return Err("SODAM_REPOSITORY_ROOT에 tools/run_local.py가 없습니다.".to_owned());
    }

    let mut candidates = Vec::new();
    if let Ok(current) = std::env::current_dir() {
        candidates.push(current);
    }
    if let Ok(executable) = std::env::current_exe() {
        candidates.extend(executable.ancestors().map(Path::to_path_buf));
    }
    candidates
        .into_iter()
        .find(|candidate| candidate.join("tools").join("run_local.py").is_file())
        .ok_or_else(|| {
            "tools/run_local.py를 찾을 수 없습니다. SODAM_REPOSITORY_ROOT를 설정하세요.".to_owned()
        })
}

fn python_command() -> Result<String, String> {
    if let Ok(value) = std::env::var("SODAM_PYTHON") {
        let trimmed = value.trim();
        if trimmed.is_empty() {
            return Err("SODAM_PYTHON이 비어 있습니다.".to_owned());
        }
        let candidate = Path::new(trimmed);
        if candidate.components().count() > 1 {
            if candidate.is_file() {
                return Ok(trimmed.to_owned());
            }
            return Err(format!("SODAM_PYTHON 파일을 찾을 수 없습니다: {}", trimmed));
        }
        if matches!(trimmed, "python" | "python3" | "py") {
            return Ok(trimmed.to_owned());
        }
        return Err("SODAM_PYTHON은 python, python3, py 또는 절대 경로여야 합니다.".to_owned());
    }
    if Path::new(DEFAULT_PYTHON_PATH).is_file() {
        return Ok(DEFAULT_PYTHON_PATH.to_owned());
    }
    Ok(if cfg!(windows) { "python" } else { "python3" }.to_owned())
}

fn model_path() -> PathBuf {
    std::env::var("SODAM_MODEL_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(DEFAULT_MODEL_PATH))
}

fn ffmpeg_path() -> Option<PathBuf> {
    let candidate = std::env::var("SODAM_FFMPEG")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(DEFAULT_FFMPEG_PATH));
    candidate.is_file().then_some(candidate)
}

fn operation_handle() -> (String, OperationHandle) {
    let id = format!("op-{}", NEXT_OPERATION_ID.fetch_add(1, Ordering::Relaxed));
    let handle = OperationHandle {
        cancel: Arc::new(AtomicBool::new(false)),
        child: Arc::new(Mutex::new(None)),
    };
    if let Ok(mut state) = operations().lock() {
        state.insert(id.clone(), handle.clone());
    }
    (id, handle)
}

fn emit<T: Serialize + Clone>(app: &AppHandle, name: &str, payload: T) {
    let _ = app.emit(name, payload);
}

fn emit_failure(app: &AppHandle, operation_id: &str, code: &str, message: String) {
    emit_failure_with_category(
        app,
        operation_id,
        code,
        safe_category_for_code(code),
        message,
    );
}

fn emit_failure_with_category(
    app: &AppHandle,
    operation_id: &str,
    code: &str,
    category: &str,
    message: String,
) {
    emit(
        app,
        "job_failed",
        serde_json::json!({
            "operation_id": operation_id,
            "error": {"code": code, "category": category, "message": message}
        }),
    );
}

fn handle_progress_line(app: &AppHandle, operation_id: &str, line: &str) -> bool {
    let Ok(mut value) = serde_json::from_str::<serde_json::Value>(line) else {
        return false;
    };
    let Some(object) = value.as_object_mut() else {
        return false;
    };
    object.insert("operation_id".to_owned(), serde_json::json!(operation_id));
    emit(app, "progress", value);
    true
}

fn sanitize_stderr_line(line: &str) -> String {
    let lower = line.to_ascii_lowercase();
    for category in [
        "model_response",
        "transcription",
        "media_extraction",
        "input_source",
        "storage",
        "protection",
    ] {
        if lower.contains(category) {
            return format!("{}: [redacted backend detail]", category);
        }
    }
    if lower.contains("prompt")
        || lower.contains("transcript")
        || lower.contains("source")
        || lower.contains("model")
        || lower.contains(":\\")
        || lower.contains(":/")
    {
        return "[redacted backend detail]".to_owned();
    }
    let mut value = line.trim().to_owned();
    if value.len() > MAX_STDERR_CHARS {
        value.truncate(MAX_STDERR_CHARS);
    }
    value
}

fn remember_stderr_line(tail: &mut VecDeque<String>, line: &str) {
    let sanitized = sanitize_stderr_line(line);
    if sanitized.is_empty() {
        return;
    }
    if tail.len() >= MAX_STDERR_LINES {
        tail.pop_front();
    }
    tail.push_back(sanitized);
}

fn drain_stderr_line(
    app: &AppHandle,
    operation_id: &str,
    line: &str,
    tail: &mut VecDeque<String>,
) {
    if !handle_progress_line(app, operation_id, line) {
        remember_stderr_line(tail, line);
    }
}

fn safe_category_for_code(code: &str) -> &'static str {
    if code.contains("PYTHON") || code.contains("BACKEND") {
        "runtime_error"
    } else if code.contains("SOURCE") || code.contains("PREFLIGHT") {
        "input_source"
    } else {
        "runtime_error"
    }
}

fn classify_stderr_tail(tail: &VecDeque<String>) -> &'static str {
    for line in tail {
        let lower = line.to_ascii_lowercase();
        if lower.contains("model_response") {
            return "model_response";
        }
        if lower.contains("transcription") {
            return "transcription";
        }
        if lower.contains("media_extraction") {
            return "media_extraction";
        }
        if lower.contains("input_source") {
            return "input_source";
        }
        if lower.contains("storage") {
            return "storage";
        }
        if lower.contains("protection") {
            return "protection";
        }
    }
    "runtime_error"
}

fn valid_backend_report(report: &serde_json::Value) -> bool {
    report.is_object()
        && report
            .get("resilience")
            .map(|value| value.is_object())
            .unwrap_or(true)
}

fn run_backend(
    app: AppHandle,
    operation_id: String,
    source: String,
    output_mode: String,
    handle: OperationHandle,
) {
    let root = match repository_root() {
        Ok(value) => value,
        Err(error) => {
            let _ = error;
            emit_failure(
                &app,
                &operation_id,
                "BACKEND_UNAVAILABLE",
                "Python backend를 찾을 수 없습니다.".to_owned(),
            );
            remove_operation(&operation_id);
            return;
        }
    };
    let python = match python_command() {
        Ok(value) => value,
        Err(error) => {
            let _ = error;
            emit_failure(
                &app,
                &operation_id,
                "PYTHON_UNAVAILABLE",
                "Python 실행 환경을 찾을 수 없습니다.".to_owned(),
            );
            remove_operation(&operation_id);
            return;
        }
    };

    let mut command = Command::new(python);
    command
        .current_dir(root.clone())
        .arg("-B")
        .arg(root.join("tools").join("run_local.py"))
        .arg("--mode")
        .arg("run")
        .arg("--output-mode")
        .arg(output_mode)
        .arg("--progress-format")
        .arg("jsonl")
        .arg("--model-path")
        .arg(model_path())
        .arg("--qwen-model")
        .arg(DEFAULT_QWEN_MODEL)
        .arg(source)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(ffmpeg) = ffmpeg_path() {
        if let Some(bin_dir) = ffmpeg.parent() {
            let separator = if cfg!(windows) { ";" } else { ":" };
            let current_path = std::env::var("PATH").unwrap_or_default();
            command.env(
                "PATH",
                format!("{}{}{}", bin_dir.display(), separator, current_path),
            );
        }
    }
    #[cfg(windows)]
    command.creation_flags(WINDOWS_HIDE_CONSOLE);

    let mut child = match command.spawn() {
        Ok(value) => value,
        Err(error) => {
            let _ = error;
            emit_failure(
                &app,
                &operation_id,
                "BACKEND_START_FAILED",
                "Python backend를 시작할 수 없습니다.".to_owned(),
            );
            remove_operation(&operation_id);
            return;
        }
    };
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    if let Ok(mut slot) = handle.child.lock() {
        *slot = Some(child);
    } else {
        emit_failure(
            &app,
            &operation_id,
            "BACKEND_STATE_FAILED",
            "작업 상태를 저장할 수 없습니다.".to_owned(),
        );
        remove_operation(&operation_id);
        return;
    }

    let (line_tx, line_rx) = mpsc::channel::<String>();
    let stderr_thread = stderr.map(|stream| {
        let tx = line_tx.clone();
        thread::spawn(move || {
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                let _ = tx.send(line);
            }
        })
    });
    drop(line_tx);
    let stdout_thread = stdout.map(|stream| {
        thread::spawn(move || {
            let mut output = String::new();
            let _ = BufReader::new(stream).read_to_string(&mut output);
            output
        })
    });

    let mut cancelled = false;
    let mut stderr_tail = VecDeque::new();
    let status = loop {
        while let Ok(line) = line_rx.try_recv() {
            drain_stderr_line(&app, &operation_id, &line, &mut stderr_tail);
        }
        if handle.cancel.load(Ordering::SeqCst) {
            cancelled = true;
            if let Ok(mut slot) = handle.child.lock() {
                if let Some(process) = slot.as_mut() {
                    let _ = process.kill();
                }
            }
        }
        let result = match handle.child.lock() {
            Ok(mut slot) => match slot.as_mut() {
                Some(process) => process.try_wait(),
                None => Ok(None),
            },
            Err(_) => Err(std::io::Error::other("작업 상태 잠금 실패")),
        };
        match result {
            Ok(Some(value)) => break value,
            Ok(None) => thread::sleep(Duration::from_millis(50)),
            Err(error) => {
                emit_failure(
                    &app,
                    &operation_id,
                    "BACKEND_WAIT_FAILED",
                    "backend 프로세스 상태를 확인할 수 없습니다.".to_owned(),
                );
                remove_operation(&operation_id);
                return;
            }
        }
    };
    while let Ok(line) = line_rx.try_recv() {
        drain_stderr_line(&app, &operation_id, &line, &mut stderr_tail);
    }
    if let Some(thread) = stderr_thread {
        let _ = thread.join();
    }
    while let Ok(line) = line_rx.try_recv() {
        drain_stderr_line(&app, &operation_id, &line, &mut stderr_tail);
    }
    let stdout_text = stdout_thread
        .and_then(|thread| thread.join().ok())
        .unwrap_or_default();

    if cancelled {
        emit(
            &app,
            "job_cancelled",
            serde_json::json!({"operation_id": operation_id}),
        );
    } else if status.success() {
        match serde_json::from_str::<serde_json::Value>(stdout_text.trim()) {
            Ok(report) if valid_backend_report(&report) => emit(
                &app,
                "job_result",
                serde_json::json!({"operation_id": operation_id, "report": report}),
            ),
            _ => emit_failure(
                &app,
                &operation_id,
                "INVALID_BACKEND_RESULT",
                "backend가 올바른 JSON 결과를 반환하지 않았습니다.".to_owned(),
            ),
        }
    } else {
        let category = classify_stderr_tail(&stderr_tail);
        let tail = stderr_tail.iter().cloned().collect::<Vec<_>>().join(" | ");
        let message = if tail.is_empty() {
            "backend 작업에 실패했습니다.".to_owned()
        } else {
            format!("backend 작업에 실패했습니다: {}", tail)
        };
        emit_failure_with_category(
            &app,
            &operation_id,
            "BACKEND_FAILED",
            category,
            message,
        );
    }
    remove_operation(&operation_id);
}

fn remove_operation(operation_id: &str) {
    if let Ok(mut state) = operations().lock() {
        state.remove(operation_id);
    }
}

#[tauri::command]
fn doctor_report() -> Result<serde_json::Value, String> {
    let root = repository_root();
    let python = python_command();
    let ffmpeg = ffmpeg_path().is_some();
    let model = model_path().is_dir();
    let script_ready = root.is_ok();
    let python_ready = python.is_ok();
    let backend_connected = script_ready && python_ready;
    let mut required_actions = Vec::new();
    if !script_ready {
        required_actions.push("SODAM_REPOSITORY_ROOT 또는 tools/run_local.py 확인");
    }
    if !python_ready {
        required_actions.push("SODAM_PYTHON 확인");
    }
    if !ffmpeg {
        required_actions.push("SODAM_FFMPEG 절대 경로 설정");
    }
    if !model {
        required_actions.push("faster-whisper 모델 경로 확인");
    }
    Ok(serde_json::json!({
        "is_ready": backend_connected && ffmpeg && model,
        "backend_connected": backend_connected,
        "qwen_model": DEFAULT_QWEN_MODEL,
        "checks": {"python": python_ready, "backend_script": script_ready, "ffmpeg": ffmpeg, "stt_model": model},
        "required_actions": required_actions,
    }))
}

#[tauri::command]
fn shell_readiness() -> ShellReadiness {
    let connected = repository_root().is_ok() && python_command().is_ok();
    ShellReadiness {
        shell_version: env!("CARGO_PKG_VERSION"),
        backend_connected: connected,
        message: if connected {
            "Python backend 연결 준비됨".to_owned()
        } else {
            "Python backend를 찾을 수 없습니다".to_owned()
        },
    }
}

#[tauri::command]
fn start_job(app: AppHandle, request: StartJobRequest) -> Result<OperationAccepted, String> {
    require_non_blank(&request.source, "source")?;
    require_non_blank(&request.runtime_profile_name, "runtime_profile_name")?;
    if !matches!(
        request.output_mode.as_str(),
        "summary" | "introduction" | "both"
    ) {
        return Err("output_mode가 올바르지 않습니다.".to_owned());
    }
    preflight_source(request.source.clone())?;
    let (operation_id, handle) = operation_handle();
    let worker_id = operation_id.clone();
    thread::spawn(move || run_backend(app, worker_id, request.source, request.output_mode, handle));
    Ok(OperationAccepted { operation_id })
}

#[tauri::command]
fn start_setup(request: StartSetupRequest) -> Result<OperationAccepted, String> {
    require_non_blank(&request.runtime_profile_name, "runtime_profile_name")?;
    Err("개인용 실행에서는 setup.py를 직접 실행하세요.".to_owned())
}

#[tauri::command]
fn cancel_job(operation_id: String) -> Result<CancelResponse, String> {
    require_non_blank(&operation_id, "operation_id")?;
    let key = operation_id.trim();
    let handle = operations()
        .lock()
        .map_err(|_| "작업 상태를 읽을 수 없습니다.".to_owned())?
        .get(key)
        .cloned()
        .ok_or_else(|| "작업을 찾을 수 없습니다.".to_owned())?;
    let cancelled = !handle.cancel.swap(true, Ordering::SeqCst);
    if let Ok(mut slot) = handle.child.lock() {
        if let Some(process) = slot.as_mut() {
            let _ = process.kill();
        }
    }
    Ok(CancelResponse {
        operation_id: key.to_owned(),
        cancelled,
    })
}

#[tauri::command]
fn preflight_source(path: String) -> Result<SourcePreflight, String> {
    let candidate = Path::new(path.trim());
    let metadata = std::fs::symlink_metadata(candidate)
        .map_err(|_| "선택한 파일을 확인할 수 없습니다.".to_owned())?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("일반 로컬 파일만 선택할 수 있습니다.".to_owned());
    }
    let extension = candidate
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
        .ok_or_else(|| "지원하지 않는 파일 형식입니다.".to_owned())?;
    if !["mp3", "m4a", "wav", "flac", "mp4", "mkv", "mov", "webm"].contains(&extension.as_str()) {
        return Err("지원하지 않는 파일 형식입니다.".to_owned());
    }
    let file_name = candidate
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "파일 이름을 확인할 수 없습니다.".to_owned())?;
    Ok(SourcePreflight {
        file_name: file_name.to_owned(),
        byte_length: metadata.len(),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            shell_readiness,
            doctor_report,
            preflight_source,
            start_job,
            start_setup,
            cancel_job
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Sodam desktop shell");
}
