# 작업 명세: T01 — 결정론적 테스트 Fake와 Fixture 생성기

## 1. 작업 식별

- **작업 ID:** T01
- **작업 종류:** 테스트 도구 구현
- **선행 작업:** B01 (도메인 타입·예외 계약) 완료
- **대상 파일:** `tests/fakes.py`, `tests/fixture_factories.py`
- **허용되는 보조 수정 파일:** 없음

## 2. 목적과 책임

실제 STT 엔진, Qwen 런타임, 파일 시스템, 모델, 네트워크를 사용하지 않고도 후속 단위·통합 테스트가 결정론적으로 의존성을 대체할 수 있게 한다. 또한 B01의 도메인 계약을 손쉽게 생성하는 fixture factory를 제공한다.

이 작업은 제품 코드, 실제 테스트 함수, 실제 fixture 데이터 파일, 실제 미디어/모델, 파일 삭제, 네트워크 및 subprocess 호출을 구현하지 않는다.

## 3. 구현 대상과 함수 시그니처

### `tests/fakes.py`

표준 라이브러리만 사용한다. 각 fake는 공개 기록 필드를 통해 호출을 검사할 수 있어야 한다.

```python
class FakeSttEngine:
    def __init__(self, responses: dict[str, object] | None = None, default_response: object | None = None, error: Exception | None = None) -> None: ...
    def transcribe(self, audio_path: str) -> object: ...

class FakeQwenRuntime:
    def __init__(self, responses: dict[str, str] | None = None, default_response: str = "", error: Exception | None = None) -> None: ...
    def complete(self, prompt: str) -> str: ...

class FakeFileSystem:
    def __init__(self, existing_paths: set[str] | None = None, error_paths: set[str] | None = None) -> None: ...
    def remove(self, path: str) -> None: ...
```

각 인스턴스는 다음 공개 기록 필드를 가져야 한다.

| 클래스 | 기록 필드 | 사후 조건 |
|---|---|---|
| `FakeSttEngine` | `transcribed_paths: list[str]` | `transcribe`가 호출될 때마다 입력 경로가 한 번 추가된다. |
| `FakeQwenRuntime` | `prompts: list[str]` | `complete`가 호출될 때마다 입력 프롬프트가 한 번 추가된다. |
| `FakeFileSystem` | `existing_paths: set[str]`, `removed_paths: list[str]` | 성공한 `remove`는 대상 경로를 `existing_paths`에서 제거하고 `removed_paths`에 한 번 추가한다. |

동작 규칙:

1. `FakeSttEngine.transcribe`는 먼저 경로를 기록한다. 생성자 `error`가 있으면 **동일한 예외 객체**를 raise한다. 그렇지 않으면 `responses[audio_path]`가 있으면 반환하고, 없으면 `default_response`를 반환한다.
2. `FakeQwenRuntime.complete`는 먼저 프롬프트를 기록한다. 생성자 `error`가 있으면 **동일한 예외 객체**를 raise한다. 그렇지 않으면 `responses[prompt]`가 있으면 반환하고, 없으면 `default_response`를 반환한다.
3. `FakeFileSystem.remove`는 `path`가 `error_paths`에 있으면 `OSError`를 raise하고 어떠한 기록도 변경하지 않는다. 그렇지 않고 `path`가 `existing_paths`에 없으면 `FileNotFoundError(path)`를 raise하고 어떠한 기록도 변경하지 않는다. 성공 시에만 위 표의 사후 조건을 만족한다.
4. 생성자 인자는 복사해 보관한다. 호출자가 이후 원본 dict/set을 바꿔도 fake 내부 상태가 변하면 안 된다.
5. 응답 객체는 반환 전에 복사하거나 변형하지 않는다.

### `tests/fixture_factories.py`

`backend.contracts`에서 타입만 import한다. 시간, UUID, 임시 폴더, 환경 변수, 실제 파일 시스템을 사용하지 않는다.

```python
def make_job_options(**overrides: object) -> JobOptions: ...
def make_job(**overrides: object) -> Job: ...
def make_raw_segment(**overrides: object) -> RawSegment: ...
def make_transcript(**overrides: object) -> Transcript: ...
```

| 함수 | 기본 생성값 |
|---|---|
| `make_job_options` | `JobOptions()` |
| `make_job` | `job_id="job-001"`, `source="fixture://source"`, `status="queued"`, `work_dir=Path("fixture-work")`, `options=make_job_options()` |
| `make_raw_segment` | `segment_id="segment-001"`, `start_seconds=0.0`, `end_seconds=1.0`, `raw_text="fixture text"`, `confidence=None` |
| `make_transcript` | `segments=(make_raw_segment(),)`, `final_text="fixture text"` |

Factory 공통 규칙:

1. `overrides`의 키는 대상 dataclass의 필드명이어야 한다.
2. 알 수 없는 키는 dataclass 생성자가 발생시키는 `TypeError`를 그대로 전파한다.
3. `make_job`의 `options` 기본값은 호출마다 새 `JobOptions` 인스턴스여야 한다.
4. `make_transcript`의 `segments` 기본값은 호출마다 새 tuple을 생성한다.
5. 입력 검증, 변환, I/O, 무작위 값 생성은 하지 않는다.

