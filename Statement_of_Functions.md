# 작업 명세: B02 — 작업 생성, 상태 전이, 취소 요청

## 1. 작업 식별

- **작업 ID:** B02
- **작업 종류:** 함수 구현
- **선행 작업:** B01(도메인 계약), T01(결정론적 fake·fixture 도구) 완료
- **대상 파일:** `backend/jobs.py`, `backend/contracts.py`
- **허용되는 보조 수정 파일:** 없음

## 2. 목적과 책임

외부 미디어 획득·STT·저장소·DB를 호출하지 않고, 새 작업의 불변 `Job` 객체를 만들고 안전한 상태 전이와 취소 요청을 표현한다. 실제 데이터베이스 기록과 전용 작업 디렉터리 생성은 B03 및 후속 오케스트레이션 작업의 책임이다.

생성된 `Job.work_dir`은 Git 작업 트리 밖의 기본 경로 `D:\AI-Legion\Sodam-data\tmp\jobs\<job_id>`를 **가리키기만** 한다. 이 작업은 해당 경로 또는 그 부모 경로를 만들거나 삭제하지 않는다.

## 3. 구현 대상과 시그니처

### `backend/contracts.py`

아래 예외 하나를 `SodamError`의 직접 하위 클래스로 추가한다.

```python
class JobStateError(SodamError):
    """Raised when a requested Job status transition is not permitted."""
```

예외 선언 외에는 기존 데이터 클래스·타입 별칭·기존 예외의 필드, 상속 구조, 동작을 변경하지 않는다.

### `backend/jobs.py`

다음 이름을 구현한다.

```python
def create_job(source: str, options: JobOptions) -> Job: ...
def transition_job(job: Job, target_status: JobStatus) -> Job: ...
def request_cancellation(job: Job) -> Job: ...
```

`dataclasses.replace`, `pathlib.Path`, `urllib.parse.urlparse`, `uuid.uuid4`와 `backend.contracts`의 `InputSourceError`, `JobStateError`, `Job`, `JobOptions`, `JobStatus`만 사용한다.

## 4. 함수 계약

### `create_job(source, options) -> Job`

- **입력:** 비어 있지 않은 `str` source와 `JobOptions` 인스턴스
- **출력:** 새 UUID hex 문자열 `job_id`, 정규화 source, `status="queued"`, 작업 외부 기본 경로, 제공된 `options`를 갖는 frozen `Job`
- **사전 조건:** `options`는 `JobOptions`여야 한다.
- **정상 source:**
  - `http` 또는 `https` URL이며 hostname이 비어 있지 않은 경우. URL 문자열의 앞뒤 공백은 제거해 저장한다.
  - 존재하고 일반 파일인 로컬 경로. `Path.expanduser().resolve(strict=True)` 결과의 문자열을 저장한다.
- **예외:**
  - source가 `str`이 아니거나 공백뿐이면 `InputSourceError`
  - `options`가 `JobOptions`가 아니면 `TypeError`
  - URL의 scheme이 `http`/`https`가 아니거나 hostname이 없으면 `InputSourceError`
  - 로컬 경로가 없거나 디렉터리이면 `InputSourceError`
- **부수 효과:** 없음. 디렉터리/파일 생성·삭제, DB 기록, 네트워크, subprocess 호출 금지.
- **사후 조건:** 반환 job은 `queued` 상태이며 `work_dir.name == job_id`이고, work_dir의 부모는 정확히 `Path(r"D:\AI-Legion\Sodam-data\tmp\jobs")`다.

### `transition_job(job, target_status) -> Job`

- **입력:** `Job`과 유효한 `JobStatus` 문자열
- **출력:** target 상태로 바뀐 새 frozen `Job`; 입력 `job`은 변경하지 않는다.
- **예외:** job이 `Job`이 아니거나 target이 유효하지 않으면 `TypeError`; 아래 표에 없는 전이는 `JobStateError`.
- **부수 효과:** 없음.

허용 전이는 다음뿐이다.

| 현재 상태 | 허용 target 상태 |
|---|---|
| `queued` | `acquiring`, `cancelling`, `failed` |
| `acquiring` | `extracting`, `cancelling`, `failed` |
| `extracting` | `transcribing`, `cancelling`, `failed` |
| `transcribing` | `normalizing`, `cancelling`, `failed` |
| `normalizing` | `correcting`, `cancelling`, `failed` |
| `correcting` | `reviewing`, `cancelling`, `failed` |
| `reviewing` | `summarizing`, `cancelling`, `failed` |
| `summarizing` | `completed`, `cancelling`, `failed` |
| `cancelling` | `cancelled`, `failed` |
| `completed` | `cleaning` |
| `cancelled` | `cleaning` |
| `failed` | `cleaning` |
| `cleaning` | `archived` |
| `archived` | 없음 |

동일 상태로의 전이는 허용하지 않는다.

### `request_cancellation(job) -> Job`

