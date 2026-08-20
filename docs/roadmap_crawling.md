# RS Scanner 크롤링 개선 및 Hermes 연동 로드맵

> **2026-08-15 전환 안내:** 아래 repair queue·Kiwoom fallback 내용은 전환 기간의 레거시 기록입니다. 현재 기본 흐름은 배치별 `crawl_quality_reports`를 남기고, 사용자가 요청한 주간 분석에서만 Sam이 제한된 Kiwoom 표본을 검증하는 방식입니다. 운영 계약은 [주간 크롤링 품질 분석 PRD](prd-weekly-crawl-quality-analysis.md)를 기준으로 합니다.

상태: PostgreSQL migration·Repair API·reconciler·synthetic canary 완료 (실제 Sam Kiwoom canary 대기)
작성일: 2026-08-14
상세 요구사항: [분석 후속 PRD](prd-crawl-analysis-followup.md), [기반 PRD](prd-crawling-reliability-hermes.md)

실행 현황 (2026-08-14): Naver 주 수집 경로, Kiwoom 보조 공급자 코드, Sam의
`kiwoom-ohlc-query` 읽기 전용 스킬, 기존 Hermes read-only API 서버 기반이 준비되어 있다.
다음 autobot 작업은 공유 폴더 브리지를 확장하는 것이 아니라 PostgreSQL repair request/attempt/result,
Sam 전용 Repair API, 결과 reconciler를 운영 경계에 연결하는 것이다. 코드·contract test는
구현했고 운영 PostgreSQL migration과 PostgreSQL 기반 synthetic API round trip까지 검증했다.
실제 Sam의 `kiwoomcli` 호출을 포함한 staging canary는 아직 남아 있다.

## 1. 목표

이 로드맵은 다음 두 가지 결과를 달성하기 위한 실행 순서다.

1. 종목별 가격 수집 누락을 탐지하고 원인을 추적할 수 있게 한다.
2. 검증된 RS 데이터를 Hermes Agent에 인증된 읽기 전용 API로 제공한다.

작업 원칙은 관측 가능성과 데이터 완전성을 먼저 확보하고, 그다음 속도와 외부 API를 개선하는 것이다. RS 계산 산식과 기존 프론트엔드 API는 유지한다.

## 2. 현재 진단

| 영역 | 현재 문제 | 우선순위 |
|---|---|---|
| 파서 | fchart 오류가 빈 목록으로 변환되어 신규 데이터 없음과 구분되지 않음 | P0 |
| 실패 기록 | 가격 실패 호출부가 URL을 전달하지 않아 failure insert가 실패할 수 있음 | P0 |
| 배치 통계 | 일부 실패가 있어도 symbols_failed=0으로 완료될 수 있음 | P0 |
| 종목 universe | 목록에서 사라진 종목을 inactive로 reconcile하지 않음 | P1 |
| 수집 대상 | inactive, ETF, ETN까지 가격 요청 대상에 포함될 수 있음 | P1 |
| 기업 액션 | BatchContext에 price_source가 없어 수정주가 재수집이 연결되지 않음 | P1 |
| 성능 | 종목별 순차 요청과 0.8~2.5초 지연으로 실행 시간이 길어짐 | P1 |
| Hermes 제공 | 인증·버전·coverage·신선도 메타데이터를 가진 Agent API가 없음 | P1 |
| 복구 전달 경로 | 파일 공유 권한·세션 문제로 Sam 결과 전달이 운영상 불안정함 | P0 |
| 복구 무결성 | Kiwoom 결과를 queue에 기록하고 canonical 반영하기 위한 상태·lease·idempotency가 없음 | P0 |
| API 경계 | 기존 Agent API는 읽기 전용이며 Sam용 repair mutation scope/endpoint가 없음 | P0 |

## 3. 상태 정의

각 eligible 종목은 배치 종료 시 아래 상태 중 하나를 가져야 한다.

- fetched: 유효한 행을 수신하고 DB 저장까지 완료
- no_new_data: 응답은 유효하지만 신규 거래일이 없음
- partial: 일부 행만 유효하거나 일부 저장에 문제가 있음
- failed: HTTP, 파싱, 검증, DB 저장 중 실패
- skipped: 정책상 수집하지 않음

