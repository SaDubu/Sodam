# Sodam 로컬 영상 전사·요약·소개글 생성 데스크톱 앱 설계안

> 상태: 구현 승인 전 상세 설계 v2
>
> 이 문서는 기존 설계를 전체 대체한다. 현재의 전사·교정·근거 연결 요약 기능은 유지하며, 영상 소개글 생성 기능과 설치·진행률 UI를 추가한다. 사용자 승인 전에는 제품 코드, 테스트 코드, 설정 파일, 외부 다운로드를 변경하지 않는다.

## 1. 프로젝트 목표와 해결하려는 문제

Sodam은 YouTube URL 또는 로컬 미디어를 로컬 PC에서 처리하여 다음 결과를 만드는 데스크톱 프로그램이다.

1. 시간 구간과 원문이 보존된 전사문
2. 보호값과 변경 근거를 확인할 수 있는 교정 전사문
3. 전사문에 근거한 기존의 간결한 요약
4. 시청자의 관심을 끌도록 작성하되 사실을 꾸며내지 않는 영상 소개글
5. 처리 단계, 진행률, 경과 시간, 예상 남은 시간, 오류와 재시도 상태를 보여 주는 UI

이번 변경의 핵심은 요약을 소개글로 바꾸는 것이 아니다. 두 결과는 목적과 품질 기준이 다르므로 독립 기능으로 유지한다.

- 요약: 내용을 빠르고 정확하게 파악하기 위한 사실 중심 결과
- 영상 소개글: 영상의 주제와 실제 하이라이트를 활용해 시청 동기를 만드는 홍보 문안
- 둘 다: 한 번의 전사·교정 결과로 두 산출물을 함께 생성

현재 문제는 실제 파이프라인이 실행되더라도 어느 단계를 수행 중인지, 얼마나 남았는지 알기 어렵고, 설치·모델 준비·실행 UI가 서로 분리되어 있다는 점이다. 또한 기존 최종 요약 프롬프트 일부가 소개 문안 역할까지 겸하여 요약과 소개글의 계약이 섞여 있다. 이를 분리하고 측정 가능한 진행 이벤트를 전 구간에 연결한다.

## 2. 기능 범위와 구현하지 않을 범위

### 2.1 포함 범위

- 로컬 영상·오디오 파일과 지원되는 YouTube URL 입력
- FFmpeg 표준 오디오 추출
- faster-whisper 기반 로컬 STT와 타임스탬프
- 보호 토큰, 제한적 규칙 정규화, Qwen 교정, 검토 큐
- 기존 근거 연결 요약 기능의 유지와 회귀 검증
- 신규 영상 소개글 생성과 근거 검증
- 출력 모드 선택: 요약, 영상 소개글, 둘 다
- 설치 전 검사, 의존성·모델 준비, 진행률 표시, 중단 후 재시도
- 처리 단계·진행률·경과 시간·예상 남은 시간·로그·취소 UI
- 결과 화면의 전사문, 요약, 소개글, 검토 큐 탭
- Windows용 실행 파일과 설치 패키지
- macOS와 Linux를 위한 동일 소스의 운영체제별 빌드 정의
- 설정에서 STT 모델과 Ollama 모델 태그 선택
- 오프라인 실행을 기본값으로 유지

### 2.2 제외 범위

- 전사문이나 사용자 미디어를 클라우드로 보내는 기능
- 사실 근거가 없는 클릭베이트 문구 생성
- 영상 썸네일·제목·태그·자막 영상의 자동 게시
- YouTube 계정 로그인이나 채널 업로드
- 모든 운영체제 실행 파일을 Windows 한 대에서 교차 빌드
- Ollama, FFmpeg 등 제3자 프로그램의 라이선스 동의 우회
- 관리자 권한을 몰래 획득하거나 보안 설정을 변경하는 설치
- 모델 재학습 또는 파인튜닝
- 정확한 완료 시각을 보장하는 가짜 ETA
- 기존 Summary 계약과 summary.json을 소개글 형식으로 변경

## 3. 사용자 경험과 출력 모드

### 3.1 최초 실행

배포 사용자는 운영체제에 맞는 설치 패키지를 실행한다. 개발자·복구 사용자를 위해 저장소 루트의 setup.py를 얇은 부트스트랩 진입점으로 제공한다.

최초 실행 흐름은 다음과 같다.

    운영체제·CPU·RAM·GPU·디스크 검사
      -> Python 런타임/FFmpeg/Ollama 상태 검사
      -> STT 모델과 Qwen 모델 프로필 선택
      -> 다운로드 크기·예상 디스크 사용량 표시 및 사용자 동의
      -> 의존성 및 모델 다운로드
      -> 해시·버전·로컬 API 검사
      -> 앱 실행 파일 또는 설치 결과 확인
      -> Sodam 실행

setup.py는 Python 패키징의 전통적인 setuptools 스크립트로 사용하지 않는다. bootstrap 명령만 해석하는 프로젝트 전용 실행기다. 일반 배포는 미리 빌드된 OS별 앱을 제공하고, setup.py는 개발 모드 빌드나 설치 복구를 담당한다. 소스에서 빌드하려면 Rust·Node.js 등 개발 도구가 필요하므로 일반 사용자 경로와 분리한다.

### 3.2 메인 화면

메인 화면은 다음 입력과 선택을 제공한다.

- 로컬 미디어 선택 또는 URL 입력
- 출력 모드
  - 요약만
  - 영상 소개글만
  - 둘 다
- 모델 프로필
  - 품질 우선: qwen3.6:35b-a3b-agent-64k
  - 호환성 우선: 검증된 소형 Qwen 태그
- 임시 파일 보관 정책
- 실행, 취소, 재시도

### 3.3 진행 화면

진행 화면은 최소한 다음 정보를 보여 준다.

- 현재 단계 이름과 설명
- 전체 진행률 또는 측정 중 표시
- 현재 단계 진행률
- 완료 단위와 전체 단위
- 경과 시간
- 예상 남은 시간 또는 계산 중
- 현재 처리 중인 파일·구간·배치의 안전한 표시
- 접을 수 있는 상세 로그
- 취소 버튼
- 실패 시 원인, 다시 시도, 진단 정보 복사

### 3.4 결과 화면

- 전사문 탭: 시간 구간별 텍스트와 전체 글
- 검토 탭: 위험 변경과 승인 상태
- 요약 탭: 기존 Summary 결과와 근거 구간
- 소개글 탭: 제목형 한 줄, 본문, 선택된 하이라이트, 근거 구간
- 파일 위치 열기와 결과 복사
- 둘 다 선택했을 때 두 결과를 독립적으로 다시 생성

## 4. 전체 구조와 데이터 흐름

### 4.1 제품 데이터 흐름

    [Tauri 데스크톱 UI]
             |
             v
    [작업 명령 및 이벤트 브리지]
             |
             +--> [환경 진단·설치 관리자]
             |
             v
    [PipelineApplication + ProgressSink + CancellationToken]
             |
             +--> 입력 검증·소스 획득
             +--> FFmpeg 오디오 추출
             +--> faster-whisper 전사
             +--> 보호·규칙 정규화·Qwen 교정
             +--> 검토 큐·승인 결과 조립
             |
             +--> 요약 모드 ----------> 기존 Summary
             |
             +--> 소개글 모드 --------> 신규 VideoIntroduction
             |
             v
    [영속 저장소: transcript / summary / introduction / progress / metadata]
             |
             v
    [UI 완료 이벤트와 결과 탭]

