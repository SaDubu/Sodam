# Sodam — 로컬 영상 전사·요약·소개글 생성 파이프라인

Sodam은 영상 파일을 외부 클라우드로 전송하지 않고, 사용자의 PC에서 **FFmpeg → faster-whisper → Ollama/Qwen**을 연결해 전사와 콘텐츠 결과물을 만드는 로컬 우선 애플리케이션입니다. 기존의 사실 중심 `summary`를 유지하면서, 같은 전사문에서 시청자의 호기심을 유도하는 `introduction`을 선택적으로 생성할 수 있습니다.

이 저장소는 단순 데모가 아니라 계약(contract) 기반 도메인 모델부터 보호 토큰, 근거 연결 요약, 검토 큐, 재시도·복원력 보고, CLI와 Tauri UI까지 단계적으로 쌓아 올린 포트폴리오용 구현입니다.

## 무엇을 해결하는가

긴 영상에서 사람이 반복하는 작업은 오디오 추출, 전사, 핵심 내용 선별, 사실 보존, 소개 문구 작성입니다. Sodam은 이 흐름을 하나의 작업 ID로 묶고 각 단계의 입력·출력·실패를 기록합니다. LLM이 원문을 임의로 바꾸지 않도록 고유 placeholder로 보호하고, 수정 제안은 별도로 검증한 뒤 안전한 변경만 자동 반영합니다. 확신할 수 없는 변경은 자동 승인하지 않고 review queue로 보냅니다.

## 제공 기능

| 모드 | 결과 | 용도 |
| --- | --- | --- |
| `summary` | 근거 구간이 연결된 사실 중심 요약 | 기존 요약 기능, 기본 모드 |
| `introduction` | 제목형 한 줄, 핵심 매력 포인트, 호기심 gap, CTA를 포함한 소개글 | 영상 업로드·홍보 문구 |
| `both` | 같은 전사문에서 summary와 introduction 모두 생성 | 비교·검수·콘텐츠 제작 |

공통 기능으로 단계별 progress 이벤트(JSONL/human), ETA·재시도 수·검토 필요 수를 포함한 resilience report, 취소 가능한 job lifecycle, 결과 재열기(`inspect_job.py`), review 승인 도구를 제공합니다.

## 설계 포인트

- **Local-first**: Qwen은 Ollama loopback(`127.0.0.1`)으로만 호출하고 STT 모델·미디어·결과는 Git 저장소 밖에 둡니다.
- **명시적 조립**: FFmpeg, STT, Qwen을 Protocol/adapter로 주입해 실제 런타임과 fake 테스트를 분리했습니다.
- **원문 보존**: URL·금액·날짜·숫자·glossary를 occurrence 단위 placeholder로 보호합니다. 수정 제안은 placeholder 순서·개수·근거 ID를 검증합니다.
- **안전한 실패**: 경로 탈출·심볼릭 링크·덮어쓰기·잘못된 JSON·모델 오류를 계약 예외로 분류합니다. CLI/Tauri stderr에는 비밀값과 raw prompt 대신 안전한 오류 category만 노출합니다.
- **결정론적 재조립**: locked text와 editable text를 분리하고, 검토 대상/identity 결과를 구분해 같은 입력에서 재현 가능한 결과를 만듭니다.
- **UI와 CLI의 동일 계약**: `tools/run_local.py`의 진행·결과 schema를 Tauri reducer와 공유해 화면을 닫았다 다시 열어도 persisted job 상태를 해석할 수 있습니다.

상세 설계는 [architecture](docs/ai/01-architecture.md), 단계별 결정과 실행 결과는 [implementation order](docs/ai/04-implementation-order.md), 제품화 계획은 [productization roadmap](docs/ai/05-productization-roadmap.md), 실제 모델 경계는 [runtime profile](docs/ai/06-runtime-profile.md)에서 확인할 수 있습니다.

## 설치 전 조건

Windows 10/11 x64, Python 3.12, 16 GB RAM 이상과 모델·작업 데이터를 위한 여유 디스크를 권장합니다. 실제 검증 환경은 다음과 같았지만 설치 경로는 사용자 환경에 맞춰 지정합니다.

```text
Python:  D:\AI-Legion\Sodam-runtime\Scripts\python.exe
FFmpeg:  D:\AI-Legion\Sodam-data\tools\ffmpeg-9.0.1\bin\ffmpeg.exe
STT:     D:\AI-Legion\Sodam-models\faster-whisper\turbo-0a363e9
Ollama:  http://127.0.0.1:11434, qwen3.6:35b-a3b-agent-64k
```

`setup.py`는 현재 설치 계획과 진단을 보여주는 부트스트랩입니다. 모델을 묵시적으로 다운로드하지 않으므로 먼저 계획만 확인하세요. 모델 가중치와 개인 미디어는 절대 이 저장소에 커밋하지 않습니다.

```powershell
python setup.py --plan-only
python tools/doctor.py --json
```

