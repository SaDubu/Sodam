# Sodam 제품화 로드맵과 검증 계획

> 상태: 구현·검증 진행 중(2026-08-31). 계약 기반 파이프라인과 실제 로컬 CLI 수직 슬라이스가 연결되어 있다. 모델·미디어·외부 runtime은 repository 밖에서만 사용하며, 남은 항목은 수동 품질평가와 Tauri 설치물 smoke다.

## 1. 현재 기준선

현재 저장소는 입력 검증, 작업 상태, 안전한 작업 폴더 경계, 오디오 추출·STT·Qwen 호출의 **주입형 계약**, 보호·정규화·검토·전사문·요약 파이프라인, fake 기반 단위/통합 테스트를 갖추고 있다.

`backend.main.PipelineApplication`은 다음 네 collaborator를 호출자에게서 받아 한 작업을 실행할 수 있다.

- URL 소스 오디오 획득기 (`SourceAudioAdapter`)
- FFmpeg 실행기 (`FfmpegRunner`)
- STT 엔진 (`SttEngine`)
- Qwen JSON 응답 런타임 (`QwenRuntime`)

실제 adapter와 `tools/run_local.py`가 이 collaborator들을 명시적으로 조립한다. Python 3.12, FFmpeg 9.0.1, faster-whisper turbo snapshot, Ollama `qwen3.6:35b-a3b-agent-64k`로 60초 `both` E2E가 성공했으며 결과·진행 이벤트가 repository 밖에 저장되었다. 따라서 현재 상태는 **로컬 CLI 실행 가능 제품 후보**이며, 서명된 설치물과 다중 영상 품질 평가는 아직 완료되지 않았다.

## 2. 제품화 목표와 완료 정의

### 2.1 최소 실행 가능 제품(MVP)

Windows PC에서 사용자가 로컬 미디어 파일 하나를 선택해 다음 결과를 얻는다.

1. 표준 WAV로 변환된 오디오가 로컬 STT로 전사된다.
2. 보호 토큰과 제한적 규칙 정규화 뒤, 로컬 Qwen runtime의 JSON 교정이 검증된다.
3. 검토가 필요한 변경과 근거 구간이 연결된 요약을 사용자가 확인·저장할 수 있다.
4. 성공·실패·취소 뒤 임시 미디어는 작업 전용 폴더 밖을 건드리지 않고 정리된다.

첫 MVP의 기본 경로는 로컬 파일이다. URL 다운로드는 사용자가 권한을 가진 입력에 `--allow-url --mode run`을 명시한 경우에만 opt-in으로 동작하며, 자동 모델 다운로드와 다중 작업 병렬 실행은 기본 경로에 포함하지 않는다.

### 2.2 제품 출시 후보의 완료 조건

- 새 PC에서 문서화된 사전 조건만으로 진단, 모델 설치, 로컬 파일 처리까지 재현된다.
- 실제 FFmpeg/STT/Qwen을 사용한 성공·실패·취소 경로가 자동 및 수동 검증을 통과한다.
- 사용자 전사문·요약·용어집·모델 가중치·비밀값이 Git 작업 트리 밖에 저장된다.
- 보존된 결과를 다시 열고, 검토 보류 항목을 승인/수정할 수 있다.
- UI 또는 CLI가 오류 원인·로그 위치·다음 행동을 사용자에게 명확히 표시한다.

## 3. 고정 안전 원칙

1. 모든 제품 구현은 한 작업씩 `Statement_of_Functions.md`에 명세한 뒤 진행한다.
2. 실제 모델 다운로드, URL 획득, subprocess 실행, 사용자 데이터 생성·삭제는 작업별 별도 승인을 받는다.
3. 모델, 미디어, 작업 DB, 사용자 산출물, `.env`는 repository 밖에 둔다.
4. 외부 collaborator는 기존 Protocol 계약을 지키며, `KeyboardInterrupt`와 `SystemExit`은 숨기지 않는다.
5. 작업 artifact 쓰기·삭제는 `D:\AI-Legion\Sodam-data`의 명시된 job 소유 경계 안에서만 수행한다.
6. URL 다운로드는 지원 플랫폼의 약관·저작권·사용 권한을 검토하고, 사용자가 처리 권한을 가진 입력만 대상으로 한다.
7. 실제 모델 응답은 신뢰하지 않는다. 기존 JSON·placeholder·근거 ID 검증을 우회하지 않는다.

## 4. 선행 결정 사항