요약과 소개글은 전사·교정까지의 공통 결과를 재사용하지만 생성기, 프롬프트, 검증기, 저장 파일을 공유하지 않는다. 한 생성기가 실패해도 정책에 따라 다른 생성 결과를 보존하고 부분 실패 상태를 표시한다.

### 4.2 설치 데이터 흐름

    [setup.py 또는 최초 실행 마법사]
             |
             v
    [SystemProbe]
             |
             v
    [InstallationPlan]
             |
             +--> OS별 필수 도구 설치/탐색
             +--> STT 모델 다운로드·해시 검증
             +--> Ollama 실행 확인
             +--> Ollama /api/pull 스트림
             +--> 앱 바이너리 확인 또는 개발 모드 빌드
             |
             v
    [InstallationReceipt + RuntimeProfile]

설치 단계도 제품 처리와 동일한 ProgressEvent 형식을 사용한다. Ollama pull API가 제공하는 스트림 진행 상태를 그대로 단위 값으로 변환한다.

### 4.3 진행률 단계

ProgressStage는 다음의 안정된 식별자를 가진다.

- environment_check
- dependency_install
- model_download
- source_validation
- source_acquisition
- audio_extraction
- transcription
- text_protection
- rule_normalization
- correction
- review_validation
- transcript_assembly
- summarization
- introduction
- persistence
- cleanup
- completed
- failed
- cancelled

표시 문자열은 UI 번역 자원에서 관리하며 백엔드 식별자와 분리한다.

### 4.4 진행률 계산 원칙

- 전체 진행률은 고정 숫자를 임의로 증가시키지 않는다.
- 전체 단위를 알 수 없는 단계는 indeterminate로 표시한다.
- 소스 길이를 얻은 뒤 전사는 마지막 완료 세그먼트 시간 나누기 오디오 길이로 계산한다.
- 교정은 완료 청크 수 나누기 전체 청크 수로 계산한다.
- 요약은 완료 배치와 최종 합성 호출을 각각 단위로 계산한다.
- 소개글은 하이라이트 추출, 생성, 검증의 세 단위로 계산한다.
- 모델 다운로드는 수신 바이트와 전체 바이트가 있을 때만 백분율을 표시한다.
- 전체 진행률은 단계 가중치와 측정된 단계 진행률로 계산하고 뒤로 감소하지 않는다.
- ETA는 최근 처리량의 이동 평균과 남은 단위가 모두 있을 때만 계산한다.
- 표본이 부족하거나 단계 전환 직후에는 ETA를 null로 보내고 UI에는 계산 중으로 표시한다.
- 대형 모델의 첫 로드 시간은 별도 warming_up 메시지로 표현한다.
- 취소 요청은 can_cancel이 true인 단계에서만 받으며 안전한 정리 후 cancelled로 끝낸다.

## 5. 생성·수정이 필요한 파일과 책임

아래 목록은 승인 후의 예상 범위다. 실제 구현 작업마다 Statement_of_Functions.md에 더 좁은 범위를 다시 명시한다.

### 5.1 백엔드

- backend/contracts.py
  - OutputMode, ProgressStage, ProgressEvent, VideoIntroduction, IntroductionOptions, 설치 결과 계약 추가
  - 기존 Summary와 Job 계약 보존
- backend/progress.py
  - 진행 이벤트 검증, 단계 가중치, 단조 진행률, ETA 계산
- backend/introduction.py
  - 하이라이트 추출, 소개글 프롬프트, JSON 응답 검증, 근거 연결
- backend/summarization.py
  - 기존 요약 전용 프롬프트로 복원·고정
  - 소개글 문체 지시 제거
- backend/main.py
  - 출력 모드 분기, 진행 이벤트 발행, 부분 결과 처리
- backend/local_adapters.py
  - 모델 태그와 생성 옵션을 RuntimeProfile에서 주입
  - Ollama 구조화 출력 스키마와 로컬 엔드포인트 제한
- backend/persistence.py
  - introduction.json, progress.jsonl, 설치 영수증 저장
- backend/installer.py
  - 시스템 검사, 설치 계획, 다운로드 재개, 검증, 복구
- backend/runtime_profile.py
  - OS별 경로와 모델 선택을 검증된 설정으로 읽기

### 5.2 CLI와 부트스트랩

- setup.py
  - bootstrap 진입점, 설치 마법사 호출, 개발 모드 빌드 명령
- tools/run_local.py
  - output-mode, qwen-model, progress-format 옵션
  - stdout에는 최종 결과 JSON, stderr에는 사람용 진행률
- tools/doctor.py
  - 모델 태그, Ollama API, FFmpeg, 디스크, GPU 적합성 진단
- scripts/setup-models.ps1
  - Windows 설치 관리자 내부 도구로 재사용하되 UI 이벤트와 영수증 계약에 맞춤
- config/runtime-profile.json 또는 동등한 사용자 설정
  - 하드코딩된 Python·모델·도구 경로 제거

### 5.3 데스크톱

- apps/desktop/src/state.ts
  - 상세 진행 이벤트, 출력 모드, 소개글 결과, 설치 상태 reducer
- apps/desktop/src/main.ts
  - 입력 폼, 진행 화면, 결과 탭, 취소와 재시도
- apps/desktop/src/style.css
  - 접근 가능한 진행 표시와 반응형 레이아웃
- apps/desktop/src-tauri/src/lib.rs
  - 하드코딩 Python 경로 제거
  - 백엔드 프로세스 실행, JSONL 이벤트 전달, 취소, 결과 조회
- apps/desktop/src-tauri/tauri.conf.json
  - OS별 번들·설치 메타데이터
- apps/desktop/tests
  - reducer, IPC, 설치/처리 UI 회귀 테스트

### 5.4 테스트와 문서

- tests/unit/test_progress.py
- tests/unit/test_introduction.py
- tests/unit/test_installer.py
- tests/unit/test_runtime_profile.py
- tests/integration/test_output_modes.py
- tests/integration/test_progress_pipeline.py
- tests/e2e 또는 데스크톱 동등 테스트
- docs/ai/04-implementation-order.md
- docs/ai/05-productization-roadmap.md
- docs/ai/06-runtime-profile.md
- README.md와 apps/desktop/README.md

## 6. 라이브러리·프레임워크·외부 도구

### 6.1 유지할 기술

- Python 3.12: 현재 백엔드와 테스트 자산 재사용
- Tauri 2 + TypeScript: 가벼운 OS별 데스크톱 번들, Rust IPC 경계
- faster-whisper: 로컬 STT
- FFmpeg: 표준 오디오 추출
- yt-dlp: 사용 권한이 있는 URL 미디어 획득
- Ollama 로컬 API: Qwen 모델 실행
- pytest: 단위·통합 테스트

