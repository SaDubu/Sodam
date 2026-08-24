# 로컬 영상 전사·교정·2문장 요약 프로그램 설계안

> 상태: 아이디어 검토용 설계. 이 문서는 구현 승인 전의 제안이며, 소스 코드·테스트 코드·외부 서비스 연동은 포함하지 않는다.

## 1. 목표와 문제

사용자가 제공한 YouTube 링크, 영상 또는 오디오 파일을 로컬 PC에서 처리하여 다음 산출물을 만든다.

1. 시간 정보가 보존된 STT 원문
2. 띄어쓰기·명백한 문장부호 노이즈를 정리하고, 문맥 교정 결과와 변경 이력을 함께 가진 최종 전사문
3. 최종 전사문에 근거한 **최대 두 문장**의 한국어 요약

핵심 문제는 STT 결과가 띄어쓰기, 문장 경계, 조사, 동음이의어에서 불완전하며, 이 오류가 후속 요약의 신뢰도를 낮춘다는 점이다. Qwen3 8B는 오디오를 듣는 모델이 아니라 텍스트 모델이므로, STT와 교정·요약을 명확히 분리한다.

## 2. 범위

### 포함

- 사용자가 로컬에서 선택한 영상/음성 파일 처리
- 사용자가 입력한 YouTube 링크에서 음성 처리에 필요한 미디어만 일회성으로 가져오기
- 로컬 STT와 타임스탬프 보존
- 숫자·날짜·금액·URL·영문 약어·사용자 등록 고유명사의 보호
- 로컬 규칙 기반 띄어쓰기/문장부호 정리
- Qwen3 8B(Q5 GGUF 우선)의 제한적 문맥 교정
- 수정 차이와 위험 변경의 검수 큐 표시
- 긴 전사문의 계층형 요약과 두 문장 제한
- 처리 후 임시 파일 정리 선택권

### 제외

- 네이버 맞춤법 검사기 등 비공식 외부 서비스 호출
- 클라우드 전송, 계정 로그인, 협업 기능
- 모델 가중치·사용자 영상·전사 결과를 Git 저장소에 커밋하거나 푸시
- 음성 자체를 사람이 검수하는 편집 도구의 완성 구현
- 맞춤법 사전 또는 STT/LLM 모델의 재학습
- 네이버 검사기와 동일한 규칙·품질 보장

## 3. 제안 구조와 데이터 흐름

```text
[데스크톱 UI: YouTube URL 또는 로컬 파일]
      |
      v
[작업 관리자] -- 작업 상태/취소/보관 정책 --> [로컬 작업 저장소]
      |
      +--> [URL 유효성/지원 여부 확인] --> [음성 전용 임시 획득]
      |                                         |
      |                                  즉시 원본 미디어 정리
      |
      +--> [로컬 파일 오디오 추출] -------------+--> [STT 엔진] --> raw_segments.json
                                            |
                                            v
                             [보호 토큰 추출·치환]
                                            |
                                            v
                [Kiwi 띄어쓰기 + 안전 규칙 + 문장 경계 후보]
                                            |
                                            v
                     [Qwen3 8B: JSON 형식 문맥 교정]
                                            |
                                            v
                [차이 검증·보호 토큰 복원·검수 큐 생성]
                                            |
                       +--------------------+--------------------+
                       v                                         v
             최종 전사문/타임스탬프                    계층형 요약 --> 두 문장 요약
```

### 실행 원칙

