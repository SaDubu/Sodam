# CR-06 — Tauri stderr bridge·retry/identity UI 표시

## 작업 ID와 범위

- 작업 ID: CR-06
- 작업 종류: Rust IPC·TypeScript UI 구현 및 기존 desktop 테스트 보강
- 대상 저장소: D:\AI-Legion\Sodam
- 선행 작업: CR-05
- 수정 허용 파일:
  - apps/desktop/src-tauri/src/lib.rs
  - apps/desktop/src/main.ts
  - apps/desktop/src/state.ts
  - apps/desktop/src/progress-contract.ts
  - apps/desktop/tests/ipc-contract.test.mjs
  - apps/desktop/tests/ui-contract.test.mjs
  - apps/desktop/tests/state.test.mjs
  - docs/ai/04-implementation-order.md
  - Statement_of_Functions.md
- 수정 금지 파일:
  - backend/
  - tools/
  - persistence schema
  - package/build/signing configuration
  - 새 파일·실제 모델/미디어·네트워크 실행
- 커밋과 푸시는 수행하지 않는다.

## 목적

CR-05의 JSONL progress와 resilience report를 Tauri 이벤트로 안전하게
전달하고, UI에서 retry 진행·identity fallback·review 필요 상태·safe error
category를 사용자가 구분할 수 있게 한다. stderr 원문 전체나 prompt·전사문·
절대 경로는 UI 이벤트에 포함하지 않는다. 기존 start/cancel/setup/result 흐름과
summary/introduction/both 결과 탭은 유지한다.

## Rust bridge 계약

### bounded stderr 처리

- backend child의 stderr를 줄 단위로 수집한다.
- 유효한 ProgressEvent JSONL은 기존 progress 이벤트로 전달한다.
- 그 외 stderr는 마지막 1~2줄만 보존하고 경로, prompt, 전사문, 긴 payload를
  제거한 bounded safe tail로 축약한다.
- child exit code와 safe category를 함께 job_failed error payload로 보낸다.
- malformed stdout, non-zero exit, cancelled, stale operation을 서로 다른
  terminal 이벤트로 유지한다.
- shell 문자열 실행, 임의 URL·filesystem 권한, backend 로직 변경은 금지한다.

### job_result resilience 전달

- stdout report의 resilience object를 검증된 JSON object로만 전달한다.
- retry attempt reason은 safe category allowlist 밖의 값이면 runtime_error로
  정규화한다.
- report 원문을 임의 문자열로 합치지 않고 구조화 payload로 emit한다.

## TypeScript 상태·UI 계약

### state reducer

- job_result의 resilience를 detached UI state에 보존한다.
- progress message에서 retry/identity 상태를 표시하되 stale sequence와
  terminal event 보호를 유지한다.
- identity_group_count > 0이면 terminal은 완료(검토 필요)로 표시하고,
  summary/introduction/transcript 탭은 계속 열 수 있어야 한다.
- job_failed error는 code/category/message를 검증하고 raw stderr는 보존하지
  않는다.

### main.ts 표시

- 진행 화면에 현재 stage, 진행률, ETA와 함께 재시도 n회, 원문 유지 n개,
  검토 필요 n개를 표시한다.
- safe error category별 안정적인 사용자 메시지를 표시한다. Some(120) 같은
  generic exit text만 단독으로 표시하지 않는다.
- 결과 화면에 resilience 요약과 review 필요 상태를 접근 가능한 live region으로
  표시한다.
- 기존 키보드 탐색, aria label, output mode selector, cancel 동작을 보존한다.

## 테스트

기존 Node 테스트만 수정·확장한다.

- Rust 정적 계약: bounded stderr tail, safe category, resilience payload,
  job_failed/job_result/job_cancelled 이벤트
- reducer: retry/identity/terminal/stale 이벤트와 raw 누출 거부
- UI 정적 계약: resilience counters, review 상태, safe error, 접근성 label
- 기존 IPC/start/cancel/setup 및 summary/introduction/both 회귀

## 실행 명령

    npm --prefix apps/desktop test
    npm --prefix apps/desktop run check
    npm --prefix apps/desktop run build
    cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
    git diff --check -- apps/desktop/src-tauri/src/lib.rs apps/desktop/src/main.ts apps/desktop/src/state.ts apps/desktop/src/progress-contract.ts apps/desktop/tests docs/ai/04-implementation-order.md Statement_of_Functions.md

## 통과 기준

- Node 테스트·TypeScript check/build·cargo check가 모두 통과한다.
- retry/identity/resilience 정보가 구조화 event와 UI에 표시된다.
- stderr는 bounded safe tail만 전달하며 prompt·전사문·절대 경로가 노출되지 않는다.
- 기존 output mode, cancel, stale/terminal 보호가 회귀하지 않는다.
- 실제 Tauri 창·backend·모델·네트워크 실행은 수행하지 않는다.

## 구현하지 않아야 할 범위

- Python backend 및 CR-03/CR-05 로직 변경
- persistence schema·installer·signing 변경
- 실제 모델/미디어 smoke, 새 파일 생성, 커밋·푸시

## 완료 후 보고

- Rust bridge와 UI reducer/display 변경 요약
- Node/TypeScript/cargo/diff 검증 결과
- raw 정보 누출 방지 및 retry/identity 표시 확인
- CR-07 실제 통합·수동 smoke에 남은 위험
- 커밋·푸시를 하지 않았다는 확인
