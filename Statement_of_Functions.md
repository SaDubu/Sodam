# CR-07 — 실제 Local Pipeline·Desktop Smoke 검증

## 작업 ID와 목적

- 작업 ID: CR-07
- 목적: CI에서 검증한 desktop bundle과 기존 local-first pipeline을 실제
  짧은 WAV 한 건으로 연결해 backend 결과, progress/resilience 보고, Tauri
  process 기동을 확인한다.

## 승인된 입력·외부 동작

- 입력: `D:\AI-Legion\Sodam-data\tmp\v2-e2e-r2\sample.wav`
- 실행 runtime: repository 밖의 FFmpeg, faster-whisper `turbo`, local Ollama
  `qwen3.6:35b-a3b-agent-64k` loopback endpoint
- artifact: Sodam-data 아래 이 실행의 job 결과만 생성·보존한다. Git worktree와
  source WAV는 수정·삭제하지 않는다.
- 허용: local subprocess, local model inference, Tauri debug process start,
  read-only job inspection.

## 수정 허용 범위

- `Statement_of_Functions.md`
- `docs/ai/04-implementation-order.md`의 검증 기록

제품 코드·테스트·runtime/model 설정·workflow·installer configuration은 수정하지
않는다. 새 제품 파일·모델 다운로드·URL download·GitHub release·installer 설치/
제거·서명은 수행하지 않는다.

## 실행 계약

1. 전체 Python·desktop regression을 먼저 실행한다.
2. `tools/run_local.py`를 `sample.wav`, `--mode run`, `--output-mode both`,
   `--progress-format jsonl`, explicit STT model/Qwen tag로 실행한다.
3. stdout의 terminal JSON, stderr JSONL progress, 저장된 job directory를 확인한다.
   terminal은 `archived`, output mode는 `both`, report에는 resilience object가 있어야 한다.
4. `tools/inspect_job.py`로 결과를 재열고 summary·introduction·review artifact가
   읽히는지 확인한다.
5. `npm run tauri:check`로 debug app을 compile하고, 실제 executable을 짧게
   기동해 프로세스가 즉시 종료하지 않는지 확인한다. 모델 job을 UI로 중복 실행하지
   않는다.

## 실행 명령과 통과 기준

```powershell
D:\AI-Legion\Sodam-runtime\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
npm --prefix apps/desktop test
npm --prefix apps/desktop run check
npm --prefix apps/desktop run build
npm --prefix apps/desktop run tauri:check
git diff --check
```

- local CLI는 timeout/interrupt 없이 archived terminal 결과를 반환한다.
- progress event는 최소 한 개 이상이며 final report의 resilience가 object다.
- result root는 repository 밖, source WAV는 변경되지 않는다.
- actual UI process가 5초 동안 생존하거나, OS policy blocker를 정확히 기록한다.

## 보고

- regression 결과, 실제 runtime/version/input hash
- job ID·result root·terminal status·output/review/resilience 요약
- Tauri process smoke 결과와 OS policy blocker 여부
- 수정 파일과 남은 실제 품질·installer·signing 위험
