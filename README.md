# Sodam

YouTube 링크 또는 로컬 영상 파일로부터 한국어 전사문, 요약, 영상 소개글을 만드는 프로그램입니다. 설치형 앱 없이 Python/Tk 창으로 실행합니다.

처리 순서는 소스 획득 → FFmpeg 오디오 추출 → faster-whisper 전사 → Ollama 문맥 교정·검증 → Hermes Agent 요약·소개글 생성 → 결과 저장입니다. 소개글은 질문, 근거 하이라이트, CTA의 3문장을 검증하며, 생성 결과가 기준을 충족하지 못하면 최대 3회 시도하고 실패 내용과 검증 사유를 표시합니다.

## 화면에서 할 수 있는 일

- YouTube URL 입력 또는 로컬 파일 선택
- `summary`, `introduction`, `both` 선택
- 현재 작업, 전체 진행률과 막대, 전체·단계별 경과 시간 확인
- 전사문·요약·소개글·실행 기록 확인, 결과 복사 및 결과 폴더 열기

예상 남은 시간은 표시하지 않습니다. 전체 진행률은 단계별 가중치이며, 새 이벤트가 없는 동안 같은 값에 머물 수 있습니다. 한 번에 한 영상만 처리하고, 실행 중에는 완료 후 창을 닫습니다.

## 1. 새 Windows PC 준비

아래 명령은 **Windows 10/11 x64의 PowerShell** 기준입니다. 별도 Sodam 설치 프로그램, Node/Tauri 빌드는 필요하지 않습니다.

| 구성 요소 | 역할 |
| --- | --- |
| Git | 저장소 받기·업데이트, Hermes의 Git Bash 사용 |
| Python 3.12 x64 + Tcl/Tk | 가상환경과 간단 UI |
| FFmpeg | 영상·오디오 변환 |
| Ollama | 로컬 Qwen 실행 |
| Deno | yt-dlp의 YouTube JavaScript 처리 |
| faster-whisper, yt-dlp | Sodam 가상환경에 설치 |
| Hermes Agent 0.19.0 | 별도 가상환경에 설치하는 생성 에이전트 |

이미 설치된 항목은 건너뜁니다. `winget`이 없다면 각 프로젝트 공식 설치 프로그램을 사용하세요.

```powershell
winget install --id Git.Git --exact
winget install --id Python.Python.3.12 --exact
winget install --id Gyan.FFmpeg --exact
winget install --id Ollama.Ollama --exact
winget install --id DenoLand.Deno --exact
```

설치 후 **새 PowerShell 창**을 열어 PATH를 갱신합니다.

```powershell
git --version
py -3.12 --version
ffmpeg -version
ollama --version
deno --version
```

Qwen 35B 모델은 큰 메모리·디스크 용량을 요구합니다. Ollama의 GPU 지원 및 모델 크기를 확인하고 여유 공간을 확보하세요. 전사 기본값은 CPU/int8이며, 이 안내의 실행 명령에는 CUDA 설치가 필수가 아닙니다. 모델 준비·YouTube 다운로드에는 인터넷이 필요하고, 이후 전사·생성은 이 PC에서 처리합니다.

## 2. 저장소와 가상환경 만들기

아래 예시는 사용자 홈에 저장소를 만듭니다. 다른 위치도 가능하며 기존 저장소가 있으면 `git clone` 대신 그 폴더로 이동하세요.

```powershell
Set-Location $env:USERPROFILE
git clone https://github.com/SaDubu/Sodam.git
Set-Location .\Sodam
$root = (Get-Location).Path

py -3.12 -m venv .venv
$python = Join-Path $root '.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt
& $python -m pip check
& $python -c "import tkinter, faster_whisper, yt_dlp; print('SODAM_READY')"
```

가상환경 활성화 없이 `$python`으로 직접 실행하므로 다른 Python 설치와 혼동하지 않습니다. `pip install .`은 사용하지 마세요. 루트의 `setup.py`는 pip 패키지 설치 파일이 아니라 기존 진단 도구입니다.

## 3. Hermes Agent 설치

Hermes는 모델 이름이 아니라 에이전트입니다. Sodam과 의존성을 분리하기 위해 별도 가상환경에 검증 대상 버전을 설치합니다.

```powershell
py -3.12 -m venv .hermes-venv
$hermesPython = Join-Path $root '.hermes-venv\Scripts\python.exe'
& $hermesPython -m pip install --upgrade pip
& $hermesPython -m pip install 'hermes-agent==0.19.0'
& $hermesPython -m pip check

$hermes = Join-Path $root '.hermes-venv\Scripts\hermes.exe'
$hermesRoot = (& $hermesPython -c "import pathlib, run_agent; print(pathlib.Path(run_agent.__file__).resolve().parent)").Trim()
& $hermes --version
```

