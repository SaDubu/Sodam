# CI-01 — Desktop GitHub Actions 교정

## 작업 ID와 목적

- 작업 ID: CI-01
- 목적: `desktop-build` GitHub Actions가 Windows, Ubuntu, macOS에서
  동일한 desktop 계약 테스트와 Tauri 번들을 실행할 수 있게 한다.
- 배경: run `33421283486`에서 Windows는 PowerShell의 test glob 처리로,
  Ubuntu/macOS는 Tauri 기본 PNG 아이콘 누락으로 실패했다.

## 수정 허용 범위

- `apps/desktop/package.json`
- `apps/desktop/src-tauri/tauri.conf.json`
- `apps/desktop/src-tauri/icons/` 안의 platform icon assets
- `apps/desktop/tests/build-contract.test.mjs`
- `docs/ai/04-implementation-order.md`
- `Statement_of_Functions.md`

수정 금지: Python backend, product logic, model/runtime 설정, workflows의
trigger/권한, dependency version, signing, installer 배포, 실제 모델·미디어 실행.

## 구현 계약

### 1. 플랫폼 중립 Node 테스트 실행

- `npm test`는 PowerShell, sh, zsh에서 모두 동작해야 한다.
- shell glob expansion에 의존하지 않고 `apps/desktop/tests`의 기존
  `*.test.mjs` 파일을 Node test runner가 발견하게 한다.
- 테스트 파일의 이름·테스트 의미를 바꾸지 않는다.

### 2. Tauri 아이콘 집합

- 기존 `icons/icon.ico`의 브랜드 이미지를 source로 사용한다.
- Tauri가 요구하는 `icons/icon.png`, `icons/32x32.png`,
  `icons/128x128.png`, `icons/128x128@2x.png`, `icons/icon.icns`,
  `icons/icon.ico`를 repository에 둔다.
- `tauri.conf.json`의 `bundle.icon`은 위 desktop icon set을 명시한다.
- PNG는 square RGBA 32-bit이고, macOS용 ICNS와 Windows용 ICO는
  각 platform build에 사용 가능해야 한다.
- model·media·개인 데이터·certificate를 icon asset에 포함하지 않는다.

## 테스트와 완료 기준

다음을 실행한다.

```powershell
npm --prefix apps/desktop test
npm --prefix apps/desktop run check
npm --prefix apps/desktop run build
git diff --check
```

추가 정적 검증:

- package test script가 `tests/*.test.mjs` shell glob을 쓰지 않는다.
- config가 Tauri의 다중 platform icon set을 모두 가리킨다.
- icon 파일 모두 존재하고 비어 있지 않다.

수동 검증:

- GitHub Actions 재실행에서 Windows의 test step이 통과하고,
  Linux/macOS가 icon missing 오류 없이 bundle 단계로 진입한다.

## 구현하지 않을 범위

- 실제 NSIS/MSI/DMG/AppImage 설치·서명·배포
- Python backend 또는 local model smoke
- GitHub release 생성

## 보고

- 수정 파일 및 icon set 목록
- 로컬 Node/TypeScript/build/diff 결과
- GitHub Actions 재실행 결과
- 남은 platform-specific bundle·signing 위험
