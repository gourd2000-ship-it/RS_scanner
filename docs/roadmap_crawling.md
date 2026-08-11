# RS Scanner 크롤링 개선 및 Hermes 연동 로드맵

상태: 코드 구현 완료 (Gate 3·공급자 계약·staging 운영 검증 대기)  
작성일: 2026-08-10  
상세 요구사항: [PRD](prd-crawling-reliability-hermes.md)

실행 현황 (2026-08-11): P0~P1, EOD 계약/검증 계층, Naver fallback·요청 예산·bounded concurrency,
Hermes API/adapter, 운영 baseline/metrics/canary 제어기를 반영했다. PostgreSQL migration·API 통합·E2E
회귀 테스트와 2,400종목 synthetic benchmark를 통과했다. 실제 EOD 공급자 계약, staging coverage/성능,
provider canary 3회 연속 관측은 외부 계약과 운영 환경 확인 후 진행한다.

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

## 7. Phase 3 - EOD 공급자와 성능 개선

목표: 전종목 bulk EOD 수집을 우선하고 Naver는 fallback·backfill로 제한한다.

### CRAWL-08 EOD 공급자 결정

- [x] KRX 또는 계약된 EOD 공급자 후보 조사
- [ ] 라이선스·상업적 사용·요청 제한 확인
- [ ] 기준일, 시장, 가격 조정 여부, 파일/API 형식 결정
- [x] 공급자 장애와 fallback 조건 정의

완료 기준:

- 공급자와 계약 조건이 문서화되어 있다.
- 데이터 사용 범위가 Hermes 제공 범위와 충돌하지 않는다.

### CRAWL-09 EOD adapter와 bulk upsert

- [x] PriceSource 계층에 EOD provider adapter 추가
- [x] checksum, 기준일, 필수 필드, 중복, 종목 수 검증
- [x] 시장별 bulk upsert 구현
- [x] 종목별 fetched/no_new_data/failed 결과 생성
- [x] provider와 기준일을 target result에 저장

완료 기준:

- staging에서 active stock coverage 99.5% 이상을 달성한다.
- 부분 파일은 저장되지 않고 해당 배치가 partial/failed로 표시된다.

### CRAWL-10 Naver fallback 및 요청 예산

- [x] EOD 누락·실패 종목만 fallback queue에 넣음
- [x] Naver 전체 이력 backfill 및 corporate action 용도 분리
- [x] retry와 concurrency 상한 설정
- [x] provider별 요청 수와 실행 시간 측정
- [x] 기존 0.8~2.5초 지연 정책의 운영 한계 재검토

코드 검증용 benchmark: `scripts/benchmark_price_sync.py --symbols 2400 --workers 4`.
실제 staging의 30분·coverage 목표는 OPS-01/Gate 3에서 별도로 확인한다.

완료 기준:

- 기준선 대비 외부 요청 수 80% 이상 감소
- staging 가격 단계 30분 이내
- coverage 99.5% 이상 유지

예상 기간: CRAWL-08~10 합계 5~8일  
Gate 3: canary에서 3회 연속 coverage·최신성·시간 기준 통과

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
- [x] coverage 99.5% 미만, 최신일 지연, 동일 종목 3회 반복 실패 알림

### OPS-03 canary와 rollback

- [x] universe inactive 변경은 첫 배포에서 dry-run
- [x] EOD 공급자는 일부 시장 또는 일부 종목에 canary
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

    CRAWL-02~10 + HERMES-01~04 -> OPS-01 -> OPS-02 -> OPS-03

병행 가능 작업:

- CRAWL-01과 HERMES-01 설계
- CRAWL-05 migration 초안과 CRAWL-08 공급자 조사
- HERMES API mock contract와 Hermes adapter 골격

## 11. 최종 완료 정의

- [x] eligible 종목 모두가 배치 종료 시 최종 상태를 가진다.
- [x] malformed response가 성공이나 no_new_data로 숨겨지지 않는다.
- [x] failure record와 배치 통계가 실제 결과와 일치한다.
- [x] 부분 universe snapshot으로 정상 종목을 비활성화하지 않는다.
- [x] active stock만 기본 가격·RS 대상이다.
- [x] 기업 액션 재수집이 실제 source와 연결된다.
- [ ] 가격 단계가 coverage 99.5% 이상, 목표 시간 이내다.
- [x] Hermes API가 인증, 버전, freshness, coverage를 제공한다.
- [ ] canary와 rollback이 staging에서 실제로 검증된다.