배치 통계 불변식:

    total = fetched + no_new_data + partial + failed + skipped

## 4. Phase 0 - 기준선과 계약 확정

목표: 수정 전후를 비교할 수 있는 기준선과 상태 계약을 확정한다.

### CRAWL-00 기준선 수집

- [x] 최근 3회 배치의 대상 종목 수와 실행 시간 기록
- [ ] 최근 3회 배치의 요청 수와 재시도 수를 실제 운영 로그로 보완
- [x] 시장별 active stock, ETF, ETN, inactive 수량 기록
- [x] 최근 거래일, coverage rate, 반복 실패 종목 목록 추출
- [ ] 2,400종목·약 2시간 수치를 실제 운영 로그로 검증

수집기: `scripts/collect_crawl_baseline.py`  
최근 개발 DB 결과: [reports/crawl_baseline.json](../reports/crawl_baseline.json). 과거 배치에
`crawl_target_results`가 없었던 항목의 요청·재시도 수는 측정 불가로 `null` 처리한다.

완료 기준:

- 배치별 기준선 보고서가 저장되어 있다.
- 아래 Phase의 성능·coverage 비교에 사용할 수 있다.

### CRAWL-01 상태·오류 taxonomy 확정

- [x] fetched, no_new_data, partial, failed, skipped 정의
- [x] 오류 단계 정의: universe, request, parse, validate, persist, corporate_action
- [x] 재시도 가능한 오류와 즉시 실패 오류 구분
- [x] 민감정보를 제외한 실패 메타데이터 정의

의존성: 없음  
예상 작업량: 0.5~1일

## 5. Phase 1 - P0 누락 방지와 관측 가능성

목표: 실패가 성공이나 신규 데이터 없음으로 숨겨지지 않게 한다.

### CRAWL-02 파서 결과 계약 변경

- [x] parse_fchart_prices()의 빈 응답 처리 정책 분리
- [x] JSONDecodeError, 응답 구조 오류, 무효 행을 typed exception으로 표현
- [x] 유효 행 일부와 폐기 행 수를 partial 결과로 표현
- [x] HTTP 응답 URL·상태·응답 크기를 fetch 결과에 포함

관련 코드:

- app/crawler/parsers/fchart.py
- app/crawler/sources/base.py
- app/crawler/sources/naver.py
- app/services/batch/sync_prices.py

완료 기준:

- 잘못된 JSON이 no_new_data 또는 성공으로 저장되지 않는다.
- empty valid response와 malformed response에 서로 다른 테스트가 있다.

### CRAWL-03 실패 기록 보장

- [x] 모든 failure record에 source URL 전달
- [x] CrawlFailure 모델, repository, API schema의 nullable 계약 일치
- [x] failure insert를 savepoint 또는 별도 transaction으로 보호
- [x] failure 저장 자체의 오류를 별도 log/metric으로 남김
- [x] error_message에 토큰과 원본 응답 본문이 포함되지 않도록 정제

관련 코드:

- app/models/crawl_failure.py
- app/repositories/crawl_failure_repository.py
- app/services/batch/sync_prices.py
- app/api/v1/endpoints/crawl.py

완료 기준:

- 실패한 종목의 URL, HTTP status, error class, retry count를 Operations API에서 조회한다.
- 원래 크롤링 실패가 failure insert 실패 때문에 사라지지 않는다.

### CRAWL-04 종목별 결과와 통계 정합성

- [x] crawl_target_results 모델·migration·repository 추가
- [x] attempt와 최종 결과를 종목·단계별 저장
- [x] crawl_jobs에 completed_with_errors 상태 추가
- [x] symbols_succeeded/symbols_failed를 실제 가격 단계 결과에서 계산
- [x] 청크 checkpoint에 처리·실패·재시도 대상 수 기록
- [x] 실패 종목만 재수집할 수 있는 내부 서비스 추가

관련 코드:

- app/models/crawl_job.py
- app/services/batch/orchestrator.py
- app/services/batch/sync_prices.py
- alembic/

완료 기준:

- 부분 실패 배치가 성공률 100%로 보이지 않는다.
- 배치 종료 시 상태 합계 불변식이 검증된다.
- 재시작 후 이미 성공한 종목과 실패 종목이 혼동되지 않는다.