### 6.2 Qwen 모델 정책

이 PC의 실제 Ollama 목록에는 다음 두 태그가 모두 존재한다.

- qwen3.6:35b-a3b-agent-64k, Q4_K_M, 약 23GB
- qwen3.6:35b-a3b-agent-64k, 약 23GB

콘텐츠 교정·요약·소개글 기본 품질 프로필은 qwen3.6:35b-a3b-agent-64k를 사용한다. Hermes가 같은 태그를 사용하더라도 Sodam이 Hermes 설정을 읽는 것은 아니다. Sodam은 로컬 Ollama API 요청의 model 필드에 정확한 태그를 넣어 같은 Ollama 모델을 선택한다.

현재 코드 변경의 개념적 형태는 다음과 같다.

    LocalOllamaRuntime(
        model=runtime_profile.qwen_model,
        endpoint="http://127.0.0.1:11434/api/chat"
    )

요청 본문은 역할에 따라 다음 정책을 쓴다.

- model: qwen3.6:35b-a3b-agent-64k
- stream: false
- think: false
- format: 문자열 json이 아니라 가능하면 작업별 JSON Schema
- options.temperature
  - 교정·요약: 0
  - 소개글: 낮은 값으로 시작하고 품질 시험 후 고정
- context 크기: 전체 256K를 무조건 예약하지 않고 작업에 필요한 상한만 설정

공식 Ollama 모델 페이지는 qwen3.6 계열이 thinking을 지원하고 35B 기본 배포가 약 23GB, 256K context임을 표시한다.
https://ollama.com/library/qwen3.6

Ollama 구조화 출력은 format에 JSON Schema를 제공할 수 있고 낮은 temperature를 권장한다.
https://docs.ollama.com/capabilities/structured-outputs

thinking 모델은 API의 think 필드로 추론 출력을 제어할 수 있다.
https://docs.ollama.com/capabilities/thinking

이 PC의 GPU VRAM보다 모델 파일이 크므로 일부 계층이 시스템 메모리로 오프로딩될 가능성이 있다. 기능 사용 가능 여부와 실제 속도는 별개다. 설치 마법사는 RAM·VRAM·디스크를 보여 주고, 첫 실행 벤치마크로 토큰 생성 속도와 예상 처리 시간을 기록한다. 성능이 낮으면 작은 호환 모델을 선택할 수 있어야 한다.

### 6.3 설치와 빌드 정책

- Ollama 모델 다운로드는 /api/pull의 스트림 진행 상태를 사용한다.
  https://docs.ollama.com/api/pull
- 모델 파일, 전사 결과, 미디어는 Git 저장소 밖의 데이터 루트에 둔다.
- 다운로드는 partial 파일 또는 제공 도구의 재개 기능을 사용한다.
- 완료 전 해시·크기·모델 조회 검사를 통과해야 한다.
- Windows는 NSIS 또는 MSI, macOS는 app/dmg, Linux는 AppImage/deb를 각 OS runner에서 빌드한다.
- 배포 앱은 가능한 한 백엔드 런타임을 sidecar로 묶어 시스템 Python 하드코딩을 제거한다.
- Ollama와 FFmpeg를 포함해 재배포할 수 없는 구성 요소는 공식 설치 경로를 안내하고 명시적 동의를 받는다.

## 7. 클래스·함수·인터페이스 계약

### 7.1 도메인 타입

OutputMode

- 값: summary, introduction, both
- 기존 요약 기본 동작의 호환성을 위해 CLI 기본값은 summary로 유지한다.
- 신규 UI는 사용자의 명시 선택을 저장하며 둘 다 선택을 쉽게 제공한다.

ProgressEvent

- 필드
  - operation_id: 비어 있지 않은 문자열
  - scope: setup 또는 job
  - stage: ProgressStage
  - stage_label: 사용자 표시 문자열
  - stage_progress: 0 이상 1 이하 또는 None
  - overall_progress: 0 이상 1 이하 또는 None
  - completed_units: 0 이상의 수 또는 None
  - total_units: completed_units 이상인 수 또는 None
  - elapsed_seconds: 0 이상의 유한수
  - eta_seconds: 0 이상의 유한수 또는 None
  - message: 사용자 안전 메시지
  - can_cancel: bool
  - sequence: 단조 증가 정수
  - timestamp: UTC ISO 8601
- 토큰, 전체 프롬프트, 민감한 로컬 경로를 기본 message에 포함하지 않는다.

VideoIntroduction

- title_hook: 영상 주제를 드러내는 한 줄
- body: 2~3문장의 소개글
- highlights: 원문에서 실제 확인된 브랜드·금액·등급·특징의 튜플
- evidence_segment_ids: 모든 사실 주장을 뒷받침하는 segment_id
- question_used: 물음표를 사용했는지
- call_to_action: body의 마지막 문장과 동일한 CTA
- 기존 Summary와 상속·대체 관계를 만들지 않는다.

PipelineResult

- 기존 job, transcript, review_queue, summary 필드를 유지한다.
- introduction 필드를 선택적으로 추가한다.
- output_mode에 따라 요구되는 결과만 필수로 검증한다.

### 7.2 진행률 인터페이스

ProgressSink.emit(event: ProgressEvent) -> None

- 입력: 검증 완료된 ProgressEvent
- 출력: 없음
- 예외: 잘못된 이벤트는 TypeError 또는 ValueError
- 부작용: 구현에 따라 UI 채널, stderr, JSONL 로그에 전달
- 사전 조건: 같은 operation_id에서 sequence가 증가
- 사후 조건: 제품 파이프라인 상태는 변경하지 않음
- 금지: sink 오류로 제품 결과를 훼손하는 것
- 테스트: RecordingProgressSink로 순서와 payload 검사

ProgressTracker.start_stage(stage, total_units=None, message="") -> ProgressEvent

- 입력: 유효한 단계, 선택적 전체 단위, 안전한 메시지
- 출력: 새 단계의 첫 이벤트
- 예외: 음수·NaN 단위는 ValueError
- 부작용: 내부 단계 시간과 sequence 갱신
- 사전 조건: terminal 단계 이후 호출 금지
- 사후 조건: 전체 진행률은 이전 값보다 작지 않음
- 테스트: 단계 전환, unknown total, terminal 호출 차단

ProgressTracker.advance(completed_units, message="") -> ProgressEvent

- 입력: 현재 단계의 누적 완료 단위
- 출력: 진행 이벤트
- 예외: 감소·초과·NaN은 ValueError
- 부작용: 이동 평균 처리량과 ETA 갱신
- 사후 조건: stage_progress와 overall_progress가 단조 비감소
- 테스트: 정상 증가, 0단위, 느린 표본, ETA null 조건

estimate_eta(samples, remaining_units) -> float | None

- 입력: 시간·완료 단위 표본, 남은 단위
- 출력: 초 단위 ETA 또는 None
- 예외: 구조가 잘못된 입력은 TypeError 또는 ValueError
- 부작용: 없음
- 사후 조건: 반환 시 유한하고 0 이상
- 테스트: 표본 부족, 0 처리량, 이상치, 정상 이동 평균

