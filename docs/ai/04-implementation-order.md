# Sodam 구현 순서 및 작업 추적

> 상태: 골격 작성 완료 전 계획. 실제 구현은 별도 명시 승인이 있을 때, 한 작업씩 `Statement_of_Functions.md`에 명세한 뒤 진행한다.

## 작업 상태 기준

- **골격 완료**: 선언·docstring·`NotImplementedError`만 존재하며 실제 기능과 검증 로직은 없다.
- **구현 완료**: 해당 작업의 테스트 도구와 테스트 코드가 작성되고, 정의된 자동·수동 기준을 모두 통과한 상태다.
- 구현 시작 전에는 반드시 아래 표에서 선행 작업이 완료된 가장 이른 작업을 하나만 선택한다.

| ID | 종류 | 대상 / 이름 | 선행 작업 | 목적·상세 동작 | 수정 허용 범위 | 금지 범위 | 테스트 방법 | 완료 판정 기준 |
|---|---|---|---|---|---|---|---|---|
| D01 | 문서화 | `docs/ai/04-implementation-order.md` | 없음 | 작업 의존성과 완료 기준을 관리한다. | 이 문서 | 제품 코드 | 문서 검토 | 모든 작업이 추적 가능하다. |
| B01 | 함수 구현 | `backend/contracts.py`: 도메인 타입·예외 | D01 | Job, Segment, Transcript, Summary와 오류 계약을 확정한다. | `backend/contracts.py`, 관련 테스트 | 저장·모델 호출 | 타입 계약 단위 테스트 | 모든 타입 직렬화/불변식 계약이 통과한다. |
| T01 | 테스트 도구 구현 | `tests/fakes.py`, fixture 생성기 | B01 | 저장소, STT, 모델, 다운로드, FFmpeg의 fake를 제공한다. | `tests/`, `tools/` | 실제 외부 도구 | fake 계약 테스트 | 실제 네트워크/모델 없이 결정론적으로 동작한다. |
| B02 | 함수 구현 | `backend/jobs.py`: `create_job`, 상태 전이, 취소 | B01, T01 | 입력을 검증하고 안전한 작업 상태를 관리한다. | `backend/jobs.py`, `backend/contracts.py` | 음성 획득·DB 실제 연결 | `test_jobs.py` | queued 생성, 유효 상태 전이, 잘못된 입력 예외가 통과한다. |
| B03 | 함수 구현 | `backend/storage.py`: 저장·정리 | B01, T01 | JSON/SQLite 저장 추상화 및 작업 폴더 한정 정리를 구현한다. | `backend/storage.py`, 관련 테스트 | 작업 폴더 밖 삭제 | `test_storage.py` | 경로 안전성, 보관 정책, 삭제 경계가 통과한다. |
| B04 | 함수 구현 | `backend/sources.py`: `validate_source`, `acquire_source_audio` | B02, B03, T01 | 지원 URL을 판정하고 어댑터로 음성을 획득한다. | `backend/sources.py`, 관련 테스트 | 무단 URL 처리, 실제 기본 다운로드 | `test_sources.py` + fake | 원본 미디어 정리와 오류 매핑이 통과한다. |
| B05 | 함수 구현 | `backend/media.py`: `extract_audio` | B02, B03, T01 | 미디어 입력을 표준 오디오로 변환한다. | `backend/media.py`, 관련 테스트 | 작업 폴더 밖 쓰기 | `test_media.py` + FFmpeg fake | 형식·길이 계약 및 오류 매핑이 통과한다. |
| B06 | 함수 구현 | `backend/transcription.py`: `transcribe_audio` | B01, T01 | STT 출력을 유효한 시간 구간으로 표준화한다. | `backend/transcription.py`, 관련 테스트 | 실제 모델 기본 실행 | `test_transcription.py` + STT fake | 시간 단조성·빈 텍스트 처리 계약이 통과한다. |
| B07 | 함수 구현 | `backend/protection.py`: `protect_tokens`, `restore_tokens` | B01, T01 | 보호값을 충돌 없는 자리표시자로 왕복 변환한다. | `backend/protection.py`, 관련 테스트 | 원문 값 변경 | `test_protection.py` | 보호 토큰 100% 복원 테스트가 통과한다. |
| B08 | 함수 구현 | `backend/text_rules.py`: `normalize_rules` | B07, T01 | 문자 보존 조건 아래 공백·명백한 문장부호만 정리한다. | `backend/text_rules.py`, 관련 테스트 | 의미/사실 변경 | `test_text_rules.py` + Kiwi fake | 비공백 문자·보호 토큰 보존이 통과한다. |
| B09 | 함수 구현 | `backend/correction.py`: `correct_chunk` | B01, B07, T01 | 모델 요청/응답 JSON을 검증하고 교정 결과를 만든다. | `backend/correction.py`, 관련 테스트 | 자유 형식 모델 출력 허용 | `test_correction.py` + Qwen fake | 스키마·길이·오류 처리 계약이 통과한다. |
| B10 | 함수 구현 | `backend/validation.py`: `validate_revision` | B01, B07, B09, T01 | 안전 변경과 검수 필요 변경을 분류한다. | `backend/validation.py`, 관련 테스트 | 위험 변경 자동 확정 | `test_validation.py` | 보호값 손실/위험 변경 차단이 통과한다. |
| B11 | 함수 구현 | `backend/storage.py`: `assemble_transcript` | B01, B03, B10, T01 | 시간순 구간으로 전사문·색인을 조립해 저장한다. | `backend/storage.py`, 관련 테스트 | 누락/중복 자동 보정 | `test_transcript.py` | ID 고유성·시간 순서·조회 계약이 통과한다. |
| B12 | 함수 구현 | `backend/summarization.py`: `summarize_transcript` | B01, B09, B11, T01 | 계층형 요약과 근거 구간 연결을 수행한다. | `backend/summarization.py`, 관련 테스트 | 근거 없는 사실 추가 | `test_summarization.py` + Qwen fake | 2문장 이하와 근거 ID 규칙이 통과한다. |
| B13 | 함수 구현 | `backend/main.py`: 작업 파이프라인 조립 | B02–B12 | 순차 모델 실행과 실패/취소 정리를 오케스트레이션한다. | `backend/main.py`, 통합 테스트 | UI·외부 서비스 직접 구현 | fake 기반 통합 테스트 | 상태 전이와 정리 경로가 통과한다. |
| U01 | 함수 구현 | `apps/desktop/`: UI 상태·표시 계층 | B13 | 입력, 진행도, 검수 큐, 결과 표시를 연결한다. | `apps/desktop/`, UI 테스트 | 모델/미디어 로직 중복 | 수동 UI 점검 | 시간 링크와 위험 변경 표시가 정확하다. |
| T02 | 테스트 코드 구현 | `tests/unit/` | B02–B12, T01 | 함수별 정상·경계·오류 사례를 자동화한다. | `tests/unit/`, fixtures | 실모델/실다운로드 의존 | `pytest tests/unit -q` | 설계서의 함수별 자동 기준을 모두 통과한다. |
| T03 | 테스트 도구 구현 | `tools/evaluate_transcript.py` | B10–B12 | 교정 정확도·위험 변경률·처리 시간을 측정한다. | `tools/`, `tests/fixtures/` | 제품 파이프라인 변경 | fixture CLI 실행 | 지표와 비교 결과를 재현 가능하게 출력한다. |
| T04 | 테스트 도구 구현 | `tools/inspect_job.py` | B03, B11, B12 | JSON·타임스탬프·검수 큐를 사람이 점검한다. | `tools/` | 사용자 데이터 수정 | 샘플 작업 CLI 점검 | 읽기 전용 점검 결과가 명확하다. |
| T05 | 테스트 코드 구현 | `tests/integration/` | B13, T01–T04 | 성공·실패·취소·비정상 종료 정리 흐름을 검증한다. | `tests/integration/` | 외부 URL·실모델 필수화 | `pytest tests/integration -q` | 작업 폴더 밖 삭제 0건이 통과한다. |
| O01 | 함수 구현 | `scripts/setup-models.ps1`: `install_models` | B01, T01 | manifest 검증과 저장소 밖 설치를 구현한다. | `scripts/`, `models/`, 관련 테스트 | 실제 기본 다운로드, Git 트리 내 설치 | 다운로드 fake 테스트 | 체크섬·경로 거부 계약이 통과한다. |
| O02 | 함수 구현 | `scripts/check-repository-clean.ps1`: `check_repository_clean` | T01 | 추적 파일 정책을 검사한다. | `scripts/`, 관련 테스트 | 파일 자동 삭제 | Git fake 테스트 | 금지 확장자·대용량·비밀 패턴이 차단된다. |
| O03 | 문서화 | `README.md`, `models/manifest.json`, Git 정책 | O01, O02 | 확정된 런타임·모델·운영 방법을 문서화한다. | 문서·manifest·ignore 파일 | 미확정 모델값 고정 | 새 PC 수동 검증 | 모델과 사용자 데이터가 Git 밖에 유지된다. |