예상 기간: CRAWL-02~04 합계 3~5일  
Gate 1: P0 단위·통합 테스트 통과 후 다음 Phase로 이동

## 6. Phase 2 - 종목 universe와 RS 대상 정합성

목표: 오래된 종목을 반복 요청하지 않고, 부분 목록 수집으로 정상 종목을 잘못 비활성화하지 않는다.

### CRAWL-05 universe snapshot

- [x] 시장별 페이지 수집 완료 여부 기록
- [x] 중복, 필수 필드, 최소 건수, 페이지 종료 조건 검증
- [x] symbol_universe_snapshots 모델·migration 추가
- [x] symbols에 last_seen_at과 snapshot ID 저장
- [x] snapshot이 completed일 때만 누락 종목 inactive 처리
- [x] partial/failed snapshot은 기존 active 상태 유지
- [x] inactive 처리 전 dry-run 목록을 Operations에서 확인 가능하게 함

관련 코드:

- app/services/batch/sync_symbols.py
- app/repositories/symbol_repository.py
- app/models/symbol.py
- 신규 symbol_universe_snapshot 모델

완료 기준:

- 완전한 snapshot에서 사라진 종목은 is_active=False와 delisted_at을 갖는다.
- 수집 중간 오류가 발생한 날에는 기존 정상 종목이 비활성화되지 않는다.

### CRAWL-06 가격·RS 수집 정책 통합

- [x] active stock 전용 repository query 추가
- [x] sync_prices() 기본 대상을 is_active=True AND symbol_type=stock으로 변경
- [x] RS 계산도 동일한 active stock 정책 사용
- [x] ETF·ETN 수집은 명시적인 별도 모드로 분리
- [x] 대상 수와 skipped 수를 배치 통계에 반영

관련 코드:

- app/repositories/symbol_repository.py
- app/services/batch/sync_prices.py
- app/services/batch/calculate_rs.py
- app/services/rs/policy.py

완료 기준:

- inactive, ETF, ETN이 기본 가격 수집 요청에 포함되지 않는다.
- price target count와 실제 target result count가 일치한다.

### CRAWL-07 corporate-action 재수집 wiring

- [x] BatchContext에 price_source 추가
- [x] DB context와 memory context에 source 주입
- [x] orchestrator가 같은 source를 calculate_rs까지 전달
- [x] 전체 수정주가 재수집 후 corporate action 재검사
- [x] 재수집 실패·재검증 실패를 별도 결과 상태로 저장

관련 코드:

- app/services/batch/context.py
- app/services/batch/orchestrator.py
- app/services/batch/calculate_rs.py

완료 기준:

- 재수집 성공 종목이 같은 배치의 RS 계산에 다시 포함된다.
- 재수집 실패 종목은 실패 이유와 재시도 횟수를 가진다.

예상 기간: CRAWL-05~07 합계 3~5일  
Gate 2: universe·기업 액션 회귀 테스트와 PostgreSQL 통합 테스트 통과

## 7. Phase 3 - PostgreSQL repair queue와 Sam Kiwoom 업무

목표: Naver를 기본 수집 경로로 유지하면서 실패 종목만 PostgreSQL queue에 등록하고,
Sam은 제한된 API로 한 건의 읽기 전용 Kiwoom 업무를 수행한다. 결과는 autobot이 검증·반영한다.
공유 폴더 polling과 Sam의 DB 직접 접근은 목표 경로에 포함하지 않는다.

### CRAWL-08 공급자·업무 계약 확정

- [x] Naver를 universe·benchmark·일별 가격 주 공급자로 결정
- [x] Kiwoom을 실패 종목 전용 보조 공급자로 결정
- [x] Sam `kiwoom-ohlc-query` 스킬을 국내주식 일봉·읽기 전용으로 완성
- [x] API server 기반을 준비하고 기존 Hermes read-only API를 운영 계약으로 고정
- [ ] Kiwoom 계정·IP·rate limit·데이터 사용 범위와 CLI 내부 API ID/TR 매핑 확인
- [ ] 현재 직접 REST adapter의 일봉 API ID/TR과 응답 parser를 공식 계약·실제 fixture에
  대조하고, 불일치하면 canary 전에 수정