- STT 실행과 Qwen 실행은 순차 실행한다. 두 대형 모델을 동시에 VRAM에 올리지 않는다.
- YouTube 입력은 작업 전용 임시 폴더에만 저장한다. 다운로드 도구가 영상 컨테이너를 잠시 만들더라도 오디오 추출 성공 직후 삭제하며, 원본 영상은 영구 보관하지 않는다.
- STT가 끝나면 임시 오디오도 기본적으로 즉시 삭제한다. 기본 보관물은 전사문, 변경 이력, 요약, 최소 작업 메타데이터뿐이다.
- 성공·실패·취소 모두 정리 절차를 거친다. 앱 시작 시 이전 비정상 종료에서 남은 작업 전용 임시 폴더도 안전하게 정리한다.
- 링크 입력 기능은 사용자가 접근·처리할 권한이 있는 영상에 한정한다. 실제 구현 전 대상 플랫폼 약관, 저작권, 다운로드 도구의 라이선스를 별도 검토한다.
- 교정 전후 모두 `segment_id`, 시작/종료 시간, 원문을 유지한다. 최종 요약의 각 핵심 주장도 관련 구간 ID를 내부적으로 보관한다.
- 규칙 단계는 한글 글자 자체를 수정하지 않는다. 공백 및 명백한 문장부호 노이즈만 바꾸므로 결과를 재현·감사할 수 있다.
- Qwen은 한 번에 3~10분 분량 또는 토큰 상한 이하의 인접 구간만 받는다. 영상 전체를 단일 프롬프트에 넣지 않는다.
- Qwen의 교정 출력은 자유문이 아닌 JSON 스키마여야 한다. 의미 추가/삭제, 보호 토큰 변경, 근거 없는 숫자 교체는 금지한다.

## 4. 기술 선택과 이유

| 계층 | 제안 | 이유 |
|---|---|---|
| 데스크톱 UI | Tauri 기반 UI + 로컬 백엔드 프로세스 | 설치 본체를 작게 유지하고 로컬 파일 접근과 작업 진행 표시를 제공한다. |
| YouTube 음성 획득 | URL 소스 어댑터(후보: `yt-dlp`) + FFmpeg | 지원되는 URL에서 작업용 미디어를 일시 획득한 뒤 음성만 표준 형식으로 변환한다. 플랫폼별 변경을 어댑터 안에 격리한다. |
| 영상 오디오 추출 | FFmpeg | 널리 쓰이는 컨테이너/코덱 처리 도구이며, 오디오를 표준 형식으로 통일한다. |
| STT | Whisper 계열(`turbo`를 초기 기본값으로 검토) | 다국어 음성을 전사하며, 타임스탬프가 있는 구간 결과를 만들 수 있다. |
| 띄어쓰기/형태소 | Kiwipiepy (Kiwi) | 로컬에서 띄어쓰기 복원과 형태소·문장 경계 정보를 제공한다. |
| 문장 분리 보조 | KSS | 한국어 문장 분리의 교차 검증 또는 대체 경로로 사용한다. |
| 문맥 교정·요약 | Qwen3 8B GGUF, Q5 우선 | 로컬 실행 가능성과 한국어/영어 혼합 문맥 처리의 균형을 노린다. 교정·요약 시 non-thinking 모드를 기본으로 한다. |
| 추론 런타임 | llama.cpp 또는 Ollama 중 하나를 승인 후 선택 | GGUF 로컬 배포에 적합하다. 실제 배포 크기와 Windows 패키징 난이도로 결정한다. |
| 작업 데이터 | SQLite 메타데이터 + JSON 산출물 | 작업 재개, 변경 이력, 타임스탬프를 단순하고 이식성 있게 보관한다. |

Qwen3 Q5 모델은 약 6GB, STT 모델과 런타임은 별도 용량이다. 표준 설치는 모델을 앱에 묶지 않고 첫 실행 때 선택 다운로드하는 구조를 제안한다. YouTube에서 일시 획득한 원본 영상과 임시 오디오는 모델보다 더 큰 용량을 차지할 수 있으므로, 기본값은 STT 완료 뒤 임시 오디오 삭제로 둔다.

## 5. 생성·수정이 필요한 파일(승인 후 골격 단계 기준)