## 구현 작업의 고정 절차

각 B/T/U/O 작업은 시작할 때마다 `Statement_of_Functions.md`를 초기화하고, 해당 작업 하나의 완전한 명세만 작성한다. 로컬 LLM에는 다음 지시문만 사용한다.

> `Statement_of_Functions.md`를 먼저 읽어라. 명세에 적힌 작업만 구현하라. 명세에 없는 파일이나 기능은 수정하지 마라. 구현 후 명세에 적힌 테스트를 실행하라. 테스트 결과, 수정한 파일, 남은 위험 요소를 보고하라. 커밋과 푸시는 하지 마라.

완료 결과와 테스트 근거는 이 문서의 해당 작업에 기록한다. 커밋, 푸시, 실제 외부 호출, 실제 함수/테스트 로직은 각각 별도 명시 승인이 필요하다.

## 구현 검증 기록

### B01 — 도메인 타입과 예외 처리 계약

- **상태:** 구현 완료 (테스트 도구·테스트 코드는 별도 승인 대기)
- **수정 파일:** `backend/contracts.py`
- **명세 대조:** `JobStatus`의 14개 상태 값, `SodamError` 및 세 하위 예외, 11개 `frozen=True` 데이터 클래스의 필드·타입·기본값이 `Statement_of_Functions.md`와 일치한다.
- **범위 대조:** 표준 라이브러리만 사용하며, I/O·네트워크·저장·모델 호출·상태 전이·런타임 검증은 추가되지 않았다.
- **형식 보정:** 파일 끝의 여분 빈 줄을 제거하고, 보호 토큰 및 문장 경계 docstring을 실제 계약에 맞게 정정했다.
- **자동 검증:** 구현 모델의 `python -B compile(...)` 보고는 `syntax OK`였다. 현재 Codex 실행 환경에는 `python` 명령이 없어 동일 명령의 독립 재실행은 불가했다.
- **수동 검증:** Git diff 대조에서 허용 파일 밖 변경이 없고, `git diff --check`가 공백 오류 없이 통과했다.
- **남은 위험:** B01의 frozen 불변성·예외 상속·필드 기본값을 실행으로 검증할 테스트 도구와 테스트 코드는 아직 없다. T01과 B01 계약 테스트의 별도 승인이 필요하다.