- [x] `daily_chart` 요청/결과 JSON 계약과 보안 필드 차단을 [Sam Repair API 문서](sam-repair-api.md)에 반영

완료 기준:

- Naver 실패, Kiwoom 업무, 결과 제출, canonical 반영의 소유자가 문서화되어 있다.
- CLI의 일봉 호출이 실제 일봉 결과를 반환하며 문서·코드·CLI 매핑 불일치가 없다.
- Sam에게 DB credential·공유 폴더 권한·주문 기능을 주지 않는다.

### CRAWL-09 repair queue migration과 repository

- [x] `crawl_repair_requests` migration 작성
- [x] `crawl_repair_attempts` migration 작성
- [x] `crawl_repair_results`를 날짜별 결과 행과 source lineage로 설계
- [x] `dedupe_key` unique, request 상태 check, result 날짜·OHLC 제약 추가
- [x] lease(`claim_token`, `lease_expires_at`)와 `next_attempt_at` 인덱스 추가
- [x] SQLAlchemy 모델·repository·memory fake 구현
- [x] 기존 Naver 실패 reason code 중 Kiwoom 복구 대상만 idempotent enqueue

핵심 상태 전이:

```text
pending → processing → completed → applied
                    ↘ failed      ↘ conflict / rejected
pending ← expired processing lease
```

완료 기준:

- 같은 job·종목·기준일·reason의 중복 업무가 하나만 생성된다.
- 재시도별 executor·오류·HTTP/API 상태·행 수·hash를 조회할 수 있다.
- queue 저장 실패가 Naver 실패를 성공으로 바꾸지 않고 alert/metric을 만든다.

### CRAWL-10 Sam Repair API

- [x] `POST /internal/v1/repair/requests/claim` 구현
- [x] `POST /internal/v1/repair/requests/{id}/complete` 구현
- [x] `POST /internal/v1/repair/requests/{id}/fail` 구현
- [x] `GET /internal/v1/repair/requests/{id}` 운영 조회 구현
- [x] `repair:claim`, `repair:submit`, `repair:fail` scope와 별도 service token 적용
- [x] claim에 `FOR UPDATE SKIP LOCKED`, lease, request version, idempotency 적용
- [x] 결과 API의 symbol/date/기간/OHLC/adjusted_price/row count 검증
- [x] 429·인증 오류·빈 응답·부분 결과를 성공으로 저장하지 않는 contract test 추가

Sam 업무의 한 번의 요청은 symbol, from, to, adjusted_price와 request ID만 포함한다.
Sam은 `kiwoomcli domestic candles daily`를 실행하고 정규화된 결과 또는 제한된 실패
정보만 반환한다. 상시 실행 모드나 임의 shell 명령은 요구하지 않는다.

완료 기준:

- Sam이 PostgreSQL credential 없이 claim→조회→complete/fail round trip을 수행한다.
- 오래된 claim token과 중복 complete가 canonical 데이터에 영향을 주지 않는다.
- API 로그와 결과에 token, secret, 계좌번호, 원본 응답 전문이 남지 않는다.

### CRAWL-11 autobot 결과 reconciler

- [x] completed request를 가져와 결과 행을 재검증
- [x] request의 job/symbol/trade_date와 결과 행의 일치성 검증
- [x] Naver 값 부재 시 Kiwoom 결과를 `daily_prices`와 `crawl_target_results`에 idempotent 적용
- [x] Naver와 값이 다르면 provider fingerprint와 함께 conflict/review_required 기록
- [x] 적용 transaction 재시작과 `application_status` 기반 recovery 구현
- [x] applied 결과만 RS 입력으로 승격하고 rejected/conflict는 제외
- [x] repair 결과 source lineage를 Agent stock snapshot/history에 노출

완료 기준:

- autobot 외의 계정이 canonical 가격과 RS를 직접 수정할 수 없다.
- 동일 결과를 재처리해도 가격 행과 RS 입력이 중복되지 않는다.
- completed, applied, conflict, rejected 수가 각각 리포트와 API에서 일치한다.

### CRAWL-12 Kiwoom canary와 전환