| 파일 | 책임 |
|---|---|
| `apps/desktop/` | YouTube 링크/파일 선택, 작업 진행도, 전사문/검수 큐/요약 표시 UI |
| `backend/main.py` | 로컬 백엔드 시작과 작업 API 조립 |
| `backend/jobs.py` | 작업 생성, 상태 전이, 취소, 보관 정책 |
| `backend/sources.py` | YouTube URL 검증, 메타데이터 최소 조회, 작업 전용 음성 획득 |
| `backend/media.py` | 로컬 입력 파일 검증과 오디오 추출 |
| `backend/transcription.py` | STT 호출 및 시간 구간 표준화 |
| `backend/protection.py` | 보호 토큰 식별·치환·복원 |
| `backend/text_rules.py` | 공백/문장부호 정규화와 문장 경계 후보 생성 |
| `backend/correction.py` | Qwen 요청 작성, JSON 교정 응답 파싱 |
| `backend/validation.py` | 원문-교정문 차이 분석, 위험 변경 분류 |
| `backend/summarization.py` | 구간 요약, 통합 요약, 두 문장 제한 |
| `backend/storage.py` | SQLite/JSON 저장과 임시 산출물 삭제 |
| `backend/contracts.py` | 작업·세그먼트·교정·요약 데이터 타입 |
| `tests/` | 단위·통합·회귀 테스트 |
| `tests/fixtures/` | STT 샘플, 보호 토큰, 기대 교정/요약 결과 |
| `tools/evaluate_transcript.py` | 모델별 교정 정확도와 위험 변경률을 비교하는 CLI |
| `tools/inspect_job.py` | 결과 JSON, 타임스탬프, 검수 큐를 사람이 점검하는 CLI |
| `scripts/setup-models.ps1` | Git과 분리된 로컬 모델 저장소에 Qwen/STT 모델을 내려받고 무결성을 확인 |
| `scripts/check-repository-clean.ps1` | 커밋 전 추적 파일에서 모델·미디어·대용량 파일을 탐지해 실패 처리 |
| `models/manifest.json` | 추적 가능한 모델 ID, 런타임, 양자화, 출처, 라이선스, 체크섬의 선언만 보관 |
| `.gitignore` | 모델, 사용자 미디어, 작업 임시 파일, 토큰/설정 파일의 Git 추적 차단 |
| `.gitattributes` | 대용량 바이너리를 Git LFS로 우회하지 않으며 텍스트 파일의 줄바꿈을 통일 |
| `README.md` | 사전 요구사항, 로컬 모델 설치 명령, 실행/정리/대용량 파일 금지 정책 안내 |

## 6. 주요 인터페이스와 함수 계약