아래 결정은 초기 후보 기록이며, 현재 실행 profile은 실제 검증 결과와 [runtime profile](06-runtime-profile.md)을 기준으로 한다.

| 결정 | 선택지 | 필요한 이유 | 영향 작업 |
|---|---|---|---|
| 로컬 Qwen runtime | Ollama `qwen3.6:35b-a3b-agent-64k` | loopback JSON adapter와 로컬 모델 저장소를 사용한다. | V2-R01, V2-E2E01 |
| STT 엔진 | faster-whisper `turbo`, CPU/int8 | local snapshot 경로와 segment schema를 고정한다. | V2-R01, V2-E2E01 |
| 지원 PC 최소 사양 | CPU-only / GPU VRAM 용량 / 저장공간 | 모델 profile, 성능 목표, UX 안내를 결정한다. | P01, P07 |
| URL 입력 범위 | MVP 제외 후 승인된 플랫폼부터 지원 | 법적·기술적 adapter 범위를 제한한다. | P05 |
| 결과 보존 정책 | 자동 삭제 / 전사문·요약만 보존 / 사용자 선택 | DB schema, cleanup, 개인정보 보관을 결정한다. | P04, P06 |
| 사용자 인터페이스 순서 | CLI 우선 후 Tauri / Tauri 동시 구현 | 문제 진단과 배포 복잡도를 좌우한다. | P02, P06 |

## 5. 권장 구현 순서

```text
P01 실행 환경·모델 profile 결정
  └─ P01A 모델 다운로드·무결성 검증·runtime 등록
      └─ P02 설정·사전 요구사항 진단 CLI
          └─ P03 로컬 파일 실제 adapter 수직 슬라이스
              └─ P04 결과 영속화·재열기·검토 적용
                  ├─ P05 URL source adapter (선택)
                  └─ P06 Tauri IPC·데스크톱 UI
                      └─ P07 설치·운영·릴리스 검증
```

P05와 P06은 P04 후 병렬화할 수 있지만, 실제 URL 호출과 UI 파일 선택/IPC는 각각 별도 승인과 독립 검증이 필요하다.

## 6. 단계별 작업 명세 초안

### P01 — 실행 환경과 승인된 모델 profile

**목적**: 지원 Windows 환경, Qwen runtime, STT 엔진, model profile과 실제 설치 경로를 결정한다.

**예상 대상**

- `docs/ai/05-productization-roadmap.md` 또는 결정 기록 문서
- `models/manifest.json`
- `README.md`
- 필요 시 모델 설치 script의 manifest schema 검증부

**구현 내용**

1. 선택한 runtime/STT의 공식 배포 출처, 라이선스, 버전, 모델 파일명, SHA-256, 최소 디스크·메모리를 기록한다.
2. `models/manifest.json`에 검증 가능한 profile을 추가한다. URL은 HTTPS, 파일명은 leaf name, checksum은 lowercase SHA-256이어야 한다.
3. model home은 repository 밖의 `D:\AI-Legion\Sodam-models` 또는 사용자가 승인한 동등한 외부 경로만 허용한다.
4. 실제 모델 다운로드는 profile 검토와 외부 호출 승인을 받은 다음 별도 실행 작업으로 분리한다.

**자동 검증**

```powershell
C:\Users\sow20\AppData\Local\Programs\Python\Python312\python.exe -B -m pytest tests/unit/test_model_setup.py -q
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-repository-clean.ps1 -RepositoryRoot .
```

**수동 검증**

- 공식 배포 URL·라이선스·checksum이 선택된 파일과 일치한다.
- model home이 repository의 하위 경로가 아니다.
- profile에 비밀값·토큰·사용자 경로가 없다.

**완료 기준**: profile은 review 가능한 선언으로 존재하고, 아직 다운로드하지 않은 상태에서도 schema 및 안전성 검사가 통과한다.

#### P01 결정 기록

- **선택 완료:** 현재 MVP runtime은 Ollama `qwen3.6:35b-a3b-agent-64k`와 Python `faster-whisper` `turbo` 조합이다. STT 기본 compute profile은 `cpu`/`int8`이며, GPU profile은 별도 benchmark·driver 검증 후에만 추가한다.
- **installer 경계:** 기존 schema v1 manifest/O01 installer는 단일 HTTPS file의 SHA-256 검증 계약을 유지한다. Ollama registry pull과 faster-whisper multi-file Hub snapshot은 별도 runtime-specific installer/registration 작업(P01A)으로 분리한다.
- **다음 선행 조건:** actual model/package download, local runtime registration, exact STT snapshot revision/license, model home 생성, network/subprocess 호출은 P01A에서 명시 승인 후에만 수행한다.
- **상세 기록:** [runtime profile](06-runtime-profile.md)을 참조한다.

