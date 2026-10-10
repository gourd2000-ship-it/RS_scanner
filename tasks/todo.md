# MA50·ATR14 백테스트 운영 검증 작업 목록

계획: [plan.md](plan.md). 아래 작업은 모두 미착수이며 선행 조건과 계획의 운영 경계를 따른다.

## T1 — 현재 운영 상태 확인

- [ ] 조회 시각, 최신 crawl/validation job·판정, writer, migration revision, 기능 활성화 여부를 읽기 전용으로 기록한다.
- [ ] 두 지표의 current generation 날짜·상태 수량, source 관측, dataset·RS·snapshot 상태를 대조한다.
- [ ] job_137과 최신 상태의 차이 및 미확인 항목을 구분한다.

검증: read-only transaction과 조회 범위를 기록하고 수량·식별자를 대조한다. 연결이 없으면 보관본으로 현재 상태를 확정하지 않는다.
선행: 없음. 규모: S. 예상 파일: `reports/operations/` 현황 보고서, 필요 시 `docs/tracking/findings.md`.

## T2 — 품질 실패 원인과 제한 재처리안

- [ ] 실패 target·case와 원천 관측·identity를 연결해 원인별 수량, 겹치는 종목, 미확인 원인을 정리한다.
- [ ] 양수 OHLC, 순서 모순, stale, missing, extreme return 표본을 검토하고 품질 규칙을 유지한다.
- [ ] 대상·기간·source·예상 행·근거·중단/재개 방법을 가진 manifest를 만든다. 해소된 문제는 재처리에서 제외한다.

검증: 실패 건수와 고유 종목 수를 별도 대사하고 표본별 근거 또는 부재를 확인한다. 공급자 재요청은 이 읽기 전용 단계에 포함하지 않는다.
선행: T1. 규모: M. 예상 파일: 원인 보고서, 재처리 manifest, findings.

### 점검 — 조사 완료

- [ ] 최신 근거와 미확인 항목이 구분돼 있다.
- [ ] 재처리 대상·예상 영향이 구체적이고 운영 쓰기는 수행하지 않았다.

## T3 — 운영 입력 준비 진입점 정리

- [ ] dataset 생성, dataset RS 계산, 두 지표 snapshot 생성의 실행 경로를 확인한다.
- [ ] 부족한 연결만 보완한다. 기본 dry-run, dataset/원본 run ID·hash 고정, 명시 apply, 실패 재개를 지원한다.
- [ ] source 불일치·근거 누락은 거부하고 완료 snapshot 재사용과 기존 결과 보존을 보장한다.

검증: 격리 DB에서 dry-run 전후 불변, 동일 manifest 재사용, 입력 drift 거부를 확인한다. 기존 서비스 결함은 별도 작은 수정 작업으로 나눈다.
선행: 코드 조사 즉시 가능, 운영 manifest는 T1 이후. 규모: M. 예상 파일: 필요한 `scripts/` 진입점, 관련 테스트, operations (3~5개 이내).

## T4 — 두 지표 PostgreSQL 전체 흐름 검증

- [ ] 격리 DB에서 source evidence→complete dataset·RS·두 snapshot→두 조건 요청→worker→결과 API를 검증한다.
- [ ] 불일치·warming_up·data_unavailable 거부와 이후 generation 변경에도 과거 실행이 유지됨을 확인한다.
- [ ] 빈 DB/기존 표본 migration, 고정 입력 replay, 동시 claim·중단 복구를 확인한다.

검증: `tests/integration/test_backtest_worker_postgres.py`와 관련 snapshot migration·replay 테스트를 전용 테스트 DB에서 실행한다. 변경 경로의 단위/API 테스트를 추가하고 화면을 변경한 경우 frontend 검증을 수행한다.
선행: T3. 규모: M. 예상 파일: PostgreSQL worker/fixture, 필요한 snapshot 테스트, 격리 검증 보고서 (3~5개 이내).

### 점검 — 운영 실행안 준비

