# Sodam 데스크톱 UI

`apps/desktop`은 진행률·취소·결과 탭을 표시하기 위한 Tauri shell과 순수 TypeScript 상태 계층을 포함합니다. 화면은 backend와 구조화 IPC로 연결되며 frontend가 직접 파일·모델·네트워크에 접근하지 않습니다.

## 개발 확인

```powershell
npm ci
npm run check
npm test
npm run build
npm run tauri:check
```

`npm test`는 Node 내장 test runner를 사용하고, `npm run build`는 무시되는 `dist/`만 생성합니다. `tauri:check`와 bundle은 Rust stable, MSVC C++ Build Tools, Windows SDK가 필요합니다.

## 화면 계약

- `summary`, `introduction`, `both` output mode를 선택합니다.
- 단계별 상태·완료율·경과 시간·ETA(계산 불가 시 “계산 중”)·로그를 보여 줍니다.
- 취소는 idempotent command이며 terminal job에는 중복 요청을 보내지 않습니다.
- 전사문, 요약, 소개글, review 탭은 persisted 결과 DTO만 표시합니다.

현재 CLI와 backend는 실제 로컬 미디어·Qwen pipeline을 실행할 수 있습니다. debug 실행 파일을 실제로 시작해 5초간 프로세스가 유지되는 smoke는 통과했지만, 화면의 시각·키보드 상호작용과 서명된 installer 설치 smoke는 아직 확인하지 않았습니다. 문서의 설치물은 unsigned CI 후보로 취급하고, 서명·배포 완료로 간주하지 마세요.
