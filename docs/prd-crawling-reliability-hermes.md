# PRD: 크롤링 신뢰성 개선 및 Hermes Agent 데이터 API

문서 상태: Draft  
작성일: 2026-08-10  
대상 시스템: RS Scanner  
관련 로드맵: [docs/roadmap.md](roadmap.md)

## 1. 요약

RS Scanner의 일일 배치에서 종목 가격 데이터가 조용히 누락되지 않도록 크롤링 결과를 명시적으로 분류하고, 현재 종목 universe를 안전하게 동기화하며, 실패 원인을 운영 화면에서 추적할 수 있게 한다. 이후 검증된 RS 결과를 Hermes Agent가 서버 간 API로 조회할 수 있도록 버전이 있는 읽기 전용 API를 제공한다.

핵심 방향은 기존 `symbols -> benchmarks -> prices -> rs` 파이프라인과 RS 계산 엔진을 유지하는 것이다. Naver를 universe·benchmark·일별 가격의 주 공급자로 사용한다. 2026-08-15부터 Kiwoom은 실패 종목 자동 복구가 아니라, 사용자가 요청한 Sam 주간 품질 분석의 제한된 evidence 표본으로만 사용한다. 현행 계약은 [Sam 주간 크롤링 품질 분석과 Codex 개선 루프 PRD](prd-weekly-crawl-quality-analysis.md)를 따른다. 전종목 bulk EOD 공급자 전환은 이번 범위에 포함하지 않으며 후속 선택사항으로 남긴다.

## 2. 배경과 현재 문제

현재 파이프라인은 [BatchOrchestrator](../app/services/batch/orchestrator.py)를 중심으로 다음 순서로 실행된다.

```text
종목 목록 동기화
  -> KOSPI/KOSDAQ 벤치마크 동기화
  -> 종목별 가격 증분 수집
  -> 기업 액션 검사 및 RS 계산
  -> FastAPI와 프론트엔드에서 조회
```

분석 기준으로 확인된 문제는 다음과 같다.

| 우선순위 | 문제 | 현재 동작 | 결과 |
|---|---|---|---|
| P0 | 파싱 실패 은닉 | `parse_fchart_prices()`가 빈 응답, JSON 오류, 짧은 응답을 모두 `[]`로 반환 | 신규 데이터 없음과 파싱 실패를 구분할 수 없음 |
| P0 | 실패 기록 계약 불일치 | `CrawlFailure.url`은 DB에서 사실상 필수지만 가격 실패 기록 호출부가 URL을 전달하지 않음 | 실패 기록 자체가 실패해 원인이 사라질 수 있음 |
| P0 | 배치 통계 왜곡 | 완료 시 `symbols_succeeded=len(symbols)`, `symbols_failed=0`으로 기록 | 일부 누락이 있어도 성공으로 표시될 수 있음 |
| P1 | universe stale 데이터 | `upsert_many()`는 새 목록의 종목만 재활성화하고 목록에서 사라진 종목을 비활성화하지 않음 | 상장폐지·오래된 종목이 계속 가격 요청 대상이 됨 |
| P1 | 수집 범위 과다 | `sync_prices()`가 `list_all()`을 사용해 ETF·ETN·비활성 종목도 요청 | 요청 수와 실행 시간이 불필요하게 증가 |
| P1 | 수정주가 재수집 wiring 누락 | RS 계산부는 `context.price_source`를 찾지만 `BatchContext`에 해당 필드가 없음 | 기업 액션 감지 종목의 재수집이 실행되지 않음 |
| P1 | 순차 요청 및 고정 대기 | 종목마다 0.8~2.5초 대기 후 순차적으로 Naver 요청 | 약 2,400종목 기준 대기만 약 66분, 재시도 포함 시 약 2시간 소요 가능 |

위 수치는 운영 환경에서 재측정해 기준선을 확정한다. 이 문서의 성공 기준은 단순히 배치가 끝나는 것이 아니라, 대상 종목마다 결과 상태가 남고 그 상태가 API와 운영 화면에 일관되게 반영되는 것이다.

## 3. 목표

### 3.1 제품 목표