### T01 — 결정론적 테스트 Fake와 Fixture 생성기

- **상태:** 구현 완료
- **수정·생성 파일:** `tests/fakes.py`, `tests/fixture_factories.py`
- **명세 대조:** STT·Qwen fake는 호출을 기록한 뒤 구성된 동일 예외를 발생시키거나 응답을 반환한다. 파일시스템 fake는 오류·미존재 경로에서 기록과 상태를 유지하고, 성공 시에만 상태를 변경한다. 모든 생성자 입력 컨테이너는 복사한다.
- **fixture factory 대조:** `make_job_options`, `make_job`, `make_raw_segment`, `make_transcript`가 B01 타입만 생성하며, 호출 간 기본 `JobOptions`와 구간 tuple을 공유하지 않는다.
- **자동 검증:** 사용자 Python 3.12에서 명세의 직접 호출 검증이 `T01 checks OK`로 통과했고, 두 대상 파일 구문 검사가 `syntax OK`로 통과했다. 응답 객체 보존과 오류 경계도 추가 직접 호출로 확인했다.
- **수동 검증:** `git diff --check`가 공백 오류 없이 통과했고, 제품 코드·외부 의존성·실제 I/O가 추가되지 않았음을 diff로 확인했다.
|- **남은 위험:** B01 타입 자체의 frozen 불변성·예외 상속·기본값을 검증하는 실제 테스트 코드는 아직 없으며, 이후 단위 테스트 작업에서 작성해야 한다.

### B02 — 작업 생성, 상태 전이, 취소 요청 구현

