# 거래량 MA50·ATR14 백테스트 실행 준비 보고서

- 작성일: 2026-10-09
- 판정: **코드 구현 및 격리 검증 완료 / 운영 활성화 차단**
- 근거 범위: 저장소 코드·테스트·보관된 감사 보고서

## 확인 결과

백테스트 시뮬레이터, 실행 요청·결과 조회 API, 거래량 MA50·ATR14 전략 비교 조건과 고정 snapshot, 운영자 전용 지표 조회, `/backtests` 화면, 명시적 실행 워커 CLI가 코드에 연결돼 있다. MA50·ATR14를 사용하는 요청은 필요한 날짜별 값과 입력 근거가 모두 사용 가능할 때만 queue에 들어간다. 실행은 저장된 snapshot ID/hash를 사용한다.

워커는 API 시작 시 자동 실행되지 않는다. 지표 일일 계산 설정은 기본 비활성이다. 이번 확인에서 운영 워커를 실행하거나 일일 지표 설정을 켜지 않았다.

## 데이터 품질 차단

현재 확인 가능한 최신 품질 근거는 보관 보고서 [`job_137.json`](../data_quality/job_137.json)이다. 이 보고서는 2026-10-08 일일 validation에서 coverage 94.8169%, stale 종목 201개, 입력 검증 실패 206건으로 `blocked` 판정을 기록한다. 실패 206건은 양수 OHLC 위반 188건과 OHLC 순서 모순 18건으로 분류됐다. 보고서는 실패 target의 원문 payload나 공급자 귀속 근거를 제공하지 않는다.

이 자료는 보관본이며 운영 DB의 현재 상태를 조회한 결과가 아니다. 새 품질 보고서가 통과하기 전에는 MA50·ATR14 일일 계산, 해당 데이터를 쓰는 운영 백테스트, 새 dataset 발행을 활성화할 수 없다.

백필 기록상 거래량 MA50은 2,175개 대상, 7,303,650개 value로 대조 완료됐다. ATR14도 승인 manifest 기준 2,175개 대상과 input/result 각 7,303,650행, 상태 수량 및 hash 대조 기록이 있다. 이 과거 대조는 오늘 운영 DB의 실시간 재확인을 뜻하지 않는다.

## 검증

| 확인 | 결과 |
|---|---|
| 기본 단위 selector `pytest -m 'not integration and not api'` | 562 passed, 205 deselected |
| 기존 API 통합 suite, 임시 PostgreSQL schema | 60 passed |
| 백테스트 API·지표 조회·MA50 preflight→worker→결과 API 테스트 | 14 passed |
| MA50/ATR14 snapshot·run migration 및 PostgreSQL worker 흐름 | 6 passed |
| Python compile, `git diff --check` | 통과 |
| 프런트엔드 lint·production build | 통과, `/backtests` route 생성 확인 |

PostgreSQL 검증은 전용 로컬 `localhost:5433/rs_scanner_test`의 임시 schema를 사용하고 종료 시 삭제했다. MA50 snapshot을 포함한 요청→사전 점검→워커→결과 조회는 SQLite 격리 테스트에서, complete dataset을 사용한 API 요청→워커→결과 조회와 동시 claim은 PostgreSQL 격리 테스트에서 확인했다. 실제 발행 dataset을 이용한 운영 replay는 수행하지 않았다.

## 실행 전 다음 단계

1. 실패 target과 stale case를 읽기 전용으로 원천 관측·identity·validation 근거와 대조한다. 양수·OHLC 검증을 낮추거나 근거 없는 가격 보정을 하지 않는다.
2. 원인과 재처리 범위를 운영자가 결정한 뒤 제한 표본 검증 및 새 품질 보고서를 만든다. 새 보고서가 통과하기 전까지 지표 계산과 dataset 발행을 보류한다.
3. 격리 PostgreSQL에서 migration 상태, snapshot 일치, replay와 필요한 실행 범위를 다시 확인한다. 운영 dataset은 `complete` segment만 대상으로 별도 승인된 절차로 발행한다.
4. 실제 운영 dataset의 replay·coverage 검증이 통과하고 운영 결정이 내려진 뒤에만 별도 배치 환경에 워커를 배포한다. 워커 명령은 문서화된 명시 실행으로 시작하고 자동 시작 설정은 추가하지 않는다.

## 중단·재개·되돌림

- 품질 validation이 없거나 `blocked`이면 일일 지표 설정을 계속 비활성으로 두고 batch를 진행하지 않는다. 실패 원인을 확인하기 전에는 checkpoint를 완료 처리하거나 과거 evidence를 덮어쓰지 않는다.
- 명시 실행한 워커를 중단하면 해당 프로세스가 종료됐는지 확인한다. `running` run에 결과 행이 없을 때만 `scripts/run_backtest_worker.py --fail-stale-run RUN_ID --confirm-worker-stopped`로 실패 상태를 기록할 수 있다. 이 명령은 run을 재실행하지 않는다. 필요하면 원인 검토 후 새 run을 요청한다.
- 재개는 같은 입력·정책·checkpoint와 단일 writer를 확인한 후 진행한다. 과거 결과·지표 snapshot·dataset을 수정하거나 지우지 않는다.
- 되돌림이 필요하면 향후 지표 설정을 비활성으로 유지하고 추가 batch/worker 호출을 멈춘다. 기존 run과 evidence는 보존한다. schema 문제는 기존 revision을 편집하지 않고 검증된 새 forward migration으로 처리한다.

## 작업 범위 기록

이번 실행은 운영 DB에 연결하거나 쓰지 않았고, migration을 운영 환경에 적용하지 않았으며, dataset을 발행하지 않았다. 상장폐지 lifecycle과 identity 미확인 lifecycle은 계속 백테스트 입력 범위 밖이다. 운영 활성화 여부는 새 품질 근거와 별도 운영 결정이 나온 뒤 다시 판단해야 한다.