- [ ] 원인 조사와 두 지표 PostgreSQL 검증이 갖춰졌다.
- [ ] 실제 쓰기 대상·영향·중단/재개 절차를 제시한다. AGENTS.md에 따른 운영 결정 이후 T5를 실행한다.

## T5 — 제한 재처리와 새 품질 검증

- [ ] 승인 대상만 재처리하고 원천·기존 결과·실패 이력을 보존한다. 근거 없는 가격 보정은 하지 않는다.
- [ ] 새 validation 보고서와 전후 수량을 대조한다. report_only도 운영 쓰기로 취급한다.
- [ ] 해당 범위의 passed/passed_with_warnings와 남은 경고·제외 사유를 기록한다. blocked면 후속 운영 단계를 중단한다.

검증: 승인 manifest, 새 run ID·품질 수량, source/identity 보존 대조. 최신 판정이 이미 통과했다면 재수집 대신 그 근거를 기록한다.
선행: T2, 관련 코드 검증, 운영 결정. 규모: M. 예상 파일: 실행·품질 보고서, 필요한 checkpoint, findings (3~5개 이내).

## T6 — 최초 complete dataset·지표 입력 발행

- [ ] 필요한 migration만 검증된 절차로 적용하고 승인된 complete 종목·연도와 준비 이력에 맞춰 입력 범위를 고정한다.
- [ ] dataset·RS·두 snapshot·benchmark ID/hash, 가용성, source 일치를 대조한다.
- [ ] 동일 조건 replay 두 번의 hash 일치, 페이지 누락/중복 없음, 실제 HTTP 인증·cursor 계약을 확인한다.

검증: `scripts/create_clean_backtest_dataset.py`, T3의 준비 절차, `scripts/replay_backtest_dataset.py`를 승인 범위에서 실행하고 건수를 manifest와 대조한다.
선행: T4, T5 통과와 범위별 complete 감사, migration/발행 운영 결정. 규모: M. 예상 파일: 감사 manifest, 발행·replay 결과, 운영 기록 (3~5개 이내).

## T7 — 실제 워커 1건 실행·재현

- [ ] queue/running 상태를 확인하고 승인된 전략 요청 한 건을 단일 worker로 처리한다.
- [ ] 입력 ID/hash와 결과 API, 주문·거래·자산 곡선을 대조한다.
- [ ] 모든 입력을 고정한 추가 실행에서 업무 결과가 일치함을 확인한다.

검증: `scripts/run_backtest_worker.py` 기본 1건 실행, 두 run 결과 비교, 잔류 running/부분 결과 확인. 강제 종료 실험은 격리 환경에서만 수행한다.
선행: T6, 운영 실행 결정. 규모: S. 예상 파일: 실행·재현 보고서, `docs/tracking/status.md`.

## T8 — 일일 지표 단계적 활성화

- [ ] 정책·해당 거래일 관측·품질 통과를 확인하고 승인된 배치 환경에서 MA50 다음 ATR14 순서로 활성화·검증한다.
- [ ] 기본 3개 거래일 동안 증분, 동일 입력 재사용, 처리 시간·실패·checkpoint를 관측한다. 과거 근거 변경과 blocked 거부는 격리 테스트로 확인한다.
- [ ] 정상 시 정기 실행을 적용하고 운영 상태를 갱신한다. 정기 backtest worker 스케줄은 별도 필요성과 실행 범위가 정해진 경우에만 추가한다.

검증: 일자별 validation/run/checkpoint/source 대조, 중복 writer 없음, 오류 시 후속 호출 중단과 원본 보존 확인.
선행: T5, T7, 일일 활성화 결정. 규모: M. 예상 파일: 배치 설정, 관측 보고서, operations, status.

### 점검 — 완료

- [ ] 운영 backtest와 고정 입력 재현이 통과했다.
- [ ] 일일 갱신 관측과 실패 중단/재개 절차를 확인했다.
- [ ] 생존 lifecycle·complete 제한과 미해결 문제를 결과·운영 문서에 명시했다.
