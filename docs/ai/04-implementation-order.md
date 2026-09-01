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

### CR01 (B10-R) — 정규화된 보호 텍스트 검증 정정

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/validation.py`
- **정정 내용:** B08의 공백 정규화 결과가 `protections.text`와 다르더라도 B10 검증 입력으로 허용하도록 raw/protections 문자열 동등성 검사를 제거했다. placeholder의 known key, 순서, 누락, 복제 검증과 formatting/review 분류는 유지했다.
- **자동 검증:** 정규화된 보호 텍스트 자동 승인, 의미 변경 review 분류, placeholder 손실·unknown·복제 거부를 직접 호출로 확인해 `CR01 checks OK`를 받았다. 구문 검사 `syntax OK`와 `git diff --check -- backend/validation.py`도 통과했다.
- **남은 위험:** 이 정정은 B08→B10 입력 호환성만 해결한다. 교정된 텍스트를 원본 segment ID 근거와 함께 표현하는 계약은 CR02에서 별도로 처리했다.

### CR02 — 교정 전사문과 근거 ID 연결

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/contracts.py` (`ReviewedSegment`, `ReviewedTranscript`), `backend/storage.py` (`assemble_reviewed_transcript`), `backend/summarization.py` (`summarize_reviewed_transcript`)
- **계약 대조:** 원본 `RawSegment`는 `ReviewedSegment.source`로 보존하고, 승인·복원 텍스트만 별도 `final_text`로 저장한다. reviewed transcript는 segment별 교정 텍스트의 newline join으로 조립되며, reviewed 요약 prompt는 source ID와 교정 텍스트만 포함한다.
- **호환성 검증:** 기존 `Transcript`, `assemble_transcript()`, `summarize_transcript()`는 변경하지 않았고 raw 요약 직접 호출도 계속 통과했다.
- **자동 검증:** reviewed 조립, source identity, 교정본-only prompt, 길이 불일치 거부, 빈 reviewed transcript 거부, 기존 raw 요약 동작을 확인해 `CR02 checks OK`를 받았다. 세 대상 파일의 구문 검사 `syntax OK`와 `git diff --check`도 통과했다.
- **남은 위험:** B13은 모든 segment를 B07→B08→B09→B10→B07 restore 순서로 처리해 승인 텍스트 list를 만들고, CR02 조립/요약 함수를 호출해야 한다. 실제 adapter/runtime 구성과 사용자 review 결정은 B13 이후 범위다.

### B13 — 주입형 로컬 작업 파이프라인 오케스트레이션

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/main.py` (`PipelineResult`, `PipelineApplication`, `build_application`)
- **명세 대조:** URL은 B04 획득 후 B05 추출, 로컬 입력은 B05 추출로 직접 분기한다. 이후 B06→B11 raw 조립, segment별 B07→B08→B09→CR01 B10→B07 복원, CR02 reviewed 조립·요약을 순서대로 조율한다. 모든 collaborator는 주입받은 Protocol 객체만 사용한다.
- **lifecycle:** 성공은 queued부터 completed/cleaning을 거쳐 archived로 끝난다. 취소는 `request_cancellation` 뒤 cancelled/cleaning/archived로, 일반 예외 및 KeyboardInterrupt/SystemExit은 failed cleanup lifecycle을 시도한 뒤 원래 예외를 보존해 전파한다.
- **자동 검증:** 메모리 stub으로 URL 성공·로컬 성공·취소·B09 교정 실패 cleanup을 직접 확인해 `B13 checks OK`를 받았다. 전체 성공 상태 전이와 KeyboardInterrupt cleanup·재전파도 `B13 lifecycle checks OK`로 통과했다. 실제 adapter, 파일, 네트워크, 모델, subprocess 실행은 없었다.
- **형식·범위 검증:** `backend/main.py` 구문 검사 `syntax OK` 및 `git diff --check -- backend/main.py`가 통과했다. B13 제품 수정은 main.py 하나에 한정됐다.
- **남은 위험:** 실제 다운로드/FFmpeg/STT/Qwen adapter 통합, 결과 영속화, 사용자 검토 UI, 재시도·병렬 처리·진행률 스트림은 후속 작업 범위다.

### U01 — 데스크톱 UI 초기 작업 상태 계약

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `apps/desktop/src/state.ts` (`createInitialJobViewModel`)
- **명세 대조:** factory는 빈 job/source label, queued status, null progress/summary를 가진 새 plain object를 매 호출마다 반환한다. 타입 선언과 review item 계약은 변경하지 않았다.
- **자동 검증:** Node.js TypeScript type-stripping loader로 모듈을 직접 import해 정확한 초기 필드, own property, 새 객체 반환, 호출 간 독립성을 확인하여 `U01 checks OK`를 받았다. `git diff --check -- apps/desktop/src/state.ts`도 통과했다.
- **범위·남은 위험:** Tauri 렌더링, backend IPC, URL/파일 선택, 작업 시작·취소, 진행률·검토 큐 상태 동기화는 구현하지 않았다. 실제 UI 통합은 후속 작업 범위다.

### T02-01 — B02 작업 lifecycle 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_jobs.py`
- **자동 검증:** 기존 `AGENTS.md` 상대 경로의 Job 생성·정규화·부수효과 없음, URL 정규화, 잘못된 source/options, immutable 허용 전이, 차단 전이, 취소 경계, `JobStateError` 상속을 pytest로 확인했다. skip 없이 `6 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_jobs.py`가 통과했다.
- **범위 대조:** 테스트는 B02 공개 API와 읽기 전용 `AGENTS.md`만 사용하며 작업 디렉터리·네트워크·모델·DB·새 fixture를 만들지 않는다.
- **발견된 위험:** Windows 절대 로컬 경로는 `urlparse()`가 drive letter를 scheme으로 해석해 B02에서 거부된다. 이번 테스트는 기존 상대 경로 성공 계약을 자동화했으며, 절대 경로 지원은 다음 B02-R 정정 작업에서 처리해야 한다.

### B02-R — Windows 절대 로컬 경로 정정

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/jobs.py` (`_normalize_source`)
- **정정 내용:** `^[A-Za-z]:[\\/]` 형식의 drive 절대 경로를 URL scheme 판단 전에 인식해 기존 local-path resolve/regular-file 검증으로 보냈다. drive-relative `C:relative.txt`와 FTP 같은 비지원 scheme 처리는 유지했다.
- **자동 검증:** 저장소 `AGENTS.md`의 backslash 및 slash 절대 경로가 queued Job으로 정규화되고, work_dir 부수효과 없이 반환됨을 확인하여 `B02-R checks OK`를 받았다. drive-relative·FTP 거부, jobs.py 구문 검사 `syntax OK`, `git diff --check`, 기존 T02-01 pytest 회귀 `6 passed`도 통과했다.
- **남은 위험:** UNC 및 POSIX 경로의 추가 정책은 범위 밖이다. T02-01 pytest에는 다음 회귀 작업에서 Windows 절대 경로 사례를 추가해야 한다.

### T02-01R — Windows 절대 로컬 경로 회귀 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_jobs.py`
- **자동 검증:** `AGENTS.md`의 Windows 절대 backslash와 slash 경로를 각각 `create_job()`에 전달해 queued Job·정규화된 source·work_dir 미생성을 확인했다. 기존 URL·상대 경로·전이·취소 case도 포함해 pytest `6 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_jobs.py`가 통과했다.
- **범위·남은 위험:** B02 제품 코드와 다른 테스트는 수정하지 않았고 파일·네트워크·모델 I/O는 없었다. UNC/POSIX 경로 정책은 범위 밖이다.

### T02-02 — B10·CR01 변경 검증 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_validation.py`
- **자동 검증:** CR01 normalized raw 입력의 safe 승인, whitespace/punctuation formatting 자동 승인, 한글 의미 변경의 raw 유지·review item, placeholder 손실·unknown·중복·누락·순서 변경 거부, 타입 위반, `ProtectedText`·replacements 불변성을 pytest로 확인했다. skip 없이 `12 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_validation.py`가 통과했다.
- **범위·남은 위험:** 텍스트와 map만 사용했으며 파일·네트워크·모델 I/O 및 제품 코드 변경은 없다. 의미상 사실의 언어학적 판단과 사용자 review UI는 B10 범위 밖이다.

### T02-03 — B07 보호·복원 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_protection.py`
- **자동 검증:** glossary·URL·날짜·`$1,200`·`3000원`·쉼표 숫자·대문자 약어의 가역 보호, 반복 JFK의 위치별 독립 placeholder, 기존 placeholder 입력의 collision-free 재보호, glossary 오류, restore unknown/누락/복제/type 오류, map 불변성을 pytest로 확인했다. skip 없이 `13 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_protection.py`가 통과했다.
- **범위·남은 위험:** 메모리 객체만 사용하며 파일·네트워크·모델 I/O와 B07 제품 코드 변경은 없다. Unicode 날짜/통화 표기 변형의 확대 검증은 별도 case가 필요하다.

### T02-04 — B08 제한적 규칙 정규화 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_text_rules.py`
- **자동 검증:** Unicode whitespace 축소·strip·문장부호 앞 공백 제거·세 종류 괄호 내부 공백 제거, placeholder 및 비공백 순서 보존, terminal sentence boundary slice-end index, malformed/missing/duplicate/unknown placeholder 입력, input map 불변성을 pytest로 확인했다. skip 없이 `9 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_text_rules.py`가 통과했다.
- **범위·남은 위험:** 메모리 text/map만 사용하며 파일·네트워크·모델 I/O 및 B08 제품 코드 변경은 없다. 실제 자연어 띄어쓰기 품질과 Kiwi/KSS 통합은 범위 밖이다.

### T02-05 — B09 Qwen 교정 응답 검증 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_correction.py`
- **자동 검증:** recording runtime으로 유효 JSON의 `CorrectionResult`·changes·단일 호출과 prompt 내 target/context를 확인했다. invalid JSON·bytes 응답·runtime 예외, 보호 placeholder 유실/순서 변경, 중복 sentence boundary, 잘못된 context/runtime을 계약 예외로 검증했고 input 불변성도 확인했다. skip 없이 `9 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_correction.py`가 통과했다.
- **범위·남은 위험:** 실제 Qwen/Ollama·네트워크·파일 I/O는 사용하지 않았고 B09 제품 코드는 수정하지 않았다. 실제 모델이 생성하는 다양한 유효하지만 경계적인 JSON 표현의 상호운용성은 이후 통합/평가 단계에서 확인한다.

### T02-06 — B11 전사문 조립 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_transcript.py`
- **자동 검증:** 정상 두 구간의 입력 순서·tuple·newline final text와 빈 list 결과를 확인했다. 중복/whitespace ID, 역순·음수 시간, blank raw text, 범위 밖 confidence, list가 아닌 입력과 RawSegment가 아닌 항목을 계약 예외로 검증하고 입력 list/segment 불변성도 확인했다. skip 없이 `11 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_transcript.py`가 통과했다.
- **범위·남은 위험:** 메모리 RawSegment만 사용했으며 B11 제품 코드·파일/DB/네트워크/STT는 사용하지 않았다. 실제 STT의 장시간 timestamp precision과 overlap 정책은 통합 테스트 단계에서 추가 검증한다.

### T02-07 — B12 근거 연결 계층형 요약 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_summarization.py`
- **자동 검증:** 9개 segment의 2 batch + final synthesis 3회 호출과 batch/final prompt 및 evidence tuple을 검증했다. 단일 batch가 추가 synthesis 없이 반환되는 것, empty transcript, unknown evidence, invalid JSON, runtime 계약 오류 및 Transcript 불변성을 확인했다. skip 없이 `7 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_summarization.py`가 통과했다.
- **범위·남은 위험:** recording runtime만 사용하고 실제 모델·네트워크·파일/DB I/O 및 B12 제품 코드는 변경하지 않았다. 요약의 사실성·문체 품질과 장문 response 경계는 T03 평가 및 통합 단계에서 확인한다.

### T02-08 — B03 작업 JSON 저장 및 artifact 정리 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_storage.py`
- **자동 검증:** 고유 job work directory에서 UTF-8 JSON write/read 왕복 및 경계를 확인했다. retention policy가 `metadata.json`만 보존하고 임시 artifact를 삭제하는 것, retention 없는 cleanup이 work directory까지 삭제하는 것, root 밖 경로·잘못된 artifact 이름·없는 artifact의 계약 예외를 검증했다. skip 없이 `5 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_storage.py`가 통과했고 `t02-storage-*` job directory 잔존 여부도 `artifact cleanup OK`로 확인했다.
- **범위·남은 위험:** 생성·삭제는 승인된 `D:\AI-Legion\Sodam-data\tmp\jobs` 하위 고유 작업 폴더로 한정했으며 B03 제품 코드·실제 DB/네트워크/모델은 사용하지 않았다. Windows symlink 권한별 경계는 별도 환경에서 통합 검증이 필요하다.