| 함수 | 입력 → 출력 | 예외·부작용 | 사전/사후 조건 |
|---|---|---|---|
| `create_job(source, options) -> Job` | YouTube URL 또는 로컬 파일 경로와 옵션 → 대기 상태 작업 | 잘못된 URL/경로, 미지원 형식 예외; DB에 작업 기록 | 입력은 읽을 수 있어야 한다. 반환 작업에는 고유 ID와 전용 임시 경로가 있다. |
| `acquire_source_audio(job) -> AudioArtifact` | URL 또는 로컬 파일 작업 → 표준 오디오 파일 | 지원하지 않는 URL, 획득 실패, 접근 거부 예외; 작업 전용 임시 파일 작성 | URL은 지원 소스여야 하며, 로컬 파일은 읽을 수 있어야 한다. 성공 뒤 원본 다운로드는 제거되고 오디오 산출물만 남는다. |
| `extract_audio(job) -> AudioArtifact` | 작업의 영상/음성 → 표준 오디오 파일 | 코덱 실패 예외; 임시 오디오 작성 | 작업이 대기/실행 상태여야 한다. 산출물 길이는 입력의 재생 시간과 허용 오차 내다. |
| `transcribe_audio(audio, config) -> list[RawSegment]` | 오디오 → 시간·신뢰도·원문을 가진 STT 구간 | 엔진 실패/모델 없음 예외; 모델 캐시 사용 | 오디오는 표준 형식이다. 모든 구간은 유효한 시간 범위와 원문을 갖는다. |
| `protect_tokens(segments, glossary) -> ProtectedText` | STT 구간/사용자 용어집 → 치환 문자열과 토큰 표 | 없음; 메모리상 토큰 매핑 생성 | 보호 대상은 원문 그대로 보관된다. 자리표시자는 충돌하지 않는다. |
| `normalize_rules(protected_text) -> RuleNormalizedText` | 치환 문자열 → 공백/명백한 기호가 정리된 텍스트 | 불변식 위반 예외; 없음 | 보호 자리표시자와 비공백 한글/영문/숫자 문자는 보존된다. |
| `correct_chunk(text, context) -> CorrectionResult` | 인접 구간과 교정 지침 → 스키마 검증된 교정 결과 | 모델 시간초과/비정상 JSON 예외; 로컬 추론 호출 | 입력 길이는 상한 이하다. 결과에는 원문, 교정문, 수정 유형, 검수 여부가 있다. |
| `validate_revision(raw, corrected, protections) -> ReviewResult` | 원문/교정문/보호 표 → 허용 교정과 보류 변경 | 보호 토큰 손실 예외; 없음 | 원문과 교정문이 같은 구간에 대응한다. 위험 변경은 자동 확정되지 않는다. |
| `assemble_transcript(segments) -> Transcript` | 검증된 구간 → 최종 전사문과 타임스탬프 색인 | 누락/중복 구간 예외; JSON 저장 | 구간 순서는 시간순이다. 원문과 최종문을 모두 조회할 수 있다. |
| `summarize_transcript(transcript) -> Summary` | 최종 전사문 → 두 문장 이하 요약과 근거 구간 ID | 모델 시간초과/형식 오류 예외; 로컬 추론 호출 | 전사문이 비어 있지 않다. 요약은 2문장 이하이며 새 사실을 포함하지 않는다. |
| `cleanup_artifacts(job, policy) -> CleanupReport` | 작업과 보관 정책 → 삭제/보존 결과 | 권한/경로 안전성 예외; 임시 미디어 삭제 | 삭제 대상은 해당 작업 전용 디렉터리 안이다. 기본 정책에서는 원본 영상·임시 오디오를 항상 삭제하고 전사문/요약만 보존한다. |
| `install_models(manifest, model_home) -> InstallReport` | 추적된 모델 선언과 Git 외부 경로 → 설치/검증 결과 | 네트워크, 저장공간, 체크섬 불일치 예외; 모델 파일 작성 | 모델 경로는 저장소 밖이어야 한다. 선언된 버전·체크섬의 모델만 설치된다. |
| `check_repository_clean(repo_root) -> RepositoryCheck` | 저장소 경로 → 금지 파일 검사 결과 | 추적된 모델/미디어/임계값 초과 파일 발견 시 `RepositoryPolicyError`; 없음 | Git 저장소여야 한다. 통과하면 금지 패턴과 용량 제한을 위반한 추적 파일이 없다. |

## 7. 교정·요약 정책

### 자동 확정 가능한 변경

- 중복 공백 및 문장부호 앞 공백 제거
- 괄호·따옴표 주변의 명백한 공백 노이즈 정리
- 보호 대상이 아닌 단어의 확실한 띄어쓰기 복원
- 동일한 단어의 연속 반복 중 STT 노이즈로 명확히 판별되는 사례(기본값은 검수 큐)

### 자동 확정하면 안 되는 변경

- 숫자, 날짜, 금액, 단위, 항공편명, URL
- 인명, 지명, 브랜드, 영어 약어, 사용자 용어집 항목
- 음성 없이 확정할 수 없는 동음이의어 교체
- 문장의 주장·의도·사실관계를 바꾸는 축약 또는 재서술

### Qwen3 교정 프롬프트의 필수 제약

1. 입력의 의미와 사실을 추가·삭제·추론하지 않는다.
2. 보호 자리표시자를 한 글자도 바꾸지 않는다.
3. 교정 종류를 `spacing`, `punctuation`, `grammar`, `possible_asr_error`로 분류한다.
4. `grammar`와 `possible_asr_error`는 기본적으로 검수 여부를 명시한다.
5. JSON 이외 텍스트를 출력하지 않는다.