`doctor.py`는 `SODAM_FFMPEG` 절대 경로를 PATH보다 우선하고 Qwen `qwen3.6:35b-a3b-agent-64k`를 검사합니다. 환경변수를 설정하지 않으면 PATH에 있는 `ffmpeg`를 사용하므로, 외부 설치 경로를 사용하는 경우 환경변수를 설정하세요.

## 로컬 파일 실행

```powershell
$py = 'D:\AI-Legion\Sodam-runtime\Scripts\python.exe'
$env:Path = 'D:\AI-Legion\Sodam-data\tools\ffmpeg-9.0.1\bin;' + $env:Path
$model = 'D:\AI-Legion\Sodam-models\faster-whisper\turbo-0a363e9'
& $py -B tools/run_local.py 'C:\path\to\video.mp4' --mode run --output-mode summary
& $py -B tools/run_local.py 'C:\path\to\video.mp4' --mode run --model-path $model --qwen-model qwen3.6:35b-a3b-agent-64k --output-mode introduction --progress-format human
& $py -B tools/run_local.py 'C:\path\to\video.mp4' --mode run --model-path $model --qwen-model qwen3.6:35b-a3b-agent-64k --output-mode both --progress-format jsonl
```

stdout에는 최종 JSON만, stderr에는 단계별 진행 로그가 출력됩니다. `jsonl` 이벤트에는 상태·단계·완료율·경과 시간이 포함되며 ETA를 계산할 수 없을 때는 null로 남습니다. 결과는 `D:\AI-Legion\Sodam-data\jobs\<job-id>`에 저장되고 `tools/inspect_job.py JOB_DIR`로 다시 읽을 수 있습니다.

승인된 URL은 사용 권한이 있는 경우에만 `--allow-url --mode run`을 함께 사용하세요. cookie, 로그인 정보, playlist, proxy, 원격 API fallback은 사용하지 않습니다.

## 검토와 재생성

```powershell
python tools/inspect_job.py D:\AI-Legion\Sodam-data\jobs\<job-id>
python tools/resolve_review.py <job-id> 0 --decision accept_suggested --result-root D:\AI-Legion\Sodam-data\jobs
python tools/refresh_summary.py <job-id> --result-root D:\AI-Legion\Sodam-data\jobs
```

원본 전사·검토 queue는 audit으로 보존되며, 사용자가 명시적으로 refresh할 때만 `resolved_summary.json`을 추가 생성합니다. 기존 summary는 덮어쓰지 않습니다.

## 데스크톱 UI

`apps/desktop`은 Tauri shell과 순수 TypeScript 상태 계층으로 구성됩니다. 파일 선택, `summary`/`introduction`/`both` 모드, 단계별 진행률·ETA·로그, 취소, 결과·전사문·review 탭, 재시도/identity 결과를 표시하도록 설계했습니다. 프런트엔드는 파일·모델·네트워크에 직접 접근하지 않고 backend의 구조화 이벤트만 소비합니다.

TypeScript 검사, Node 계약 테스트, 정적 frontend build는 통과했습니다. 현재 개발 환경의 Windows Code Integrity 정책과 Tauri 의존성 상태 때문에 실제 Rust/Tauri bundle/window smoke는 별도 운영 환경 검증이 필요하므로, unsigned installer를 배포 완료로 주장하지 않습니다. CLI는 UI 없이도 전체 pipeline을 실행할 수 있습니다.

## 개인정보와 저장 경계

모델, 사용자 미디어, 전사문, 결과와 임시 audio는 Git repository 밖에 둡니다. 작업 임시물은 `D:\AI-Legion\Sodam-data\tmp\jobs` 아래 해당 job 경계 안에서만 생성·정리됩니다. prompt 전문·비밀값·사용자 URL token을 로그나 commit에 넣지 마세요.

## 검증

```powershell
C:\Users\sow20\AppData\Local\Programs\Python\Python312\python.exe -B -m pytest -q -p no:cacheprovider
npm --prefix apps/desktop test
npm --prefix apps/desktop run check
npm --prefix apps/desktop run build
git diff --check
```

검증 기준선은 Python 전체 테스트 `252 passed, 1 skipped`, 데스크톱 Node 계약 테스트 `11 passed`, TypeScript `check` 및 frontend `build` 통과입니다. `cargo check`는 현재 호스트의 Tauri 의존성/Code Integrity 환경에서 `E0463 (can't find crate for tauri)`가 발생해 코드 결함과 분리된 환경 blocker로 기록했습니다. 실제 모델을 사용하는 60초 `both` 수직 슬라이스는 Ollama `qwen3.6:35b-a3b-agent-64k`, faster-whisper `turbo`, FFmpeg 9.0.1 조합으로 `archived`까지 확인했습니다.

## 알려진 범위와 다음 과제

이 저장소는 개인용 로컬 실행 후보입니다. 자동 모델 다운로드·클라우드 fallback·무단 URL 수집은 포함하지 않으며, 사용 권한이 있는 입력만 처리합니다. 다음 릴리스 전 과제는 깨끗한 Windows PC에서의 Tauri installer smoke, 실제 5개 영상에 대한 사람 품질평가, 모델/드라이버별 성능 기준, 필요 시 서명된 배포물 검증입니다.