## 4. 입력, 반환, 예외, 사전·사후 조건

- **입력:** 위 시그니처의 생성자·메서드 인자와 factory override 키워드 인자
- **반환:** 설정된 fake 응답 또는 B01 도메인 데이터 클래스 인스턴스
- **예외:** 구성된 동일 예외, `OSError`, `FileNotFoundError`, dataclass 생성자의 `TypeError`만 위 규칙대로 발생한다. 새 도메인 예외를 만들지 않는다.
- **사전 조건:** 호출자는 문자열 키와 명세된 override 필드를 제공한다.
- **사후 조건:** 외부 상태는 변하지 않으며, fake의 공개 기록 필드만 명세에 따라 변한다.

## 5. 내부 동작 순서

1. 기존 `tests/fakes.py`의 선언 전용 `NotImplementedError` 골격을 위 계약의 결정론적 구현으로 교체한다.
2. `tests/fixture_factories.py`를 새로 만들고 B01 타입을 생성하는 순수 factory만 구현한다.
3. 각 함수와 클래스에 계약·예외·부수 효과를 설명하는 docstring을 추가한다.
4. 구현 후 명세의 검증 명령을 실행한다.
5. 제품 코드, 실제 테스트, fixture 데이터, 설정 파일은 수정하지 않는다.

## 6. 허용·금지 의존성

- **허용:** Python 표준 라이브러리, `backend.contracts`의 `JobOptions`, `Job`, `RawSegment`, `Transcript`
- **금지:** 외부 패키지, `pytest`, 실제 STT/Qwen/FFmpeg/다운로드 도구, SQLite, 파일/네트워크/subprocess I/O, 시간·무작위·UUID·환경 변수 API

## 7. 수정 범위

- **수정 허용:** `tests/fakes.py`, `tests/fixture_factories.py`
- **수정 금지:** 그 외 모든 파일. 특히 `backend/`, `tests/unit/`, `tests/integration/`, `tests/fixtures/`, `docs/`, 설정·스크립트·UI 파일을 수정하지 않는다.

## 8. 테스트 도구·Mock·Fixture·테스트 데이터

- 이 작업의 산출물이 후속 테스트의 Fake와 fixture 생성기다.
- 실제 테스트 함수, pytest fixture decorator, JSON/오디오 fixture, Mock/Stub 프레임워크는 구현하지 않는다.
- 검증은 아래의 짧은 표준 라이브러리 실행 명령으로 구현 대상을 직접 호출해 수행한다.

## 9. 실행할 검증 명령

로컬 Python 실행기가 있을 때, 저장소 루트에서 다음 명령을 실행한다.

```powershell
python -B -c "from backend.contracts import JobOptions; from tests.fakes import FakeFileSystem, FakeQwenRuntime, FakeSttEngine; from tests.fixture_factories import make_job, make_raw_segment, make_transcript; stt=FakeSttEngine({'a.wav': ['ok']}); assert stt.transcribe('a.wav') == ['ok'] and stt.transcribed_paths == ['a.wav']; qwen=FakeQwenRuntime({'p': '{}'}); assert qwen.complete('p') == '{}' and qwen.prompts == ['p']; fs=FakeFileSystem({'tmp.wav'}); fs.remove('tmp.wav'); assert fs.removed_paths == ['tmp.wav'] and not fs.existing_paths; assert make_job().options == JobOptions() and make_raw_segment().segment_id == 'segment-001' and make_transcript().final_text == 'fixture text'; print('T01 checks OK')"
```

그 다음 다음 명령으로 두 대상 파일의 문법을 확인한다.

```powershell
python -B -c "from pathlib import Path; [compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in ('tests/fakes.py', 'tests/fixture_factories.py')]; print('syntax OK')"
```

`python`이 없으면 설치·다운로드·대체 런타임을 사용하지 않고, 실행 불가 사유만 보고한다.

## 10. 자동·수동 통과 기준

- **자동:** 위 직접 호출 검증과 구문 검사가 모두 성공한다.
- **수동:** `git diff --check`가 공백 오류 없이 통과하고, diff가 두 허용 테스트 도구 파일에만 한정됨을 확인한다.
- **실패:** 외부 의존성 호출, 실제 파일 삭제, 잘못된 fake 기록, 공유 입력 컨테이너 변경, 범위 밖 파일 수정 하나라도 있으면 실패다.

## 11. 구현하지 않을 범위

- 제품 기능 또는 `backend/` 수정
- 실제 pytest 테스트 코드·fixture 데이터 구현
- 실제 디스크·네트워크·모델 호출
- 성능 측정, 모델 응답 스키마 검증, 상태 전이
- 커밋·푸시

## 12. 완료 후 보고 항목

1. 수정·생성한 파일 목록
2. 각 fake의 응답·예외·호출 기록 동작 결과
3. 각 factory의 기본값·override 결과
4. 실행한 검증 명령과 결과, 또는 실행 불가 사유
5. `git diff --check` 및 변경 범위 확인 결과
6. 남은 위험 요소와 후속 작업(B02 또는 함수별 실제 테스트 코드)의 필요성