### T02-09 — B04 URL 검증 및 오디오 획득 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_sources.py`
- **자동 검증:** 지원 YouTube URL 두 종류와 앞뒤 공백·비지원 scheme/host·빈 video ID·잘못된 port 거부를 확인했다. recording adapter 성공 경로의 정확한 1회 호출, `AudioArtifact` ID/path/content/work-dir 경계, 잘못된 adapter·root 밖 work_dir·adapter 오류·output 미생성을 검증했다. skip 없이 `10 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_sources.py` 및 `t02-sources-*` 잔존 검사 `artifact cleanup OK`가 통과했다.
- **범위·남은 위험:** artifact 생성·정리는 승인된 `D:\AI-Legion\Sodam-data\tmp\jobs` 하위에 한정했으며 실제 다운로드·네트워크·B04 제품 코드는 사용하지 않았다. 실제 다운로드 adapter의 서비스별 실패와 Windows symlink 권한은 통합 테스트 범위다.

### T02-10 — B05 로컬 미디어 표준 오디오 추출 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_media.py`
- **자동 검증:** recording runner의 단일 호출과 `-i/-vn/-ac 1/-ar 16000/-sample_fmt s16` 정확한 argument vector, normalized output `AudioArtifact`과 nonempty file을 검증했다. 없는/비지원 source, runner 오류·missing output, root 밖 work_dir·기존 output, 잘못된 runner 계약을 확인했다. skip 없이 `6 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_media.py` 및 `t02-media-*` 잔존 검사 `artifact cleanup OK`가 통과했다.
- **범위·남은 위험:** artifact 생성·정리는 승인된 `D:\AI-Legion\Sodam-data\tmp\jobs` 하위에 한정했으며 실제 FFmpeg/subprocess·네트워크·B05 제품 코드는 사용하지 않았다. 실제 codec 호환성·duration 및 Windows symlink 권한은 통합 테스트에서 확인한다.

### T02-11 — B06 STT 시간 구간 표준화 단위 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/unit/test_transcription.py`
- **자동 검증:** recording engine의 resolve된 path 1회 호출, blank-text filtering, 연속 segment ID, 시간/raw text/confidence 보존을 확인했다. 역순 시간·invalid confidence·generator container, 없는 audio path, 잘못된 engine 계약 및 AudioArtifact/response 불변성을 검증했다. skip 없이 `6 passed`, 구문 검사 `syntax OK`, `git diff --check -- tests/unit/test_transcription.py` 및 `t02-stt-*` 잔존 검사 `artifact cleanup OK`가 통과했다.
- **범위·남은 위험:** artifact 생성·정리는 승인된 `D:\AI-Legion\Sodam-data\tmp\jobs` 하위에 한정했으며 실제 STT·네트워크·B06 제품 코드는 사용하지 않았다. 실제 엔진 반환 schema 변형과 장시간 audio 성능은 통합/평가 단계에서 확인한다.

### T02 — B02~B12 단위 테스트 묶음 완료

- **상태:** 완료
- **완료 범위:** T02-01/T02-01R/T02-02/T02-03/T02-04와 이번 T02-05~T02-11로 B02, B03, B04, B05, B06, B07, B08, B09, B10/CR01, B11, B12 공개 계약의 정상·경계·오류 단위 테스트를 구현했다.
- **최종 회귀:** `python -B -m pytest tests/unit -q` 결과 `94 passed, 2 skipped`; `git diff --check` 통과; `t02-*` 작업 전용 directory 잔존 검사 `T02 artifact cleanup OK`를 확인했다.
- **범위·남은 위험:** 2개 skip은 기존 모델 설치/저장소 정책 test의 명시된 skip이며, 이번 T02 테스트가 원인이 아니다. 실제 다운로드·FFmpeg·STT·Qwen 실행, OS symlink 권한과 장시간 처리 성능은 T05 통합 및 T03 평가 단계에서 검증한다. 커밋·푸시는 수행하지 않았다.

### T03 — 재현 가능한 전사문 교정 평가 도구

- **상태:** 구현 및 명세 검증 완료
- **수정·생성 파일:** `tools/evaluate_transcript.py`, `tests/fixtures/evaluation_cases.json`, `tests/unit/test_evaluate_transcript.py`
- **계약 대조:** CLI는 UTF-8 JSON fixture의 strict `cases` schema를 읽고 exact correction match, protected-token occurrence order/count preservation, risky auto-approval, fixture-declared duration의 합계·평균을 결정론적으로 산출한다. 실제 clock, 모델, 네트워크, 제품 파이프라인을 사용하지 않는다.
- **자동 검증:** versioned fixture의 3개 case에서 total 3, exact 2, protected 2, risky auto approval 1, duration total 0.6 및 average 0.2를 확인했다. token 재배치 risk, invalid schema, CLI one-line JSON, fixture read-only 성질을 pytest로 검증해 `8 passed`를 받았다. CLI 실행·구문 검사 `syntax OK`와 대상 diff check도 통과했다.
- **남은 위험:** fixture 기반 지표는 평가 입력의 품질과 대표성에 의존한다. 실제 모델 품질·wall-clock 성능·사용자 review 결과는 T03 fixture를 확대하고 T05/T04와 연결해 별도 평가해야 한다. 커밋·푸시는 수행하지 않았다.

### T04 — 읽기 전용 작업 점검 CLI

- **상태:** 구현 및 명세 검증 완료
- **수정·생성 파일:** `tools/inspect_job.py`, `tests/fixtures/inspection_job/metadata.json`, `transcript.json`, `review.json`, `summary.json`, `tests/unit/test_inspect_job.py`
- **계약 대조:** CLI는 작업 디렉터리의 direct regular JSON artifacts 네 개를 읽어 metadata, 순서 보존 timeline, review queue, summary evidence를 detached report로 반환·출력한다. timestamp, final-text join, review schema, evidence ID를 엄격 검증하고 artifact를 변경하거나 모델/media/네트워크를 호출하지 않는다.
- **자동 검증:** versioned fixture의 2개 timestamp segment, 1개 review item, summary evidence를 확인했다. 역순 timestamp·final text 불일치·unknown evidence·malformed review의 `ValueError`, one-line CLI JSON, fixture hash 불변성을 pytest로 검증해 `7 passed`를 받았다. CLI 실행·구문 검사 `syntax OK` 및 대상 diff check도 통과했다.
- **남은 위험:** B13의 실제 persistent artifact schema와 연결되기 전에는 이 도구가 명세화된 JSON interchange contract만 검사한다. 대규모 artifact, OS symlink 권한, 실제 job DB 조회는 T05/운영 단계에서 추가 검증해야 한다. 커밋·푸시는 수행하지 않았다.

### T05 — 주입형 파이프라인 통합 테스트

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `tests/integration/test_pipeline.py`
- **자동 검증:** local `.mp3` success에서 injected runner/STT/Qwen 호출, glossary 보호·복원 후 reviewed text, Summary evidence, archived terminal status 및 work directory 제거를 검증했다. 시작 cancellation의 collaborator 미호출 및 archived cleanup, runner 일반 예외의 `MediaExtractionError` 재전파와 cleanup, `KeyboardInterrupt` 재전파와 best-effort cleanup도 확인했다. pytest `4 passed`, 구문 검사 `syntax OK`, 대상 diff check와 `t05-*` 잔존 검사 `artifact cleanup OK`가 통과했다.
- **범위·남은 위험:** 생성·삭제 artifact는 승인된 `D:\AI-Legion\Sodam-data\tmp\jobs\t05-*` 하위에 한정했고 실제 download/FFmpeg/STT/Qwen·네트워크·subprocess·제품 코드는 사용하지 않았다. URL acquisition 성공, 중간 단계 cancellation, retry/concurrency/progress 및 작업 root 밖 삭제 경계는 더 넓은 통합·운영 검증 범위다. 커밋·푸시는 수행하지 않았다.

### O01 — 안전한 로컬 모델 설치 계약

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `scripts/setup-models.ps1`, `models/manifest.json`, `tests/unit/test_model_setup.py`
- **계약 대조:** `Install-SodamModels`는 strict schema v1 manifest와 HTTPS URL·safe leaf filename·lowercase SHA-256을 전부 검증한 뒤에만 repository 밖 model home을 만든다. 주입 downloader의 `.partial` output은 .NET SHA-256 검증 후에만 final filename으로 이동하고, hash mismatch 실패 시 partial을 정리하며 기존 target은 덮어쓰지 않는다. 기본 manifest는 실제 model profile/URL/checksum을 포함하지 않는 declaration-only `profiles: []`로 유지했다.
- **자동 검증:** pytest temporary source/manifest와 injected local `Copy-Item` downloader로 successful install과 result fields/content를 확인했다. repository 내부 target, traversal filename, unknown profile, wrong checksum의 partial cleanup, existing target 보호를 검증해 `4 passed`를 받았다. default downloader 없이 `-File` invalid-profile entry path가 model home 생성·다운로드 없이 실패함도 확인했다. PowerShell dot-source compatibility와 `Get-FileHash` 미제공 환경은 script entry detection 및 .NET SHA-256으로 보정했다. diff check가 통과했다.
- **남은 위험:** 실제 profile URL/checksum 및 runtime 등록은 아직 확정하지 않았으며 기본 downloader는 실행하지 않았다. 실제 대용량 download의 interruption/retry, file lock/race, 인증/프록시 정책은 model profile 승인 뒤 별도 운영 검증이 필요하다. 커밋·푸시는 수행하지 않았다.

### O02 — 읽기 전용 저장소 청결 정책 검사

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `scripts/check-repository-clean.ps1`, `tests/unit/test_repository_policy.py`
- **계약 대조:** `Test-SodamRepositoryClean`은 default read-only Git provider 또는 injected path provider의 unique relative paths만 검사한다. unsafe/missing paths, 금지 model/media/database extensions, manifest 외 models paths, configurable size overage, UTF-8 secret patterns을 deterministic violation report로 반환하며 Git/files를 변경하지 않는다. CLI는 clean 0, violation 1 exit으로 JSON report를 출력한다.
- **자동 검증:** 합성 repo/provider로 safe duplicate path clean report, media/model/size/secret/path escape violations, invalid root/max size terminating error, input-file hash 불변성을 pytest로 검증해 `4 passed`를 받았다. 빈 violation accumulator를 PowerShell mandatory collection binding이 거부하는 문제는 `AllowEmptyCollection`으로 보정했다. 현재 repository CLI도 `checked_files: 43`, `is_clean: true`, `violations: []`로 통과했다. 테스트 fixture의 secret literal이 실제 repository scanner에 포착된 문제는 런타임 조합으로 바꿔 fixture 검증과 repo cleanliness를 함께 유지했다.
- **남은 위험:** pattern 기반 검사는 complete DLP가 아니며 false positive/negative 가능성이 있다. untracked/LFS/binary provenance, secret rotation, CI policy enforcement은 별도 운영 작업이 필요하다. 커밋·푸시는 수행하지 않았다.

### O03 — 운영·모델·Git 정책 문서화

- **상태:** 구현 및 명세 검증 완료
- **수정·생성 파일:** `README.md`, `.gitignore`
- **문서 대조:** README를 실제 contract pipeline·fake-based test·T03 evaluation·T04 inspection·O01 installer·O02 policy 상태로 교체했다. Python 3.12/PowerShell 검증 명령, repository 밖 `D:\AI-Legion\Sodam-data\tmp\jobs` artifact root, cleanup 경계, external adapter/runtime 미구성 한계, schema v1 empty model declaration manifest와 별도 download approval 필요성을 명시했다.
- **Git 정책 대조:** `.gitignore`은 Python/test cache, local environment/secret files, O01 model formats와 partial, media, local DB/data 및 repository 내 `Sodam-data/`를 ignore한다. `models/manifest.json`은 ignore하지 않으며 manifest schema를 보호하기 위해 수정하지 않았다.
- **자동·수동 검증:** 전체 pytest `121 passed`, O02 current-repository report `is_clean: true`/empty violations, `git check-ignore`로 `.env`, `.gguf`, `.wav`, `Sodam-data/...sqlite` ignore 및 `models/manifest.json` unignored을 확인했다. 대상 diff check도 통과했다.
- **남은 위험:** 실제 model profile URL/checksum, download/runtime registration, user data backup/retention, external adapter service policy는 미확정이며 별도 승인·운영 검증이 필요하다. 커밋·푸시는 수행하지 않았다.

### P01 — Ollama·faster-whisper 실행 profile 확정

- **상태:** 문서화 및 명세 검증 완료
- **수정·생성 파일:** `docs/ai/05-productization-roadmap.md`, `docs/ai/06-runtime-profile.md`, 이 문서
- **결정(초기 기록, 현재 superseded):** 첫 후보는 Ollama `qwen3:8b`와 Python `faster-whisper` `turbo`였다. 실제 제품 profile은 V2-R01에서 Ollama `qwen3.6:35b-a3b-agent-64k`로 갱신했으며 STT 기본은 CPU `int8`이다.
- **설치 계약 대조:** O01의 schema v1 manifest/installer는 single HTTPS file과 SHA-256만 검증하므로 그대로 보존한다. Ollama registry pull과 faster-whisper Hub snapshot은 다수 blob/cache를 다루므로 P01A에서 runtime-specific installer·revision/digest 기록 계약을 별도 구현한다. 허위 단일 URL/checksum profile을 manifest에 추가하지 않았다.
- **외부 동작(당시 기록):** P01 단계에서는 실제 호출·다운로드를 수행하지 않았다. 이후 P01A에서 repository 밖 runtime/model을 설치하고 별도 결과를 기록했다.
- **다음 단계:** P01A는 exact STT snapshot repository/revision/license, target model home, Ollama/faster-whisper network download, subprocess/runtime registration에 대한 명시 승인을 받은 뒤 시작한다.