요약은 구간별 핵심을 먼저 만들고, 이를 다시 통합해 두 문장으로 제한한다. 최종 문장마다 최소 하나의 근거 구간 ID를 내부 결과에 남긴다. UI에는 필요 시 사용자가 그 시간으로 이동할 수 있게 한다.

## 8. 테스트 전략과 검증 기준

### 공통 테스트 데이터·도구

- `tests/fixtures/stt_korean.json`: 띄어쓰기 누락, 무음 구간, 영어·숫자·고유명사가 섞인 STT 구간
- `tests/fixtures/glossary.json`: 항공사, 도시, 마일리지, 금액 등 보호 대상
- `tests/fixtures/audio/`: 짧은 한국어 음성 및 기대 시간 범위를 가진 허가된 테스트 음성
- `tools/evaluate_transcript.py`: 원문 대비 수정 비율, 보호 토큰 보존율, 사람 라벨과의 교정 일치율, 처리 시간 측정
- `tools/inspect_job.py`: 결과 전사문과 요약의 근거 타임스탬프를 사람이 확인

| 테스트 대상 함수 | 정상·경계 입력 | 잘못된 입력/예상 예외 | Mock/Fake | 자동 통과 기준 | 수동 검증 | 계획된 실행 명령 |
|---|---|---|---|---|---|---|
| `create_job` | YouTube URL, MP4, WAV; 빈 옵션 | 잘못된 URL, 없는 경로, 디렉터리 경로 → `InputSourceError` | 임시 DB | 상태가 `queued`, URL/경로가 정규화됨 | UI에서 링크/파일명이 맞는지 확인 | `pytest tests/unit/test_jobs.py -q` |
| `acquire_source_audio` | 지원 YouTube URL, 로컬 WAV | 비지원 URL, 획득 실패 → `SourceAcquisitionError` | URL source fake, 다운로드 도구 fake | 작업 폴더에 오디오만 남고 원본 다운로드는 0개 | 실제 권한 있는 영상에서 음성만 처리되는지 확인 | `pytest tests/unit/test_sources.py -q` |
| `extract_audio` | 짧은 MP4; 오디오만 있는 WAV | 손상 파일 → `MediaExtractionError` | FFmpeg fake runner | 표준 샘플레이트와 허용 길이 | 실제 영상에서 음성 누락 여부 | `pytest tests/unit/test_media.py -q` |
| `transcribe_audio` | 한국어/영어 혼합 짧은 음성; 무음 | 지원하지 않는 엔진 결과 → `TranscriptionError` | STT fake | 구간 시간 단조 증가, 빈 텍스트 제거 | 실제 음성과 전사 대조 | `pytest tests/unit/test_transcription.py -q` |
| `protect_tokens` | `8만 마일`, `JFK`, 도시명; 인접 토큰 | 중첩된 자리표시자 → `ProtectionError` | 없음 | 보호값 100% 복원 가능 | 사용자 용어집의 표기가 보존되는지 확인 | `pytest tests/unit/test_protection.py -q` |
| `normalize_rules` | 공백 없음, 중복 공백, 기호 앞 공백 | 자리표시자 손실 → `InvariantError` | Kiwi adapter fake | 비공백 문자/자리표시자 동일, 공백 규칙 통과 | 자연스러운 띄어쓰기 30문장 표본 점검 | `pytest tests/unit/test_text_rules.py -q` |
| `correct_chunk` | 1~10분 인접 문맥; 혼합 언어 | 비JSON, 상한 초과 → `ModelResponseError` | Qwen fake server | JSON 스키마 통과, 지시 밖 필드 없음 | Qwen 결과의 조사/어순 자연스러움 | `pytest tests/unit/test_correction.py -q` |
| `validate_revision` | 공백 교정, 보호값 동일 | 숫자/고유명사 변경 → `ReviewRequired` | 없음 | 위험 변경 자동 승인 0건 | 보류 항목이 UI에 잘 드러나는지 확인 | `pytest tests/unit/test_validation.py -q` |
| `assemble_transcript` | 연속/비연속 시간 구간 | 중복 ID, 역순 시간 → `TranscriptAssemblyError` | 파일 저장 fake | 색인에서 모든 구간 조회 가능 | 타임스탬프 클릭이 올바른 영상 위치인지 확인 | `pytest tests/unit/test_transcript.py -q` |
| `summarize_transcript` | 짧은 전사문, 긴 다중 챕터 전사문 | 빈 전사문 → `EmptyTranscriptError` | Qwen fake server | 두 문장 이하, 근거 ID 존재, 형식 통과 | 새 사실/숫자 왜곡이 없는지 검토 | `pytest tests/unit/test_summarization.py -q` |
| `cleanup_artifacts` | 보존/삭제 정책 각각 | 작업 폴더 밖 경로 → `UnsafePathError` | 임시 파일 시스템 | 작업 폴더 밖 파일 0개 삭제 | 사용자 설정에 따라 결과가 남는지 확인 | `pytest tests/unit/test_storage.py -q` |
| `install_models` | 선언된 Qwen/STT 모델; 이미 존재하는 모델 | 저장공간 부족, 체크섬 불일치 → `ModelInstallError` | 다운로드 fake, 파일 시스템 fake | Git 저장소 밖의 `MODEL_HOME`에만 설치, 선언 체크섬 일치 | 설치 명령이 README대로 동작하는지 확인 | `pytest tests/unit/test_model_setup.py -q` |
| `check_repository_clean` | 소스·문서·작은 fixture | `*.gguf`, 영상, 오디오, 임계값 초과 추적 파일 → `RepositoryPolicyError` | Git status/list-files fake | 금지 파일을 하나라도 발견하면 비정상 종료 | 실제 커밋 직전 검사 결과 확인 | `pytest tests/unit/test_repository_policy.py -q` |