버전이 0.19.0인지 확인합니다. `run_agent` import가 실패하면 설치가 완료되지 않은 상태입니다. 기존 Hermes를 사용하려면 `$hermes`, `$hermesPython`, `$hermesRoot`를 **그 설치의 실행 파일·Python·run_agent.py가 있는 폴더**로 바꾸세요. 설치 위치를 다른 사람의 경로 그대로 복사하면 안 됩니다.

현재 Sodam은 Hermes에 로컬 Ollama의 `http://127.0.0.1:11434/v1`을 지정합니다. 다른 클라우드 제공자의 API 키는 이 실행 경로에 필요하지 않습니다.

참고: [Hermes 설치 안내](https://hermes-agent.nousresearch.com/docs/getting-started/installation/), [Hermes 0.19.0 배포](https://pypi.org/project/hermes-agent/0.19.0/).

## 4. Qwen과 전사 모델 준비

Ollama 앱을 실행한 뒤 다음 명령을 수행합니다. 연결되지 않으면 별도 터미널에서 `ollama serve`를 실행하세요.

```powershell
ollama pull qwen3.6:35b-a3b
ollama create qwen3.6:35b-a3b-agent-64k -f .\models\Modelfile.qwen
ollama list
```

`qwen3.6:35b-a3b-agent-64k`는 이 프로그램에서 사용하는 **로컬 사용자 정의 태그**입니다. 공개 모델을 받은 뒤 저장소의 Modelfile로 생성합니다. 이 태그를 바로 `ollama pull`하지 마세요. 실제 호출의 컨텍스트 설정은 Sodam/Hermes의 요청 설정을 따릅니다. [Ollama Qwen 모델](https://ollama.com/library/qwen3.6:35b-a3b)

전사 모델은 저장소 밖에 내려받습니다.

```powershell
$env:SODAM_DATA_ROOT = Join-Path $env:USERPROFILE 'Sodam-data'
$env:SODAM_STT_MODEL = Join-Path $env:SODAM_DATA_ROOT 'models\faster-whisper-turbo'
& $python -c "import os; from faster_whisper.utils import download_model; print(download_model('turbo', output_dir=os.environ['SODAM_STT_MODEL']))"
& $python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['SODAM_STT_MODEL'], device='cpu', compute_type='int8', local_files_only=True); print('STT_READY')"
```

이 단계에서 모델을 한 번 다운로드합니다. Sodam 작업 중에는 준비된 로컬 모델만 읽습니다. [faster-whisper 안내](https://github.com/SYSTRAN/faster-whisper)

## 5. UI 실행

새 터미널을 열었을 때도 다음 블록을 사용할 수 있습니다. 먼저 저장소 폴더로 이동하세요.

```powershell
Set-Location (Join-Path $env:USERPROFILE 'Sodam')
$root = (Get-Location).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$hermesPython = Join-Path $root '.hermes-venv\Scripts\python.exe'
$hermes = Join-Path $root '.hermes-venv\Scripts\hermes.exe'
$hermesRoot = (& $hermesPython -c "import pathlib, run_agent; print(pathlib.Path(run_agent.__file__).resolve().parent)").Trim()

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$guiOptions = @{
    PythonPath = $python
    HermesCommand = $hermes
    HermesPython = $hermesPython
    HermesRoot = $hermesRoot
}
& .\tools\start_simple_gui.ps1 @guiOptions
```

실행 정책 변경과 UI 실행은 **서로 다른 명령**입니다. `Set-ExecutionPolicy ... Bypass .\tools\...`처럼 한 줄로 합치면 안 됩니다. Process 범위 설정은 현재 터미널을 닫으면 끝납니다.

조직 정책으로 PowerShell 스크립트가 차단된 경우 Python으로 직접 실행할 수 있습니다.

```powershell
& $python .\tools\simple_gui.py --python-path $python --hermes-command $hermes --hermes-python $hermesPython --hermes-root $hermesRoot
```

입력은 `https://www.youtube.com/watch?v=영상ID` 같은 **원래 URL** 또는 `C:\Videos\sample.mp4` 같은 로컬 절대 경로입니다. Markdown 링크 표현인 `[주소](주소)`는 입력하지 않습니다.

## 경로 변경과 기존 설치 사용

기본 모델·작업 데이터는 `%USERPROFILE%\Sodam-data`에 저장됩니다. 환경변수는 **UI 실행 전에** 설정해야 하며 이 예시는 현재 터미널에만 적용됩니다.

```powershell
$env:SODAM_DATA_ROOT = 'E:\Sodam-data'
$env:SODAM_STT_MODEL = 'E:\Models\faster-whisper-turbo'
$env:SODAM_RESULT_ROOT = 'E:\Sodam-results'
```

| 설정 | 기본값 / 의미 |
| --- | --- |
| `SODAM_DATA_ROOT` | 사용자 홈의 `Sodam-data`; 임시 파일은 `tmp\jobs` 하위 |
| `SODAM_STT_MODEL` | 데이터 루트의 `models\faster-whisper-turbo` |
| `SODAM_RESULT_ROOT` | 데이터 루트의 `jobs` |
| 런처 `-PythonPath` | 저장소의 `.venv\Scripts\python.exe` |
| 런처 `-ResultRoot` | 지정하면 환경변수보다 우선하며 자식 CLI에도 전달 |
| FFmpeg | PATH에 있는 `ffmpeg`; 설치 폴더의 `bin`을 PATH에 추가 가능 |

기존에 다른 위치의 가상환경·모델을 사용했다면 다시 설치할 필요 없이 위 환경변수와 런처 인자를 기존 경로로 지정합니다. **이전 결과는 자동 이동하지 않습니다.** 예전 결과를 보려면 그 저장 위치를 사용하세요.

## CLI 실행과 결과 확인

UI와 같은 준비가 끝난 PowerShell에서 실행합니다.

```powershell
$options = @(
    '--mode', 'run',
    '--output-mode', 'both',
    '--generation-backend', 'hermes',
    '--hermes-command', $hermes,
    '--hermes-python', $hermesPython,
    '--hermes-root', $hermesRoot
)
& $python .\tools\run_local.py @options 'C:\Videos\sample.mp4'
& $python .\tools\run_local.py @options --allow-url 'https://www.youtube.com/watch?v=VIDEO_ID'
```

최종 JSON은 stdout, 진행·오류는 stderr에 출력됩니다. 결과 JSON의 `result_path`가 실제 저장 폴더입니다.

```powershell
& $python .\tools\inspect_job.py 'C:\Users\YOUR_NAME\Sodam-data\jobs\JOB_ID'
```

모델 출력은 사람의 검토가 필요합니다. 성공 여부와 별도로 전사 정확도, 고유명사, 요약과 소개글의 사실관계를 확인하세요.

## 문제 해결

| 증상 | 확인할 내용 |
| --- | --- |
| Python/Tk import 오류 | Python 3.12의 Tcl/Tk 설치 및 `.venv`의 Python 사용 여부 |
| FFmpeg를 찾지 못함 | 새 터미널에서 `ffmpeg -version` 확인 |
| STT 모델 경로 오류 | 다운로드 완료 여부와 `SODAM_STT_MODEL` 값 |
| Ollama 연결·모델 오류 | Ollama 실행 및 `ollama list`의 사용자 정의 태그 확인 |
| Hermes incompatible | 버전 0.19.0, 실행 파일과 Python이 같은 설치인지, `run_agent.py` 경로 확인 |
| YouTube 소스 획득 실패 | URL, 네트워크·영상 접근 권한, Deno/PATH, `& $python -m pip install -U "yt-dlp[default]"` |
| 생성 검증 실패 | 실행 기록의 실패 내용·검증 기준 확인; 전사 자체가 부정확할 수도 있음 |
| 새 PC에서 예전 D: 경로를 찾음 | 저장소 업데이트 여부 및 남아 있는 런처 인자·환경변수 확인 |

## 개발·저장소 관리

```powershell
& $python -m pip install -r requirements-dev.txt
& $python -B -m pytest -q -p no:cacheprovider
git diff --check
git pull --ff-only
```

## 문서 안내

| 문서 | 용도 |
| --- | --- |
| 이 README | Windows 설치, 가상환경, Tk UI·CLI 실행 |
| [Tauri UI 개발 안내](apps/desktop/README.md) | 별도 Tauri UI의 현재 범위와 빌드 방법 |
| [테스트 데이터 안내](tests/fixtures/README.md) | 공개 JSON 예제와 검증 명령 |

`apps/desktop`의 Tauri UI는 Tk UI와 기능 범위가 다릅니다. 일반 실행에는 이 README의 `start_simple_gui.ps1`을 사용하세요.

공개 저장소에는 실행 코드, 테스트, 설치 안내, 모델 설정만 보관합니다. 모델 가중치·미디어·전사 결과·가상환경·비밀값은 커밋하지 않습니다. 설계·명세·작업지시·분석 문서는 로컬의 `.local/work-docs/`에 따로 보관하며 Git에서 제외합니다. 런타임이 읽는 `backend/prompts/introduction.md`는 제품 기능에 필요한 파일이므로 포함합니다.

`.gitignore`는 이미 커밋된 파일의 과거 이력을 삭제하지 않습니다. 공개 이력 정리가 필요하면 별도의 이력 재작성 작업이 필요합니다.