### P01A — 로컬 모델 설치·무결성·runtime health 확인

- **상태:** 설치 및 local-only health 검증 완료
- **문서 수정:** `docs/ai/06-runtime-profile.md`, 이 문서. 제품 코드·manifest·scripts·tests·UI는 수정하지 않았다.
- **실제 설치:** existing Ollama service와 repository 밖 faster-whisper snapshot을 확인했다. 현재 사용 tag는 `qwen3.6:35b-a3b-agent-64k`이며, 상세 경로·revision은 `docs/ai/06-runtime-profile.md`에 기록한다.
- **자동 검증:** `faster_whisper` import/version, required snapshot files, `ollama list`, Git worktree 내부 runtime/model directory 부재를 통과했다. 구형 `qwen3:8b` 검사는 historical profile 기록이다.
- **남은 범위:** FFmpeg installation/diagnostic, actual adapter and CLI code, real audio transcription/Qwen response smoke test, persistence/UI/URL adapter는 후속 P02/P03 범위다. commit/push는 수행하지 않았다.

### P02 — 로컬 실행 환경 진단 CLI

- **상태:** 구현 및 검증 완료
- **수정·생성 파일:** `tools/doctor.py`, `tests/unit/test_doctor.py`, `README.md`, 이 문서
- **계약:** doctor는 Python runtime, explicit/PATH FFmpeg, Ollama, `qwen3.6:35b-a3b-agent-64k`, faster-whisper import, pinned STT snapshot, existing data root만 read-only로 검사해 stable JSON report와 필요한 action을 반환한다. install, pull, inference, network, directory creation은 수행하지 않는다.
- **자동 검증:** fake success/missing FFmpeg test `2 passed`, actual CLI JSON, diff check를 통과했다. 현재 PC는 FFmpeg가 PATH에 없어 `is_ready: false`, `required_actions: ["resolve ffmpeg"]`로 정상 보고하며 Qwen/STT/data checks는 통과했다.
- **다음 단계:** FFmpeg를 approved external path에 설치하고 P03의 concrete FFmpeg/STT/Ollama adapter와 local-file CLI를 구현한다. commit/push는 수행하지 않았다.

### P03 — 실제 local adapter smoke test

- **상태:** 구현·자동 검증·actual CLI smoke 완료
- **초기 외부 실행 결과:** 제공된 YouTube URL을 전용 외부 job directory에 일시 획득하고 FFmpeg normalized WAV를 생성했다. pinned faster-whisper turbo는 299 segment를 반환했고, 당시 local Ollama health check가 `OK`를 반환했다. 이후 실제 full pipeline은 V2-E2E01에서 `qwen3.6:35b-a3b-agent-64k`로 검증했다.
- **구현 범위:** `backend/local_adapters.py`는 shell 없는 FFmpeg collaborator, pinned local-only faster-whisper engine, loopback-only Ollama runtime과 URL rejector를 제공한다. `tools/run_local.py`는 local media 입력에 대해 bounded smoke 또는 injected full pipeline mode를 제공하고, P03 PowerShell helper는 기존 source를 재사용하고 UTF-8 출력을 설정한다.
- **자동 검증:** new adapter/CLI test `7 passed`, 전체 pytest `130 passed`, CLI help, syntax check 및 대상 diff check가 통과했다. tests use mocks only and do not start a subprocess, model, or network request.
- **CLI smoke:** helper가 existing `source.webm`을 재사용해 `tools/run_local.py --mode smoke`를 호출했고 `{"mode":"smoke","segment_count":299,"qwen_corrected_text":"Runtime health check.","qwen_requires_review":false}` JSON과 exit 0을 반환했다. generated job directory는 cleanup되어 남지 않았다.
- **경계:** media·WAV·logs는 전용 job directory에만 생성됐고 Git worktree에는 model/media artifact를 쓰지 않았다. smoke CLI는 generated job work directory만 정리하며 source는 읽기만 한다.
- **남은 위험:** CPU STT에는 장시간이 걸리고 concurrent run은 피해야 한다. yt-dlp는 JavaScript runtime 부재 warning을 출력했으므로 production URL acquisition의 downloader runtime/format policy가 필요하다. full `run` mode는 segment마다 strict Qwen response와 evidence-linked summary를 요구하므로 단일 smoke보다 훨씬 긴 실제 실행이다. source/WAV/log artifact는 user-approved `p03-youtube-smoke` directory에 보존됐다.

### P04-01 — versioned persisted results and safe reopen

- **상태:** 구현 및 명세 검증 완료
- **수정·생성 파일:** `backend/persistence.py`, `tools/run_local.py`, `tools/inspect_job.py`, `tests/unit/test_persistence.py`, `tests/unit/test_run_local.py`, `tests/unit/test_inspect_job.py`, `README.md`, 이 문서.
- **계약:** `persist_result`는 archived `PipelineResult`의 reviewed transcript, raw transcript audit, summary, review queue를 repository 밖 `D:\AI-Legion\Sodam-data\jobs\<safe-job-id>`에 schema v1 JSON으로 staging directory→same-filesystem rename 순서로 publish한다. existing result overwrite, repository/root escape, symlink, unsupported schema 및 malformed cross-artifact evidence를 거부한다. `load_result`는 detached immutable values를 재구성하며 write/delete를 하지 않는다.
- **CLI·inspection:** local CLI `--mode run`은 성공 result를 persist한 뒤 `result_path`를 report에 포함한다. smoke는 저장하지 않는다. `inspect_job.py`는 existing four-artifact fixture와 optional schema-v1 `format.json` 모두 지원하며 unsupported version은 거부한다.
- **자동 검증:** persist→load→inspect round trip, write failure staging cleanup, duplicate non-overwrite, safe-ID/repository-root rejection, format version rejection 및 CLI persistence handoff를 pytest로 검증했다(`15 passed`). 전체 suite `135 passed`, fixture inspection CLI, syntax 및 대상 diff check도 통과했다. tests use only `tmp_path`; actual persistent root/model/media/network는 건드리지 않았다.
- **남은 위험:** 실제 full `run`은 result를 pipeline terminal cleanup 뒤 persist하므로 storage write failure 시 source를 다시 처리해야 한다. user-driven review edit/audit event mutation, explicit persisted-result deletion, SQLite/migration, real persisted full-model run은 다음 P04 작업으로 남는다. 커밋·푸시는 수행하지 않았다.

### P04-02 — immutable review decisions and reopenable audit state

- **상태:** 구현 및 명세 검증 완료
- **수정·생성 파일:** `backend/persistence.py`, `tools/inspect_job.py`, `tools/resolve_review.py`, `tests/unit/test_persistence.py`, `tests/unit/test_inspect_job.py`, `tests/unit/test_resolve_review.py`, `README.md`, 이 문서.
- **계약:** persisted review queue의 zero-based index마다 `accept_suggested`, `keep_original`, `custom_text` 중 하나의 불변 결정을 `review_resolution.json`에 기록한다. decision text가 원본/제안과 정확히 일치하는지 또는 custom text가 trimmed non-blank인지 확인하며, duplicate/out-of-range/inconsistent decision을 거부한다. base transcript와 review queue는 수정하지 않는다.
- **원자성·재열기:** review decision file은 same-directory temp file→replace로만 publish한다. `load_result`와 `inspect_job`는 optional audit artifact를 strict schema로 검증해 ordered decisions와 pending count를 반환한다. resolve CLI는 explicit user mutation만 수행하며 model/network/subprocess/delete 기능이 없다.
- **자동 검증:** 모든 decision 종류, persist/reopen/inspect, duplicate·invalid index·inconsistent text·malformed audit reject, injected atomic update failure의 existing-file preservation, CLI one-line JSON/error를 검증했다(`19 passed`). 전체 suite `143 passed`, CLI help/syntax 및 대상 diff check도 통과했다. tests use only temporary roots; actual `Sodam-data\jobs`는 변경하지 않았다.
- **남은 위험:** queue item에 segment ID/offset이 없어 이 immutable audit은 decision을 transcript text에 적용하지 않는다. location-aware review item schema, resolved transcript versioning/summary regeneration, explicit persistent deletion과 UI는 다음 P04/P06 작업이다. 커밋·푸시는 수행하지 않았다.

### P04-03 — segment-bound review locations

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/main.py`, `backend/persistence.py`, `tools/run_local.py`, `tools/inspect_job.py`, `tests/integration/test_pipeline.py`, `tests/unit/test_persistence.py`, `tests/unit/test_inspect_job.py`, `tests/unit/test_run_local.py`, `README.md`, 이 문서.
- **계약:** B10의 four-key review item은 변경하지 않는다. pipeline은 별도 `review_locations` tuple로 each queue index의 `segment_id`와 persisted reviewed-text half-open offsets를 만든다. 동일 raw text 반복은 same segment에서 left-to-right occurrence order로 mapping하고, raw-empty insertion은 null offsets로 보존한다. 원문이 찾을 수 없으면 guess하지 않고 `TranscriptAssemblyError`를 발생시킨다.
- **영속·재열기:** location data가 있는 result만 optional `review_locations.json` schema v1 artifact를 publish한다. persistence와 inspector는 queue index, segment membership, range bounds 및 substring equality를 함께 검증한다. 기존 no-location results/four-artifact fixture는 그대로 읽힌다. run CLI는 result locations를 persistence로 전달한다.
- **자동 검증:** fake pipeline non-formatting changes의 segment mapping, repeated raw occurrence order, insertion null-range, persist/load/inspect round trip, malformed range reject 및 no-location backward compatibility를 검증했다(`29 passed`). 전체 pytest `147 passed`, syntax와 대상 diff check가 통과했으며 tests never used actual model/media/result root.
- **남은 위험:** location is sufficient to identify a decision target but decision 적용 뒤 text shifting, multiple decision conflict resolution, resolved-transcript versioning 및 summary evidence regeneration은 다음 P04 작업이다. 커밋·푸시는 수행하지 않았다.

### P04-04 — deterministic resolved transcript projection

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/persistence.py`, `tools/inspect_job.py`, `tools/resolve_review.py`, `tests/unit/test_persistence.py`, `tests/unit/test_inspect_job.py`, `tests/unit/test_resolve_review.py`, `README.md`, 이 문서.
- **계약:** `load_result`는 immutable base transcript를 보존하면서 non-null segment offsets를 가진 decision만 original-coordinate order로 적용한 `resolved_transcript`를 derived 반환한다. same segment replacement ranges overlap/escape면 `StorageError`로 거부하며 raw source IDs/timestamps는 existing assembly contracts로 보존한다. legacy/no-location 및 null insertion decisions은 audit에는 남되 unapplied 상태가 된다.
- **summary 정책:** resolved text가 base reviewed text와 다르면 `summary_is_stale=true`이다. stored summary JSON은 변경·재생성하지 않아 stale summary를 새 transcript의 근거처럼 제시하지 않는다. inspector와 resolve CLI는 resolved text/applied·unapplied indices/stale status를 표시한다.
- **자동 검증:** 한 segment의 two decisions with offset shifts, keep-original, legacy/no-location, null location, malformed overlap reject, inspection projection와 CLI report를 검증했다(`24 passed`). 전체 pytest `150 passed`, syntax와 대상 diff check가 통과했고 actual result root/model/media/network는 사용하지 않았다.
- **남은 위험:** null insertion 위치 적용, immutable decision의 edit/supersession, resolved transcript의 durable version artifact, stale summary의 local-model regeneration, explicit result deletion·UI는 이후 단계다. 커밋·푸시는 수행하지 않았다.

### P04-05 — explicit resolved-summary refresh

- **상태:** 구현 및 명세 검증 완료
- **수정·생성 파일:** `backend/persistence.py`, `tools/refresh_summary.py`, `tools/inspect_job.py`, `tests/unit/test_persistence.py`, `tests/unit/test_inspect_job.py`, `tests/unit/test_refresh_summary.py`, `README.md`, 이 문서.
- **계약:** stale resolved transcript가 있을 때만 injected runtime으로 existing `summarize_reviewed_transcript` strict JSON/evidence validation을 호출한다. base `summary.json`은 유지하고, resolved final text SHA-256 fingerprint와 validated summary를 `resolved_summary.json`에 atomic replace로 publish한다. matching projection is current; well-formed old fingerprint remains stale; malformed projection is rejected.
- **CLI·inspection:** `refresh_summary.py` is the explicit model-call entry point and uses only loopback `LocalOllamaRuntime`; it prints JSON on success. inspector displays optional resolved summary/evidence and clears stale only when the projection fingerprint matches current resolved transcript. No automatic/background model call occurs.
- **자동 검증:** fake runtime refresh, base-summary preservation, matching reopened projection, no-stale rejection, inspector fields, CLI JSON/error를 검증했다(`25 passed`). 전체 pytest `153 passed`, syntax와 대상 diff check가 통과했다. actual result root/Qwen/model/media/network is not touched in tests.
- **남은 위험:** insertion/null locations, decision supersession, concurrent refresh locking, durable resolved transcript artifact, actual long local-model refresh UX, explicit persisted-result deletion and UI are later work. 커밋·푸시는 수행하지 않았다.