통합 통과 기준은 다음과 같다.

- 고정 테스트 세트에서 보호 토큰 보존율 100%
- 위험 범주 변경의 자동 확정 0건
- 최종 요약은 문장 분리 기준 2문장 이하
- 모든 요약 문장에 근거 구간 ID가 하나 이상 존재
- 성공·실패·취소·강제 종료 뒤 작업 전용 폴더 밖의 파일 삭제 0건, 기본 정책에서 작업 전용 폴더 안의 원본 영상/임시 오디오 잔존 0건
- 커밋 전 검사에서 모델 가중치, 사용자 미디어, 작업 데이터, 비밀 설정 파일의 추적 0건
- 한 시간 영상 처리 목표 시간과 디스크 사용량은 대상 PC에서 측정해 별도 기준으로 확정

## 9. 위험 요소와 사용자 결정이 필요한 항목

| 항목 | 위험/영향 | 필요한 결정 |
|---|---|---|
| 맞춤법 기대치 | LLM과 로컬 도구만으로 네이버 검사기와 동일한 결과를 보장할 수 없다. | “정확한 교정”보다 “위험 변경을 보류하는 신뢰성”을 우선할지 결정 |
| 모델 품질/용량 | Q5는 약 6GB이며 긴 컨텍스트와 동시 실행은 메모리를 더 사용한다. | 최소 지원 PC의 GPU VRAM/RAM과 Q4/Q5 기본값 결정 |
| STT 품질 | 음질·화자 겹침·고유명사 오류가 교정 단계까지 전파된다. | 한국어 전용/다국어 혼합 영상에서 사용할 STT 모델과 처리 시간 목표 결정 |
| YouTube 소스 | 플랫폼 UI·기술·약관 변화와 저작권 이슈가 URL 처리 성공률 및 배포 가능성에 영향을 준다. | 지원할 사이트 범위와 사용자의 권한 확인 방식 결정 |
| 개인정보 | 영상·음성·전사문은 민감할 수 있다. | 기본 보관 기간, 임시 오디오 자동 삭제, 결과 암호화 필요 여부 결정 |
| 고유명사 | 사전이 없으면 올바른 이름도 오인식될 수 있다. | 사용자 용어집 UI와 채널별 용어집을 제공할지 결정 |
| 라이선스 | 모델·런타임·사전 라이선스가 배포 방식에 영향을 준다. | 상용 배포 여부와 법무 검토 범위 결정 |
| 요약 신뢰 | 두 문장 제약은 핵심 정보를 누락시킬 수 있다. | “요약만” 또는 “핵심 요약 + 챕터별 요약”을 함께 제공할지 결정 |