1. 일일 가격 수집 대상인 모든 유효 주식 종목이 `fetched`, `no_new_data`, `failed`, `skipped` 중 하나로 분류되게 한다.
2. 파싱·HTTP·검증·DB 저장 실패를 종목 코드, 단계, 공급자, URL, 재시도 횟수와 함께 조회할 수 있게 한다.
3. 완전한 종목 snapshot만을 기준으로 상장폐지 또는 오래된 종목을 비활성화하고, 부분 수집 결과로 정상 종목을 잘못 비활성화하지 않는다.
4. ETF·ETN을 기본 주식 가격 수집과 RS 계산 대상에서 분리한다.
5. 기업 액션 감지 후 수정주가 전체 이력을 재수집하고, 성공 여부에 따라 RS 포함 여부를 재평가한다.
6. 일일 배치 시간과 Naver 요청 수를 줄인다. 1차 목표는 현재 기준선 대비 요청 수 80% 이상 감소, 가격 단계 실행 시간 30분 이내이며 실제 수치는 staging 측정 후 확정한다.
7. Hermes Agent가 최신성·완전성 정보를 함께 받으면서 RS 랭킹과 종목 상세를 안전하게 조회할 수 있게 한다.

### 3.2 비목표

- RS 산식 자체를 재설계하거나 프론트엔드 화면을 전면 개편하지 않는다.
- 실시간 호가·체결 스트리밍을 제공하지 않는다.
- Hermes에 DB 직접 접근 권한을 주지 않는다.
- 1차 릴리스에서 Naver를 제거하지 않는다. Kiwoom은 실패 종목 전용 폴백으로만 사용한다.
- 사용자를 위한 회원가입·로그인 기능을 추가하지 않는다. Hermes 연동은 서버 간 인증으로 처리한다.

## 4. 대상 사용자와 사용 시나리오

### 운영자

- 최근 배치에서 가격 수집 대상, 성공, 신규 데이터 없음, 실패, 제외 수를 확인한다.
- 특정 종목의 실패 URL, HTTP 상태, 파싱 단계, 재시도 횟수를 조회한다.
- 부분 수집으로 판단된 배치를 재시도하거나 실패 종목만 재수집한다.
- 종목 universe snapshot이 완전한지 확인한 뒤 비활성화 결과를 승인한다.

### Hermes Agent

- 특정 시장에서 RS 상위 종목과 RS 기준일을 조회한다.
- 종목 코드로 최신 가격, RS Rating, 시장, 데이터 기준일을 조회한다.
- 브리핑을 만들기 전에 데이터가 최신인지, 부분 수집인지, 실패율이 임계치를 넘었는지 확인한다.
- 필요한 경우 제한된 기간의 RS·가격 이력을 조회한다.

## 5. 기능 요구사항

### FR-1. 크롤링 결과 상태를 명시적으로 표현한다

가격 소스와 파서는 `list[DailyPricePayload]`만 반환하는 현재 계약을 확장해 성공 결과와 메타데이터를 함께 표현한다. 구현 방식은 `PriceFetchResult`와 typed exception을 권장한다.

```text
fetched       : 유효한 행을 수신하고 DB 저장까지 완료
no_new_data   : 응답은 유효하지만 since_date 이후 신규 거래일이 없음
partial       : 일부 행만 유효하고 일부 행은 폐기됨. 운영 검토 대상
failed        : HTTP, 파싱, 검증, 저장 중 하나가 실패
skipped       : 비활성 종목, ETF/ETN, 정책상 제외
```

요구사항:

- 빈 응답, 잘못된 JSON, 헤더만 있는 응답, 모든 행이 잘못된 응답은 `no_new_data`가 아니라 `failed`로 처리한다.
- 유효 행이 일부 존재하는 경우 폐기 행 수와 사유를 남긴다.
- `fetched`는 DB commit 또는 idempotent upsert 검증이 끝난 뒤에만 부여한다.
- 같은 종목에 대해 한 배치에서 최종 상태가 하나만 남도록 한다. 재시도 이력은 별도 attempt로 보존한다.

### FR-2. 실패 기록을 잃지 않는다

`crawl_failures`의 필수 식별 정보는 항상 기록되어야 한다.

- `job_id`, `step_name`, `target_type`, `target_key`
- `provider`, `url`, `http_status`, `error_class`, `error_message`
- `retry_count`, `response_bytes`, `attempt_started_at`, `created_at`
- 가능하면 `request_id`와 응답 fingerprint

