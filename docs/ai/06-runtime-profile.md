# Sodam P01 실행 Runtime Profile

> 상태: P01~P03 실행 결과를 반영한 runtime profile. 모델·package는 repository 밖에 설치되어 있으며, 실제 경로와 버전은 `doctor.py --json`으로 다시 확인한다.

## 1. 선택된 MVP 조합

| 역할 | 선택 | 초기 profile | 실행 경계 |
|---|---|---|---|
| 교정·요약·소개글 LLM | Ollama | `qwen3.6:35b-a3b-agent-64k` | Windows의 loopback endpoint `http://127.0.0.1:11434`만 사용 |
| STT | Python `faster-whisper` | `turbo`, `cpu`, `int8` | repository 밖의 local model snapshot만 사용 |
| 미디어 표준화 | FFmpeg executable | mono / 16 kHz / s16 WAV | `FfmpegRunner`로 주입된 local executable만 사용 |
| 제품 pipeline | `PipelineApplication` | 기존 contracts | 실제 adapter를 명시적으로 조립해 주입 |

MVP는 로컬 파일 입력부터 처리한다. URL downloader, cloud API, remote fallback, 계정·token·telemetry 연동은 이 profile에 포함하지 않는다.

## 2. 선택 근거와 공식 출처

### 2.1 Ollama와 `qwen3.6:35b-a3b-agent-64k`

- 제품 검증에는 Ollama tag `qwen3.6:35b-a3b-agent-64k`를 사용한다. 모델 크기·context·메모리 요구사항은 설치된 Ollama의 `ollama show` 결과를 기준으로 확인한다.
- Ollama의 공식 local chat 예시는 `http://localhost:11434/api/chat`을 사용한다. Sodam adapter는 같은 loopback endpoint를 `127.0.0.1`으로 명시하고, `stream: false` 응답의 content만 기존 JSON 검증기로 전달한다.
- Ollama의 model pull API는 local `/api/pull` endpoint에서 model name과 progress stream을 처리한다. 실제 pull은 P01A에서만 실행한다.

공식 출처:

