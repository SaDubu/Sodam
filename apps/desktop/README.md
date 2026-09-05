# Tauri UI 개발 안내

이 폴더는 별도의 Tauri 데스크톱 UI 소스입니다. 일반 사용을 위한 Python/Tk UI 설치와 실행은 [루트 README](../../README.md)를 따르세요. Tk UI에는 이 폴더의 빌드가 필요하지 않습니다.

## 현재 구현 범위

| 항목 | 이 Tauri UI의 동작 |
| --- | --- |
| 입력 | 파일 선택창을 통한 로컬 미디어 입력 |
| 생성 | CLI의 기본 direct Ollama 경로; Hermes 옵션을 전달하지 않음 |
| 출력 | `summary`, `introduction`, `both` 및 전사·검토 탭 |
| 진행 표시 | 현재 단계, 진행률, 경과 시간, ETA 표시 |

루트 README의 YouTube 입력·Hermes 생성·ETA 없는 진행 표시는 Tk UI 기준입니다. 두 UI는 실행 진입점과 제공 기능이 다릅니다.

## 프런트엔드 검증

Node.js와 npm을 준비한 뒤 **저장소 루트에서** 실행합니다. 사용되는 의존성은 [package.json](package.json)과 lockfile에 정의되어 있습니다.

```powershell
Set-Location .\apps\desktop
npm ci
npm run check
npm test
npm run build
```

`check`는 TypeScript 검사, `test`는 Node 계약 테스트, `build`는 프런트엔드 정적 파일 생성입니다. `dist/`는 Git에서 제외되며 다시 빌드할 수 있습니다. 이 검사들의 성공이 Rust 빌드나 실제 창의 정상 동작까지 보장하지는 않습니다.

## Windows 실행 파일 빌드

위 프런트엔드 도구 외에 Rust stable, MSVC C++ Build Tools, Windows SDK가 필요합니다. `apps/desktop` 폴더에서 실행합니다.

```powershell
npm run tauri:check
```

명령 이름과 달리 실제 작업은 `tauri build --debug --no-bundle`입니다. 성공하면 기본 Cargo 출력 경로에 `src-tauri/target/debug/sodam-desktop.exe`가 생성됩니다. Python, FFmpeg, STT 모델과 Ollama는 별도로 준비해야 합니다.

이미 빌드된 실행 파일을 시작하는 런처는 [tools/start_desktop.ps1](../../tools/start_desktop.ps1)입니다. 필수 인자는 `-PythonPath`, `-FfmpegPath`, `-SttModelPath`이며, `-DesktopExecutable`로 빌드 결과를 지정할 수 있습니다. `-WhatIf`는 경로와 로컬 모델 준비 여부를 검사하되 창을 시작하지 않습니다.

## 배포 상태

[CI 설정](../../.github/workflows/desktop-build.yml)은 Windows NSIS, macOS DMG, Linux AppImage 빌드를 정의합니다. 생성물은 서명되지 않은 빌드 산출물이며, 새 PC에서 설치·실행 검증을 마친 공식 배포판으로 간주하지 않습니다.