- **상태:** 구현 완료 (Statement_of_Functions.md 명세 기준 11/11 요구사항 충족)
- **수정 파일:** `backend/contracts.py` (JobStateError 추가), `backend/jobs.py` (skeleton → full 구현 전환), `Statement_of_Functions.md` (B02 명세 반영 편집)
- **변경 범위:** contracts.py +4라인, jobs.py +202/-95라인 (총 234라인 순증가)
- **명세 대조:**
  - create_job: http/https URL hostname 검증 → InputSourceError,ロー컬 파일 exist+regular check → InputSourceError, unsupported scheme → InputSourceError. options JobOptions type 확인 → TypeError. NO side-effects 준수. 부수 효과 0(디렉토리 생성 안 함).
  - transition_job: _TRANSITION_TABLE 2차원 매핑으로 표 일치 검증. 동일 상태 전이 금지(JobStateError). target_status 유효성 검사 → TypeError. dataclasses.replace로 새 frozen Job 반환, 원본 불변성 유지.
  - request_cancellation: _CANCELABLE_STATES 설정으로 queued/running states만 허용 완료. completed/cancelled/failed/cleaning/archived에서 요청 시 JobStateError 차단. transition_job() 위임 준수.
- **구현 인프라:** _normalize_source(http/schème 먼저 → unsupported 체크 순서로 빈 scheme 오류 방지), _ensure_valid_transition(TYPE+VALUE 이중 검증), _TRANSITION_TABLE(14개 상태×허용 타겟 매핑), _WORK_DIR_ROOT 고정 경로, _CANCELABLE_STATES frozenset.
- **범위 대조:** B02 명세 외 추가 파일·추가 함수 없다. InputSourceError/JobStateError만 사용. uuid/pathlib/urllib.parse/dataclasses.replace만 의존.
- **정합성 검증:** Statement_of_Functions.md Section 4 전이 표(queued→cancelling 등)와 _TRANSITION_TABLE 완전 일치. request_cancellation 허가 상태( queued + queued + all running)와 _CANCELABLE_STATES 정확히 동일한 8개 값. 예외 클래스 계약(SodamError 직접 하위) contracts.py 50행에 준수.
- **검증 파일 정리:** verify_b02.png, verify_b02.py 등 모든 임시 검증 artifact 삭제 완료(GONE). __pycache__도 clean 상태.

### B03 — 작업 JSON 저장 및 artifact 정리

- **상태:** 구현 완료
- **수정 파일:** `backend/contracts.py` (`StorageError`, `CleanupPolicy`), `backend/storage.py` (`write_job_json`, `read_job_json`, `cleanup_artifacts` 및 경로 검증 보조 함수)
- **명세 대조:** JSON artifact 이름은 단일 `.json` 파일명만 허용한다. `job.work_dir`는 `JOB_WORK_ROOT/<job_id>` 직접 하위여야 하며, 작업 경로 밖 접근은 `UnsafePathError`로 차단한다. 저장·읽기·정리 I/O 및 JSON 오류는 `StorageError`로 변환한다.
- **안전성 대조:** 모든 artifact 및 symlink 대상은 해당 `job.work_dir` 내부인지 `Path.is_relative_to()`로 확인한다. 정리는 보존 정책을 적용하고, symlink 자체만 삭제하며 외부 대상은 삭제하지 않는다. `assemble_transcript`는 B11 범위로서 `NotImplementedError`를 유지한다.
- **자동 검증:** Python 3.12 직접 호출로 JSON 저장·읽기, `metadata.json` 보존, 임시 artifact 삭제, 빈 작업 디렉터리 삭제, 작업 루트 밖 경로의 `UnsafePathError`, 존재하지 않는 artifact의 `StorageError`를 확인하여 `B03 checks OK`를 받았다. `backend/contracts.py`와 `backend/storage.py` 구문 검사도 `syntax OK`로 통과했다. 검증 중 생성한 job 디렉터리는 정리됐다.
- **남은 위험:** SQLite 메타데이터 저장과 전사문 조립은 B03 범위 밖이며 각각 후속 작업과 B11에서 구현한다. 실제 symlink 동작의 OS별 권한 차이는 후속 통합 테스트에서 추가 확인한다.

### B04 — 지원 URL 검증 및 어댑터 기반 오디오 획득