### P01A — 실제 모델 다운로드, 무결성 확인, runtime 등록

**목적**: P01에서 승인된 model profile을 repository 밖으로 실제 설치하고, 선택한 STT/Qwen runtime이 해당 모델을 사용할 수 있게 등록한다.

**선행 조건**: P01의 profile·배포 URL·license·SHA-256·목표 model home 확정, 네트워크/외부 호출과 대용량 파일 생성에 대한 작업별 승인.

**예상 대상**

- `scripts/setup-models.ps1` 실행 및 필요한 최소 보완
- runtime별 등록/진단 script 또는 adapter configuration
- `models/manifest.json`의 승인된 profile
- 설치 결과 문서(모델 바이너리 자체는 절대 Git에 추가하지 않음)

**실행 내용**

1. `Install-SodamModels`로 manifest의 모델을 `D:\AI-Legion\Sodam-models` 또는 승인된 repository 밖 model home에 다운로드한다.
2. 다운로드한 파일의 SHA-256을 manifest와 비교하고, mismatch·중단·partial file은 installer 계약에 따라 정리한다.
3. 선택 runtime(Ollama 또는 llama.cpp 계열)에서 Qwen 모델을 명시 profile 이름으로 등록하고, STT runtime에서 STT 모델 경로를 읽도록 설정한다.
4. runtime endpoint/process가 외부 클라우드가 아닌 로컬 endpoint/process만 사용하는지 확인한다.
5. 설치 결과에는 profile 이름, 파일명, checksum 검증 결과, runtime 버전, model/data home만 남긴다. prompt, 사용자 media, API key, 모델 파일 내용은 로그나 Git에 남기지 않는다.

**자동 검증**

- installer의 fake downloader 계약 test와 repository policy scan을 실행한다.
- runtime wrapper의 health probe를 model name, local endpoint, expected minimal response에 대해 opt-in smoke test로 실행한다.
- `git status --short`와 `check-repository-clean.ps1`으로 model binary가 Git 후보가 아님을 확인한다.

**수동 검증**

- 설치 경로가 repository 밖인지 파일 탐색기와 resolved path로 확인한다.
- 다운로드한 실제 파일 checksum이 승인된 manifest 값과 일치한다.
- runtime이 선택된 model을 local-only로 로드하며, 모델이 없는 상태의 오류도 진단 CLI에서 이해 가능하게 표시된다.

**완료 기준**: 실제 Qwen/STT model 파일이 Git 밖에 checksum 검증을 거쳐 설치되고, 선택한 runtime이 두 모델을 local-only로 찾을 수 있다.

### P02 — 설정·사전 요구사항 진단 CLI

**목적**: 사용자가 실행 전 부족한 Python, FFmpeg, model runtime, STT model, writable data path를 한 번에 확인하게 한다.

**예상 대상**

- 새 CLI 모듈 또는 `scripts/`의 read-only 진단 script
- `tests/unit/`의 진단 contract tests
- `README.md`

**구현 내용**

1. `sodam doctor` 또는 동등 CLI를 추가한다.
2. 명령은 발견한 실행 파일 버전, runtime endpoint reachability, model profile 존재, data root writeability만 report한다.
3. 기본값은 변경하지 않는 read-only 검사다. 설치·다운로드·폴더 생성은 명시 opt-in 명령으로 분리한다.
4. JSON 출력과 사람이 읽는 출력 중 하나를 명확한 stable contract로 정한다.

**자동 검증**

- subprocess 및 filesystem probe를 fake로 주입해 missing FFmpeg, missing model, unwritable data root, 정상 환경을 결정론적으로 검증한다.
- 실제 시스템 PATH나 실제 runtime은 unit test의 필수 조건으로 만들지 않는다.

**수동 검증**

- 새 PC에서 진단 결과가 설치 안내와 정확히 연결된다.
- 진단 실행 전후 repository와 data root에 새 파일이 생기지 않는다.

**완료 기준**: 사용자가 실패 원인을 코드 traceback 없이 식별하고, 다음 설치 단계로 이동할 수 있다.