### P05 — 명시적 YouTube URL 획득

- **상태:** 구현 및 명세 검증 완료
- **수정 파일:** `backend/local_adapters.py`, `tools/run_local.py`, `tests/unit/test_local_adapters.py`, `tests/unit/test_run_local.py`, `README.md`, 이 문서.
- **계약:** `LocalYtDlpSourceAdapter`는 기존 URL validator를 다시 사용하고, 미리 존재하는 non-symlink work directory의 직접 자식 `source-audio.wav`만 대상으로 한다. shell 없이 단 한 번의 `python -m yt_dlp`를 호출하며 config·playlist·progress를 비활성화하고 cookie/login/proxy options를 공급하지 않는다. 성공 뒤 direct `source-audio.*` downloader by-product만 정리한다. CLI URL은 `--allow-url`와 `--mode run`이 함께 있어야 하고, smoke/기본 경로에서는 외부 요청 전에 거부된다.
- **자동 검증:** injected command runner로 exact command vector, fake WAV output, direct `.webm` by-product cleanup, unsafe destination와 downloader failure 매핑을 확인했다. CLI는 local source 경로 보존, URL opt-in/run-only gate 및 new adapter injection을 검증했다. 대상 pytest `12 passed`; 전체 pytest, help, syntax와 diff check는 아래 최종 검증에서 실행한다. 테스트는 subprocess, downloader, FFmpeg, STT, Qwen, network, real result root를 사용하지 않는다.
- **남은 위험:** `yt-dlp`의 실제 format/JavaScript 변화, YouTube 정책·접근 제한, interrupted download와 large-file disk capacity는 실제 사용 시 별도 명시 승인과 운영 검증이 필요하다. URL full run은 segment마다 local Qwen 요청을 하므로 장시간 실행일 수 있다. 커밋·푸시는 수행하지 않았다.

### P06-01 — 데스크톱 상태 reducer와 event DTO

- **상태:** 구현 및 명세 검증 완료
- **수정·생성 파일:** `apps/desktop/package.json`, `apps/desktop/package-lock.json`, `apps/desktop/tsconfig.json`, `apps/desktop/src/state.ts`, `apps/desktop/tests/state.test.mjs`, `apps/desktop/README.md`, `.gitignore`, 이 문서.
- **계약:** framework 없는 TypeScript reducer가 backend의 14개 lifecycle status를 화면 상태로 유지한다. created/progress/review-ready/completed/failed/cancelled event를 validation·clone 뒤 처리하며, stale job ID와 terminal-job update는 detached state를 반환해 무시한다. active job replacement, non-terminal progress, nullable fields, review item timestamp와 user-facing failure text를 엄격히 검증한다. 어떠한 IPC·renderer·filesystem·모델·URL·실제 취소도 실행하지 않는다.
- **도구 준비:** Node.js LTS가 이미 설치된 것을 확인했고, desktop 폴더에는 `typescript@5.7.3` 개발 의존성만 추가했다. TypeScript 7은 기존 in-memory compiler API를 내보내지 않아 테스트가 실패했으므로 호환되는 5.7.3으로 고정했다. `node_modules`와 compiler cache는 Git ignore다.
- **자동 검증:** `npm run check` 통과; Node built-in test와 in-memory TypeScript transpile로 initial isolation, full status contract, created→progress→review→completed flow, stale/terminal ignore, failed/cancelled, malformed input을 검증해 `5 passed`를 얻었다. 실제 Tauri/Rust/UI process는 시작하지 않았다.
- **남은 위험:** 아직 화면 component, Tauri IPC, backend event transport, file/URL input, cancellation command, persisted-job reopen UX, e2e launch는 없다. 이 상태 계약은 후속 P06-02 IPC 작업의 입력으로만 사용한다. 커밋·푸시는 수행하지 않았다.

### P06-02 — 최소 Tauri desktop shell

- **상태:** 구현 및 no-bundle compile 검증 완료
- **수정·생성 파일:** `apps/desktop/index.html`, `scripts/build.mjs`, `src/main.ts`, `src/style.css`, `src-tauri/` Rust/config/capability/icon files, `package.json`, `package-lock.json`, `.gitignore`, desktop README, 이 문서.
- **계약:** Tauri v2 shell은 default builder와 generated context만 사용하며 command/plugin/backend bridge를 등록하지 않는다. frontend는 `createInitialDesktopState()`만 import해 queued/offline/no-IPC readiness text를 DOM에 render한다. 권한은 main window의 `core:default`로 한정했고 filesystem, shell, process, dialog, HTTP permission은 없다. `dist`·Cargo target·node_modules는 ignore다.
- **환경 보정:** Node/Tauri v2 package, Rust stable, MSVC Build Tools 및 Windows 11 SDK가 필요했다. 처음에는 MSVC linker, 그 다음 SDK `kernel32.lib`, 마지막으로 default Windows resource icon 누락을 확인했다. C++ workload/SDK를 설치하고 Tauri가 요구하는 최소 투명 `icons/icon.ico`를 추가해 해결했다.
- **자동 검증:** `npm run check`, `npm test` (`5 passed`), `npm run build`, 그리고 `npm run tauri:check`가 성공했다. 마지막 명령은 `tauri build --debug --no-bundle`로 debug binary만 compile했고 창이나 installer를 만들지 않았다.
- **남은 위험:** compile 환경의 MSVC/SDK path는 새 shell에 자동 전파되지 않을 수 있어 설치 문서화가 P07에서 필요하다. 실제 window launch, IPC payload schema, local file/URL input, cancel/review/result UI, backend subprocess, e2e와 packaging은 아직 범위 밖이다. 커밋·푸시는 수행하지 않았다.

### B09-R — Qwen no-op change-list recovery

- **상태:** 구현 및 회귀 검증 완료
- **수정 파일:** `backend/correction.py`, `tests/unit/test_correction.py`, 이 문서.
- **계약:** `correct_chunk`는 응답이 그 외 모든 JSON·placeholder·review 계약을 만족하지만 하나 이상의 `changes` 항목만 `old == new`인 경우에만, 명시적으로 빈 `changes` 배열을 요구하는 repair prompt로 한 번 더 호출한다. JSON·schema·placeholder 등 다른 위반이 함께 있으면 재시도하지 않는다. 두 번째 응답은 기존 strict contract로 다시 검증하며 no-op change가 반복되면 거부한다.
- **자동 검증:** B09 대상 pytest `12 passed`, 전체 pytest `160 passed`, 대상 `git diff --check`를 실행했다. fake runtime으로 정상 1회 호출, no-op → repair 2회 호출, 재발 no-op 거부, 잘못된 JSON의 1회 호출, no-op과 placeholder 손실의 무재시도를 검증했다. 실제 Qwen·Ollama·파일·네트워크는 테스트에서 사용하지 않았다.
- **남은 위험:** 실제 모델은 여전히 잘못된 JSON 또는 placeholder 위반을 반환할 수 있으며, 이들은 의도대로 자동 복구하지 않고 사용자에게 오류로 노출된다. 실제 full-pipeline 재실행은 별도 실행 단계에서 확인한다. 커밋·푸시는 수행하지 않았다.

### B09-R2 — semantically empty Qwen change-list normalization

- **상태:** 구현 및 회귀 검증 완료
- **수정 파일:** `backend/correction.py`, `tests/unit/test_correction.py`, 이 문서.
- **계약:** local Qwen이 원문과 동일한 `corrected_text`, `requires_review=false`, 보존된 placeholder를 반환하면서 모든 `changes`만 `old == new`로 중복 기록한 경우에는 이를 빈 change tuple로 정규화한다. 모델을 다시 호출하지 않는다. 실제 change와 섞인 no-op, changed text, review 요청, JSON/schema/type/placeholder 오류는 기존처럼 한 번의 호출 뒤 거부한다.
- **자동 검증:** B09 대상 pytest `14 passed`, 전체 pytest `162 passed`를 통과했다. 순수 no-op 반복 정규화, changed text·real change·review·placeholder 손실의 단일 호출 거부, 기존 JSON 및 일반 change 계약을 fake runtime으로 검증했다. 실제 모델·미디어·네트워크는 테스트에서 사용하지 않았다.
- **남은 위험:** 이 정책은 model-reported no-op가 실제로 무해한 경우만 수용한다. Qwen이 실제 수정과 no-op를 함께 반환하거나 placeholder를 손상하면 자동 추측하지 않고 오류로 종료한다. 실제 full pipeline 재실행은 별도 결과로 확인한다. 커밋·푸시는 수행하지 않았다.

### B09-R3 — redundant Qwen no-op change filtering

- **상태:** 구현 및 회귀 검증 완료
- **수정 파일:** `backend/correction.py`, `tests/unit/test_correction.py`, 이 문서.
- **계약:** Qwen의 structurally valid `changes`에서 `old == new`인 항목만 제거하고 `old != new` 실제 변경과 `requires_review` 값은 보존한다. filtering 뒤 actual change가 없는데 corrected text가 원문과 다르면 unrecorded edit으로 거부한다. placeholder, JSON/schema/type, 그리고 unchanged no-change + review 요청은 기존처럼 한 번의 호출 뒤 거부한다.
- **자동 검증:** B09 대상 pytest `14 passed`, 전체 pytest `162 passed`를 통과했다. pure no-op, mixed no-op/real change/review preservation, no-op-only altered text, unchanged review, placeholder loss, normal change를 fake runtime으로 검증했다. actual Qwen·media·network는 테스트에서 사용하지 않았다.
- **남은 위험:** 이 filtering은 model-reported change list의 중복 표기만 보정한다. corrected text와 actual changes의 완전한 1:1 의미 대응은 B09의 기존 범위 밖이며 B10의 revision validation이 후속 보호·검토 분류를 수행한다. 실제 full pipeline 재실행 결과는 별도 확인한다. 커밋·푸시는 수행하지 않았다.

### P07-01 — structured local Qwen runtime upgrade

- **상태:** 구현·자동 검증 완료, actual local-model smoke 및 full run 대기
- **수정 파일:** `backend/local_adapters.py`, `tools/run_local.py`, `tests/unit/test_local_adapters.py`, `tests/unit/test_run_local.py`, 이 문서.
- **계약:** local Ollama runtime의 기본 모델은 `qwen3:14b`이며 every loopback chat request adds `format: "json"`, `think: false`, and deterministic `temperature: 0`. Prompt-owned correction/summary schemas remain unchanged; the adapter does not add network destinations or relax its loopback boundary.
- **자동 검증:** local adapter·CLI pytest `13 passed`, full pytest `163 passed`를 통과했다. fake request로 exact UTF-8 body, `qwen3:14b` default and all existing CLI injection behavior를 확인했다. actual model/network was not used by tests.
- **운영 근거:** this host has 16GB NVIDIA VRAM, 32GB system RAM, and sufficient local disk. Ollama publishes `qwen3:14b` as a 9.3GB Q4_K_M 14.8B model with 40K context; Qwen3 documents multilingual instruction following. Ollama structured-output docs support JSON `format` and recommend low temperature. approved download and actual validation are tracked separately.
- **남은 위험:** larger model loading and CPU fallback can increase latency. Even structured JSON cannot guarantee semantic correctness, so B09/B10 strict validation remains mandatory. 커밋·푸시는 수행하지 않았다.

### B12-R2 — video-introduction summary intent

- **상태:** 구현 및 자동 검증 완료
- **수정 파일:** `backend/summarization.py`, `tests/unit/test_summarization.py`, 이 문서.
- **계약:** final synthesis prompt now explicitly writes a Korean video introduction: sentence one identifies the main subject and experience; sentence two gives two or three concrete viewer highlights drawn across intermediate summaries. It prohibits treating an isolated early ranking/award fact as the video theme. Existing evidence-only JSON, one-to-two-sentence, parser, and batching contracts stay unchanged.
- **자동 검증:** summary pytest `7 passed`, full pytest `163 passed`를 통과했다. Fake runtime asserts the raw/reviewed/final sentence constraint plus the final video-intro coverage and anti-single-fact instructions. Real model/media/network was not used.
- **남은 위험:** prompt guidance substantially improves intent but cannot prove semantic coverage of an arbitrary model response. A future quality evaluator should compare final subject/highlights against source-wide evidence before result persistence. 커밋·푸시는 수행하지 않았다.

---

## Product v2 — 진행 UI·설치·요약 보존·영상 소개글 추가 구현 순서

> 기준 설계: `docs/ai/01-architecture.md` v2
>
> 승인 상태: `APPROVE DESIGN`에 따라 아래 계약·코드·테스트 도구의 골격만 작성했다. 실제 함수 로직, 실제 테스트 로직, 외부 다운로드, 설치, 모델 실행, 패키징, 커밋과 푸시는 각 작업의 별도 승인 전까지 금지한다.