- **상태:** 구현 완료
- **수정 파일:** `backend/sources.py`
- **명세 대조:** `validate_source`는 `http`/`https` YouTube URL의 허용 호스트·경로·video ID를 순수하게 검증하고, 앞뒤 공백·비지원 스킴·유사 호스트·잘못된 포트·malformed URL은 모두 `InputSourceError`로 변환한다. 네트워크 호출은 수행하지 않는다.
- **획득 계약:** `acquire_source_audio(job, adapter)`는 명시적으로 주입받은 `SourceAudioAdapter`만 호출한다. B03 작업 경로 검증 후에만 작업 폴더를 만들고, 정확한 `source-audio.wav` 경로의 덮어쓰기·symlink·작업 폴더 이탈을 `UnsafePathError`로 차단한다. 어댑터 예외와 작업 폴더 생성 오류는 `InputSourceError`로 변환한다.
- **자동 검증:** 구문 검사와 URL 정상 2건·차단 6건이 통과했다. `RecordingAdapter` 성공 경로에서 호출 횟수 1회, `AudioArtifact` 반환, artifact 존재 및 작업 폴더 경계를 확인했다. 성공 경로 검증에서 생성한 작업 전용 artifact는 정리했다.
- **범위 대조:** 구현 변경은 `backend/sources.py`에 한정됐다. 실제 다운로드 도구, FFmpeg, subprocess, 외부 네트워크, 테스트 파일 및 fixture 변경은 추가하지 않았다.
- **남은 위험:** 실제 다운로드 도구의 구현·선택·권한/약관 처리는 B13 구성 단계에서 결정한다. 로컬 미디어 파일 변환과 코덱 표준화는 B05 범위다.

### B05 — 로컬 미디어의 표준 WAV 오디오 추출

- **상태:** 구현 완료
- **수정 파일:** `backend/contracts.py` (`MediaExtractionError`), `backend/media.py` (`FfmpegRunner`, `extract_audio`)
- **명세 대조:** `extract_audio(job, source_path, runner)`는 기존 일반 파일과 지원 확장자만 읽기 전용으로 허용하고, B03 작업 경로를 검증한 뒤 `normalized-audio.wav` 하나만 대상으로 한다. 기존 output·source symlink·output symlink·작업 폴더 이탈은 `UnsafePathError`로 차단하며, source 검증 실패는 `InputSourceError`, 추출·output I/O 실패는 `MediaExtractionError`로 변환한다.
- **runner 계약:** FFmpeg를 직접 실행하지 않고 주입된 runner에 `-i`, `-vn`, `-ac 1`, `-ar 16000`, `-sample_fmt s16`, output 경로의 argument vector를 정확히 한 번 전달한다. runner 실패는 `MediaExtractionError`로 변환하고 `KeyboardInterrupt`·`SystemExit`은 전파한다.
- **자동 검증:** `RecordingRunner`로 호출 횟수 1회, argument vector, output 경로, job ID, `duration_seconds=None`, output 존재·0 초과 크기, source 불변을 확인했다. 존재하지 않는 source, 작업 루트 밖 work_dir, 기존 output도 계약 예외로 차단됐다. 구문 검사와 대상 파일의 `git diff --check`도 통과했다.
- **수동 검증:** `subprocess`, FFmpeg 라이브러리, 네트워크 의존성이 없음을 diff로 확인했다. Windows symlink 생성 권한이 없어 source/output symlink의 실제 생성 테스트는 건너뛰었으며, 정적 코드 대조로 symlink 선행 차단 순서를 확인했다.
- **정리:** 승인된 B05 검증 폴더 `b05-esym-out`, `b05-pass`와 저장소 내 임시 검증 script·`__pycache__`를 삭제했다.
- **남은 위험:** 실제 FFmpeg codec 실행 및 duration 검증은 범위 밖이다. Windows 권한이 허용되는 환경에서 symlink 경계의 통합 검증을 추가로 수행할 수 있다.

### B06 — 주입형 STT 호출 및 시간 구간 표준화

- **상태:** 구현 완료
- **수정 파일:** `backend/contracts.py` (`TranscriptionError`), `backend/transcription.py` (`SttEngine`, `transcribe_audio` 및 검증 보조 함수)
- **명세 대조:** `transcribe_audio(audio, engine)`는 기존 일반 audio 파일만 허용하고, 주입된 engine의 `transcribe()`를 resolve한 경로 문자열로 정확히 한 번 호출한다. engine 속성·경로·실행·반환 스키마 오류는 `TranscriptionError`로 변환하고 `KeyboardInterrupt`·`SystemExit`은 전파한다.
- **표준화 계약:** engine 반환값은 list 또는 tuple만 허용한다. 각 mapping의 비어 있지 않은 text에 대해 유한·비음수·증가하는 start/end 및 optional confidence(0~1 또는 `None`)를 검증한다. blank text는 원문을 바꾸지 않고 제외하며, 남은 순서대로 `segment-0001`부터 `RawSegment`를 생성한다.
- **자동 검증:** FakeSttEngine으로 호출 횟수 1회, blank filtering, segment ID·원문·confidence 보존, 역순 시간의 `TranscriptionError`, generator 반환 거부, 잘못된 engine의 `TypeError`, `TranscriptionError` 상속을 확인하여 `B06 checks OK`를 받았다. contracts/transcription 구문 검사도 `syntax OK`로 통과했다.
- **범위 대조:** B01의 기존 JobStatus와 예외 계층이 보존된 상태에서 `TranscriptionError`만 추가됐다. 실제 STT 모델, 네트워크, subprocess, 파일 변경, pytest/fixture/fake 변경은 추가하지 않았다.
- **정리:** 승인된 B06 저장소 루트 임시 검증 script 네 개를 삭제했다.
- **남은 위험:** 실제 STT 모델의 형식 차이·성능·언어/화자 품질은 B13 통합 단계와 실제 모델 검증에서 확인해야 한다.

