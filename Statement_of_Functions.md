# 작업 명세: B01 — 도메인 타입과 예외 처리 계약

## 1. 작업 식별

- **작업 ID:** B01
- **작업 종류:** 함수 구현 준비 작업 중 도메인 계약 구현
- **대상 파일:** `backend/contracts.py`
- **허용되는 보조 수정 파일:** 없음

## 2. 목적과 책임

`backend/contracts.py`에 로컬 전사 파이프라인의 경계를 넘나드는 불변 데이터 계약과 예외 계층을 구현한다. 이 작업은 입력 검증, 파일 접근, 저장, 모델 호출, 네트워크 통신, 직렬화, 상태 전이를 구현하지 않는다. 이후 작업은 이 파일의 타입과 예외 이름만 의존할 수 있어야 한다.

## 3. 구현 대상

다음 이름을 `backend.contracts`에서 공개한다.

### 타입 별칭

```python
JobStatus = Literal[
    "queued", "acquiring", "extracting", "transcribing", "normalizing",
    "correcting", "reviewing", "summarizing", "completed", "cancelling",
    "cancelled", "failed", "cleaning", "archived",
]
```

### 예외 계층

- `SodamError(Exception)`: 모든 도메인 오류의 기반 예외
- `InputSourceError(SodamError)`: 잘못되었거나 지원되지 않는 입력 소스
- `UnsafePathError(SodamError)`: 작업 전용 디렉터리를 벗어난 경로 시도
- `ModelResponseError(SodamError)`: 모델 응답 스키마 위반

이 예외들은 추가 동작, 로깅, I/O를 수행하지 않는다.

### 불변 데이터 클래스

아래 클래스는 모두 `@dataclass(frozen=True)`여야 하며, 필드의 기본값과 타입은 다음과 정확히 일치해야 한다.

| 클래스 | 필드 |
|---|---|
| `JobOptions` | `retain_raw_transcript: bool | None = None`, `retain_result: bool | None = None`, `glossary_name: str | None = None` |
| `Job` | `job_id: str`, `source: str`, `status: JobStatus`, `work_dir: pathlib.Path`, `options: JobOptions` |
| `AudioArtifact` | `job_id: str`, `path: pathlib.Path`, `duration_seconds: float | None = None` |
| `RawSegment` | `segment_id: str`, `start_seconds: float`, `end_seconds: float`, `raw_text: str`, `confidence: float | None = None` |
| `ProtectedText` | `text: str`, `replacements: dict[str, str]` |
| `RuleNormalizedText` | `text: str`, `sentence_boundaries: tuple[int, ...] = ()` |
| `CorrectionResult` | `corrected_text: str`, `changes: tuple[dict[str, str], ...] = ()`, `requires_review: bool = False` |
| `ReviewResult` | `approved_text: str`, `review_items: tuple[dict[str, str], ...] = ()` |
| `Transcript` | `segments: tuple[RawSegment, ...]`, `final_text: str` |
| `Summary` | `text: str`, `evidence_segment_ids: tuple[str, ...]` |
| `CleanupReport` | `retained: tuple[pathlib.Path, ...] = ()`, `removed: tuple[pathlib.Path, ...] = ()` |

## 4. 입력, 반환, 예외, 사전·사후 조건

이 작업에는 공개 함수가 없다. 각 데이터 클래스 생성자가 입력 경계다.

- **입력:** 표에 정의된 Python 값
- **반환:** 생성된 해당 데이터 클래스 인스턴스
- **예외:** 이 작업에서는 타입 런타임 검사나 도메인 검증을 추가하지 않으므로, Python/dataclass 표준 생성 오류 외의 새 예외를 발생시키지 않는다.
- **사전 조건:** 호출자는 타입 별칭과 필드 타입을 준수한다.
- **사후 조건:** 인스턴스는 불변이며, 표의 필드·기본값이 보존된다. 부수 효과는 없다.

## 5. 내부 동작 순서

1. 필요한 표준 라이브러리(`dataclasses`, `pathlib`, `typing`)만 가져온다.
2. `JobStatus`와 예외 계층을 선언한다.
3. 표의 순서대로 frozen 데이터 클래스를 선언한다.
4. 각 선언의 docstring을 유지하거나 계약을 명확히 하는 수준으로 보완한다.
5. `__post_init__`, 사용자 정의 생성자, I/O, 환경 변수 접근, import-time 동작을 추가하지 않는다.

## 6. 허용·금지 의존성

- **호출 가능한 의존성:** Python 표준 라이브러리 `dataclasses`, `pathlib`, `typing`
- **금지된 의존성:** backend의 다른 모듈, 외부 패키지, STT/LLM 런타임, 데이터베이스, 파일시스템 조작, 네트워크, subprocess

## 7. 파일 수정 범위

- **수정 허용:** `backend/contracts.py`만
- **수정 금지:** 위 파일을 제외한 저장소의 모든 파일. 특히 `tests/`, `docs/ai/04-implementation-order.md`, 설정·스크립트·UI 파일을 수정하지 않는다.

## 8. 테스트 도구·Mock·Fixture·테스트 데이터

- 실제 테스트 코드와 테스트 도구 구현은 이번 승인 범위에 포함되지 않는다.
- 후속의 별도 승인된 T01/B01 테스트 작업에서 표준 라이브러리만으로 계약 인스턴스 생성, frozen 불변성, 예외 상속을 검증한다.
- Mock, Fake, Fixture, 외부 테스트 데이터는 이 작업에 필요하지 않다.

## 9. 실행할 검증 명령

로컬 Python 실행기가 존재하는 경우에만 다음 읽기 전용 구문 검사를 실행한다.

```powershell
python -B -c "from pathlib import Path; compile(Path('backend/contracts.py').read_text(encoding='utf-8'), 'backend/contracts.py', 'exec'); print('syntax OK')"
```

`python`이 없으면 설치·다운로드·대체 런타임 실행을 하지 않고, 실행 불가 사유를 보고한다.

## 10. 자동·수동 통과 기준

- **자동 통과 기준:** Python 실행기가 있을 때 구문 검사가 성공한다. 공개 이름과 필드·기본값이 이 문서의 표와 일치한다.
- **수동 검증 기준:** 외부 의존성, 실제 비즈니스 로직, I/O, 상태 전이 코드가 추가되지 않았음을 diff로 확인한다.

## 11. 구현하지 않을 범위

- 입력 값 검증과 상태 전이
- JSON/SQLite 직렬화와 저장
- 미디어 처리, STT, Qwen 호출
- 실제 테스트 코드·fake·fixture 구현
- `.gitignore`, 모델 manifest, 패키지 설정 변경
- 커밋·푸시

## 12. 완료 후 보고 항목

1. 수정한 파일 목록
2. 표와의 계약 일치 여부
3. 실행한 검증 명령과 결과, 또는 실행 불가 사유
4. 남은 위험 요소 및 후속 작업(B01 테스트 계약, T01)의 필요성