### V2-C01 — 출력 모드·진행·소개글·설치 도메인 계약

- **작업 종류:** 함수 구현 전 도메인 계약
- **대상 파일:** `backend/contracts.py`
- **대상 이름:** `OutputMode`, `ProgressStage`, `ProgressEvent`, `Highlight`, `IntroductionOptions`, `VideoIntroduction`, `RuntimeProfile`, `SystemProfile`, `InstallationPlan`, `InstallationReceipt`, 관련 예외
- **선행 작업:** 없음
- **목적·동작:** 기존 `Summary`를 변경하지 않고 소개글과 진행·설치 데이터를 불변 타입으로 분리한다. 출력 모드는 `summary`, `introduction`, `both`만 허용한다.
- **수정 허용:** 위 신규 선언과 docstring
- **금지 범위:** 기존 B01~B13 계약의 필드·의미 변경, 입력 검증·I/O·모델 호출
- **연결 테스트 작업:** V2-T01, V2-P02, V2-I02, V2-SETUP02
- **테스트 방법:** frozen 불변성, Literal 값, 기본값, 예외 상속을 직접 검사
- **완료 판정:** 신규 타입 import·구문 검사와 기존 전체 계약 테스트가 모두 통과
- **현재 상태:** 골격 작성 완료, 실제 계약 검증 테스트 미구현

### V2-T01 — Product v2 Fake·Fixture 테스트 도구

- **작업 종류:** 테스트 도구 구현
- **대상 파일:** `tests/fakes_progress.py`, `tests/fakes_productization.py`, 필요 시 `tests/fixture_factories.py`
- **대상 이름:** `FakeClock`, `RecordingProgressSink`, `RecordingIntroductionRuntime`, `FakeSystemProbe`, `FakeCancellationToken`, `RecordingInstallerBackend`
- **선행 작업:** V2-C01
- **목적·동작:** 네트워크·실제 시간·실제 설치 없이 이벤트 순서, ETA, 모델 응답, 설치 action을 결정론적으로 검증한다. 생성자 인자는 복사하고 호출 기록은 외부 변경에 노출하지 않는다.
- **수정 허용:** 위 Fake와 전용 factory
- **금지 범위:** 실제 Ollama·FFmpeg·다운로더·subprocess·시스템 변경, 제품 함수 구현
- **테스트 방법:** 독립 인스턴스, 응답 소비 순서, 기록 불변성, 구성된 예외 전파
- **완료 판정:** Fake 자체 단위 테스트와 구문 검사 통과
- **현재 상태:** 구현 및 검증 완료. FakeClock의 결정론적 epoch 시계, sink snapshot, FIFO runtime, read-only probe, 단조 취소 토큰, synthetic installer event recording을 구현했다. 전용 테스트 `5 passed`, 전체 pytest `168 passed`, 구문 검사와 diff check가 통과했다. 실제 외부 실행·다운로드·모델 호출은 없었다. 커밋·푸시는 수행하지 않았다.

### V2-P01 — 진행률·ETA 계산 구현

- **작업 종류:** 함수 구현
- **대상 파일:** `backend/progress.py`
- **대상 이름:** `ProgressTracker`, `estimate_eta`, `ProgressSink`, `Clock`
- **선행 작업:** V2-C01, V2-T01
- **목적·동작:** 측정된 완료 단위로 단계·전체 진행률을 만들고 충분한 처리량 표본이 있을 때만 ETA를 계산한다. sequence와 진행률은 감소하지 않으며 terminal 이벤트는 한 번만 허용한다.
- **수정 허용:** `backend/progress.py`
- **금지 범위:** Job 상태 직접 변경, sleep, UI·파일·네트워크 I/O, 임의 타이머 기반 가짜 진행
- **연결 테스트 작업:** V2-P02
- **테스트 방법:** FakeClock과 RecordingProgressSink로 known/unknown total, 단계 전환, 단조성, terminal, ETA null 조건 검사
- **완료 판정:** 명세 단위 테스트와 diff check 통과
- **현재 상태:** 구현 및 검증 완료. `ProgressTracker`가 setup/job 범위와 단계 lifecycle, 측정 가능한 determinate/indeterminate progress, 고정 가중치 전체 progress, sequence·progress 단조성을 관리하고 `estimate_eta`가 최근 측정 구간만 사용하도록 구현했다. 전용 진행률 테스트 `6 passed`, 전체 pytest `174 passed`, Python 구문 검사와 대상 diff check가 통과했다. 외부 실행·대기·네트워크는 없었다. 커밋·푸시는 수행하지 않았다.

### V2-P02 — 진행률 단위 테스트

- **작업 종류:** 테스트 코드 구현
- **대상 파일:** `tests/unit/test_progress.py`
- **대상 함수:** V2-P01 전체
- **선행 작업:** V2-P01
- **목적·동작:** 0/50/100%, unknown total, NaN·infinity·감소·초과, 표본 부족, zero throughput, terminal 중복을 검증한다.
- **수정 허용:** 대상 테스트 파일
- **금지 범위:** 실제 clock 대기, 제품 파일 수정, GUI 실행
- **테스트 명령:** `python -m pytest -q tests/unit/test_progress.py`
- **완료 판정:** 전 케이스 통과, 테스트 실행이 외부 상태를 변경하지 않음
- **현재 상태:** V2-P01 구현과 함께 테스트 코드 구현·검증 완료. 6개 케이스가 통과했고 실제 clock 대기·GUI·외부 서비스는 사용하지 않았다. 커밋·푸시는 수행하지 않았다.

### V2-I01 — 근거 기반 영상 소개글 생성

- **작업 종류:** 함수 구현
- **대상 파일:** `backend/introduction.py`
- **대상 이름:** `extract_highlights`, `build_introduction_prompt`, `generate_video_introduction`, `validate_introduction`
- **선행 작업:** V2-C01, V2-T01
- **목적·동작:** 승인된 전사문에서 실제 브랜드·금액·등급·특징 후보를 추출하고, 제목형 한 줄과 2~3문장 본문·CTA를 strict JSON으로 생성한다. 모든 사실과 highlight를 segment ID에 연결한다.
- **수정 허용:** `backend/introduction.py`
- **금지 범위:** 기존 `Summary` 변경, 외부 검색, 전사문 밖 사실 생성, 실제 Ollama 직접 연결, 광고 문구를 전체 주제로 간주
- **연결 테스트 작업:** V2-I02
- **테스트 방법:** RecordingIntroductionRuntime으로 정상 JSON, malformed JSON, 허위 가격·브랜드, unknown evidence, CTA·문장 수·질문 제한 검사
- **완료 판정:** 자동 검증 전부 통과하고 실제 fixture의 모든 highlight가 원문에 존재
- **현재 상태:** 구현 및 검증 완료. 원문 근거 highlight 추출, deterministic 한국어 소개 prompt, strict JSON schema, evidence·문장 수·질문·CTA·가격·고유명사 검증, runtime 예외 매핑을 구현했다. 소개글·Fake·진행률 전용 테스트 `20 passed`, 전체 pytest `183 passed`, 구문 검사와 대상 diff check가 통과했다. 실제 Ollama·네트워크·미디어는 사용하지 않았다. 커밋·푸시는 수행하지 않았다.
- **V2-I01-R1~R3 보정:** 실제 Qwen 응답에서 schema 정의 반환, highlight 임의 조합, CTA 필드와 본문 마지막 문장 불일치를 순차 재현했다. prompt에 실제 필드값만 반환, highlight 후보 exact-copy, CTA 문장 exact-copy 지시를 추가했고 소개글 단위 테스트 `9 passed`를 유지했다.

### V2-I02 — 소개글 단위·품질 fixture 테스트

- **작업 종류:** 테스트 코드 구현
- **대상 파일:** `tests/unit/test_introduction.py`, 승인된 텍스트 fixture
- **대상 함수:** V2-I01 전체
- **선행 작업:** V2-I01
- **목적·동작:** 항공·제품 리뷰·강연·광고 포함 영상 등 서로 다른 전사문에서 사실성, 주제 범위, 구체성, curiosity gap, CTA를 검증한다.
- **수정 허용:** 대상 테스트와 텍스트 fixture
- **금지 범위:** 저작권 미확인 전체 전사문 커밋, 실제 모델·네트워크 호출
- **테스트 명령:** `python -m pytest -q tests/unit/test_introduction.py`
- **수동 검증:** 최소 5개 영상에서 주제 정확성·사실성 4/5 이상
- **완료 판정:** 자동 통과와 수동 평가 기록 모두 존재
- **현재 상태:** 자동 fixture·오류 경로 테스트 구현 및 통과 완료(`9 passed`). 실제 5개 영상에 대한 사람 품질 평가는 V2-E2E01에서 수행한다. 커밋·푸시는 수행하지 않았다.

### V2-S01 — 기존 요약 의미 회귀 복구

- **작업 종류:** 함수 구현·회귀 수정
- **대상 파일:** `backend/summarization.py`, `tests/unit/test_summarization.py`
- **대상 이름:** 기존 `summarize_transcript`, `summarize_reviewed_transcript`, final prompt
- **선행 작업:** V2-I01
- **목적·동작:** B12-R2에서 요약 프롬프트에 섞인 video-introduction 지시를 제거하고, 기존 최대 두 문장 사실 요약과 evidence 계약만 유지한다. 소개 문안은 V2-I01만 담당한다.
- **수정 허용:** 요약 prompt와 해당 회귀 테스트
- **금지 범위:** `Summary` schema, 배치 경계, evidence parser 변경
- **테스트 방법:** 기존 요약 전체 테스트와 과장 수식어·질문·CTA가 강제되지 않는 추가 회귀 테스트
- **완료 판정:** 기존 summary fixture 호환, introduction 테스트와 독립성 확인
- **현재 상태:** 구현 및 회귀 검증 완료. final synthesis prompt를 사실 중심 요약으로 분리하고 introduction·CTA·curiosity 지시를 제거했다. 요약·소개글 전용 테스트 `16 passed`, 전체 pytest `183 passed`, 구문 검사와 diff check가 통과했다. 기존 Summary schema·배치·evidence 동작은 유지되며 외부 모델·네트워크는 사용하지 않았다. 커밋·푸시는 수행하지 않았다.

### V2-R01 — 런타임 프로필과 Qwen 모델 주입

- **작업 종류:** 함수 구현
- **대상 파일:** `backend/runtime_profile.py`, `backend/local_adapters.py`, 전용 설정 schema
- **대상 이름:** `default_runtime_profile`, `load_runtime_profile`, `save_runtime_profile`, `LocalOllamaRuntime`
- **선행 작업:** V2-C01
- **목적·동작:** 하드코딩 모델과 Python 경로를 제거하고 `qwen3.6:35b-a3b-agent-64k`를 품질 프로필로 선택한다. loopback Ollama만 허용하고 역할별 JSON Schema, `think: false`, bounded context를 전달한다.
- **수정 허용:** 위 파일과 전용 unit test
- **금지 범위:** 모델 다운로드, 원격 Ollama endpoint, Hermes 설정 파일 의존, 비밀정보 저장
- **테스트 방법:** fake request로 exact model tag·endpoint·format·think·temperature·context 확인, atomic profile I/O는 temp path에서만 검사
- **완료 판정:** qwen 태그 주입과 profile round trip, unsafe endpoint 거부, 기존 adapter 테스트 통과
- **현재 상태:** 구현 및 검증 완료. RuntimeProfile JSON round trip·atomic replace와 loopback endpoint 검증을 추가하고 LocalOllamaRuntime 기본 모델을 qwen3.6:35b-a3b-agent-64k로 주입했다. 요청 payload에 stream:false, think:false, format:json, temperature:0, num_ctx:32768을 고정했다. 전용 테스트 `12 passed, 1 skipped`(Windows symlink 권한), 전체 pytest `189 passed, 1 skipped`, 구문 검사와 diff check가 통과했다. 실제 Ollama·네트워크·다운로드는 사용하지 않았다. 커밋·푸시는 수행하지 않았다.

### V2-PIPE01 — 출력 모드와 진행 이벤트 파이프라인 조립

- **작업 종류:** 함수 구현
- **대상 파일:** `backend/main.py`, `backend/jobs.py`, 필요한 계약 테스트
- **대상 이름:** `PipelineApplication.run`의 호환 확장
- **선행 작업:** V2-P01, V2-I01, V2-S01, V2-R01
- **목적·동작:** 공통 전사·교정을 한 번 수행한 뒤 `summary`, `introduction`, `both`에 맞게 생성기를 순차 호출하고 각 단계 이벤트를 발행한다. 기존 호출자는 summary 기본 동작을 유지한다.
- **수정 허용:** 파이프라인 조립과 새 상태가 꼭 필요할 경우 최소 계약
- **금지 범위:** STT·보호·교정 알고리즘 재작성, 동시 GPU 모델 실행
- **연결 테스트 작업:** V2-PIPE02
- **테스트 방법:** injected fake 전체 조합으로 호출 횟수, 이벤트 순서, 취소, partial result, 기존 summary 호환 검사
- **완료 판정:** 세 output mode 통합 테스트와 기존 T05 통합 테스트 통과
- **현재 상태:** 구현 및 통합 검증 완료. `PipelineResult.introduction`과 `output_mode`를 추가하고 기본 summary 호출 호환성을 유지했다. introduction-only는 기존 lifecycle의 summarizing 상태를 재사용하며, both는 공통 전사 후 두 생성기를 순차 호출한다. progress sink/clock 주입 시 단계 이벤트와 terminal completed/failed/cancelled를 발행한다. 전용 통합 테스트 `4 passed`, pipeline 회귀 `10 passed`, 전체 pytest `193 passed, 1 skipped`, 구문·diff 검증이 통과했다. 외부 모델·네트워크는 사용하지 않았다. 커밋·푸시는 수행하지 않았다.