### 7.3 영상 소개글 인터페이스

extract_highlights(transcript: Transcript) -> tuple[Highlight, ...]

- 목적: 소개글에 사용할 수 있는 근거 있는 구체 요소 후보 생성
- 정상 입력: 조립된 비어 있지 않은 Transcript
- 출력: 원문 문자열과 segment_id를 가진 불변 후보
- 예외: 타입 오류는 TypeError, 빈 전사문은 IntroductionError
- 부작용: 없음
- 동작: 브랜드·가격·등급·고유 특징 후보를 원문에서 추출하고 중복 제거
- 금지: 원문에 없는 값을 추론해 생성
- 테스트: 브랜드, 원화·달러 금액, 객실 등급, 후보 없음, 반복 후보

build_introduction_prompt(transcript, highlights, options) -> str

- 목적: 모델에게 영상 소개글 역할과 사실 제약을 명확히 전달
- 입력: 전체 전사문이 아니라 검증된 계층형 근거 요약과 선택 후보
- 출력: 결정론적으로 구성된 프롬프트
- 예외: 잘못된 타입은 TypeError, 근거 ID 불일치는 IntroductionError
- 부작용: 없음
- 사전 조건: 모든 highlight가 입력 근거에 존재
- 사후 조건: 출력 JSON Schema와 금지 규칙 포함
- 테스트: 같은 입력의 동일 프롬프트, 광고 구간 제외, 후보 없음

generate_video_introduction(transcript, runtime, options) -> VideoIntroduction

- 목적: 시청 동기를 만드는 사실 기반 한국어 소개글 생성
- 입력: 승인·복원된 Transcript, QwenRuntime, IntroductionOptions
- 출력: 새 VideoIntroduction
- 예외
  - 입력 계약 위반: TypeError 또는 ValueError
  - 모델 호출 실패·비문자 응답·JSON 위반: ModelResponseError
  - 근거·문체·구조 위반: IntroductionError
- 부작용: 주입된 runtime.complete 또는 구조화 chat 정확히 필요한 횟수만 호출
- 내부 순서
  1. 전사문 전 범위에서 주제와 근거 후보 생성
  2. 스폰서·광고 구간을 주제 근거에서 기본 제외
  3. 원문에 존재하는 하이라이트 선택
  4. 엄격한 JSON Schema로 소개글 생성
  5. title_hook, body, CTA, 물음표, 근거 ID 검증
  6. 사실 문자열을 원문 근거와 대조
- 사후 조건
  - 원문에 브랜드·금액·등급 후보가 있으면 최소 하나를 자연스럽게 사용
  - 후보가 없으면 해당 값을 꾸며내지 않음
  - 질문은 실제 내용의 궁금증을 만들며 결과를 거짓으로 은폐하지 않음
  - 마지막 문장은 영상에서 확인할 가치가 있는 구체 이유를 담은 CTA
  - 과장 수식어는 근거 없이 단독 사용하지 않음
- 테스트: RecordingRuntime, malformed JSON, 환각 하이라이트, 근거 누락, CTA 누락, 물음표 정책

validate_introduction(introduction, transcript, options) -> None

- 입력: 생성 결과와 원전
- 출력: 없음
- 예외: 불일치는 IntroductionError
- 부작용: 없음
- 검증
  - 모든 evidence_segment_id가 존재
  - 모든 highlight가 해당 근거 텍스트에 존재
  - title_hook 길이와 개행 제한
  - body 문장 수
  - call_to_action이 마지막 문장
  - 원문에 없는 금액·브랜드·등급 삽입 거부
  - 지나치게 한 초기 구간에만 근거가 몰리지 않았는지 검사
- 테스트: 정상, unknown ID, invented price, early-only evidence, duplicated CTA

기존 summarize_reviewed_transcript 함수

- 기존 Summary 반환 계약과 최대 두 문장·근거 ID 검증을 유지한다.
- 소개글 문체, CTA, curiosity gap 지시는 제거한다.
- 저장 파일과 호출자 호환성을 보존한다.
- 신규 회귀 테스트로 과장 문구나 필수 물음표가 요약에 강제되지 않음을 확인한다.

### 7.4 설치 인터페이스

probe_system() -> SystemProfile

- 입력: 없음
- 출력: OS, 아키텍처, CPU, RAM, GPU, VRAM, 디스크, 도구 버전
- 예외: 일부 정보를 읽지 못해도 전체 실패하지 않고 unavailable로 기록
- 부작용: 읽기 전용 시스템 조회
- 테스트: FakeSystemProbe로 Windows, macOS, Linux, GPU 없음

plan_installation(system, requested_profile) -> InstallationPlan

- 입력: 시스템 프로필과 사용자 선택
- 출력: 필요한 작업, 다운로드 크기, 디스크 요구량, 경고
- 예외: 지원하지 않는 OS·아키텍처는 InstallationError
- 부작용: 없음
- 사후 조건: 실행 전 모든 외부 다운로드가 계획에 명시
- 테스트: 충분·부족 디스크, 이미 설치됨, 23GB 모델 선택

execute_installation(plan, sink, cancellation) -> InstallationReceipt

- 입력: 검증된 계획, ProgressSink, CancellationToken
- 출력: 설치된 버전·모델 digest·경로를 가진 영수증
- 예외: 다운로드·검증·권한 오류는 InstallationError
- 부작용: 사용자 동의 범위에서 다운로드·설치·설정 저장
- 사전 조건: 사용자 승인과 충분한 공간
- 사후 조건: 성공 시 doctor 검사 통과, 실패 시 partial 상태가 식별 가능
- 테스트: FakeDownloader, 체크섬 실패, 취소, 재개, 기존 파일 보호
- 수동 검증: 깨끗한 Windows VM에서 최초 설치와 재설치

build_desktop(target_os, mode) -> BuildArtifact

- 입력: 대상 OS와 release 또는 development
- 출력: 현재 OS에서 생성된 번들 경로·해시
- 예외: 다른 OS 교차 빌드 요청은 BuildError
- 부작용: 빌드 디렉터리에만 산출물 생성
- 테스트: 명령 계획 단위 테스트, CI OS별 smoke test

### 7.5 파이프라인과 UI 브리지

PipelineApplication.run(job, output_mode, progress_sink, cancellation_requested) -> PipelineResult

- 기존 run 계약을 호환 가능한 방식으로 확장한다.
- summary 모드는 기존 요약만 생성한다.
- introduction 모드는 신규 소개글만 생성한다.
- both 모드는 공통 전사 결과로 두 생성기를 순차 실행한다.
- 각 상태 전환 전에 progress 이벤트를 보낸다.
- 모델 두 개를 동시에 GPU에 올리지 않는다.
- 취소 시 정리 정책을 실행하고 마지막 cancelled 이벤트를 보낸다.
- 필수 결과 하나가 실패하면 실패 원인을 보존하되 이미 검증된 다른 결과를 삭제하지 않는다.

Tauri start_job(request) -> operation_id