- [x] 단계 0: synthetic request로 queue/API 상태 전이와 실패 경로 검증
- [ ] 단계 1: 005930 한 종목, 짧은 기간으로 실제 읽기 전용 조회
- [ ] 단계 2: 5~10개 실패 종목, rate limit·중복·충돌 검증
- [ ] 단계 3: 실제 실패 100~300개 중 allowlist만 대상으로 제한 canary
- [ ] 각 단계 3회 연속 coverage·최신성·시간·충돌·rate limit 기준 확인
- [ ] 실패 시 `KIWOOM_FALLBACK_ENABLED=false`로 되돌리고 마지막 정상 dataset을 stale로 제공
- [ ] 파일 브리지는 canary의 기본 경로로 사용하지 않고 전환 후 비활성화

검증 지표:

```text
recovery_rate = applied / eligible_repair_requests
conflict_rate = conflict / completed
rate_limit_rate = rate_limit_attempts / total_attempts
queue_age = completed_at - requested_at
```

예상 기간: CRAWL-08~12 합계 6~10일
Gate 3: 단일 종목 → 5~10종목 → 100~300종목 canary를 각 3회 관측하고 기준 통과

## 8. Phase 4 - Hermes Agent API

목표: Hermes가 최신성·coverage를 확인한 뒤 RS 데이터를 조회할 수 있게 한다.

### HERMES-01 인증 middleware

- [x] Bearer service token 검증
- [x] rs:read, stock:read, status:read scope 적용
- [x] token rotation과 Secret 저장 방식 확정
- [x] IP allowlist 또는 내부망 정책 적용
- [x] request ID와 민감정보 로그 필터링
- [x] 401, 403, 429 테스트 추가

완료 기준:

- 인증 없는 요청은 401
- scope 없는 token은 403
- 배치 실행·재수집 기능은 Hermes token으로 호출 불가

### HERMES-02 versioned agent facade

- [x] GET /api/v1/agent/v1/status
- [x] GET /api/v1/agent/v1/briefing
- [x] GET /api/v1/agent/v1/rankings/rs
- [x] GET /api/v1/agent/v1/stocks/{code}
- [x] GET /api/v1/agent/v1/stocks/{code}/history
- [x] 공통 data/meta envelope 정의
- [x] dataset_id, trade_date, as_of, data_status, coverage 제공
- [x] 기존 /api/v1 프론트엔드 계약은 유지

완료 기준:

- complete, partial, stale, unavailable 상태를 API contract test로 검증한다.
- Hermes가 하나의 briefing 요청으로 기준일과 RS 상위 목록을 받을 수 있다.
- 대량 daily_prices를 하나의 기본 응답으로 반환하지 않는다.

### HERMES-03 캐시와 freshness 정책

- [x] dataset ID와 query 조합으로 briefing/rankings 캐시
- [x] ETag와 Last-Modified 지원
- [x] X-Data-As-Of, X-Dataset-Id, X-Data-Status header 제공
- [x] 429 Retry-After 제공
- [x] 최신 데이터 부재 시 503 또는 stale 응답 정책 적용

완료 기준:

- 동일 dataset 재요청이 조건부 요청 또는 캐시 hit가 된다.
- partial/stale 데이터가 complete로 표현되지 않는다.

### HERMES-04 Hermes adapter 연결

- [x] get_data_status
- [x] get_rs_briefing
- [x] get_stock_snapshot
- [x] get_stock_history
- [x] API base URL과 token을 Hermes Secret으로 주입
- [x] 401/403은 재시도하지 않고 429/5xx만 제한적으로 재시도

완료 기준:

- Hermes 브리핑이 dataset 기준일과 data_status를 반영한다.
- stale 데이터가 최신 데이터라는 문장으로 생성되지 않는다.

예상 기간: HERMES-01~04 합계 4~6일  
Gate 4: 내부망 contract test 및 운영 인증 검증 통과

## 9. Phase 5 - 운영 검증과 전환

### OPS-01 테스트 보강