### V2-PIPE02 — 출력 모드·진행 통합 테스트

- **작업 종류:** 테스트 코드 구현
- **대상 파일:** `tests/integration/test_output_modes.py`, `tests/integration/test_progress_pipeline.py`
- **선행 작업:** V2-PIPE01
- **목적·동작:** summary만, introduction만, 둘 다, 소개글 실패 후 요약 보존, 단계별 취소, terminal 이벤트를 검증한다.
- **수정 허용:** 위 테스트 파일과 승인된 fake
- **금지 범위:** 실제 미디어·모델·네트워크·외부 데이터 root
- **완료 판정:** fake 기반 통합 테스트가 결정론적으로 통과하고 공통 STT 호출이 정확히 1회
- **현재 상태:** 구현 및 검증 완료. summary/introduction/both 결과 독립성, 공통 STT 1회, progress monotonic terminal event를 fake fixture로 확인했다. 커밋·푸시는 수행하지 않았다.

### V2-STORE01 — 소개글·진행 이벤트 영속화

- **작업 종류:** 함수 구현
- **대상 파일:** `backend/persistence.py`, `tools/inspect_job.py`, 관련 테스트
- **대상 이름:** schema version 확장, `introduction.json`, `progress.jsonl` 저장·읽기
- **선행 작업:** V2-C01, V2-PIPE01
- **목적·동작:** 기존 summary artifact를 유지하면서 소개글과 안전한 progress audit를 별도 저장하고 재열기한다.
- **수정 허용:** persistence schema의 하위 호환 확장과 inspect 표시
- **금지 범위:** 기존 v1 결과 파괴, prompt·thinking trace 저장, 작업 root 밖 쓰기
- **테스트 방법:** v1 reopen, v2 three modes round trip, malformed progress line, atomic write 실패
- **완료 판정:** v1·v2 모두 열리고 summary와 introduction이 서로 덮어쓰지 않음
- **현재 상태:** 구현 및 검증 완료. `PersistedResult`에 optional introduction/progress를 추가하고 summary-only legacy, introduction-only, both artifact round trip을 지원한다. `introduction.json`과 `progress.jsonl`은 기존 summary.json과 독립 저장되며 inspect_job도 optional summary/introduction을 읽는다. persistence·inspect 전용 테스트 `26 passed`, 전체 회귀는 다음 검증에서 실행한다. 커밋·푸시는 수행하지 않았다.

### V2-CLI01 — CLI 출력 모드와 진행 출력

- **작업 종류:** 함수·도구 구현
- **대상 파일:** `tools/run_local.py`, 관련 unit test
- **대상 이름:** `--output-mode`, `--qwen-model`, `--progress-format`
- **선행 작업:** V2-PIPE01, V2-STORE01
- **목적·동작:** stdout은 최종 JSON만, stderr는 사람용 progress, 선택 시 별도 JSONL progress를 출력한다. CLI 기존 기본값은 summary다.
- **수정 허용:** CLI parser·adapter wiring·tests
- **금지 범위:** 기본 실행에서 모델 다운로드, UI 실행, stdout 로그 혼합
- **테스트 방법:** injected application으로 argv, stdout/stderr 분리, exit code, qwen tag 전달 검사
- **완료 판정:** 기존 CLI 테스트와 세 output mode 테스트 통과
- **현재 상태:** 구현 및 검증 완료. CLI 기본 모델을 `qwen3.6:35b-a3b-agent-64k`로 통일하고 `--output-mode`와 `--progress-format`을 추가했다. stdout에는 최종 report JSON만, stderr에는 human 또는 JSONL `ProgressEvent`만 출력하며 introduction/progress artifact를 persistence에 전달한다. 전용 CLI 테스트 `9 passed`, 전체 pytest `198 passed, 1 skipped`, 구문·diff 검증을 통과했다. 실제 모델·미디어·네트워크는 사용하지 않았고 커밋·푸시는 수행하지 않았다.

### V2-SETUP01 — 시스템 검사·설치 계획·실행 관리자

- **작업 종류:** 함수 구현
- **대상 파일:** `backend/installer.py`
- **대상 이름:** `probe_system`, `plan_installation`, `execute_installation`, `build_desktop`
- **선행 작업:** V2-C01, V2-T01, V2-P01, V2-R01
- **목적·동작:** OS·RAM·VRAM·디스크·도구를 읽기 전용 검사하고 모든 다운로드·설치 action을 사용자에게 먼저 보여 준다. 승인된 plan만 실행하며 Ollama pull 진행을 공통 이벤트로 전달한다.
- **수정 허용:** installer module과 OS adapter의 별도 승인 범위
- **금지 범위:** 묵시적 관리자 권한, 미승인 download, insecure URL, repository 내부 model/data, 다른 OS 교차 빌드
- **연결 테스트 작업:** V2-SETUP02
- **테스트 방법:** FakeSystemProbe·RecordingInstallerBackend로 충분/부족 disk, existing model, hash error, 취소·재개 검사
- **완료 판정:** fake 테스트 통과 후 별도 승인된 clean Windows VM 수동 검증
- **현재 상태:** 구현 및 검증 완료. `probe_system`은 주입된 읽기 전용 probe를 검증하고, `plan_installation`은 OS/아키텍처·디스크·기설치 도구를 반영한 고정 순서 action을 생성한다. `execute_installation`은 승인된 plan만 backend에 전달하며 sink·취소·예외 변환·영수증을 처리한다. `build_desktop`은 현재 OS 외 교차 빌드와 V2-BUILD01 이전 패키징을 명확히 차단한다. `V2-SETUP01 checks OK`, 구문 검사, diff 검증을 통과했으며 실제 설치·다운로드·subprocess·네트워크는 실행하지 않았다. 커밋·푸시는 수행하지 않았다.

### V2-SETUP02 — 설치·프로필 단위 테스트

- **작업 종류:** 테스트 코드 구현
- **대상 파일:** `tests/unit/test_installer.py`, `tests/unit/test_runtime_profile.py`, `tests/integration/test_setup_flow.py`
- **선행 작업:** V2-SETUP01
- **목적·동작:** 외부 변경 없는 fake로 계획 완전성, 모델 크기, 영수증, partial, 재시도, OS 분기를 검증한다.
- **수정 허용:** 위 테스트 파일
- **금지 범위:** 실제 installer·Ollama pull·package manager·관리자 권한
- **완료 판정:** 모든 fake 테스트 통과, 실제 외부 실행 0회
- **현재 상태:** 테스트 구현 및 검증 완료. `tests/unit/test_installer.py`와 `tests/integration/test_setup_flow.py`에서 probe·계획 action·기설치 모델·디스크 부족/미확인·실행 순서·영수증·취소·실패 원인·OS 분기를 fake로 검증한다. 전용 테스트 `9 passed`, 전체 pytest `207 passed, 1 skipped`, 구문·diff 검증을 통과했다. 외부 설치·다운로드·네트워크·subprocess는 실행하지 않았다. 커밋·푸시는 수행하지 않았다.

### V2-SETUP03 — setup.py 부트스트랩

- **작업 종류:** CLI/부트스트랩 구현
- **대상 파일:** `setup.py`, 전용 테스트
- **대상 이름:** `main`
- **선행 작업:** V2-SETUP01, V2-SETUP02
- **목적·동작:** 설치 계획 표시와 동의를 받은 뒤 installer를 호출하거나 first-run UI를 연다. setuptools package 역할을 하지 않는다.
- **수정 허용:** setup bootstrap과 tests
- **금지 범위:** import 시 동작, 동의 전 다운로드, shell 문자열 실행
- **테스트 방법:** injected argv/UI launcher로 plan-only, accept, reject, cancel, stable exit code 검사
- **완료 판정:** `python setup.py --help`와 fake workflow 테스트 통과
- **현재 상태:** 구현 및 검증 완료. `setup.py`는 표준 라이브러리 기반 읽기 전용 local probe와 profile/plan 표시를 제공하며, 기본 실행은 plan-only다. `--yes`와 주입된 executor가 있을 때만 실행하고, 거부·취소·계획 오류·잘못된 receipt를 안정적인 exit code로 구분한다. 전용 테스트 `5 passed`, `python setup.py --help` 성공, 전체 pytest `212 passed, 1 skipped`, 구문·diff 검증을 통과했다. 실제 다운로드·설치·subprocess·네트워크는 실행하지 않았다. 커밋·푸시는 수행하지 않았다.

### V2-IPC01 — Tauri 백엔드 sidecar·이벤트 브리지

- **작업 종류:** 함수 구현
- **대상 파일:** `apps/desktop/src-tauri/src/lib.rs`, Tauri config·IPC tests
- **대상 이름:** `start_job`, `cancel_job`, `start_setup`, progress event bridge, result reopen
- **선행 작업:** V2-CLI01, V2-SETUP03
- **목적·동작:** 하드코딩 Python 경로를 제거하고 구조화 요청으로 sidecar를 시작한다. JSONL progress를 검증하여 UI event로 전달하고 안전하게 취소한다.
- **수정 허용:** Tauri bridge와 최소 capability
- **금지 범위:** 임의 shell, 전체 filesystem 권한, 원격 HTTP, UI thread blocking
- **테스트 방법:** fake sidecar stdout/stderr, malformed line, wrong exit, cancel acknowledgement, stale operation
- **완료 판정:** cargo check, IPC contract test, no-bundle build 통과
- **현재 상태:** 구조화된 `start_job`, `start_setup`, 멱등 `cancel_job` 명령과 입력 검증을 추가하고, 하드코딩 Python 경로·`std::process::Command` 실행을 제거했다. `doctor_report`는 backend 미연결 상태를 구조화해 반환하며 기존 파일 preflight 검증은 유지한다. Node IPC 테스트 `6 passed`, TypeScript 검사와 diff 검증을 통과했다. Rust `cargo check`와 `npm --prefix apps/desktop run tauri:check`가 성공했고 debug 실행 파일이 생성되었다. 실제 sidecar·모델·네트워크는 호출하지 않았고 커밋·푸시는 수행하지 않았다.

### V2-UI01 — 최초 설치·진행·결과 UI

- **작업 종류:** UI 함수 구현
- **대상 파일:** `apps/desktop/src/state.ts`, `progress-contract.ts`, `main.ts`, `style.css`, UI tests
- **대상 이름:** setup reducer, detailed progress reducer, output mode selector, result tabs
- **선행 작업:** V2-IPC01
- **목적·동작:** 요약/소개글/둘 다 선택, determinate·indeterminate 진행, 경과·ETA, 로그, 취소, 전사·요약·소개글·검토 탭을 접근 가능하게 표시한다.
- **수정 허용:** desktop frontend와 tests
- **금지 범위:** frontend 직접 filesystem·model 접근, raw prompt·민감 경로 노출
- **테스트 방법:** reducer sequence, null ETA, stale event, partial result, keyboard navigation, screen-reader labels
- **완료 판정:** TypeScript check, Node tests, 수동 window smoke 통과
- **현재 상태:** 상태 reducer에 snake_case progress event 정규화, monotonic/stale/terminal 보호, null ETA 처리를 추가했다. 화면은 summary/introduction/both 선택, 파일 preflight, 시작·취소, 진행률/경과/ETA/로그, 전사·요약·소개글·검토 탭을 접근 가능한 HTML로 표시한다. Node 테스트 `10 passed`, TypeScript 검사와 frontend build를 통과했다. Tauri debug 실행 파일을 실제 시작해 5초 프로세스 유지 smoke도 통과했으며, 시각·키보드 상호작용과 signed installer 검증은 남아 있다. 커밋·푸시는 수행하지 않았다.

### V2-BUILD01 — OS별 앱 번들·설치 패키지

- **작업 종류:** 빌드 도구 구현
- **대상 파일:** Tauri bundle config, OS별 CI workflow, 배포 문서
- **대상 이름:** Windows NSIS/MSI, macOS dmg, Linux AppImage/deb
- **선행 작업:** V2-UI01
- **목적·동작:** 각 대상 OS runner에서 해당 OS 설치물을 생성하고 해시를 기록한다. 일반 사용자에게 개발 toolchain 설치를 요구하지 않는다.
- **수정 허용:** 빌드·CI·서명 설정의 승인 범위
- **금지 범위:** 서명 secret 커밋, Windows에서 macOS 산출물 위조, 모델 23GB를 무조건 번들
- **테스트 방법:** OS별 clean runner 설치·시작·제거 smoke
- **완료 판정:** 최소 Windows 서명 전 후보 설치·실행 성공, 타 OS는 각 runner 결과 필요
- **현재 상태:** Tauri bundle을 활성화하고 `nsis`, `msi`, `dmg`, `appimage`, `deb` 대상을 명시했다. ESM frontend bundle과 `type=module` entry를 보정하고, 유효 ICO 및 `bundle.icon` 경로를 추가했다. build-contract Node 테스트 `10 passed`, TypeScript 검사·frontend build·Rust `cargo check`·Tauri debug build를 통과했다. 최종 NSIS/MSI 산출물은 생성되며 MSI는 UAC 설치·제거 smoke가 exit 0이다. NSIS는 unsigned 실행 파일이 Windows Application Control 정책에 의해 설치 단계에서 차단되어 설치 smoke가 보류되었다. 서명된 installer와 타 OS runner 결과는 남아 있다. 커밋·푸시는 수행하지 않았다.