- 입력: 소스, OutputMode, 모델 프로필, 정리 정책
- 출력: 즉시 operation_id
- 예외: 요청 스키마 오류
- 부작용: 백그라운드 sidecar 프로세스 시작
- UI 스레드를 차단하지 않는다.

Tauri progress event

- Rust 브리지는 백엔드 JSONL 한 줄을 한 ProgressEvent로 검증한 뒤 UI에 전달한다.
- 파싱 불가 stdout과 stderr 원문을 그대로 사용자에게 노출하지 않는다.
- 프로세스 exit code와 terminal 이벤트 불일치를 실패로 처리한다.

Tauri cancel_job(operation_id) -> cancellation acknowledgement

- 정확한 자식 프로세스·작업만 취소한다.
- 강제 종료는 정상 취소 유예 시간이 지난 뒤에만 사용한다.
- 작업 폴더 밖 파일은 삭제하지 않는다.

## 8. 영상 소개글 프롬프트 계약

프롬프트는 자유로운 부탁이 아니라 역할·근거·출력 스키마·금지 조건을 함께 제공한다.

### 8.1 의도

- 영상을 보지 않은 사람이 주제를 한 번에 이해
- 실제 하이라이트 때문에 다음 내용이 궁금해짐
- 영상에서 확인할 구체적 보상을 마지막 문장에 제시
- 정보 요약처럼 결론을 전부 나열하지 않음
- 허위·과장·전사문 밖 사실을 추가하지 않음

### 8.2 지시 구조

1. 역할
   - 한국어 영상 소개 문안을 작성하는 편집자
2. 근거
   - 전체 전사문을 대표하는 검증된 구간별 요약
   - 각 사실의 segment_id
   - 원문에서 추출된 highlight 후보
3. 제목형 한 줄
   - 영상의 중심 주제를 구체적으로 표현
   - 의미 없는 최고, 압도적, 놀라운의 남용 금지
4. 본문
   - 2~3문장
   - 구체 하이라이트 최소 하나 사용 가능할 때 사용
   - 자연스러운 curiosity gap
   - 질문 문장은 옵션에 따라 0~1개
5. CTA
   - 마지막 문장은 영상에서 확인할 실제 결과·비교·반전·경험을 지목
6. 금지
   - 원문에 없는 브랜드, 금액, 등급, 수상 이력
   - 모든 사실의 결론을 첫 문장에 소진
   - 광고·협찬 멘트를 영상 전체 주제로 오인
   - JSON 밖 텍스트
7. 출력
   - title_hook, body, highlights, evidence_segment_ids, question_used, call_to_action

### 8.3 품질 예시의 사용 원칙

사용자가 제시한 문구는 고정 문장 템플릿으로 복사하지 않는다. 영상마다 동일한 과연 어떤 모습일까 또는 확인해 보세요가 반복되면 품질이 낮아진다. 다음 불변식만 유지한다.

- 구체성: 실제 브랜드·가격·등급·특징
- 긴장감: 핵심 결과를 모두 선공개하지 않음
- 진실성: 전사 근거 밖 사실 없음
- 행동 이유: 마지막에 시청으로 얻는 보상
- 다양성: 같은 종결 표현의 기계적 반복 억제

## 9. 테스트 전략과 검증 방법

### 9.1 진행률 단위 테스트

테스트 대상

- ProgressEvent 검증
- ProgressTracker.start_stage
- ProgressTracker.advance
- estimate_eta
- 단계 가중치 집계

정상 사례

- 알려진 전체 단위의 0%, 50%, 100%
- 전사 타임스탬프 기반 진행률
- 교정 청크와 요약 배치
- 설치 다운로드 바이트

경계값

- total 0
- total unknown
- 첫 표본
- 완료 직전 부동소수 오차
- 단계 전환
- 매우 느린 첫 모델 로드

잘못된 입력과 예상 예외

- NaN, infinity, 음수, total 초과: ValueError
- sequence 감소: ValueError
- terminal 후 advance: JobStateError 또는 ProgressStateError
- 잘못된 stage 타입: TypeError

Mock·Fake

- FakeClock
- RecordingProgressSink
- FakeDownloader
- FakeTranscriber emitting timestamps

자동 통과 기준

- 전체와 단계 진행률이 범위를 벗어나지 않음
- 같은 operation에서 진행률이 감소하지 않음
- 계산 불가능한 ETA는 None
- terminal 이벤트 정확히 한 번

수동 검증

- 5분 이상 미디어에서 UI가 멈춘 것처럼 보이지 않음
- 단계와 로그가 실제 수행 작업과 일치
- ETA가 급격히 흔들릴 때 계산 중으로 안전하게 복귀

실행 명령

    python -m pytest -q tests/unit/test_progress.py
    python -m pytest -q tests/integration/test_progress_pipeline.py
    npm --prefix apps/desktop test

### 9.2 소개글 단위 테스트

테스트 대상

- extract_highlights
- build_introduction_prompt
- generate_video_introduction
- validate_introduction

정상 사례

- 항공사명·객실 등급이 있는 전사문
- 가격이 있는 제품 리뷰
- 구체 고유명사가 없는 강연
- 긴 전사문의 초·중·후반 근거

경계값

- 최소 길이 전사문
- highlight 후보 없음
- 질문 없이도 자연스러운 소개글
- 브랜드가 반복되는 전사문
- 광고 문구가 서두에 있는 영상

잘못된 입력과 예상 예외

- 빈 전사문: IntroductionError
- 비문자 모델 응답: ModelResponseError
- 스키마 밖 키·누락 키: ModelResponseError
- 원문에 없는 가격·브랜드: IntroductionError
- unknown evidence ID: IntroductionError
- CTA가 마지막 문장이 아님: IntroductionError

Mock·Fake

- RecordingQwenRuntime
- invalid JSON runtime
- hallucinating runtime
- fixture transcript factory

자동 통과 기준

- 모든 사실 요소가 원문 구간에 연결
- 기존 Summary 테스트 전부 회귀 통과
- summary와 introduction 저장물이 서로 덮어쓰지 않음
- output_mode 세 값의 통합 테스트 통과

수동 검증

- 실제 영상 5종 이상에서 사람이 주제 정확성, 구체성, 호기심, CTA, 과장 여부를 5점 척도로 평가
- 주제 정확성 또는 사실성이 5점 중 4점 미만이면 통과하지 않음
- 같은 종결 표현이 반복되지 않는지 확인
- 기존 두 문장 요약이 소개글 문체로 변하지 않았는지 비교

실행 명령

    python -m pytest -q tests/unit/test_introduction.py
    python -m pytest -q tests/unit/test_summarization.py
    python -m pytest -q tests/integration/test_output_modes.py

### 9.3 설치 테스트

테스트 대상

- probe_system
- plan_installation
- execute_installation
- RuntimeProfile 저장·읽기
- Tauri 번들 smoke

정상 사례

- 새 PC
- 이미 Ollama와 모델이 있는 PC
- 설치 중 취소 후 재시도
- 소형 모델에서 품질 모델로 변경

경계값

- 디스크가 요구량과 정확히 같음
- GPU 없음
- Ollama 서비스 중지
- 모델 digest 불일치
- 경로에 공백·한글 포함