`url`은 DB에서 nullable로 약화하지 않고, Naver 또는 Kiwoom 요청 URL을 항상 전달한다. 파서 실패도 HTTP client가 반환한 URL과 응답 메타데이터를 사용한다. 실패 기록은 대상 데이터 저장 트랜잭션과 분리하거나 독립 savepoint를 사용하여 원래 실패가 failure insert를 취소하지 않게 한다. 응답 본문 전체와 인증 정보는 저장하지 않는다.

### FR-3. 종목 universe를 snapshot 단위로 reconcile한다

매일 수집한 KOSPI·KOSDAQ 목록을 하나의 snapshot으로 관리한다.

- snapshot은 시장별 페이지 수집 완료, 중복 제거, 최소 건수, 필수 필드 검증을 통과해야 `completed`가 된다.
- snapshot이 `completed`일 때만 이번 목록에 없는 기존 종목을 `is_active=False`로 변경하고 `delisted_at`을 기록한다.
- 페이지 중간 HTTP 오류, 파싱 오류, 비정상적으로 작은 건수이면 snapshot을 `partial` 또는 `failed`로 남기며 기존 종목을 비활성화하지 않는다.
- 종목별 `last_seen_at`과 snapshot 식별자를 보존한다.
- `sync_prices()`와 `calculate_rs()`는 기본적으로 `is_active=True AND symbol_type='stock'`인 종목만 사용한다.
- ETF·ETN 가격 수집은 별도 정책으로 명시적으로 요청한 경우에만 실행한다.

권장 데이터 변경:

- `symbols`: `last_seen_at`, `last_seen_snapshot_id` 추가. 기존 `delisted_at` 활용.
- 신규 `symbol_universe_snapshots`: 공급자, 시장, 시작/종료 시각, 상태, 관측 건수, 검증 메시지, checksum 저장.

### FR-4. 기업 액션 재수집을 실제 배치에 연결한다

- `BatchContext`에 `price_source`를 추가하고 DB·메모리 context 생성부에서 주입한다.
- 기업 액션 감지 종목은 전체 수정주가 이력을 재수집한다.
- 재수집 결과가 검증을 통과하면 같은 실행에서 RS 계산 대상에 다시 포함한다.
- 재수집 실패 또는 재검증 실패는 `corporate_action_refetch_failed`로 기록하고 RS 제외 이유를 노출한다.
- 재수집은 무한 반복하지 않고 종목별 최대 횟수와 cooldown을 둔다.

### FR-5. 배치 통계를 실제 처리 결과와 일치시킨다

`crawl_jobs`의 단계별 결과는 다음 합계를 만족해야 한다.

```text
total = fetched + no_new_data + partial + failed + skipped
```

기존 `completed` 외에 `completed_with_errors` 상태를 추가한다. 하나라도 실패가 있으면 운영 화면과 API에서 성공률 100%로 표시하지 않는다. 체크포인트는 실패 종목이 남아 있는 청크를 단순 성공으로 표시하지 않고, 재시도 대상 수를 보존한다.

권장 신규 테이블은 `crawl_target_results`다.

```text
job_id, step_name, target_key, status, provider,
attempt_count, rows_received, rows_persisted,
latest_date_before, latest_date_after, error_class, created_at
```

이 테이블은 운영 감사와 Hermes의 데이터 coverage 계산에 사용한다.

### FR-6. Naver 주 공급자와 PostgreSQL repair queue 기반 Kiwoom 폴백을 분리한다

공급자 인터페이스는 유지하되 다음 정책을 추가한다.

1. Naver를 universe·benchmark·일별 가격의 주 공급자로 사용한다.
2. Naver의 실패·빈 응답·기업행위 미해결 종목만 `crawl_repair_requests`에 등록한다.
3. Repair API는 Sam에게 `daily_chart` 한 건을 전달하고, Sam의 읽기 전용
   `kiwoomcli domestic candles daily` 결과를 검증해 attempt/result로 저장한다.
4. Kiwoom은 전종목 bulk 수집기가 아니며, 전체 universe를 대상으로 호출하지 않는다.
5. Kiwoom의 응답은 기준일, 조정주가 여부, OHLC, 이력 길이, stale 정책을 검증한 뒤에만
   `daily_prices`와 RS 입력으로 승격한다.
6. Naver와 Kiwoom의 값이 다르면 기존 가격을 자동으로 덮어쓰지 않고
   `provider_conflict` 또는 `review_required`로 기록한다.
7. Sam은 DB credential, generic SQL, 주문·계좌 기능에 접근하지 않는다. 계정·앱키·시크릿·IP
   허용 정책은 Sam 실행 환경의 Secret 관리 체계에서만 관리한다.