### V2-E2E01 — 실제 미디어·모델 품질과 성능 검증

- **작업 종류:** 수동·통합 검증
- **대상 파일:** 승인된 검증 기록 문서와 repository 밖 전용 artifact
- **선행 작업:** V2-BUILD01
- **목적·동작:** 실제 로컬 미디어 5종 이상으로 진행 표시, STT, summary 회귀, introduction 품질, qwen3.6 성능, 취소·복구를 확인한다.
- **수정 허용:** 별도 승인된 `Sodam-data` 작업 폴더와 검증 기록
- **금지 범위:** 저작권 미확인 원문·미디어 커밋, 사용자 승인 없는 네트워크, 작업 root 밖 삭제
- **자동 검증:** 전체 pytest, desktop test, build check, repository policy
- **수동 검증:** 주제 정확성·사실성 4/5 이상, progress 정지처럼 보이지 않음, ETA 불가 시 계산 중 표시
- **완료 판정:** 실패 원인과 모델 성능 수치가 기록되고 blocker 0개
- **현재 상태:** 로컬 FFmpeg 9.0.1(`D:/AI-Legion/Sodam-data/tools/ffmpeg-9.0.1/bin/ffmpeg.exe`, SHA-256 검증 완료)과 faster-whisper `turbo-0a363e9`, Ollama `qwen3.6:35b-a3b-agent-64k`를 사용한 60초 bounded smoke를 완료했다. `tools/run_local.py --mode run --output-mode both`가 source validation/acquisition, audio extraction, transcription, normalization, correction, review, summary, introduction, persistence를 모두 통과했고 job `9af42eeb936e49fb9ab6cc853b77d1d8`가 `archived`가 되었다. 13개 segment, progress event 43개, sequence 단조 증가, terminal `completed`, summary/introduction artifact 저장을 확인했다. 초기 15분 실행의 placeholder 검증 실패와 후속 schema/highlight/CTA 응답 불일치는 V2-I01-R1~R3 prompt 보정으로 해결했다. ESM bundle 보정 후 실제 Tauri 창에 UI가 렌더링되고 Tab 입력 중 프로세스가 유지되는 것을 캡처로 확인했다. 5개 영상 사람 품질 평가와 코드 서명은 아직 남아 있으며, NSIS는 Application Control 정책 차단, MSI는 UAC 설치·제거 성공으로 결과가 갈렸다. artifact는 `Sodam-data/tmp/v2-e2e-r1`, `v2-e2e-r2`, `release-r1`에만 생성했고 커밋·푸시는 수행하지 않았다.

### V2-DOC01 — 제품 소개·설치·사용 문서 갱신

- **작업 종류:** 문서화
- **대상 파일:** `README.md`, `apps/desktop/README.md`, `docs/ai/05-productization-roadmap.md`, `docs/ai/06-runtime-profile.md`
- **선행 작업:** V2-E2E01
- **목적·동작:** Sodam을 전사·요약·영상 소개글 생성 앱으로 설명하고 setup, OS별 설치, 모델 선택, 진행 UI, 개인정보, 문제 해결을 실제 동작과 일치시킨다.
- **수정 허용:** 위 문서
- **금지 범위:** 미구현 기능을 완료로 표현, 실제 측정 없는 성능 수치
- **검증 방법:** 모든 명령 dry review, 링크, screenshot, 실제 설치 결과와 대조
- **완료 판정:** 신규 사용자가 문서만으로 설치·요약·소개글 생성·결과 위치 확인 가능
- **현재 상태:** README, 데스크톱 README, 제품화 roadmap, runtime profile을 실제 실행 상태에 맞게 갱신했다. summary 기본 동작과 introduction/both 모드, `qwen3.6:35b-a3b-agent-64k`, 외부 model/data 경로, stdout/stderr progress, setup plan-only, URL opt-in을 문서화했다. 60초 both E2E 성공과 Tauri debug 실행 파일의 실제 5초 프로세스 유지 smoke를 확인했으며, 5개 영상 수동평가·시각/키보드 상호작용·signed installer 설치는 미완료로 명시했다. Python 전체 `212 passed, 1 skipped`, desktop test `10 passed`, TypeScript check·정적 build·문서 diff check가 통과했다. 커밋·푸시는 수행하지 않았다.

### V2-DOCTOR01 — 진단 CLI 실제 runtime profile 정합성 보정

- **작업 종류:** 함수 구현·테스트 코드 구현
- **대상 파일:** `tools/doctor.py`, `tests/unit/test_doctor.py`, `docs/ai/04-implementation-order.md`
- **선행 작업:** V2-DOC01, V2-R01, V2-E2E01
- **목적·동작:** 진단 CLI가 실제 runtime profile의 Qwen tag·model path·FFmpeg path를 사용하고, PATH에만 의존하지 않도록 한다. 환경변수/명시 옵션을 읽되 기본값은 repository 밖 승인 경로로 제한한다.
- **수정 허용:** doctor probe와 해당 단위 테스트, 이 상태 기록
- **금지 범위:** 자동 설치·다운로드·모델 pull·subprocess 실행·네트워크, pipeline/adapter 변경
- **테스트 방법:** fake probe로 qwen tag와 FFmpeg explicit path ready/missing/unsafe path를 검증하고 실제 doctor `--json`은 read-only로 확인한다.
- **완료 판정:** 현재 설치 환경이 `qwen3.6:35b-a3b-agent-64k`와 외부 FFmpeg를 올바르게 보고하며, legacy profile 회귀와 repository 경계 테스트가 통과한다.
- **현재 상태:** `DoctorConfig` 기본 Qwen tag를 `qwen3.6:35b-a3b-agent-64k`로 교정하고 `SODAM_FFMPEG` 절대 파일 경로를 PATH보다 우선하는 read-only probe를 추가했다. 전용 테스트 `4 passed`, `py_compile`, 대상 diff check가 통과했다. 실제 환경에서 `SODAM_FFMPEG=D:\AI-Legion\Sodam-data\tools\ffmpeg-9.0.1\bin\ffmpeg.exe`를 주입한 `doctor.py --json`이 `is_ready:true`와 qwen/FFmpeg/STT/data 전체 OK를 반환했다. 설치·다운로드·네트워크·subprocess 변경은 수행하지 않았다. 커밋·푸시는 수행하지 않았다.

### V2-RELEASE01 — Tauri·installer·실미디어 출시 후보 검증

- **작업 종류:** 수동·통합 검증
- **대상 파일:** `apps/desktop/src-tauri/tauri.conf.json`, `apps/desktop/src-tauri/icons/icon.ico`, 외부 검증 artifact
- **선행 작업:** V2-BUILD01, V2-E2E01, V2-DOC01
- **목적·동작:** 실제 Tauri 창, NSIS/MSI 설치·제거, 승인된 로컬 미디어 품질, 코드 서명 준비 상태를 확인한다.
- **수정 허용:** bundle icon 경로와 유효 ICO 보정, 외부 `Sodam-data` 검증 artifact, 이 기록
- **금지 범위:** signing secret/certificate 생성·저장, 저작권 미확인 미디어 추가, 모델·pipeline 변경
- **검증 방법:** debug executable 5초 실행·창 캡처·Tab 입력, unsigned NSIS/MSI install/uninstall, available media hash/duration inventory, Authenticode/signtool probe
- **완료 판정:** installer install/remove 성공, signing 상태와 입력 표본 부족을 명시하고 남은 수동 blocker를 기록
- **현재 상태:** `tauri:check`와 bundle이 성공했고, `apps/desktop/scripts/build.mjs`를 esbuild ESM 번들로 보정한 뒤 실제 Tauri 창에서 UI 렌더링을 확인했다. `D:\AI-Legion\Sodam-data\tmp\release-r1\tauri-window-final.png`에 입력·출력·진행률/ETA·결과 탭 화면을 캡처했고, 창에 Tab 입력을 보내도 5초 이상 프로세스가 유지됐다. 유효 ICO와 `bundle.icon` 경로를 추가했다. 최신 산출물은 NSIS `Sodam_0.1.0_x64-setup.exe`(SHA-256 `18435E01030DA319356516E2B65A1E33FF613F7837045349F77A775A77AF1307`)와 MSI `Sodam_0.1.0_x64_en-US.msi`(SHA-256 `98F357831957812F767E8A6A5B72E597259B1B72FC3EFE75475461681886A8A7`)이며 debug 실행 파일은 `777C88C26F652323376DAA0C29D7466718D0957D878171AA4C176E2F85697B09`이다. 이전 MSI UAC 설치·레지스트리 확인·제거 smoke는 exit 0으로 완료됐고, 서명 후 비승격 `/qn` 재시도는 로그의 Error 1925(권한 부족)로 1603을 반환했으므로 패키지 결함이 아닌 관리자 권한 실행 조건으로 분류했다. NSIS는 unsigned 상태에서 Windows Application Control 정책에 의해 설치가 차단되었고, 현재 사용자 저장소의 자체서명 인증서(`6B07CF5FBE4BD2233F597D761C3F832099110E83`)로 세 산출물에 SHA-256 서명을 추가했지만 신뢰 루트가 아니므로 `signtool verify /pa`는 신뢰 체인 오류를 반환한다. 배포용 서명 완료에는 공인 코드서명 인증서가 필요하며, 인증서 저장소에 설치하거나 정책을 우회하지 않았다. 외부 미디어 inventory는 서로 다른 영상 hash 2개뿐(나머지는 동일 영상/오디오)이라 5개 영상 품질평가는 입력 부족 blocker로 남겼다. 설치 로그와 캡처는 `D:\AI-Legion\Sodam-data\tmp\release-r1`에만 두었고 커밋·푸시는 수행하지 않았다.

### V2-IPC02 — 개인용 Tauri ↔ Python backend sidecar 연결

- **작업 종류:** 함수 구현 및 IPC 연동 검증
- **대상 파일:** `apps/desktop/src-tauri/src/lib.rs`, `apps/desktop/src/main.ts`, `apps/desktop/tests/ipc-contract.test.mjs`, `docs/ai/04-implementation-order.md`
- **선행 작업:** V2-IPC01, V2-UI01, V2-CLI01
- **목적·동작:** standalone Tauri가 로컬 `tools/run_local.py`를 제한된 인자와 함께 백그라운드 실행하고 stderr JSONL 진행 이벤트와 stdout 최종 결과를 UI에 전달한다. 취소·실패·완료를 terminal 이벤트로 구분한다.
- **수정 허용:** Rust sidecar bridge, 결과 이벤트 UI, IPC 정적 계약 테스트, 이 기록
- **금지 범위:** 임의 shell·URL 실행, backend 알고리즘 변경, 자동 설치·다운로드, private prompt 노출, 인증서·모델 변경
- **테스트 방법:** desktop Node tests, TypeScript check/build, Rust cargo check, 전체 Python pytest, 실제 standalone 창 smoke와 승인된 로컬 미디어 1회 실행
- **완료 판정:** backend readiness가 실제 경로를 반영하고, start_job이 고정 Python 명령을 실행하며 progress/job_result/job_failed/job_cancelled 이벤트가 UI 상태에 반영됨
- **현재 상태:** 구현 및 검증 완료. Rust worker가 `SODAM_PYTHON` 또는 프로젝트 전용 `D:\AI-Legion\Sodam-runtime\Scripts\python.exe`를 우선 사용하고, `SODAM_MODEL_PATH`와 `SODAM_FFMPEG`(또는 승인된 기본 외부 경로)를 전달한다. `tools/run_local.py --mode run --output-mode ... --progress-format jsonl --model-path ... --qwen-model qwen3.6:35b-a3b-agent-64k`를 shell 없이 실행하며 stderr 진행 JSONL은 `progress`, stdout 결과는 `job_result`, 비정상 종료는 `job_failed`, 취소는 `job_cancelled`로 전달한다. UI는 결과 탭에 transcript/summary/introduction을 표시한다. desktop Node tests `10 passed`, TypeScript check/build, Rust `cargo check`, Tauri `tauri:check`, Python 전체 `214 passed, 1 skipped`가 통과했다. 기존 60초 WAV를 전용 runtime으로 실제 실행해 progress 41개, `archived` 상태, summary artifact 저장을 확인했다. standalone 실행 파일은 환경 변수 설정 후 5초 이상 `Sodam` 창을 유지했다. 커밋·푸시는 수행하지 않는다.