## 10. GitHub 저장소와 로컬 모델 배포 설계

### 원칙

- 프로젝트 이름과 목표 원격 저장소 이름은 `Sodam`으로 둔다. 목표 원격은 `https://github.com/SaDubu/Sodam.git`이며, 이 문서는 GitHub에 저장소를 만들거나 원격을 등록하지 않는다.
- 표준 Git 작업 디렉터리는 `D:\AI-Legion\Sodam`으로 둔다. 실제 clone은 상위 폴더 `D:\AI-Legion`에서 수행해 `D:\AI-Legion\Sodam\Sodam`처럼 중첩된 저장소가 생기지 않게 한다.
- Git에는 소스, 문서, 테스트용 소형 fixture, 모델 선언 파일만 넣는다. Qwen/Whisper 가중치, 양자화 파일, 사용자 영상·오디오, 전사 결과, 로그, API 토큰은 넣지 않는다.
- 모델은 저장소 밖의 `D:\AI-Legion\Sodam-models`를 기본 `MODEL_HOME`으로 사용한다. 작업 데이터와 임시 미디어는 `D:\AI-Legion\Sodam-data`에 둔다. 프로젝트 폴더나 Git worktree를 모델/작업 데이터 저장소로 쓰지 않는다.
- `.gitignore`은 실수 방지용 1차 장치일 뿐이다. 강제 추가를 포함한 실수를 막기 위해 커밋 훅과 CI가 동일한 저장소 검사 도구를 실행한다.
- Git LFS는 모델 파일을 우회해 올리는 수단으로 사용하지 않는다.

### 추적/비추적 경계

| Git 추적 | Git 미추적(로컬 전용) |
|---|---|
| 소스 코드, 테스트, 문서, `.gitignore`, `.gitattributes`, `models/manifest.json`, 설치 스크립트 | `*.gguf`, `*.safetensors`, `*.bin`, `*.pt`, `*.onnx`, 모델 런타임 캐시 |
| 모델 ID, 양자화 프로필, 출처 URL, 버전, SHA-256, 라이선스 고지 | `data/jobs/`, `tmp/jobs/`, 내려받은 영상, 추출 오디오, STT 중간 산출물 |
| 재현 가능한 설치/실행 명령 | 사용자 전사문, 요약, 용어집, 로컬 설정, 인증 토큰, 로그 |

### 표준 로컬 디렉터리 레이아웃

```text
D:\AI-Legion\
├─ Sodam\                 # Git worktree: clone, pull, commit, push 대상
├─ Sodam-models\          # Qwen/Whisper 등 대용량 모델: Git 비추적
└─ Sodam-data\
   ├─ jobs\               # 보존하도록 선택한 전사문·요약
   └─ tmp\                # URL 획득 영상/오디오 등 즉시 정리 대상
```

`Sodam-models`와 `Sodam-data`는 `Sodam` Git 작업 트리 밖에 있으므로, `.gitignore`에 의존하지 않고도 모델과 사용자 데이터가 커밋 대상이 되지 않는다. 설치 스크립트는 이 경로들을 명시적으로 받거나 기본값으로 사용하며, 다른 드라이브/경로를 선택했을 때도 Git worktree 내부 경로는 거부한다.

### 모델 선언과 설치 흐름

`models/manifest.json`은 다음 정보만 갖는다.

- 프로필 이름: `standard` 또는 `quality`
- Qwen3 8B의 런타임별 모델 ID와 양자화 유형
- STT 모델 ID
- 공식 또는 승인된 배포 출처 URL, 버전, SHA-256, 라이선스 정보
- 필요 디스크 공간과 최소 메모리 안내