8. provider, API ID/TR, 기준일, 조정주가 여부, 재시도 수, HTTP 상태와 폴백 결과를
   `crawl_target_results`, repair request/attempt/result에 기록한다. API ID/TR 매핑은
   canary 전에 CLI 실제 응답과 공식 계약으로 검증한다.

파일 공유 브리지는 목표 운영 경로에서 제외한다. 기존 파일 계약은 전환 전 진단용
legacy 문서로만 남기며 기본 feature flag는 비활성화한다.

Naver의 기본 경로에는 대상 필터, 증분 수집, 명시적 결과 상태, 제한된 요청 동시성,
재시도 예산을 적용한다. Kiwoom은 실패 종목 전용 복구·교차검증 경로로 제한한다.

## 6. Hermes Agent API 설계

### 6.1 제공 방식

Hermes에는 DB나 내부 repository를 노출하지 않고, FastAPI에 별도 읽기 전용 router를 둔다. 기존 `/api/v1/rankings/rs`, `/api/v1/stocks`, `/api/v1/crawl`의 query/repository를 재사용하되, Hermes용 응답에는 데이터 상태 메타데이터를 추가한다.

MVP에서는 전용 prefix를 사용한다.

```text
/api/v1/agent/v1/status
/api/v1/agent/v1/briefing
/api/v1/agent/v1/rankings/rs
/api/v1/agent/v1/stocks/{code}
/api/v1/agent/v1/stocks/{code}/history
```

전용 prefix를 두면 프론트엔드 호환성을 깨지 않고 Hermes 계약을 독립적으로 버전 관리할 수 있다. 내부망에서 빠른 검증이 필요하면 기존 GET API를 먼저 같은 인증 middleware 뒤에 두고, Hermes 연동 완료 후 전용 facade로 전환한다.

### 6.2 인증과 접근 제어

- `Authorization: Bearer <service-token>`만 허용한다.
- token은 환경변수에 평문으로 커밋하지 않고 배포 Secret 또는 secret manager에 저장한다.
- 최소 scope는 `rs:read`, `stock:read`, `status:read`로 나눈다.
- Hermes 전용 토큰은 읽기만 가능하고 배치 실행·재수집 endpoint는 제공하지 않는다.
- IP allowlist 또는 내부 네트워크 제한을 적용한다.
- 토큰 교체와 폐기를 지원하고 모든 요청에 `request_id`를 남긴다.
- CORS는 서버 간 통신의 보안 수단으로 간주하지 않는다.

### 6.3 공통 응답 envelope

모든 agent API 응답은 다음 메타데이터를 포함한다.

```json
{
  "data": {},
  "meta": {
    "api_version": "v1",
    "dataset_id": "crawl-job-123",
    "trade_date": "2026-08-10",
    "as_of": "2026-08-11T00:25:10Z",
    "data_status": "complete",
    "coverage": {
      "eligible": 2380,
      "successful": 2374,
      "no_new_data": 4,
      "failed": 2,
      "coverage_rate": 0.9992
    },
    "staleness_seconds": 1800
  }
}
```

`data_status`는 `complete`, `partial`, `stale`, `unavailable` 중 하나다. `partial`이나 `stale`이어도 데이터 자체를 반환할 수 있지만 Hermes가 응답 문장에 최신 데이터라고 표현하지 않도록 메타를 필수로 한다. 사용 가능한 dataset이 없을 때만 503을 반환한다.

### 6.4 엔드포인트 계약

#### `GET /api/v1/agent/v1/status`

Hermes가 브리핑 전 호출하는 상태 확인 API다.

- 최근 배치 ID와 상태
- 최신 거래일과 생성 시각
- 시장별 eligible/success/failure/coverage
- 데이터가 stale로 간주되는 기준과 현재 staleness
- 최근 실패 요약. 개별 오류 전문은 포함하지 않음

#### `GET /api/v1/agent/v1/briefing`

Hermes가 한 번의 요청으로 시장 요약과 상위 종목을 받는 기본 API다.

주요 query:

```text
market=KOSPI|KOSDAQ
trade_date=YYYY-MM-DD (선택)
min_rs=80 (선택)
limit=20, 최대 100
```

응답 data에는 기준일, 시장 요약, RS 상위 목록, 전일 대비 변화가 포함된다. 가격 이력 전체를 이 응답에 넣지 않는다.