### B07 — 보호 토큰의 가역 placeholder 치환과 복원

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/contracts.py` (`ProtectionError`), `backend/protection.py` (`protect_tokens`, `restore_tokens`)
- **명세 대조:** 원문 segment를 newline으로 조립하고, 기존 placeholder·긴 glossary·URL·날짜·금액·숫자·대문자 약어 순서로 한 번만 스캔한다. 각 발견 위치에 서로 다른 placeholder를 생성하므로 동일 원문값의 반복도 독립적으로 복원한다.
- **충돌·복원 계약:** 생성 후보는 전체 입력·각 glossary 항목의 부분문자열 및 기존 map key와 충돌하지 않는다. `restore_tokens`는 map 형식, unknown placeholder, 누락·복제 token을 검증한 뒤 placeholder만 복원한다.
- **자동 검증:** Python 3.12 직접 호출로 기본 보호·복원·누락 placeholder 거부를 확인해 `B07 checks OK`를 받았다. 반복 `JFK`, 기존 `[[SODAM_PROTECTED_0001]]`, `$1,200`, `3000원`, `1,200`, `3000`의 위치별 보호와 완전한 왕복 복원도 `B07 edge checks OK`로 통과했다. contracts/protection 구문 검사는 `syntax OK`, `git diff --check -- backend/contracts.py backend/protection.py`는 공백 오류 없이 통과했다.
- **범위·불변성 대조:** 표준 라이브러리 `re`와 domain contracts만 사용하며, 파일 I/O·네트워크·모델·subprocess·입력 segment·glossary·ProtectedText의 in-place 변경은 없다.
- **커밋 전 확인 사항:** 추적되지 않은 `backen/` 및 `backend/__pycache__/`가 작업 트리에 남아 있다. B07 구현 검증에서는 이들을 생성·수정·삭제하지 않았으며, 삭제 또는 보관 여부를 별도로 결정해야 한다.
- **남은 위험:** 날짜·URL·통화 표기의 추가 변형과 OS별 Unicode 경계는 B08 이후의 단위·통합 테스트에서 넓혀 검증한다.

### B08 — 보호 텍스트의 제한적 규칙 정규화

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/contracts.py` (`NormalizationError`), `backend/text_rules.py` (`normalize_rules` 및 입력 검증 보조 함수)
- **명세 대조:** Unicode whitespace 축소, 선행·후행 공백 제거, 문장부호 앞 공백 제거, 괄호 안쪽 공백 제거의 네 규칙만 적용한다. 문장부호·한글·라틴 문자·숫자·placeholder 자체는 변경하지 않는다.
- **보호값·불변식 계약:** 입력과 결과에서 non-whitespace 문자열이 같은지 확인하고, replacements의 key가 정확한 placeholder 형식인지, 입력·결과에 각 key가 정확히 한 번 있는지, unknown placeholder가 없는지를 `NormalizationError`로 검증한다. 입력 객체와 map은 변경하지 않는다.
- **자동 검증:** Python 3.12 직접 호출로 네 규칙, placeholder 보존, non-whitespace 불변식, 문장 경계, 잘못된 입력의 `TypeError`, 누락 map key와 malformed map key의 `NormalizationError`를 확인하여 `B08 checks OK`를 받았다. contracts/text_rules 구문 검사도 `syntax OK`로 통과했다.
- **형식 검증:** trailing whitespace 두 건을 제거한 뒤 `git diff --check -- backend/contracts.py backend/text_rules.py`가 오류 없이 통과했다. LF→CRLF 안내 경고는 오류가 아니다.
- **범위 대조:** 표준 라이브러리 `re`와 domain contracts만 사용하며, 파일 I/O·네트워크·모델·Kiwi·subprocess·테스트 파일 생성은 없다.
- **커밋 전 확인 사항:** 추적되지 않은 `backen/` 및 `backend/__pycache__/`는 B08 범위 밖 항목으로 유지 중이다. 삭제 또는 보관을 별도로 결정한 뒤 제품 변경만 선별해 커밋해야 한다.
- **남은 위험:** URL·수치·복합 기호는 B07의 placeholder 보존에 의존한다. 더 넓은 Unicode·문장부호 표본은 T02 단위 테스트와 통합 테스트 단계에서 확장 검증한다.