`scripts/setup-models.ps1`은 manifest만 읽어 모델을 `MODEL_HOME`으로 내려받고, 체크섬 검증이 끝난 파일만 활성화한다. 중단되거나 검증에 실패한 부분 파일은 재시도 전 삭제한다. 이 스크립트는 Git 작업 디렉터리에 모델을 쓰면 즉시 실패해야 한다.

README에는 다음처럼 소스와 모델 설치를 분리한 명령을 안내한다. 실제 모델 출처와 프로필은 manifest 확정 뒤 고정한다.

```powershell
Set-Location D:\AI-Legion
git clone https://github.com/SaDubu/Sodam.git Sodam
Set-Location D:\AI-Legion\Sodam
./scripts/setup-models.ps1 -Profile standard
./scripts/run-local.ps1
```

사용자는 `quality` 프로필을 선택해 더 큰 Qwen 양자화 모델을 설치할 수 있고, 모델을 제거할 때는 전용 정리 명령만 사용한다. `git clone`, `git pull`, `git commit`, `git push`는 모델 파일을 내려받거나 올리지 않는다.

### Git 운영 절차

- 최초 준비: 원격 `SaDubu/Sodam`이 만들어진 뒤에만 `D:\AI-Legion`에서 clone한다.
- 작업 시작: `D:\AI-Legion\Sodam`에서 `git status`를 확인하고 `git pull --ff-only`를 실행한다. fast-forward가 불가능하면 사용자가 충돌 해결 방향을 확인한다.
- 작업 종료: 저장소 검사 도구가 통과한 소스·문서·테스트 변경만 stage한다. 모델, `Sodam-data`, 임시 미디어를 stage하지 않는다.
- commit/push: 사용자의 별도 명시 승인 후에만 실행한다. push 전에는 다시 `git status`, 저장소 검사, 대상 브랜치/원격 URL을 확인한다.

### 커밋·푸시 보호선

1. `.gitignore`에서 모델 확장자, 영상/오디오 확장자, 작업 폴더, 사용자 설정과 비밀 파일을 제외한다.
2. 커밋 전 훅은 `scripts/check-repository-clean.ps1`을 실행한다.
3. 검사 도구는 추적 예정 파일과 이미 추적된 파일을 모두 검사해 다음을 차단한다.
   - 모델 가중치 확장자
   - 영상·음성 확장자
   - 사용자 작업 데이터와 로그
   - 허용 목록 밖의 20MB 초과 파일
   - API 키·토큰으로 보이는 설정 파일
4. CI에서도 같은 검사를 재실행한다. 로컬 훅을 우회해도 원격 병합 전 차단된다.
5. 실패 시 파일 경로와 차단 사유만 출력하고 자동 삭제는 하지 않는다. 사용자가 해당 파일을 Git 인덱스에서 제거한 뒤 다시 검사한다.

### 검증 시나리오

- Qwen GGUF 파일을 강제로 stage하면 커밋 전 검사가 실패한다.
- 작업 중 생성된 MP4/WAV가 작업 폴더에 있어도 Git 상태에는 나타나지 않는다.
- 모델 설치 후 `git status`가 소스 변경 없이 깨끗하다.
- URL 처리 성공·실패·취소 뒤에도 `MODEL_HOME` 외 모델 파일과 작업 전용 폴더 외 임시 미디어가 남지 않는다.
- 새 PC에서 clone 후 README의 설치 명령만으로 모델을 별도 경로에 설치하고, 저장소에 대용량 파일이 생기지 않는다.

## 승인 전 결론

이 설계는 기술적으로 실현 가능하다. 가장 중요한 제품 판단은 맞춤법 정답률을 과장하기보다, 원문 보존·변경 이력·보호 토큰·검수 큐로 사용자가 결과를 신뢰할 수 있게 하는 것이다. YouTube 링크 처리에서는 원본 영상과 임시 오디오를 기본적으로 남기지 않는 보관 정책을 우선한다. 구현을 진행하려면 위 미확정 항목, 특히 최소 지원 PC, 상용 배포 여부, 지원할 외부 소스 범위를 먼저 확정해야 한다.