#### `GET /api/v1/agent/v1/rankings/rs`

기존 RS 랭킹 API의 agent용 facade다. 페이지네이션과 `market`, `trade_date`, `min_rs`, `max_rs`, `sort_by`, `order`, `search`를 지원한다. Hermes 용도에서는 `limit` 상한을 100으로 제한하고 cursor 또는 page 기반으로 다음 결과를 요청한다.

#### `GET /api/v1/agent/v1/stocks/{code}`

종목 메타데이터, 최신 가격, 최신 RS, 벤치마크, 데이터 기준일을 반환한다. 비활성 종목이면 `is_active=false`와 비활성화 일자를 함께 반환한다.

#### `GET /api/v1/agent/v1/stocks/{code}/history`

`metric=price|rs`, `start_date`, `end_date`, `limit`을 지원한다. 기본 기간과 최대 행 수를 제한해 대량 `daily_prices` 조회가 API를 압박하지 않게 한다.

### 6.5 캐시와 오류 정책

- 최신 기준일의 rankings/briefing은 dataset ID와 query 조합으로 캐시한다.
- `ETag`와 `Last-Modified`를 제공해 Hermes가 동일 dataset을 반복 다운로드하지 않게 한다.
- 응답 header에 `X-Data-As-Of`, `X-Dataset-Id`, `X-Data-Status`를 제공한다.
- 429는 `Retry-After`와 함께 반환한다. Hermes는 exponential backoff를 사용한다.
- 401/403은 재시도하지 않는다.
- 5xx는 제한된 횟수만 재시도하며, stale cache가 있으면 status API를 통해 stale 사실을 먼저 확인한다.

### 6.6 Hermes 측 사용 흐름

```text
Hermes
  -> GET /agent/v1/status
  -> data_status와 coverage 검증
  -> GET /agent/v1/briefing 또는 rankings/rs
  -> 필요 시 stocks/{code}와 history 호출
  -> 응답의 trade_date/as_of/dataset_id를 브리핑 근거로 표시
```

Hermes adapter는 `get_data_status`, `get_rs_briefing`, `get_stock_snapshot`, `get_stock_history` 네 가지 도구로 시작한다. 각 도구는 API 오류를 원문 그대로 노출하지 않고, 사용자에게 재시도 가능 여부와 데이터 기준일을 전달한다.

## 7. 비기능 요구사항

### 데이터 완전성

- 모든 eligible 종목은 배치 결과 테이블에서 최종 상태를 가져야 한다.
- 정상 운영 목표 coverage rate는 99.5% 이상이다.
- coverage가 99.5% 미만이면 배치는 `completed_with_errors` 또는 `failed`로 표시하고 Hermes status는 `partial`로 표시한다.
- 부분 universe snapshot에서는 기존 활성 종목을 자동 비활성화하지 않는다.

### 성능

- staging에서 현재 기준선 대비 요청 수 80% 이상 감소를 확인한다.
- Naver 주 수집과 실패 종목 Kiwoom 폴백을 합친 가격 단계 목표 시간은 30분 이내다.
- agent rankings/briefing p95 응답 시간은 warm cache 기준 2초 이내다.
- 단일 종목 snapshot p95 응답 시간은 1초 이내다.
- API 하나의 응답이 100개 이상의 랭킹 항목 또는 1,000개 이상의 시계열 행을 기본으로 반환하지 않는다.

### 보안

- 인증 없는 agent endpoint는 401을 반환한다.
- scope가 없는 token은 403을 반환한다.
- 토큰, DB URL, 원본 응답 본문은 로그에 남기지 않는다.
- 요청·응답 로그에는 request ID, endpoint, status, latency, dataset ID만 남긴다.

### 호환성

- 기존 프론트엔드용 `/api/v1` endpoint의 응답 계약은 유지한다.
- agent API는 `/v1` 버전 prefix와 OpenAPI 문서, contract test를 가진다.
- 데이터 공급자는 `PriceSource` abstraction 뒤에 둔다.

## 8. 관측 지표와 알림

다음 지표를 배치·공급자·시장·단계별로 수집한다.