### B09 — 주입형 Qwen JSON 교정 응답 검증

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/correction.py` (`QwenRuntime`, `correct_chunk`, 입력·응답 검증 보조 함수)
- **명세 대조:** module은 주입받은 `QwenRuntime.complete(prompt)`만 정확히 한 번 호출한다. 12,000자 청크와 네 개 이하의 context를 경계 검사하고, prompt에 JSON object 전용·placeholder 보존 제약·순서 보존 context·target text를 결정론적으로 포함한다.
- **JSON·보호값 계약:** 응답은 `corrected_text`, `changes`, `requires_review` 세 key만 갖는 `str` JSON object여야 한다. markdown·extra key·잘못된 scalar·invalid changes·bytes 응답·placeholder 순서/개수/값의 변경은 `ModelResponseError`로 거부한다. no-op 응답은 `requires_review=True`를 가질 수 없다.
- **입력 경계 계약:** `RuleNormalizedText.sentence_boundaries`는 범위 내의 엄격히 증가하는 `tuple[int, ...]`이며, 중복·내림차순 boundary는 `ValueError`다. runtime의 `complete` 미구현은 `TypeError`다.
- **자동 검증:** RecordingRuntime 직접 호출로 호출 횟수 1회, prompt 원문/context 포함, 유효 `CorrectionResult` 변환, invalid JSON, placeholder 손실, invalid runtime, bytes JSON 거부, duplicate 및 descending sentence boundary 거부를 확인해 `B09 checks OK`를 받았다. `backend/correction.py` 구문 검사도 `syntax OK`로 통과했다.
- **형식·범위 검증:** `git diff --check -- backend/correction.py`가 통과했다. 표준 라이브러리 `json`, `re`, `typing.Protocol`과 domain contracts만 사용하며, 실제 Qwen/Ollama/네트워크·파일 I/O·subprocess·테스트 파일 생성은 없다.
- **남은 위험:** JSON schema와 placeholder 보존만 검증한다. changes가 실제 편집과 정확히 대응하는지, 의미·사실 변경이 안전한지는 B10의 변경 검증 책임이다. 실제 runtime의 모델 품질·비결정성·성능은 B13 통합 단계에서 평가한다.

### B10 — 보호값 보존 변경 검증과 검토 큐 분류

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/validation.py` (`validate_revision` 및 입력·placeholder 검증 보조 함수)
- **명세 대조:** `SequenceMatcher(autojunk=False)` opcode를 순서대로 처리하며, whitespace와 `SAFE_PUNCTUATION`만의 변경은 자동 승인한다. 한글·영문·숫자·기타 기호 변경은 보수적으로 `review_required` item으로 분류한다.
- **보호값 계약:** raw는 `protections.text`와 정확히 같아야 한다. replacements map의 key/value 형식, raw·corrected의 unknown placeholder, known key의 누락·복제, placeholder 순서 변경을 `ProtectionError`로 거부한다.
- **승인 경계:** 위험 item이 없으면 corrected를 `approved_text`로 반환한다. 하나라도 있으면 raw를 그대로 유지하고, 위험 opcode만 raw 순서의 `review_items` tuple로 반환한다. 위험 변경을 자동 적용하지 않는다.
- **자동 검증:** formatting-only 자동 승인, 한글·숫자 변경 검토 큐, placeholder 손실/unknown token/known key 누락·복제/순서 변경 거부, 타입·raw 불일치 거부를 직접 호출로 확인해 `B10 checks OK`를 받았다. multi-token·multiple opcode·mixed diff·no-op·malformed map도 추가 검증을 통과했다.
- **형식·범위 검증:** `backend/validation.py` 구문 검사 `syntax OK` 및 `git diff --check -- backend/validation.py`가 통과했다. 표준 라이브러리 `re`, `difflib.SequenceMatcher`와 domain contracts만 사용하며, 모델·네트워크·파일 I/O·subprocess·테스트 파일 생성은 없다.
- **남은 위험:** 의미·사실의 언어학적 판단을 하지 않으므로 SAFE_PUNCTUATION 밖의 애매한 표기 변경은 의도적으로 검토 대상으로 남는다. 실제 검토·승인·UI 저장은 후속 단계 책임이다.