### P03 — 로컬 파일용 실제 adapter와 CLI 수직 슬라이스

**목적**: URL 없이 로컬 미디어 하나를 실제 FFmpeg → STT → Qwen pipeline으로 끝까지 처리한다. 이 단계는 제품 코드 변경, subprocess 실행, 실제 모델 runtime 호출을 포함한다.

**예상 대상**

- `backend/adapters/ffmpeg_*.py`
- `backend/adapters/stt_*.py`
- `backend/adapters/qwen_*.py`
- application 조립 및 CLI entry point
- adapter·CLI unit tests와 real-adapter integration test

**구현 내용**

1. `FfmpegRunner.run(arguments)`은 허용된 실행 파일과 argument vector만 subprocess로 실행하고 stdout/stderr·non-zero exit를 `MediaExtractionError` 원인으로 보존한다.
2. 선택한 STT runtime wrapper는 audio path를 읽고 기존 `SttEngine.transcribe()` 반환 schema로 변환한다. 모델 load, timeout, device 오류를 `TranscriptionError`로 매핑한다.
3. Qwen wrapper는 선택 runtime의 local endpoint 또는 process에만 연결하고 `complete(prompt) -> str`을 구현한다. timeout/연결/응답 형식 실패는 `ModelResponseError`로 매핑한다.
4. CLI는 source path, profile, glossary path, retention option을 검증한 뒤 `create_job()`과 `build_application()`을 조립한다.
5. 출력은 job ID, terminal status, 보존된 결과 위치, review item 수, 실패 시 원인 유형을 안정된 schema로 제공한다.

**자동 검증**

- subprocess/STT/Qwen wrappers는 fake executable 또는 local test server로 호출 횟수, timeout, 오류 매핑을 검증한다.
- existing `pytest -q`가 계속 통과한다.
- 최소 하나의 짧고 배포 가능한 synthetic audio fixture로 실제 adapter를 포함한 opt-in integration test를 제공한다. CI에서는 external model test를 marker로 분리한다.

**수동 검증**

- 지원 media 1개가 `archived` terminal 상태까지 도달한다.
- 출력 WAV, STT segment, placeholder, reviewed transcript, summary가 같은 job ID를 유지한다.
- 실패·Ctrl+C·디스크 부족 시 job root 밖 파일이 변경되지 않는다.

**완료 기준**: 실제 로컬 파일이 결과와 검토 큐를 만들고, 모델·미디어 임시 artifact는 설정한 retention 정책대로 처리된다.

### P04 — 결과 영속화, 재열기, 검토 반영

**목적**: 현재 메모리에서 반환되는 transcript·summary·review queue를 안전하게 보존하고 다시 열 수 있게 한다.

**예상 대상**

- `backend/storage.py`와 persistence 전용 모듈
- JSON artifact schema 또는 SQLite metadata schema
- `tools/inspect_job.py`
- storage/persistence tests 및 migration tests

**구현 내용**

1. Job metadata, raw/reviewed transcript, summary, review queue, retention policy의 versioned schema를 정한다.
2. 저장 root는 `D:\AI-Legion\Sodam-data\jobs`처럼 repository 밖의 별도 보존 경로를 사용한다.
3. write는 atomic temporary file + replace 또는 SQLite transaction으로 수행한다. 실패한 write는 partially valid record로 보이지 않아야 한다.
4. 재열기 API는 안전한 job ID만 받아 known root의 direct child만 읽는다.
5. 검토 보류 항목을 사용자가 승인·수정할 때 original/raw/audit history를 보존한다.
6. cleanup은 임시 audio와 보존 결과를 구분하며, 보존 결과 삭제는 사용자의 명시 action으로만 한다.

**자동 검증**

- 저장→재열기 왕복, crash-safe partial write, duplicate job ID, schema version 불일치, root escape/symlink, concurrent update 충돌을 검증한다.
- `tools/inspect_job.py`가 실제 영속 schema fixture를 읽는지 검증한다.

**수동 검증**

- 앱 재시작 뒤 이전 작업의 요약·검토 큐·근거 segment가 조회된다.
- 결과 삭제가 선택한 job의 보존 디렉터리만 지운다.

**완료 기준**: 실제 성공 작업을 재시작 후 조회·검토·내보내기할 수 있으며, 임시 artifact와 영구 결과의 수명 정책이 분리된다.

### P05 — 승인된 URL 소스 adapter (선택)