- `crawl_eligible_total`
- `crawl_fetched_total`
- `crawl_no_new_data_total`
- `crawl_partial_total`
- `crawl_failed_total`
- `crawl_skipped_total`
- `crawl_failure_record_error_total`
- `crawl_parser_error_total`
- `crawl_provider_request_total`
- `crawl_provider_latency_seconds`
- `kiwoom_fallback_targets`, `kiwoom_recovered_targets`, `kiwoom_conflicts`
- `kiwoom_rate_limit_errors`, `kiwoom_latency_seconds`
- `crawl_duration_seconds`
- `crawl_coverage_rate`
- `symbols_deactivated_total`
- `corporate_action_refetch_total`
- `hermes_api_requests_total`, `hermes_api_errors_total`, `hermes_api_latency_seconds`

다음 상황은 알림 대상이다.

- failure record 저장 실패가 1건이라도 발생
- coverage rate 99.5% 미만
- universe snapshot이 partial/failed
- 최신 거래일이 운영 기준보다 늦음
- 같은 종목의 동일 오류가 연속 3회 이상 발생
- agent API 5xx 또는 429 비율 급증

## 9. 검증 및 완료 기준

### P0 완료 기준

1. 잘못된 fchart JSON은 `failed`로 기록되고 `no_new_data`로 집계되지 않는다.
2. 빈 유효 데이터와 파싱 실패를 서로 다른 테스트와 운영 상태로 구분한다.
3. 모든 가격 실패 기록에 URL이 존재하며 `/crawl/failures`에서 조회된다.
4. `total = fetched + no_new_data + partial + failed + skipped`가 배치마다 성립한다.
5. 종목별 failure insert 실패가 발생해도 원래 실패의 재시도·알림·요약이 사라지지 않는다.

### P1 완료 기준

1. 완전한 universe snapshot에서만 사라진 종목이 비활성화된다.
2. 가격 수집과 RS 계산에서 inactive 및 ETF/ETN이 기본 제외된다.
3. `price_source`가 DB·메모리 batch context에 주입되고 기업 액션 재수집 성공/실패 테스트가 통과한다.
4. 실패 종목만 재수집할 수 있고, 재수집 결과가 원래 job과 연결된다.

### Hermes 완료 기준

1. agent endpoint는 인증 없이 접근할 수 없고 scope를 검증한다.
2. 모든 응답에 `dataset_id`, `trade_date`, `as_of`, `data_status`, `coverage`가 있다.
3. Hermes adapter contract test가 complete/partial/stale/unavailable 상태를 각각 검증한다.
4. 2회 연속 동일 dataset 요청에서 ETag 또는 304가 동작한다.
5. 최신 배치가 부분 성공이어도 Hermes가 이를 숨기지 않고 브리핑 생성 정책에 반영한다.

## 10. 단계적 출시와 rollback

1. **관측 단계:** 기존 배치 결과는 유지하면서 target result와 파서 실패 지표를 shadow 기록한다.
2. **P0 단계:** 실패 상태·failure persistence·통계를 켠다. Naver를 주 공급자로 유지한다.
3. **universe 단계:** snapshot 검증을 켜고, 비활성화는 처음에는 dry-run으로 비교한다.
4. **Kiwoom 폴백 단계:** 실패 종목 100~300개에 Kiwoom REST adapter를 canary 적용하고
   복구율·충돌률·rate-limit·실행 시간을 비교한다.
5. **Hermes 단계:** 내부망에서 token 인증과 contract test를 통과시킨 뒤 읽기 트래픽을 연결한다.
6. **확대 단계:** coverage와 latency 기준을 3회 연속 만족하면 전체 시장으로 확대한다.

rollback 기준은 coverage 급락, 데이터 기준일 역행, 잘못된 대량 비활성화, Hermes dataset 불일치다. 공급자 feature flag를 끄고 마지막 정상 dataset을 읽기 전용으로 제공하되, stale 상태를 반드시 표시한다.

## 11. 결정이 필요한 항목

- Kiwoom REST API 사용 등록, 계정·앱키·IP 정책과 데이터 저장·제공 범위
- Naver와 Kiwoom의 조정주가·기준일·거래정지 데이터 계약 차이
- Hermes의 배포 위치, IP allowlist, token 보관 방식
- 장 마감 후 최신 데이터의 허용 지연 시간
- coverage 99.5% 미만일 때 브리핑을 차단할지, stale 브리핑을 허용할지
- 기존 `crawl_failures` 확장과 `crawl_target_results` 신규 테이블 중 최종 스키마
- 과거 267만 건 수준의 가격 데이터에 대한 backfill·재검증 범위