- [Ollama Qwen3 library](https://ollama.com/library/qwen3)
- [Ollama Pull API](https://docs.ollama.com/api/pull)

### 2.2 `faster-whisper`와 `turbo`

- `faster-whisper`는 CTranslate2 기반 Whisper implementation이며 Python 3.9 이상을 요구한다. Python 3.12는 이 요구 범위에 포함된다.
- 공식 사용 예시는 `WhisperModel`의 CPU `int8`, GPU `float16`/`int8_float16` option을 제공한다. MVP는 GPU driver/CUDA dependency를 추가하지 않는 `cpu`/`int8`부터 검증한다.
- `transcribe()`가 반환하는 segments는 generator이므로 adapter는 그것을 단 한 번 materialize하고, existing `SttEngine` contract가 요구하는 list/tuple mapping으로 변환한다.
- model size 이름으로 생성한 `WhisperModel`은 Hugging Face Hub download를 자동 시작할 수 있다. production adapter는 그 동작을 사용하지 않고, P01A가 준비한 local snapshot directory만 받는다.

공식 출처:

- [SYSTRAN faster-whisper README](https://github.com/SYSTRAN/faster-whisper)

## 3. 지원 PC와 경로 기준

### 3.1 MVP 목표 사양

| 등급 | OS / RAM | 처리 방식 | 비고 |
|---|---|---|---|
| 최소 | Windows 10/11 x64, 16 GB RAM, Python 3.12, 30 GB free disk | CPU STT `int8` + Ollama `qwen3.6:35b-a3b-agent-64k` | 장시간 media는 느릴 수 있다. |
| 권장 | Windows 10/11 x64, 32 GB RAM, 30 GB+ free disk | CPU 또는 검증된 NVIDIA GPU | 실제 성능 기준은 P03/P07에서 측정한다. |
| GPU 선택 | NVIDIA GPU 8 GB+ VRAM | CUDA와 matching CTranslate2 dependency 확인 후 opt-in | P01에서는 GPU profile을 활성화하지 않는다. |

이 값은 Sodam의 보수적인 지원 목표이며 runtime vendor의 성능 보증이 아니다. P01A 실제 설치 후 모델 파일 크기와 local cache를 재확인해 README에 최종 수치를 반영한다.

### 3.2 저장 위치와 소유권

```text
D:\AI-Legion\
├─ Sodam\                     # Git worktree: source/docs/tests only
├─ Sodam-models\
│  ├─ ollama\                  # OLLAMA_MODELS 또는 equivalent runtime storage
│  └─ faster-whisper\          # pinned local CTranslate2 snapshot
└─ Sodam-data\
   ├─ jobs\                    # persisted reviewed results (P04)
   └─ tmp\jobs\                # disposable per-job audio/media artifacts
```

- `Sodam-models`와 `Sodam-data`는 반드시 Git worktree 밖에 있어야 한다.
- Qwen model blob, STT snapshot, Python virtual environment, source media, output transcript, SQLite database, `.env`를 repository에 쓰지 않는다.
- repository policy scan은 이런 파일이 staged/tracked 되는 것을 막는 보조 장치다. 실제 경계는 resolved absolute path validation으로 강제한다.

## 4. Runtime별 설치 전략

### 4.1 Ollama model pull

P01A에서 수행할 실제 작업:

1. Windows용 Ollama 설치 여부와 version을 확인한다.
2. `OLLAMA_MODELS` 또는 supported runtime setting을 repository 밖 `D:\AI-Legion\Sodam-models\ollama`로 지정한다.
3. local Ollama process만 대상으로 승인된 `qwen3.6:35b-a3b-agent-64k` pull/status를 확인하고, pull completion을 기록한다.
4. local API로 loaded tag와 non-streaming JSON response를 health check한다.
5. pull 중단·disk exhaustion·tag mismatch·local service unavailable을 구분해 사용자에게 보고한다.

Ollama registry artifact는 runtime-managed blobs와 manifest로 구성되므로 existing O01 single HTTPS file installer의 `filename`/`url`/`sha256` schema에 억지로 표현하지 않는다. P01A에서는 selected tag와 runtime-reported digest/version을 검증 가능한 install record에 남기는 별도 contract를 만든다.

### 4.2 faster-whisper snapshot

P01A에서 수행할 실제 작업:

1. Python 3.12 virtual environment 또는 approved interpreter에 pinned `faster-whisper` package를 설치한다.
2. `turbo` CTranslate2 model snapshot의 repository ID와 immutable revision을 확정한다.
3. Hub snapshot을 `D:\AI-Legion\Sodam-models\faster-whisper` 아래에 explicit download하고, revision·파일 목록·hash를 installation record로 저장한다.
4. production adapter는 downloaded directory만 `WhisperModel` constructor에 전달하고 network access를 금지한다.
5. `cpu`/`int8` health transcription 후 output segment schema·Korean language handling·resource usage를 기록한다.

faster-whisper model snapshot은 여러 files와 metadata로 구성될 수 있으므로 O01 single-file checksum installer와 별도 snapshot installer contract가 필요하다. target path의 lock, interrupted cache, missing tokenizer/config, revision mismatch와 cache escape를 명시적으로 검사한다.

### 4.3 FFmpeg

P03에서 실제 adapter와 함께 설치·검증한다. B05의 `FfmpegRunner`는 media input을 mono 16 kHz s16 WAV로 표준화하기 위해 external executable이 필요하다. faster-whisper의 PyAV decoder가 존재하더라도, B05 pipeline output format contract를 대체하지 않는다.

## 5. Adapter 연결 계약

### 5.1 Ollama QwenRuntime adapter

새 adapter는 아래를 지켜야 한다.

- `complete(prompt: str) -> str`만 제공하고, one prompt당 local `POST /api/chat`을 정확히 한 번 호출한다.
- host는 loopback IPv4/IPv6 allowlist만 허용하며 redirect, HTTPS remote URL, cloud fallback을 사용하지 않는다.
- body는 model tag, user prompt, `stream: false`, no tool call/no file upload 설정을 명시한다.
- timeout, connection failure, malformed JSON, missing `message.content`는 `ModelResponseError`로 원인을 보존해 변환한다.
- `KeyboardInterrupt`와 `SystemExit`은 변환하지 않는다.
- response text는 existing `correct_chunk`/summary JSON validator에 그대로 전달한다.

### 5.2 faster-whisper SttEngine adapter

새 adapter는 아래를 지켜야 한다.

- initialized model object 또는 previously verified local snapshot path만 받는다.
- `transcribe(audio_path)`는 model output generator를 한 번만 소비하고, `text`, `start`, `end`, optional `confidence` mapping sequence로 변환한다.
- input path는 existing `AudioArtifact` path validation 뒤에만 전달된다.
- model load/transcribe/device/runtime 오류는 `TranscriptionError`로 변환한다.
- `KeyboardInterrupt`와 `SystemExit`은 전파한다.
- auto-download option, remote repository ID, raw model output/log은 public pipeline result로 노출하지 않는다.

## 6. P01A·P02·P03의 승인 및 검증 경계

| 단계 | 실제 변경·외부 호출 | 별도 승인 전 금지 | 자동 검증 | 수동 완료 기준 |
|---|---|---|---|---|
| P01A | package/model download, runtime install/register, model home files | real pull/download/network/subprocess | installer/path/hash/health fake tests, repository policy scan | local-only runtime 및 repository-outside paths 확인 |
| P02 | diagnostic CLI와 fake probes | 자동 설치·자동 download | missing dependency / healthy / unsafe path tests | 새 PC에서 diagnostics가 설치 안내와 일치 |
| P03 | Python adapter·CLI code, FFmpeg/STT/Qwen real integration | URL downloader, cloud fallback, persistent DB | adapter unit tests, fake pipeline regression, opt-in real smoke | local media 1건이 safe cleanup과 함께 archived terminal까지 완료 |

P01A를 시작하기 전에 사용자는 다음을 명시적으로 승인해야 한다.

1. Ollama installation/model pull과 faster-whisper package/snapshot download의 network access
2. 정확한 STT snapshot repository ID·immutable revision·license
3. `D:\AI-Legion\Sodam-models` 아래의 예상 대용량 파일 생성
4. local runtime registration/health check와 subprocess 실행

## 7. P01 검증 결과

- 이 문서, 제품화 roadmap, implementation order는 Ollama `qwen3.6:35b-a3b-agent-64k` + faster-whisper `turbo` 선택과 일치한다.
- 실제 Qwen model은 Ollama local store에서 확인했고, STT snapshot과 Python runtime은 repository 밖에 있다.
- 자동 다운로드·원격 endpoint·cloud fallback은 사용하지 않는다.

## 8. 실제 설치·검증 결과 (2026-08-31)

- **Ollama:** existing Windows installation에서 `qwen3.6:35b-a3b-agent-64k`가 사용 가능하며, 실제 E2E는 이 tag로 수행한다. endpoint는 `http://127.0.0.1:11434` loopback이다.
- **Ollama storage:** running local service의 existing repository-outside store `C:\Users\sow20\.ollama\models`를 사용했다. P01A는 service를 중지·재설정하거나 model store를 이동하지 않았다.
- **STT runtime:** `D:\AI-Legion\Sodam-runtime` virtual environment에 `faster-whisper 1.2.1`과 required Hub downloader를 설치했다.
- **STT snapshot:** MIT license의 `dropbox-dash/faster-whisper-large-v3-turbo` commit `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`를 `D:\AI-Legion\Sodam-models\faster-whisper\turbo-0a363e9`에 받았다. `config.json`, `model.bin`, `preprocessor_config.json`, `tokenizer.json`, `vocabulary.json`의 존재를 확인했다.
- **경계:** Git worktree 아래 `Sodam-models`/`Sodam-runtime` directory가 없음을 확인했다. model, Hub cache, Python runtime은 모두 repository 밖에 있다.
- **FFmpeg/STT/E2E:** FFmpeg 9.0.1과 faster-whisper snapshot으로 60초 `both` pipeline을 성공시켰고, 13개 segment·43개 progress event·archived 결과를 확인했다. 5개 영상 품질평가와 Tauri window smoke는 아직 남아 있다.
- **진단 주의:** `tools/doctor.py`는 `SODAM_FFMPEG` 절대 경로를 PATH보다 우선하고 Qwen `qwen3.6:35b-a3b-agent-64k`를 검사한다. 환경변수가 없으면 PATH의 FFmpeg를 검사하므로, 외부 설치 경로를 사용하는 경우 환경변수를 설정한다.