잘못된 입력과 예상 예외

- 지원하지 않는 OS·아키텍처
- 저장소 내부 모델 경로
- 불완전 다운로드를 완료로 오인
- 권한 거부

Mock·Fake

- FakeSystemProbe
- FakeDownloader
- FakeOllamaApi
- 임시 데이터 루트

자동 통과 기준

- 외부 작업 전 사용자 동의 계획이 생성됨
- 진행 이벤트가 다운로드 상태와 일치
- 취소 후 partial 파일이 식별되거나 안전하게 재사용
- 설치 영수증과 doctor 결과 일치

수동 검증

- 깨끗한 Windows VM 설치·실행
- macOS runner의 dmg
- Linux runner의 AppImage 또는 deb
- 네트워크 중단·재연결
- 23GB 모델 다운로드의 실제 진행률

실행 명령

    python -m pytest -q tests/unit/test_installer.py
    python -m pytest -q tests/unit/test_runtime_profile.py
    python -m pytest -q tests/integration/test_setup_flow.py
    npm --prefix apps/desktop test
    npm --prefix apps/desktop run tauri build

### 9.4 전체 수동 승인 기준

- 사용자는 현재 단계와 완료된 단계를 UI에서 구분할 수 있다.
- 측정 가능한 단계는 실제 퍼센트가 보인다.
- 측정 불가 단계는 계산 중으로 보이고 앱이 응답한다.
- 취소 후 작업 전용 임시 artifact만 정리된다.
- 요약만 실행하면 이전과 동등한 Summary 결과와 파일이 생성된다.
- 소개글만 실행하면 Summary 생성 비용을 쓰지 않는다.
- 둘 다 실행하면 공통 STT를 한 번만 수행한다.
- qwen3.6:35b-a3b-agent-64k가 선택되면 요청의 model 필드가 정확한 태그다.
- 전사문·프롬프트·결과가 외부 네트워크로 전송되지 않는다.

## 10. 예외·안전·개인정보 계약

- 설치 오류는 InstallationError 계열로 사용자 조치와 기술 세부를 분리한다.
- 진행 sink 오류는 로그에 남기되 제품 산출물을 손상시키지 않는다.
- 모델 응답 오류는 원문이나 전체 prompt를 UI 오류에 포함하지 않는다.
- setup 로그에 인증 정보, 사용자 홈 전체 경로, 전사문을 기록하지 않는다.
- Tauri 명령은 임의 shell 문자열을 받지 않고 구조화 인자만 받는다.
- 자식 프로세스는 shell=False에 해당하는 안전한 argv로 실행한다.
- 삭제는 검증된 작업 전용 디렉터리 경계 안에서만 수행한다.
- URL 다운로드는 사용자 권한과 대상 서비스 정책 준수를 안내한다.
- 앱 종료 시 실행 중 작업을 알리고 정상 취소 또는 계속 실행 정책을 선택하게 한다.

## 11. 위험 요소와 미확정 사항

### 11.1 성능

qwen3.6:35b-a3b-agent-64k는 이 PC에 설치되어 있지만 약 23GB이며 16GB VRAM을 초과한다. 시스템 RAM 오프로딩으로 동작할 수 있으나 속도와 메모리 압박을 실제 벤치마크해야 한다.

결정 제안

- 품질 우선 프로필로 qwen3.6:35b-a3b-agent-64k 지원
- 설치 마법사에서 권장 여부와 예상 자원 표시
- 호환성 모델을 항상 선택 가능하게 유지
- STT와 Qwen 순차 로드 및 가능한 모델 해제
- intro와 summary가 모두 필요하면 같은 Qwen 세션을 재사용하되 호출은 계약대로 분리

### 11.2 ETA 정확도

첫 실행의 모델 로드와 다운로드 서버 속도는 예측하기 어렵다. 숫자를 꾸며내기보다 계산 중 상태를 허용해야 한다.

### 11.3 배포 크기와 권한

모델을 앱 설치 파일에 직접 포함하면 수십 GB가 된다. 앱 바이너리와 모델 다운로드를 분리하고, 최초 실행에 사용자가 모델을 고르게 해야 한다.

### 11.4 소개글 품질

호기심을 높이는 요구와 사실성은 충돌할 수 있다. 자동 검증은 근거 없는 숫자·고유명사와 구조를 차단하지만 자연스러움은 사람 평가가 필요하다.

### 11.5 요약 호환성

현재 summarization.py의 최종 프롬프트 일부에 소개글 표현이 들어가 있다. 구현 시 기존 Summary의 목적을 사실 중심 요약으로 되돌리고 회귀 fixture로 잠근다. summary.json 구조는 변경하지 않는다.

### 11.6 사용자 결정이 필요한 항목

구현에 앞서 아래 기본값은 승인 과정에서 확정한다.

1. UI 최초 선택값
   - 제안: 둘 다
   - CLI 호환 기본값: 요약
2. 소개글 길이
   - 제안: 제목형 한 줄 + 본문 2~3문장
3. 질문 문장
   - 제안: 반드시가 아니라 내용에 맞을 때 최대 1개
4. 모델
   - 제안: 이 PC의 품질 프로필 qwen3.6:35b-a3b-agent-64k
   - 배포 기본은 하드웨어 검사 후 추천
5. setup.py
   - 제안: 개발·복구용 bootstrap 유지
   - 일반 사용자는 OS별 설치 패키지와 최초 실행 마법사 사용
6. macOS·Linux
   - 제안: 코드와 CI 빌드 정의는 포함, 첫 공개 배포 검증은 Windows 우선

## 12. 승인 후 구현 단계

설계 승인 직후에도 실제 기능 로직을 바로 구현하지 않는다. 저장소 지침에 따라 먼저 코드 골격과 테스트 도구 골격, docs/ai/04-implementation-order.md를 갱신한다. 이후 각 실제 구현은 Statement_of_Functions.md 한 작업씩 명세하고 별도 승인을 받아 진행한다.

예상 의존성 순서는 다음과 같다.

1. PUI-01 출력 모드·진행 이벤트·소개글 도메인 계약 골격
2. TUI-01 progress fake, clock, runtime fixture 골격
3. PUI-02 진행률 계산기와 단위 테스트
4. PIN-01 소개글 생성기와 단위 테스트
5. PSUM-R 기존 요약 회귀 복구
6. PPIPE-01 파이프라인 출력 모드와 progress sink 연결
7. PPERSIST-01 소개글·진행 이벤트 영속화
8. PCLI-01 CLI 출력 모드와 진행 표시
9. PSETUP-01 시스템 검사·설치 계획·다운로드 진행
10. PIPC-01 Tauri sidecar와 이벤트 브리지
11. PUX-01 설치·진행·결과 UI
12. PBUILD-01 Windows 번들, OS별 CI 빌드
13. PE2E-01 실제 로컬 미디어 smoke와 사람 품질 검증
14. PDOC-01 README·제품 소개·설치 문서 전체 정리

## 13. 설계 완료 판정 기준