**목적**: 사용 권한이 있는 지원 URL에서 오디오를 일회성으로 획득한다.

**선행 조건**: P03 완료, 지원 플랫폼·도구 라이선스·약관 검토, 네트워크 호출 승인. 이 단계는 제품 코드 변경과 실제 downloader subprocess/network 호출을 포함한다.

**예상 대상**

- `backend/adapters/source_*.py`
- URL adapter integration tests
- 사용자 동의·지원 범위 문서

**구현 내용**

1. `SourceAudioAdapter.acquire(source, destination)`을 구현한다.
2. downloader는 job work directory 안의 명시된 temporary path만 사용한다.
3. redirect, unsupported source, access denied, quota, downloader failure, output missing을 `InputSourceError`로 맥락과 함께 변환한다.
4. 원본 다운로드 컨테이너는 audio 획득 성공 후 삭제하며, 실패·취소에도 best-effort cleanup한다.

**자동 검증**

- fake downloader로 destination 경계, non-zero exit, missing output, cancellation, cleanup을 검증한다.
- 실서비스 URL은 자동 test에 넣지 않는다.

**수동 검증**

- 처리 권한이 명백한 짧은 URL 1개에서 오디오만 남고 원본 미디어가 정리되는지 확인한다.
- 서비스 약관 및 네트워크 정책을 재확인한다.

**완료 기준**: 실제 URL adapter 오류가 명확히 표시되고, 어떤 경우에도 job root 밖에 다운로드 artifact가 남지 않는다.

### P06 — Tauri IPC와 검토 가능한 데스크톱 UI

**목적**: CLI 기능을 파일 선택, URL 입력, 진행 표시, 취소, 검토, 결과 열기 화면으로 제공한다.

**예상 대상**

- `apps/desktop/`의 Tauri shell·frontend component·IPC command
- backend process/IPC bridge
- UI unit/component tests 및 e2e smoke tests

**구현 내용**

1. 기존 `JobViewModel`과 `ReviewItemViewModel`을 backend DTO와 명확히 매핑한다.
2. 파일 선택과 URL 입력은 UI에서 직접 처리하지 않고 검증된 backend command로 전달한다.
3. Job lifecycle events를 progress/status/update event로 발행한다. 오류는 사용자가 읽을 수 있는 message와 technical error ID를 함께 제공한다.
4. review 화면은 자동 승인문과 보류 변경을 구분하고, 원문·제안문·시간 구간·사유를 표시한다.
5. 취소는 idempotent action으로 만들고, terminal job에 대해 중복 작업을 수행하지 않는다.

**자동 검증**

- frontend reducer/view-model test, IPC payload schema test, mocked backend UI flow test를 작성한다.
- Playwright/WebDriver 등 선택 e2e 도구로 app launch→local file select→fake pipeline result→review display→cancel flow smoke test를 만든다.

**수동 검증**

- 긴 경로·한국어 파일명·권한 오류·runtime unavailable을 UI에서 이해할 수 있다.
- cancel과 close/reopen 후 화면 상태가 실제 persisted job과 일치한다.

**완료 기준**: CLI를 직접 실행하지 않아도 사용자가 한 작업을 시작·관찰·취소·검토·재열 수 있다.

### P07 — 설치, 릴리스, 운영 검증

**목적**: 깨끗한 Windows 환경에서 재현 가능한 설치와 안전한 운영 기준을 마련한다.

**예상 대상**

- 설치/진단 script
- CI workflow 및 release checklist
- README와 troubleshooting 문서
- packaging configuration

**구현 내용**

1. Python/runtime/FFmpeg/모델 설치의 책임을 명확히 분리한다.
2. installer 또는 setup guide는 OS architecture, data/model home, disk space, checksum failure recovery를 안내한다.
3. CI는 unit/integration fake tests, repository policy scan, formatting/syntax, artifact-root boundary tests를 실행한다.
4. release checklist에 clean checkout smoke test, local-file real pipeline opt-in test, uninstall/data retention test를 포함한다.
5. 로그에는 prompt 전문, 사용자 전사문, source URL의 query/token, 비밀값을 기본적으로 남기지 않는다.

**자동 검증**

```powershell
C:\Users\sow20\AppData\Local\Programs\Python\Python312\python.exe -B -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-repository-clean.ps1 -RepositoryRoot .
```

- clean checkout에서 docs의 bootstrap/doctor 명령을 dry-run 또는 fake dependency로 검증한다.

**수동 검증**