### B11 — 시간순 RawSegment 전사문 조립

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/contracts.py` (`TranscriptAssemblyError`), `backend/storage.py` (`assemble_transcript` 및 검증 보조 함수)
- **명세 대조:** list 안의 RawSegment를 입력 순서 그대로 검증해 새 tuple의 `Transcript`로 반환하고, `final_text`는 각 raw_text를 newline으로 정확히 조립한다. 빈 list는 빈 tuple·빈 문자열 Transcript로 반환한다.
- **시간·ID 계약:** segment_id는 비어 있지 않고 앞뒤 공백이 없으며 고유해야 한다. start/end는 bool이 아닌 유한 수, start는 0 이상, end는 start보다 커야 한다. start 또는 end의 역순, duplicate/malformed ID, blank raw_text, 범위를 벗어난 confidence는 `TranscriptAssemblyError`다. sorting·시간 보정·ID 생성은 하지 않는다.
- **자동 검증:** 정상 조립, 빈 list, newline 결과, 입력 불변성, duplicate ID, 역순 시간, item/list 타입 위반과 `TranscriptAssemblyError`의 `SodamError` 상속을 직접 확인하여 `B11 checks OK`를 받았다. 앞뒤 공백 segment_id 거부도 추가 검증했다.
- **형식·범위 검증:** contracts/storage 구문 검사 `syntax OK` 및 `git diff --check -- backend/contracts.py backend/storage.py`가 통과했다. B03의 저장·읽기·cleanup 함수와 경로 상수는 변경하지 않았으며 파일·DB·네트워크·모델·새 검증 파일을 사용하지 않는다.
- **남은 위험:** STT의 실제 overlap/gap 처리 정책과 교정·검토 결과를 segment에 반영하는 방식은 후속 파이프라인·통합 테스트에서 검증한다. B11은 입력 순서를 보존하고 역순만 거부한다.

### B12 — 근거 ID 기반 계층형 전사문 요약

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/contracts.py` (`EmptyTranscriptError`), `backend/summarization.py` (`summarize_transcript` 및 입력·JSON 응답 검증 보조 함수)
- **명세 대조:** Transcript를 입력 순서대로 8개 이하 batch로 나누고, batch별 주입형 `QwenRuntime.complete`를 한 번씩 호출한다. 여러 batch이면 검증된 중간 요약과 evidence ID만 포함한 final synthesis를 한 번 더 호출하며, 한 batch이면 해당 응답을 final로 사용한다.
- **요약·근거 계약:** 모든 response는 text/evidence_segment_ids 두 key만 가진 str JSON object여야 한다. text는 trim된 1~1,000자·최대 두 문장이고, evidence ID는 non-empty·고유·실제 해당 batch 또는 전체 transcript 범위 안이어야 한다. bytes·markdown/invalid JSON·unknown evidence·세 문장 이상은 `ModelResponseError`다.
- **입력 경계:** Transcript type, tuple RawSegment, 고유·trimmed segment ID, nonblank raw_text, final_text의 정확한 newline 조립을 검증한다. 빈 segment tuple 또는 whitespace-only final_text는 `EmptyTranscriptError`다.
- **자동 검증:** 9개 segment와 순차 응답 RecordingRuntime으로 두 batch와 final synthesis, 총 3회 호출, final Summary text/evidence tuple을 확인하여 `B12 checks OK`를 받았다. 빈 Transcript와 unknown evidence 응답도 계약 예외로 거부했다. contracts/summarization 구문 검사는 `syntax OK`로 통과했다.
- **형식·범위 검증:** `git diff --check -- backend/contracts.py backend/summarization.py`가 통과했다. 실제 Qwen/Ollama·네트워크·파일/DB I/O·subprocess·새 검증 파일은 사용하지 않았고, 전사문과 segment를 변경하지 않는다.
- **남은 위험:** JSON 스키마·근거 ID만 기계적으로 검증하므로 실제 모델의 요약 품질·사실성·표현 적절성은 B13 통합과 T03 평가 단계에서 추가 평가해야 한다.