- 기존 요약 기능이 독립 모드와 기존 저장 계약으로 명시되어 있다.
- 소개글 기능이 별도 타입·생성기·검증기·파일로 분리되어 있다.
- setup.py, 일반 사용자 설치 패키지, 최초 실행 마법사의 역할이 구분되어 있다.
- 진행률과 ETA가 측정 가능한 값에만 기반한다.
- UI, CLI, 백엔드가 같은 ProgressEvent 계약을 사용한다.
- qwen3.6:35b-a3b-agent-64k 선택 방식과 하드웨어 위험이 명시되어 있다.
- 모든 신규 함수에 입력, 출력, 예외, 부작용, 사전·사후 조건과 테스트 방법이 있다.
- 자동 테스트와 실제 PC 수동 검증 기준이 있다.
- 승인 전에는 이 문서 외 제품 파일이 변경되지 않는다.

## 14. V3: 실패를 전파하지 않는 제약 안전 교정 구조

### 14.1 목표와 문제 정의

현재 교정 단계는 각 Whisper segment의 전체 문장을 Qwen에 다시 쓰게 하고,
보호 placeholder의 값과 순서가 한 글자라도 달라지면 ModelResponseError로
전체 job을 종료한다. 이는 원문·숫자·고유명사를 안전하게 보존하려는 의도는
옳지만, 자유 생성 모델에게 보호값의 복사를 맡긴 구조가 단일 실패 지점이 된
것이다.

V3의 목표는 다음 세 조건을 동시에 만족하는 것이다.

1. Qwen이 한 청크에서 JSON 또는 보호값 계약을 어겨도 전사·요약·소개글 job은
   끝까지 완료된다.
2. 보호값은 모델 출력에 의존하지 않고 프로그램이 원문 그대로 재조립하므로
   모델이 삭제·변조할 수 없다.
3. 교정이 실제로 적용되지 않은 구간은 숨기지 않고, 재시도 횟수와 원인 범주를
   결과·검토 큐·UI에 남긴다.

이 변경은 요약과 소개글을 포기하는 fallback이 아니다. 교정 모델의 출력 책임을
완성 문장 재작성에서 검증 가능한 editable 부분 편집 제안으로 축소해,
교정·요약·소개글이 모두 안전한 입력을 받고 진행하도록 바꾸는 구조 개편이다.

### 14.2 범위와 비범위

범위:

- ProtectedText를 immutable locked part와 editable part로 분리하고 원문 순서로
  재조립한다.
- Qwen이 전체 corrected_text 대신 editable_id별 replacement proposal만
  JSON으로 반환하게 한다.
- malformed JSON, unknown id, 길이 초과, network timeout, 응답 형식 오류에
  bounded retry와 안전한 identity edit를 적용한다.
- 교정 그룹별 progress·retry·identity 적용 수를 저장하고 UI에 표시한다.
- Tauri sidecar failure event에 transcript/prompt를 제외한 짧은 stderr 원인
  범주를 전달한다.

비범위:

- 원본 영상·오디오·보호값의 자동 수정 또는 외부 전송
- Hermes의 설정·대화 기록·모델 설정을 읽거나 변경하는 기능
- 자동으로 사람 검토를 승인하는 기능
- 모델 실패 원인으로부터 사용자 전사문 또는 전체 prompt를 UI·로그에 노출하는
  기능

### 14.3 데이터 흐름

~~~
RawSegment
  -> protect_tokens
  -> split_locked_parts
  -> normalize editable parts
  -> group segments (bounded character budget)
  -> Qwen edit proposals (JSON Schema)
  -> validate proposal ids + retry if needed
  -> apply proposals to editable parts only
  -> reassemble locked original values deterministically
  -> reviewed Transcript + review queue
  -> summary / introduction
  -> persisted result + UI
~~~

각 분할 결과는 다음과 같은 개념 모델을 가진다.

~~~
EditableTextPlan(
  segment_id="s-12",
  parts=(
    EditablePart(id="s-12:e1", text="카타르항공 "),
    LockedPart(id="s-12:p1", text="2026년"),
    EditablePart(id="s-12:e2", text="에도 ..."),
  ),
)
~~~

모델에는 문맥 이해를 위해 locked part의 원문 또는 안전한 라벨을 보여줄 수
있지만, 반환 JSON에는 locked value나 placeholder를 넣지 않는다.

~~~json
{
  "edits": [
    {
      "editable_id": "s-12:e2",
      "replacement": "에도 주목할 만한 변화를 보여줍니다."
    }
  ],
  "requires_review": false
}
~~~

프로그램은 s-12:p1의 2026년을 항상 원본에서 다시 삽입한다. 따라서 모델이
보호값을 복사하는 데 실패할 수 있는 경로 자체가 사라진다.

### 14.4 제안하는 계약과 책임

구현 전 다음 이름과 세부 타입은 명세 작업에서 확정한다. 모든 새 dataclass는
immutable(frozen=True)로 만든다.

| 대상 | 책임 | 입력 / 출력 | 실패 처리 / 부작용 |
| --- | --- | --- | --- |
| backend/contracts.py | EditablePart, LockedPart, EditableTextPlan, EditProposal, CorrectionOutcome 계약 | 보호된 segment -> 부분 계획, model edit -> outcome | 타입·id·순서 계약 위반은 도메인 예외 |
| backend/protection.py | split_locked_parts, reassemble_locked_parts | ProtectedText 또는 text plan -> plan / text | 잠긴 부분의 값·순서·개수는 프로그램만 관리; I/O 없음 |
| backend/correction.py | propose_edits, validate_edit_proposal, correct_with_retry | plan group, context, runtime -> proposal/outcome | runtime·JSON 오류는 최대 N회 재시도 후 identity outcome |
| backend/main.py | 그룹화·outcome 조립·review queue 반영 | raw transcript -> reviewed transcript | 한 group의 identity outcome이 전체 job을 failed로 만들지 않음 |
| backend/persistence.py | retry·identity 적용·reason category 저장 | completed result -> persisted artifact | 기존 summary/transcript artifact 호환성 유지 |
| tools/run_local.py | progress/report에 resilience 통계 추가 | run mode -> report | stdout JSON 단일 결과, stderr JSONL progress 유지 |
| apps/desktop/src-tauri/src/lib.rs | 실패 원인 범주의 bounded stderr tail 전달 | child stderr -> event | prompt·전사문·path 전체를 event에 포함하지 않음 |
| apps/desktop/src/main.ts | retry·identity 적용 상태와 실제 오류 표시 | progress/result event -> UI | generic Some(120)만 표시하지 않음 |

핵심 함수 계약:

1. split_locked_parts(protected: ProtectedText, segment_id: str) -> EditableTextPlan
   - 사전 조건: replacement key는 유효 placeholder이며 text 안에 정확히 한 번씩 있다.
   - 사후 조건: part를 재조립하면 protected.text와 정확히 같다.
   - 예외: 타입 오류는 TypeError, map/text 불일치는 ProtectionError.
   - 부작용: 없음.