- **입력:** `Job`
- **출력:** `queued` 또는 실행 중 상태(`acquiring`, `extracting`, `transcribing`, `normalizing`, `correcting`, `reviewing`, `summarizing`)에서 `cancelling`으로 바뀐 새 Job
- **예외:** 입력이 Job이 아니거나 `cancelling`, 완료·실패·정리·보관 상태이면 `JobStateError`
- **부수 효과:** 없음. 이 함수는 `transition_job(job, "cancelling")`만 호출해야 한다.

## 5. 내부 동작 순서

1. `JobStateError`를 B01 예외 계층에 추가한다.
2. `backend/jobs.py`에서 source를 URL 또는 로컬 파일로 판별하고 위 계약대로 정규화한다.
3. UUID와 외부 기본 작업 경로를 사용해 queued `Job`을 생성한다. 작업 경로를 실제로 만들지 않는다.
4. 전이 표를 모듈 상수로 선언하고 `transition_job`에서만 상태 검사를 수행한다.
5. `dataclasses.replace`로 새 Job을 반환한다.
6. `request_cancellation`은 취소 가능 상태를 확인한 뒤 `transition_job`에 위임한다.
7. 명세의 직접 호출·구문 검증을 실행하고 수정 파일·결과·위험 요소를 보고한다.

## 6. 허용·금지 의존성

- **허용:** Python 표준 라이브러리 `dataclasses`, `pathlib`, `urllib.parse`, `uuid`; `backend.contracts`
- **금지:** 외부 패키지, `tests` import, DB/SQLite, 파일 생성·삭제, 디렉터리 생성, 네트워크, HTTP 요청, STT/LLM, FFmpeg, subprocess, 환경 변수, 로그·전역 가변 상태

## 7. 수정 범위

- **수정 허용:** `backend/jobs.py`, `backend/contracts.py`
- **수정 금지:** 그 외 모든 파일. 특히 `tests/`, `docs/`, `Statement_of_Functions.md`, 스크립트, 설정, UI 파일을 수정하지 않는다.

## 8. 테스트 도구·Mock·Fixture·테스트 데이터

- 이번 작업에서는 새 pytest 파일·fixture·fake를 만들지 않는다.
- T01의 `tests.fixture_factories.make_job`은 읽기 전용 검증에서만 사용할 수 있다.
- 새 파일을 만들지 않는 표준 라이브러리 직접 호출 명령으로 함수 입력·출력·예외·불변성을 검증한다.

## 9. 실행할 검증 명령

저장소 루트에서 아래 명령을 실행한다.

```powershell
python -B -c "from pathlib import Path; from unittest import TestCase; from backend.contracts import InputSourceError, JobOptions, JobStateError; from backend.jobs import create_job, request_cancellation, transition_job; case=TestCase(); options=JobOptions(); job=create_job('AGENTS.md', options); assert job.status == 'queued' and job.work_dir.name == job.job_id and job.work_dir.parent == Path(r'D:\AI-Legion\Sodam-data\tmp\jobs') and job.options is options; active=transition_job(job, 'acquiring'); assert active.status == 'acquiring' and job.status == 'queued'; cancelling=request_cancellation(active); assert cancelling.status == 'cancelling'; case.assertRaises(JobStateError, request_cancellation, cancelling); case.assertRaises(JobStateError, transition_job, job, 'completed'); case.assertRaises(InputSourceError, create_job, 'ftp://example.com/a', options); case.assertRaises(InputSourceError, create_job, 'not-found.file', options); assert create_job(' https://example.com/watch ', options).source == 'https://example.com/watch'; print('B02 checks OK')"
```

그 다음 구문 검사를 실행한다.

```powershell
python -B -c "from pathlib import Path; [compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in ('backend/contracts.py', 'backend/jobs.py')]; print('syntax OK')"
```

`python` 명령이 인식되지 않으면 사용자 Python 3.12 전체 경로를 사용해 같은 명령을 실행할 수 있다. 설치·다운로드·대체 런타임은 사용하지 않는다.

## 10. 자동·수동 통과 기준

- **자동:** 두 검증 명령이 각각 `B02 checks OK`, `syntax OK`를 출력한다.
- **수동:** `git diff --check`가 공백 오류 없이 통과하며, 변경 파일이 허용된 두 backend 파일에만 한정된다.
- **실패:** 실제 디렉터리/파일/DB를 만들거나 삭제함, 작업 데이터 경로가 Git 작업 트리에 있음, 허용되지 않은 전이, 입력 Job 변경, 범위 밖 파일 수정 중 하나라도 발생하면 실패다.

## 11. 구현하지 않을 범위

- SQLite/JSON 저장 및 실제 DB 기록
- 작업 디렉터리 생성·정리, 미디어·소스·STT·LLM 처리
- UI, API, 비동기/병렬 실행, 로그
- 새 실제 pytest 테스트 코드, fixture, fake 구현
- 커밋·푸시

## 12. 완료 후 보고 항목

1. 수정 파일 목록
2. source 정규화·작업 경로 계산·UUID 생성 결과
3. 허용·차단 상태 전이와 취소 요청 결과
4. 실행한 검증 명령과 결과
5. `git diff --check`와 변경 범위 확인 결과
6. 남은 위험 요소: DB 저장(B03), 실제 작업 폴더 생성/정리(B03), 함수별 pytest 테스트의 별도 승인 필요성
