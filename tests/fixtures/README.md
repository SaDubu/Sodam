# 테스트 데이터 안내

이 폴더에는 외부 모델이나 실제 영상을 실행하지 않고 도구를 검증하기 위한 작은 JSON 예제가 들어 있습니다.

| 경로 | 내용 | 사용처 |
| --- | --- | --- |
| [evaluation_cases.json](evaluation_cases.json) | 원문 일치·보호 토큰 유지·잘못된 자동 승인 계산을 위한 3개 사례 | `tools/evaluate_transcript.py`, `test_evaluate_transcript.py` |
| [inspection_job/](inspection_job/) | 작업 메타데이터, 전사 2구간, 요약, 검토 항목 | `tools/inspect_job.py`, `test_inspect_job.py` |

`evaluation_cases.json`의 문장과 처리 시간은 테스트용 값입니다. 실제 사실이나 모델 품질·속도 측정 결과를 나타내지 않습니다. `inspection_job`은 조회 도구용 최소 예제로, 실제 파이프라인이 저장하는 결과 전체의 대체물이 아닙니다.

## 실행

[루트 README](../../README.md)에 따라 가상환경을 준비한 뒤 저장소 루트에서 실행합니다.

```powershell
& .\.venv\Scripts\python.exe .\tools\evaluate_transcript.py .\tests\fixtures\evaluation_cases.json
& .\.venv\Scripts\python.exe .\tools\inspect_job.py .\tests\fixtures\inspection_job
& .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/unit/test_evaluate_transcript.py tests/unit/test_inspect_job.py
```

## 데이터 관리

사용자 미디어, 모델 가중치, 실제 전사문·작업 결과·인증정보는 이 폴더에 보관하지 않습니다. 새로운 예제는 직접 작성한 최소 데이터로 구성하고, 사용하는 테스트와 함께 유지합니다.