2. validate_edit_proposal(plan: EditableTextPlan, raw: object) -> EditProposal
   - 사전 조건: raw는 단일 JSON object이며 edit 대상은 plan의 editable id만 참조한다.
   - 사후 조건: replacement는 locked part, placeholder, 제어 문자를 포함하지 않으며
     길이 제한 안에 있다.
   - 예외: 형식 오류는 ModelResponseError.
   - 부작용: 없음.

3. correct_with_retry(plan_group, context, runtime, max_attempts=3) -> CorrectionOutcome
   - 정상: 유효 proposal을 적용한 outcome 반환.
   - 경계: 비어 있는 editable part, proposal의 빈 edits, max attempt 1.
   - 오류: malformed response, timeout, unknown id, length limit 위반은 재시도한다.
   - 최종 사후 조건: 모든 attempt가 실패해도 original editable text로 만든
     identity_applied=True outcome을 반환하고 review reason을 남긴다.
   - 부작용: local Qwen call은 최대 max_attempts회. locked part·파일·network
     endpoint는 변경하지 않는다.

4. apply_edit_proposal(plan, proposal) -> str
   - 사후 조건: 모든 locked original value가 동일 순서로 정확히 한 번씩 존재한다.
   - 모델이 편집하지 않은 editable part는 원문 그대로다.
   - 예외: 유효성 검사를 우회한 proposal은 ProtectionError.

### 14.5 재시도와 완료 정책

권장 기본값은 청크별 최대 3회(최초 1회 + repair retry 2회), temperature=0,
think=false, bounded context다.

| 상황 | 처리 | job 상태 |
| --- | --- | --- |
| 유효한 edit JSON | 적용 후 다음 group 진행 | 계속 |
| malformed JSON / unknown editable id | 오류 범주를 기록하고 repair prompt로 재시도 | 계속 |
| timeout / local Ollama transient error | 동일 input 한 번 재시도 후 repair retry | 계속 |
| 모든 attempt 실패 | editable 원문을 identity로 채택, correction_unapplied review item 저장 | 계속 |
| 보호·재조립 내부 계약 오류 | 데이터 손상 가능성이 있으므로 job failed | 중단 |
| STT / FFmpeg / persistence 오류 | 기존처럼 job failed | 중단 |

따라서 모델이 교정하지 못했다와 데이터가 안전하지 않다를 구분한다.
전자는 원문을 보존한 채 결과 생산을 계속하고, 후자만 전체 작업을 중단한다.

### 14.6 프롬프트와 모델 운용

- 교정 prompt는 전체 문장 반환 금지, editable_id 이외의 id 금지,
  JSON object only를 명시한다.
- 요청의 format에는 가능한 Ollama JSON Schema를 사용한다. Schema는 JSON
  모양을 강제하지만 semantic validation을 대체하지 않으므로 프로그램의 id·길이
  검증은 유지한다.
- 한 group은 문맥을 유지하되 1,500~3,000자 및 5~15 segment 범위로 제한한다.
  현재처럼 작은 Whisper segment마다 모델을 부르는 방식보다 호출 수·실패 표면을
  줄인다.
- summary와 introduction은 재조립된 transcript를 입력으로 별도 호출한다.
  교정 group의 retry 기록이 생성 결과 자체를 막지 않는다.
- 사용 모델은 계속 qwen3.6:35b-a3b-agent-64k이며, Hermes와의 비교는 모델
  tag가 아니라 request schema·prompt·retry·acceptance contract 차이로 기록한다.

### 14.7 UI·진단 계약

- 진행 UI는 교정 7/24, 재시도 1/3, 원문 유지 2개를 분리해 표시한다.
- terminal 상태는 완료, 완료(검토 필요), 실패를 구분한다. identity outcome이
  있으면 완료(검토 필요)이지만 summary/introduction 결과는 모두 열 수 있다.
- backend failure event는 exit code와 safe error category를 표시한다. raw stderr는
  마지막 1~2줄만, 경로·prompt·전사문을 제거한 뒤 표시한다.
- 파일 확인 성공은 파일명: bytes, 실행 준비됨으로 유지하고,
  파일 확인 오류와 이후 모델 교정 오류를 동일 메시지 영역에서 혼동하지 않게
  분리한다.

### 14.8 테스트 도구와 통과 기준

새 테스트는 실제 Ollama를 기본으로 호출하지 않는다. RecordingQwenRuntime,
MalformedThenValidRuntime, TimeoutThenValidRuntime, AlwaysInvalidRuntime을
사용하고, 실제 모델 smoke는 별도 명시 승인 때만 실행한다.

| 테스트 대상 | 정상·경계 사례 | 잘못된 입력 / 예상 결과 | 자동 통과 기준 | 수동 검증 |
| --- | --- | --- | --- | --- |
| split_locked_parts / reassemble | 브랜드·금액·날짜·반복값 mixed text | unknown placeholder -> ProtectionError | 재조립 text가 byte-for-byte 동일 | 없음 |
| proposal validation | editable id 1개·여러 개·no-op | locked id, duplicate id, oversize replacement -> ModelResponseError | model output으로 locked text 변경 불가 | 없음 |
| retry coordinator | 첫 실패 후 둘째 성공 | 3회 모두 invalid -> identity outcome + review | attempt count와 outcome reason 일치 | 로그에 원문이 없는지 확인 |
| pipeline integration | 한 group identity, 다른 group 정상 | review item이 있어도 summary/introduction 생성 | terminal archived, 산출물 세 종류 존재 | UI 탭에서 결과 확인 |
| progress / Tauri bridge | retry stage, safe stderr category | generic child failure | 실제 error category가 표시 | 15분 source에서 단계·취소 동작 확인 |
| actual local smoke | 짧은 WAV, exact Qwen tag | 장시간 source의 일부 response invalid | job이 완료되고 보호값 유지 | 결과 문장 품질과 review UX 확인 |

예정 실행 명령은 구현 작업 명세마다 좁혀 적되, 최종 회귀는 다음을 포함한다.

~~~powershell
C:\Users\sow20\AppData\Local\Programs\Python\Python312\python.exe -B -m pytest -q -p no:cacheprovider
npm --prefix apps/desktop test
npm --prefix apps/desktop run check
npm --prefix apps/desktop run tauri:check
git diff --check
~~~

### 14.9 구현 순서와 승인 필요 사항

1. CR-01: immutable part·proposal·outcome domain contract와 fake skeleton
2. CR-02: locked/editable split 및 deterministic reassembly
3. CR-03: edit proposal parser·schema·retry coordinator
4. CR-04: pipeline grouping·identity outcome·review persistence
5. CR-05: CLI progress/report 및 safe error category
6. CR-06: Tauri stderr bridge와 UI retry/result 표시
7. CR-07: unit·integration 회귀와 짧은 WAV/15분 source 수동 smoke

결정이 필요한 기본값은 max_attempts=3, group character budget
2,000, identity outcome을 terminal completed_with_review로 표시하는 것이다.
이 설계 문서는 승인 전 계획만 담는다. 실제 코드·테스트·외부 모델 호출은
사용자가 정확히 APPROVE DESIGN이라고 승인한 뒤에도 먼저 골격과 구현 순서
문서를 갱신한 후, 작업별 명세와 별도 구현 승인에 따라 진행한다.