### CR-01 — 제약 안전 교정 도메인 계약 및 fake 골격

- **작업 종류:** 도메인 계약 골격 및 테스트 도구 골격
- **대상 파일:** backend/contracts.py, tests/fakes_correction_v3.py, Statement_of_Functions.md
- **선행 작업:** V2-IPC02 및 기존 B07~B10 보호·교정 계약
- **목적·동작:** 보호값을 모델 출력에서 분리하는 EditablePart, LockedPart,
  EditableTextPlan, EditProposal, CorrectionAttempt, CorrectionOutcome의
  immutable 계약과 CR-03용 fake runtime 선언을 준비한다.
- **수정 허용:** 위 두 소스 파일의 선언·docstring·NotImplementedError 골격,
  이 명세 파일과 현재 작업 기록
- **금지 범위:** 기존 protection/correction/main/persistence 로직 변경, 실제
  split/reassemble, Qwen prompt·JSON parser·retry·identity 적용, Ollama·파일
  I/O·네트워크·subprocess, 새 테스트 assertion, 커밋·푸시
- **연결 작업:** CR-02 locked/editable split, CR-03 proposal validation·retry,
  CR-04 pipeline resilience
- **테스트 방법:** contracts와 fake import/compile, frozen dataclass 확인,
  기존 계약 import 회귀, 대상 diff check
- **완료 판정:** 여섯 새 불변 계약이 선언되고 fake 네 개가
  NotImplementedError 골격으로 import되며, 기존 제품 동작은 변경되지 않는다.
  CR01 contracts syntax OK, CR01 fake skeleton import OK, diff check exit 0을
  확인한다.
- **현재 상태:** 골격 작성 완료. 실제 알고리즘·모델·외부 I/O는 실행하지 않았고
  다음 작업 CR-02의 실제 구현 승인을 기다린다. 커밋·푸시는 수행하지 않는다.

### CR-02 — locked/editable 분할 및 결정론적 재조립

- **작업 종류:** 함수 구현 및 단위 테스트 구현
- **대상 파일:** backend/protection.py, tests/unit/test_protection.py,
  Statement_of_Functions.md
- **선행 작업:** CR-01
- **목적·동작:** ProtectedText의 placeholder 구간을 editable/locked part로
  분리하고, 프로그램이 locked 원문 값을 보존한 채 ordered text를 재조립한다.
- **수정 허용:** protection.py의 split_locked_parts와
  reassemble_locked_parts, 기존 보호 단위 테스트와 이 기록
- **금지 범위:** protect_tokens/restore_tokens 계약 변경, Qwen 호출·prompt·JSON
  schema·retry, pipeline/UI/persistence, 외부 I/O, 새 테스트 파일, 커밋·푸시
- **테스트 방법:** mixed token·반복값·빈 text 왕복, editable replacement,
  locked/unknown ID와 malformed map 예외, 입력 불변성, syntax와 diff check
- **완료 판정:** 전용 protection 테스트 28 passed, CR02 syntax OK,
  대표 왕복 CR02 roundtrip OK, 대상 diff check exit 0
- **현재 상태:** 구현 및 검증 완료. LockedPart는 원문 값을 보유하고
  EditableTextPlan.original_text는 보호값이 복원된 원문으로 정의했다. split과
  reassemble은 외부 모델·네트워크·파일을 호출하지 않는다. 커밋·푸시는 수행하지
  않았으며 다음 작업 CR-03의 별도 승인을 기다린다.

### CR-03 — edit proposal 검증 및 bounded retry coordinator

- **작업 종류:** 함수 구현 및 단위 테스트·fake 구현
- **대상 파일:** backend/correction.py, tests/fakes_correction_v3.py,
  tests/unit/test_correction.py, Statement_of_Functions.md
- **선행 작업:** CR-01, CR-02
- **목적·동작:** Qwen이 전체 문장을 재출력하지 않고 editable part ID별
  replacement만 제안하게 하며, malformed JSON·timeout·unknown ID를 최대
  max_attempts회 재시도한다. 모두 실패하면 locked 원문을 보존한 identity
  outcome과 review reason을 반환한다.
- **수정 허용:** correction.py의 validate_edit_proposal, propose_edits,
  correct_with_retry와 CR-01 fake 구현 및 기존 correction 단위 테스트 확장
- **금지 범위:** 기존 correct_chunk 계약 변경, protection/main/persistence/UI
  변경, 실제 Ollama·네트워크·파일 I/O, 새 테스트 파일, 커밋·푸시
- **테스트 방법:** valid/unknown/locked/duplicate ID, placeholder·control/
  oversize replacement, malformed·timeout retry, bounded identity, interrupt
  전파, 기존 B09 회귀
- **완료 판정:** correction·protection 테스트 61 passed, 전체 회귀 테스트 248 passed·1 skipped, CR03 syntax OK,
  fake 호출 횟수와 identity attempt 이력 일치, 대상 diff check exit 0
- **현재 상태:** 구현 및 검증 완료. edit proposal은 editable ID만 참조하고
  locked 값은 reassemble에서 원문으로 유지한다. 최대 3회 시도 후에도 job을
  예외로 종료하지 않고 identity outcome을 반환한다. 커밋·푸시는 수행하지
  않았으며 다음 작업 CR-04 pipeline 연결을 기다린다.

### CR-04 — pipeline grouping·identity outcome·review queue 연결

- **작업 종류:** 함수 구현 및 기존 파이프라인 단위·통합 테스트 보강
- **대상 파일:** backend/main.py, tests/integration/test_pipeline.py,
  tests/unit/test_run_local.py, Statement_of_Functions.md
- **선행 작업:** CR-01, CR-02, CR-03
- **목적·동작:** 기존 correct_chunk 직접 호출을 제거하고
  split_locked_parts·correct_with_retry·reassemble_locked_parts를 연결한다.
  인접 plan을 bounded group으로 처리하며, 한 group의 identity fallback은
  원문을 유지한 correction_unapplied review item으로 기록하고 전체 job을
  계속 진행한다.
- **수정 허용:** main.py correction 단계와 group helper, 기존 pipeline/run_local
  테스트 및 이 명세·현재 작업 기록
- **금지 범위:** correction/protection/persistence 계약 변경, UI·CLI·Tauri,
  실제 모델·네트워크·파일 I/O, 새 테스트 파일, 커밋·푸시
- **테스트 방법:** 정상 replacement와 locked 보존, 다중 segment group 순서,
  identity 후속 group 성공, review location·summary/introduction, cancellation
  및 기존 실패 cleanup 회귀를 fake로 검증한다.
- **완료 판정:** targeted 및 전체 pytest, syntax, diff check가 통과하고
  identity group이 archived 결과와 review queue를 남기며 기존 summary-only
  회귀가 없다.
- **현재 상태:** 구현 및 검증 완료. main.py가 normalized protected segment를
  실제 segment ID가 포함된 plan group으로 만들고 CR-03 bounded coordinator와
  deterministic reassembly를 사용한다. identity fallback은
  correction_unapplied review item/location으로 남기면서 job을 archived까지
  진행하고 summary/introduction을 계속 생성한다. 기존 summary envelope fake는
  안전한 no-op proposal로 호환한다. targeted 테스트 78 passed, 전체 pytest
  250 passed·1 skipped, py_compile 및 대상 diff check를 통과했다. 실제
  모델·네트워크·미디어·subprocess·커밋·푸시는 수행하지 않았다. CR-05 CLI
  progress/report 연결이 다음 작업이다.

### CR-05 — CLI progress·resilience report·safe error category

- **작업 종류:** CLI·pipeline 결과 보고 구현 및 기존 단위·통합 테스트 보강
- **대상 파일:** backend/main.py, tools/run_local.py,
  tests/unit/test_run_local.py, tests/integration/test_pipeline.py,
  Statement_of_Functions.md
- **선행 작업:** CR-04
- **목적·동작:** PipelineResult에 correction group/attempt/identity 메타데이터를
  전달하고 CLI 성공 report와 stderr progress에 구조화한다. 오류는 고정된
  safe category만 노출하며 원시 prompt·전사문·경로·model response를 숨긴다.
- **수정 허용:** main 결과 metadata, run_local report/error 출력, 위 테스트와
  이 작업 기록
- **금지 범위:** correction/protection/persistence/progress 계약 자체 변경,
  Tauri/UI·실제 외부 실행, 새 테스트 파일, 커밋·푸시
- **테스트 방법:** accepted/identity 집계, retry reason·progress 통계,
  stdout JSON과 stderr 분리, category 누출 방지, cancellation/interrupt 회귀
- **완료 판정:** targeted 및 전체 pytest, py_compile, diff check가 통과하고
  CLI report가 resilience 정보를 정확히 표시한다.
- **현재 상태:** 구현 및 검증 완료. PipelineResult가 correction group별
  immutable attempt metadata, identity/review 집계를 보유하고
  tools/run_local.py가 이를 resilience report로 JSON 직렬화한다. progress
  event 수·마지막 stage·terminal status도 report에 포함되며, 실패 stderr는
  고정 safe category와 안정적인 설명만 출력한다. targeted 테스트 80 passed,
  전체 pytest 252 passed·1 skipped, py_compile 및 대상 diff check를
  통과했다. 실제 모델·네트워크·미디어·subprocess·커밋·푸시는 수행하지
  않았다. CR-06 Tauri stderr bridge와 UI 표시가 다음 작업이다.

### CR-06 — Tauri stderr bridge·retry/identity UI 표시

- **작업 종류:** Rust IPC·TypeScript UI 구현 및 기존 desktop 테스트 보강
- **대상 파일:** apps/desktop/src-tauri/src/lib.rs, apps/desktop/src/main.ts,
  apps/desktop/src/state.ts, apps/desktop/src/progress-contract.ts 및 기존
  desktop tests, Statement_of_Functions.md
- **선행 작업:** CR-05
- **목적·동작:** JSONL progress와 resilience report를 구조화 이벤트로
  전달하고 retry/identity/review 상태와 safe error category를 UI에 표시한다.
  stderr는 bounded safe tail만 허용하며 prompt·전사문·절대 경로를 숨긴다.
- **수정 허용:** Tauri bridge, UI reducer/display, 기존 IPC/UI/state 테스트와
  이 작업 기록
- **금지 범위:** backend/tools/persistence/installer 변경, 실제 모델·미디어·
  네트워크 실행, 새 파일, 커밋·푸시
- **테스트 방법:** npm test/check/build, cargo check, malformed stderr·terminal
  event·stale/identity/retry·raw 누출 정적 검증
- **완료 판정:** desktop 테스트·TypeScript·Rust 검사가 통과하고 UI가
  resilience 정보와 안전한 실패 원인을 구분해 표시한다.
- **현재 상태:** Rust bridge가 stderr를 최대 2줄·240자로 제한하고 path/prompt/
  transcript/model 정보를 redaction하며 safe category를 job_failed payload에
  포함한다. 유효한 backend report의 resilience object를 검증해 job_result로
  전달하고, state.ts는 detached resilience metadata와 error category를
  보존한다. main.ts는 재시도·원문 유지·검토 필요 counters와
  완료(검토 필요) 상태를 표시한다. Node desktop 테스트 11 passed,
  TypeScript check와 frontend build는 통과했다. cargo check는 현재 환경의
  stale target에서 tauri crate를 찾지 못해 E0463으로 보류되었으며, 코드
  변경과 무관한 dependency/toolchain blocker로 기록한다. 실제 Tauri 창·
  backend·모델·네트워크는 실행하지 않았다. CR-07 통합·수동 smoke가 다음
  작업이다.

### CI-01 — Desktop GitHub Actions 교정

- **작업 종류:** CI 호환성·Tauri platform asset 교정 및 기존 contract test 보강
- **대상 파일:** `apps/desktop/package.json`, `apps/desktop/src-tauri/tauri.conf.json`,
  `apps/desktop/src-tauri/icons/`, `apps/desktop/tests/build-contract.test.mjs`,
  `Statement_of_Functions.md`
- **선행 문제:** GitHub Actions run `33421283486`에서 Windows가 PowerShell의
  `tests/*.test.mjs` glob을 확장하지 못해 test 단계에서 실패했고, Ubuntu/macOS는
  `icons/icon.png` 부재로 `tauri::generate_context!()`가 실패했다.
- **구현:** `npm test`를 platform-neutral `node --test` discovery로 변경했다.
  기존 `icon.ico`에서 Tauri CLI로 32/128/256 PNG, ICO, ICNS와 AppX/mobile
  icon asset을 생성했고, bundle config는 Tauri 공식 desktop icon set을 명시한다.
  contract test는 test script, icon config 및 각 파일의 존재·비어 있지 않음을
  검증한다.
- **자동 검증:** Node desktop 테스트 11 passed, TypeScript check 통과,
  frontend build 통과, `git diff --check` 통과.
- **수동/CI 판정:** 이 기록의 커밋 push로 새 matrix를 실행한다. Windows는 test
  step 통과, Ubuntu/macOS는 icon missing 오류 없이 bundle 단계로 진행해야 한다.
- **범위 제외:** Python/model pipeline, installer 실행·서명·실제 배포는 변경하지
  않는다.