- 지원 사양의 새 Windows 사용자 계정에서 설치·진단·로컬 파일 성공 경로를 재현한다.
- model/data home과 Git worktree가 분리된 것을 `git status`와 파일 탐색기로 확인한다.

**완료 기준**: 릴리스 후보가 문서대로 설치·진단·실행되고, 사용자의 모델·미디어·결과물이 Git에 유입되지 않는다.

## 7. 단계별 공통 검증 매트릭스

| 검증 층 | 매 단계에서 확인할 내용 | 통과 기준 |
|---|---|---|
| 명세 대조 | `Statement_of_Functions.md`의 허용 파일·예외·부작용·금지 범위 | 범위 밖 수정 0건 |
| 정적 검사 | syntax, formatter/linter 도입 시 그 결과, `git diff --check` | 오류 0건 |
| 단위 테스트 | 새 adapter/storage/UI 계약과 기존 회귀 | 관련 pytest와 전체 pytest 통과 |
| 안전성 | job root boundary, symlink, overwrite, secret/Git policy | root 밖 변경 0건, policy clean |
| 통합 테스트 | injected fake와 opt-in actual dependency의 성공/실패/취소 | terminal state와 cleanup 계약 일치 |
| 수동 검증 | 실제 Windows·실모델·실미디어의 UX·성능·한국어 품질 | 사전에 정의한 checklist 서명 |

실행 전후 기본 명령은 다음과 같다.

```powershell
C:\Users\sow20\AppData\Local\Programs\Python\Python312\python.exe -B -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-repository-clean.ps1 -RepositoryRoot .
git diff --check
git status --short
```

external runtime이 필요한 test는 기본 test suite에서 강제하지 않는다. 명시 marker 또는 opt-in script로 분리하고, 실행한 runtime·모델 profile·OS/driver·입력 fixture의 출처를 결과 문서에 남긴다.

## 8. 작업별 보고 템플릿

각 P 작업을 끝낼 때 아래를 `docs/ai/04-implementation-order.md` 또는 작업 결과 문서에 기록한다.

1. 작업 ID와 실제 수정/생성/삭제 파일 목록
2. 명세 계약 대조 결과와 의도적으로 제외한 범위
3. 실행한 명령, 자동 테스트 수, skip 사유
4. 실제 external dependency 호출 여부와 사용한 승인 범위
5. artifact 생성·보존·삭제 경로 및 root boundary 결과
6. 수동 검증 환경과 관찰 결과
7. 남은 위험, 사용자 결정 필요 사항, 다음 선행 작업

## 9. 첫 실행 작업 추천

다음 구현 작업은 **P01의 의사결정 기록**이어야 한다. 특히 Qwen runtime과 STT engine을 하나씩 선택하고, 최소 지원 PC 및 모델 배포 출처·라이선스·checksum을 확정해야 P03의 실제 adapter를 안전하게 명세할 수 있다.

P01이 확정되면 P02 진단 CLI를 먼저 만들고, 그 결과를 바탕으로 URL·UI보다 앞서 P03의 **로컬 파일 단일 작업 수직 슬라이스**를 구현한다. 이 흐름이면 외부 도구와 모델 문제를 UI·네트워크 복잡도 없이 분리해 해결할 수 있다.

## 10. Product v2 실행 결과 보충 (2026-08-31)

- `qwen3.6:35b-a3b-agent-64k` Ollama와 faster-whisper `turbo-0a363e9`, FFmpeg 9.0.1을 repository 밖에서 연결했다.
- 60초 WAV에 `tools/run_local.py --mode run --output-mode both --progress-format none`을 실행해 job `9af42eeb936e49fb9ab6cc853b77d1d8`를 `archived`까지 완료했다. 13개 segment와 43개 progress event, summary/introduction JSON 및 review artifact를 확인했다.
- stdout/stderr 분리, 진행 sequence 단조성, terminal `completed`, 결과 reopen을 확인했다. 전체 pytest는 `212 passed, 1 skipped`다.
- 15분 원본의 첫 시도는 placeholder 검증에서 중단되었고, schema 인스턴스·highlight exact-copy·CTA exact-copy prompt 보정 후 bounded smoke가 통과했다.
- Rust `cargo check`는 통과했으나 Tauri 실제 bundle/window smoke는 Windows application control 정책 오류 4551로 차단되었다. 5개 영상 사람 품질평가도 출시 전 수동 체크리스트로 남아 있다.
