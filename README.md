# Sodam

Sodam은 로컬 미디어 또는 승인된 URL을 전사하고, 보호 토큰·제한적 정규화·검토 큐를 거쳐 근거 구간이 연결된 요약을 만드는 계약 기반 파이프라인입니다. 제품 코드는 외부 collaborator를 주입받도록 설계되어 있으며, 기본 실행은 모델·다운로드·미디어 도구를 자동으로 호출하지 않습니다.

## 현재 범위

- B02~B13은 작업 lifecycle, 안전한 artifact 경계, 입력/미디어/STT/교정/검토/전사문/요약 계약과 주입형 pipeline을 구현했습니다.
- `apps/desktop/src/state.ts`는 초기 UI 상태 계약만 제공합니다. Tauri 화면·IPC·실행 UI는 아직 연결하지 않았습니다.
- `tests/unit/`과 `tests/integration/`은 fake 기반 계약과 lifecycle을 검증합니다.
- `tools/evaluate_transcript.py`는 고정 fixture로 교정 정확도·보호 토큰 보존·위험 자동승인·처리시간 지표를 계산합니다.
- `tools/inspect_job.py`는 명세화된 작업 JSON artifact를 읽기 전용으로 점검합니다.
- 실제 URL adapter, FFmpeg runner, STT engine, Qwen runtime, DB persistence는 별도 구성·승인이 필요합니다.

설계와 이력은 [architecture](docs/ai/01-architecture.md), [implementation order](docs/ai/04-implementation-order.md), 현재 단일 작업 명세는 [Statement_of_Functions.md](Statement_of_Functions.md)를 확인하세요.

## 개발 환경과 검증

Windows PowerShell과 Python 3.12를 기준으로 합니다. pytest는 Python 3.12 환경에 설치되어 있어야 합니다.

```powershell
C:\Users\sow20\AppData\Local\Programs\Python\Python312\python.exe -B -m pytest -q

C:\Users\sow20\AppData\Local\Programs\Python\Python312\python.exe -B tools/evaluate_transcript.py tests/fixtures/evaluation_cases.json

C:\Users\sow20\AppData\Local\Programs\Python\Python312\python.exe -B tools/inspect_job.py tests/fixtures/inspection_job

powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-repository-clean.ps1 -RepositoryRoot .
```

평가와 점검 CLI는 fixture만 읽고 JSON report를 stdout으로 출력합니다. repository policy 검사는 tracked/staged path만 읽기 전용으로 검사합니다.

## 작업 artifact와 사용자 데이터

작업 전용 artifact root는 `D:\AI-Legion\Sodam-data\tmp\jobs`이며 Git repository 밖에 있습니다. 각 Job은 그 아래 자신의 work directory만 소유하고, cleanup 계약은 해당 디렉터리 안에서만 정리합니다.

사용자 미디어, 전사 결과, model files, job DB와 임시 audio는 repository에 저장하거나 commit하지 마세요. `.gitignore`과 `scripts/check-repository-clean.ps1`은 이런 유입을 방지하기 위한 보조 장치이며, 사용자 data의 백업 정책을 대신하지는 않습니다.

## 모델 설치 정책

`models/manifest.json`은 schema version `1`과 빈 `profiles`만 가진 declaration manifest입니다. 승인·검증된 profile name, HTTPS URL, lowercase SHA-256 checksum이 추가되기 전에는 실제 모델 설치를 실행하지 마세요.

`scripts/setup-models.ps1`의 `Install-SodamModels`는 다음을 강제합니다.

- repository 내부 model home, path traversal, 기존 target overwrite를 거부합니다.
- 주입 또는 기본 downloader가 만든 partial file의 SHA-256이 일치할 때만 final file로 이동합니다.
- hash mismatch 등 실패 시 partial file 정리를 시도합니다.

기본 downloader를 실제로 실행하려면 별도의 model profile·외부 호출 승인이 필요합니다. 이 repository에는 확정된 model name, URL, checksum 또는 runtime 등록값이 포함되어 있지 않습니다.

## Git 정책

Git에는 source, 선언 manifest, 문서와 재현 가능한 합성 fixture만 둡니다. 모델·미디어·local database·secret environment file·repository 내부의 잘못된 `Sodam-data/`는 ignore 대상입니다. `models/manifest.json`은 추적 대상이며 ignore하지 않습니다.

변경 전에는 다음을 권장합니다.

```powershell
git diff --check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-repository-clean.ps1 -RepositoryRoot .
```

이 검사는 완전한 secret DLP나 실제 서비스의 권한·약관 검토를 대체하지 않습니다.