- [x] malformed JSON, empty response, partial rows, HTTP 오류 fixture
- [x] failure record insert 실패 시나리오
- [x] partial universe 비활성화 방지
- [x] inactive/ETF/ETN 필터
- [x] corporate-action refetch 통합 테스트
- [x] agent auth/envelope/ETag/stale contract test
- [x] 2,400종목 synthetic benchmark harness 및 요청 budget 검증
- [x] repair request dedupe·lease·재시도 상태 전이 테스트
- [x] Sam Repair API claim/complete/fail 인증·schema contract test
- [x] completed 결과의 applied/conflict/rejected reconciler 통합 테스트
- [x] 429·부분 결과·오래된 claim·중복 제출 회귀 테스트
- [ ] 실제 종목 수에 가까운 staging 성능 테스트

### OPS-02 관측과 알림

- [x] crawl_eligible_total
- [x] crawl_fetched_total
- [x] crawl_no_new_data_total
- [x] crawl_partial_total
- [x] crawl_failed_total
- [x] crawl_failure_record_error_total
- [x] crawl_coverage_rate
- [x] symbols_deactivated_total
- [x] hermes_api_errors_total
- [x] repair_pending/processing/completed/failed_total
- [x] repair_applied/conflict/rejected_total
- [x] repair_queue_age_seconds
- [x] repair_claim_latency_seconds
- [x] kiwoom_rate_limit_errors와 결과 completeness
- [x] coverage 99.5% 미만, 최신일 지연, 동일 종목 3회 반복 실패 알림

### OPS-03 canary와 rollback

- [x] universe inactive 변경은 첫 배포에서 dry-run
- [x] PostgreSQL queue/API synthetic canary
- [ ] PostgreSQL queue/API는 실제 Sam 한 종목 canary
- [ ] Kiwoom은 5~10종목, 이후 100~300 실패 종목으로 단계 확대
- [ ] 3회 연속 성공 후 전체 시장 확대
- [x] provider feature flag off 절차
- [x] 마지막 정상 dataset을 stale로 제공하는 절차
- [x] 잘못된 대량 비활성화 및 dataset 불일치 rollback runbook

완료 기준:

- 운영자가 provider와 agent traffic을 되돌릴 수 있다.
- coverage 급락, 기준일 역행, 대량 비활성화를 자동 감지한다.

## 10. 의존성

    CRAWL-00 -> CRAWL-01 -> CRAWL-02 -> CRAWL-03 -> CRAWL-04
                                      |             |
                                      v             v
                                  CRAWL-05 -> CRAWL-06 -> CRAWL-07
                                      |
                                      v
                                  CRAWL-08 -> CRAWL-09 -> CRAWL-10

    CRAWL-04 -------------------------------> HERMES-02 -> HERMES-03 -> HERMES-04
    CRAWL-01 -------------------------------> HERMES-01

    CRAWL-02~12 + HERMES-01~04 -> OPS-01 -> OPS-02 -> OPS-03

병행 가능 작업:

- CRAWL-01과 HERMES-01 설계
- CRAWL-05 migration 초안과 CRAWL-08 공급자 조사
- HERMES API mock contract와 Hermes adapter 골격
- CRAWL-09 queue schema와 CRAWL-10 API contract는 병행 가능하나 API 구현은 migration
  contract가 고정된 뒤 시작한다.

## 11. 최종 완료 정의

- [x] eligible 종목 모두가 배치 종료 시 최종 상태를 가진다.
- [x] malformed response가 성공이나 no_new_data로 숨겨지지 않는다.
- [x] failure record와 배치 통계가 실제 결과와 일치한다.
- [x] 부분 universe snapshot으로 정상 종목을 비활성화하지 않는다.
- [x] active stock만 기본 가격·RS 대상이다.
- [x] 기업 액션 재수집이 실제 source와 연결된다.
- [ ] 가격 단계가 coverage 99.5% 이상, 목표 시간 이내다.
- [x] Hermes API가 인증, 버전, freshness, coverage를 제공한다.
- [x] Naver 실패가 PostgreSQL repair request로 중복 없이 등록된다.
- [ ] Sam이 제한된 Repair API로 실제 한 건의 읽기 전용 Kiwoom 업무를 처리한다. (synthetic round trip은 완료)
- [x] 결과가 attempt/result audit을 거쳐 applied/conflict/rejected로 분류된다.
- [ ] canary와 rollback이 staging에서 실제로 검증된다.
