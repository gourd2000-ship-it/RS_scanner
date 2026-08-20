# PRD: 크롤링 분석 보고서 기반 운영 정합성 및 RS 품질 개선

- 상태: Archived for legacy repair (2026-08-15부터 주간 분석 workflow가 기본 운영 경로)
- 작성일: 2026-08-14
- 대상 시스템: RS Scanner
- 범위: 일일 크롤링 배치, 실패·품질 집계, RS 입력 게이트, 운영 리포트

> 운영 대체 공지: 이 문서의 종목별 Kiwoom 자동 복구·queue·reconciler 경로는 새 일일
> batch에서 사용하지 않는다. legacy 자료와 migration 근거를 보존하기 위한 기록이며,
> 현행 요구사항은 [Sam 주간 크롤링 품질 분석과 Codex 개선 루프 PRD](prd-weekly-crawl-quality-analysis.md)를 따른다.

## 1. 요약

실행 중인 `rs_scanner`의 크롤링 분석 결과, API와 DB 연결 자체는 정상이나 배치 성공률,
실패 원인, RS 입력 품질이 같은 기준으로 집계되지 않고 있다. 이 PRD는 수집 실패를
숨기지 않고 종목 결과와 실패 이벤트를 분리하며, 품질이 확인되지 않은 데이터를 RS
결과에 포함하지 않고, 운영 리포트가 하나의 일관된 데이터 스냅샷을 사용하도록 하는
후속 개선을 정의한다. Naver에서 복구하지 못한 종목은 공유 폴더가 아니라 PostgreSQL
repair queue에 기록하고, 제한된 Repair API를 통해 Sam에게 한 건의 읽기 전용 업무로
전달한다.

기존의 크롤링 신뢰성·데이터 품질 PRD를 대체하지 않는다. 기존 상태 모델과 validation
파이프라인을 기반으로, 최신 운영 분석에서 드러난 정합성 문제를 해결하는 후속 범위다.

### 공급자 결정

이번 개선의 공급자 구성은 다음과 같이 결정한다.

- **주 공급자:** Naver. 종목 universe, benchmark, 일별 가격의 기본 수집 경로로 사용한다.
- **폴백 공급자:** Kiwoom. Naver에서 실패·빈 응답·기업행위 미해결이 발생한 종목만
  대상으로 일봉 가격을 재조회한다. autobot은 요청을 PostgreSQL repair queue에 넣고,
  Sam은 제한된 Repair API로 업무를 받아 자신의 `kiwoom-ohlc-query` 스킬을 실행한다.
- **Kiwoom의 역할:** 전종목 bulk 수집기가 아니라 실패 종목 전용 복구·교차검증 경로다.
  Sam이 실행하는 허용 명령은 읽기 전용 `kiwoomcli domestic candles daily` 하나이며,
  주문·계좌 API는 범위에 포함하지 않는다. CLI 내부 TR 매핑은 canary 전에 실제 응답과
  Kiwoom 공식 계약으로 검증하고 고정한다.
- **범위 밖:** 이번 단계에서는 외부 bulk EOD 공급자를 주 공급자로 전환하지 않는다.

Naver와 Kiwoom의 응답은 동일한 가격 기준일, 조정주가 정책, 품질 검증을 통과한 경우에만
하나의 RS 입력으로 승격한다. 출처 간 값이 다르면 자동 덮어쓰기하지 않고 충돌 또는
보류 상태로 기록한다.

### 목표 아키텍처 결정

파일 공유 방식은 목표 운영 경로에서 제외한다. 현재 저장소에 남아 있는 파일 브리지는
마이그레이션 전 진단용 legacy 경로로만 보존하며, 기본 feature flag는 꺼 둔다.

```text
Naver price crawl
        │
        ├─ 성공 ───────────────→ canonical daily_prices → RS
        │
        └─ 실패/복구 대상
             ↓
      crawl_repair_requests (PostgreSQL)
             ↓  제한된 Repair API
       Sam에게 단일 업무 전달
             ↓
       kiwoom-ohlc-query skill
             ↓  결과 제출 API
      crawl_repair_results (PostgreSQL)
             ↓
      autobot 검증·출처 비교·반영
             ↓
      applied 또는 conflict/review_required
```

경계는 다음과 같이 고정한다.

- Sam은 PostgreSQL 자격증명, Supabase MCP, generic SQL 실행 권한을 갖지 않는다.
- Sam은 업무를 요청받을 때마다 한 건의 `daily_chart` 조회를 수행하고 결과만 제출한다.
  상시 실행 모드나 별도의 상주 역할을 요구하지 않는다.
- Repair API가 요청 claim, 결과 검증, 시도 기록을 담당한다. Sam이 canonical
  `daily_prices`, RS, 배치 상태를 직접 수정하지 않는다.
- autobot만 repair 결과를 canonical 데이터에 반영한다. 반영은 Kiwoom 결과의 기간,
  OHLC, 조정주가, 최신 거래일, Naver와의 충돌 검증을 통과한 뒤 별도 트랜잭션으로 한다.
- API 서버의 기존 Hermes read-only facade와 Sam용 Repair API는 경로, token, scope를
  분리한다. Hermes 읽기 토큰에 repair mutation 권한을 부여하지 않는다.

## 2. 근거와 현재 문제

분석 기준 문서:

- `/srv/rs_scanner-share/rs_scanner_crawl_analysis_report.md`
- [크롤링 신뢰성 및 Hermes PRD](prd-crawling-reliability-hermes.md)
- [RS 데이터 품질 검증 파이프라인 PRD](prd-data-quality-pipeline.md)
- [운영 지표 계약](operations_metrics.md)
- [Sam Repair API 업무 절차](sam-repair-api.md)

### 2.1 관측된 기준선

| 항목 | 관측값 |
|---|---:|
| 전체 작업 | 54건 |
| 작업 상태 | completed 43, completed_with_errors 3, failed 5, running 3 |
| 전체 실패 레코드 | 1,604건 |
| 최신 작업 | job 58, completed_with_errors |
| job 58 대상/성공/실패 종목 | 4,081 / 3,745 / 336 |
| job 58 API 성공률 | 91.77% |
| job 58 실패 레코드 | 441건 |
| 반복 실패 종목 | 339개 |

job 58의 종목 실패 수 336건과 실패 레코드 441건이 다르다. 이는 한 종목에 여러
단계 또는 여러 번의 실패가 기록되는 현재 구조가 종목 단위 성공률과 이벤트 단위
오류 건수를 구분하지 않고 있음을 의미한다.

### 2.2 실패 원인

| 오류 | 건수 | 비율 |
|---|---:|---:|
| `fchart response has no data rows` | 774 | 48.3% |
| `OHLC fields must be positive` | 315 | 19.6% |
| `price fields must be positive` | 285 | 17.8% |
| `corporate action remains after adjusted-price refetch` | 228 | 14.2% |
| `OHLC values are inconsistent` | 2 | 0.1% |

빈 응답, 일시적인 공급자 오류, 거래정지·신규상장·상장폐지 가능성, 실제 가격
검증 실패가 충분히 구분되지 않는다. 특히 전체 실패 레코드에서 `http_status`가
대부분 비어 있어 네트워크 문제와 파싱·검증 문제를 완전히 분리할 수 없다.

### 2.3 RS 품질 및 리포트 정합성 문제

- RS 응답의 필수 필드는 null이 아니지만 `close=0`인 종목과 기간 수익률 결측이 존재한다.
- 보고서의 표와 본문에 3개월 결측 수와 `close=0` 수치가 서로 다르게 표시된다.
- `completed_jobs`가 `completed_with_errors`를 포함하지 않아 운영 대시보드의 성공률이
  실제 상태와 다르게 보일 수 있다.
- job 54·55에서 메타데이터 저장 또는 트랜잭션 오류가 발생해 배치 결과와 원인 분석용
  카운터가 불완전할 수 있다.

위 원인 중 일부는 원시 응답과 요청별 HTTP 상태가 충분히 보존되지 않아 아직 가설이다.
이 PRD는 가설을 성공 또는 정상 데이터로 승격하지 않고, 증거를 추가로 수집하는 것을
요구한다.

## 3. 목표

1. 모든 eligible 종목이 배치 종료 시 정확히 하나의 최종 결과 상태를 갖게 한다.
2. 재시도·단계별 실패 이벤트는 최종 종목 결과와 별도로 보존한다.
3. 빈 응답, 일시 오류, 데이터 오류, 기업행위 미해결을 표준 reason code로 분류한다.
4. RS 계산은 기준일, 이력 길이, 가격 유효성, 결측 사유가 확인된 입력만 사용한다.
5. 동일한 `job_id`와 `as_of` 스냅샷에서 운영 리포트의 표·본문·API 지표를 생성한다.
6. 같은 유형의 일일 배치가 동시에 두 번 실행되지 않도록 한다.
7. 전체 재수집 없이 실패 종목만 재처리하고, 재처리 복구율을 측정한다.

## 4. 비목표

- RS 산식 자체를 재설계하지 않는다.
- Naver를 주 공급자에서 제거하거나 외부 bulk EOD 공급자를 강제 도입하지 않는다.
- 거래정지·신규상장·상장폐지를 자동으로 정상 데이터로 보정하지 않는다.
- LLM 또는 SAM이 원본 가격, 배치 상태, RS 결과를 직접 수정하도록 하지 않는다.
- 프론트엔드 전체 개편과 실시간 시세 기능은 포함하지 않는다.

## 5. 사용자와 사용 사례

### 운영자

- 최신 배치의 종목 단위 결과와 실패 이벤트 수를 구분해 확인한다.
- 특정 종목의 실패 단계, 공급자, URL, HTTP 상태, 재시도 횟수를 조회한다.
- 반복 실패 종목만 재처리하고 재처리 전후 복구율을 비교한다.
- 배치 중복 실행이나 리포트 집계 불일치를 즉시 알림으로 받는다.

### RS 사용자 및 Agent API 소비자

- RS 결과의 기준일과 최신 가격일을 확인한다.
- 부분 수집·stale·품질 제외 종목을 정상 순위와 구분한다.
- 결측을 0으로 오인하지 않고, 제외 사유를 확인한다.

## 6. 상태 및 데이터 계약

크롤링, 검증, RS 공개 상태를 분리한다.

| 상태 | 의미 |
|---|---|
| `fetched` | 유효한 데이터를 수신하고 저장까지 완료 |
| `no_new_data` | 응답은 유효하지만 요청 기간 이후 신규 거래일이 없음 |
| `partial` | 일부 행만 유효하거나 일부 저장이 완료됨 |
| `failed` | HTTP·파싱·검증·저장 중 실패 |
| `skipped` | 정책상 요청하지 않음 |
| `quality_blocked` | 수집은 됐지만 RS 입력 품질 정책을 통과하지 못함 |

배치 통계는 다음 불변식을 만족해야 한다.

```text
eligible = fetched + no_new_data + partial + failed + skipped
failure_events >= final_failed_symbols
```

`completed_with_errors`는 배치가 종료되었지만 `failed`, `partial`, 또는
`quality_blocked` 결과가 존재하는 상태로 정의한다. `completed_jobs`와
`successful_jobs`는 별도 지표로 제공한다.

repair 업무와 canonical 반영 상태는 배치 상태와 분리한다.

| 구분 | 상태 | 의미 |
|---|---|---|
| repair request | `pending` | Sam에게 아직 전달하지 않은 업무 |
| repair request | `processing` | Sam이 claim token을 가지고 처리 중인 업무 |
| repair request | `completed` | 결과 제출 및 API 형식 검증이 끝난 업무. canonical 반영을 의미하지 않음 |
| repair request | `failed` | 조회·인증·rate limit·결과 검증 실패 업무 |
| repair request | `expired` | lease 또는 업무 유효기간이 지나 재검토가 필요한 업무 |
| application | `not_applied` | 결과는 있으나 autobot 반영 검증 전 |
| application | `applied` | canonical 가격과 target result에 반영 완료 |
| application | `conflict` | Naver와 값이 달라 자동 반영하지 않음 |
| application | `rejected` | 결과가 품질·기간·조정주가 계약을 통과하지 못함 |

`completed`와 `applied`를 하나의 상태로 합치지 않는다. Sam의 성공 응답만으로
RS 입력을 승인하지 않으며, `applied`가 된 행만 canonical 데이터와 RS 계산에 사용할
수 있다.

### repair queue 최소 스키마

사용자가 제안한 두 테이블에 시도 감사 테이블을 추가한다. `attempts`가 없으면
429, 인증 오류, 부분 결과, 재시도별 executor와 오류를 잃게 되므로 운영 무결성을
검증할 수 없다.

```text
crawl_repair_requests
────────────────────────────────────────────────────────
id, dedupe_key, job_id, crawl_target_result_id
symbol, trade_date, history_from, error_type
provider, adjusted_price, status
attempt_count, max_attempts, next_attempt_at
claimed_by, claim_token, lease_expires_at
requested_at, claimed_at, completed_at, last_error_code

crawl_repair_attempts
────────────────────────────────────────────────────────
id, request_id, attempt_no, executor, status
started_at, finished_at, http_status, error_code
error_message, retryable, row_count, result_hash

crawl_repair_results
────────────────────────────────────────────────────────
id, request_id, attempt_id, symbol, trade_date
source, adjusted_price, open, high, low, close, volume
application_status, created_at
```

`dedupe_key`는 최소한 `job_id + symbol + trade_date + error_type + adjusted_price`를
포함하는 불변 키로 만들고 unique 제약을 둔다. 결과는 이력 범위의 한 날짜당 한 행이며,
`request_id + attempt_id + symbol + trade_date`를 unique하게 한다. 금액은 고정 정밀도
숫자, 거래량은 정수형으로 저장하고 양수·OHLC 관계·날짜 범위 제약을 DB와 애플리케이션
양쪽에서 검증한다.

## 7. 기능 요구사항

### FR-01. 종목 결과와 실패 이벤트를 분리한다

- `crawl_target_results`는 `(job_id, step_name, target_key)`별 최종 결과를 저장한다.
- 동일 종목의 재시도·단계별 오류는 `crawl_failures` 또는 별도 attempt 레코드로 저장한다.
- 최종 결과에는 `status`, `attempt_count`, `rows_received`, `rows_persisted`,
  `provider`, `latest_date_before`, `latest_date_after`를 포함한다.
- 한 배치의 같은 종목·단계에는 최종 상태가 하나만 존재한다.
- 통계 API는 종목 수와 이벤트 수를 필드명으로 명확히 구분한다.

### FR-02. 실패 reason code와 재시도 정책을 표준화한다

권장 분류는 다음과 같다.

| 분류 | 예시 | 기본 처리 |
|---|---|---|
| `transient_error` | timeout, 429, 5xx | 지수 백오프와 jitter로 제한 재시도 |
| `empty_response` | 빈 fchart 행 | 지연 재조회 후 `data_unavailable` 또는 `expected_empty` 판정 |
| `invalid_data` | 음수·0 가격, OHLC 불일치 | 즉시 품질 실패, 무한 재시도 금지 |
| `corporate_action_unresolved` | 보정 재수집 후에도 이벤트 잔존 | 보류 큐와 검토 대상 |
| `universe_state` | 신규상장·거래정지·상장폐지 의심 | 종목 상태 확인 후 별도 결측 사유 기록 |
| `persist_error` | DB 저장·트랜잭션 오류 | 저장 실패와 원래 수집 실패를 모두 기록 |

`empty_response`를 자동으로 성공이나 정상적인 `no_new_data`로 바꾸지 않는다.
종목 상태와 공급자 응답을 확인한 경우에만 `expected_empty`로 분류한다.

모든 시도에는 `attempt_no`, `stage`, `source`, `url`, `http_status`(가능한 경우),
`response_bytes`, `retryable`, `error_class`, `reason_code`, 시작·종료 시각을 남긴다.

### FR-03. 배치 단일 실행과 트랜잭션을 보장한다

- `daily_full + target_date`에 대해 활성 배치는 하나만 허용한다.
- DB advisory lock 또는 active job unique 제약을 사용한다.
- heartbeat와 stale job 복구 정책을 둔다.
- failure 기록 실패가 원래 크롤링 실패나 배치 카운터 rollback을 일으키지 않도록
  savepoint 또는 독립 트랜잭션을 사용한다.
- checkpoint 상태 컬럼은 실제 상태 문자열을 모두 저장할 수 있어야 한다.

### FR-04. RS 입력 품질 게이트를 강화한다

RS 계산 전 다음 조건을 검사한다.

- 기준일 `target_date`가 시장과 종목에 일관되게 적용된다.
- 최근 가격일과 기준일의 stale 차이가 정책 한도 이내다.
- 최소 거래일 이력과 기간별 수익률 계산에 필요한 이력이 존재한다.
- 종가·OHLC가 양수이고 OHLC 관계가 유효하다.
- `close=0`은 결측을 의미하는 값으로 대체하지 않으며 기본적으로 RS 대상에서 제외한다.
- 중복 날짜, 날짜 역전, 비정상적인 가격 변동을 별도 사유로 기록한다.
- 거래정지·신규상장·상장폐지는 `missing_reason`으로 구분한다.

RS API에는 다음 메타데이터를 추가한다.

```text
target_date
latest_price_date
price_history_days
data_quality_status
missing_periods
missing_reason
```

초기에는 `report_only`로 관측하고, false positive와 stale 정책을 검증한 뒤
`enforce`로 전환한다.

### FR-05. 리포트와 API의 집계를 단일 스냅샷으로 만든다

- 리포트 실행 시 `job_id`, `as_of`, 데이터셋 식별자를 고정한다.
- 표·본문·통계 API·실패 API가 같은 집계 결과를 재사용한다.
- 오류 유형별 합계, 종목 단위 실패 수, 실패 이벤트 수의 관계를 자동 검증한다.
- 합계가 맞지 않거나 같은 지표가 서로 다른 값을 가지면 리포트 상태를
  `invalid`로 표시하고 canonical 보고서로 배포하지 않는다.
- 리포트에는 원천 endpoint, 실행 시각, 쿼리 기준, 데이터 제한사항을 포함한다.

최소 검증 항목:

```text
sum(error_type_counts) == failure_events
eligible == sum(final_status_counts)
final_failed_symbols <= failure_events
table_values == prose_values
```

### FR-06. 실패 종목만 재처리한다

- `job_id`, reason code, 최대 시도 횟수로 재처리 대상을 제한한다.
- 전체 universe 재수집과 실패 큐 재처리를 분리한다.
- 재처리 전후 `recovered_symbols`, `remaining_failures`, `recovery_rate`를 기록한다.
- 동일 종목이 세 번 이상 연속 실패하면 자동 재시도를 멈추고 검토 대상으로 올린다.

### FR-07. Naver 주 공급자와 repair queue 기반 Kiwoom 폴백을 분리한다

- Naver는 universe, benchmark, 일별 가격의 기본 공급자로 유지한다.
- Kiwoom 요청 대상은 `failed`, `empty_response`, `corporate_action_unresolved` 중
  정책상 재조회 가능한 종목으로 제한한다. 전체 universe 재조회와 임의 대량 요청은
  허용하지 않는다.
- autobot은 eligible 실패를 `crawl_repair_requests`에 idempotent하게 등록한다.
  request 생성 실패는 원래 crawl failure와 별도로 alert·metric으로 남기며 성공으로
  숨기지 않는다.
- Sam의 허용 업무는 `operation=daily_chart` 하나다. Sam은 자신의
  `kiwoom-ohlc-query` 스킬로 `kiwoomcli domestic candles daily`를 실행하고,
  결과 JSON을 Repair API에 제출한다. 주문·정정·취소·계좌·잔고·토큰 관리와 임의
  shell 실행은 금지한다.
- API의 claim 응답에는 symbol, `from`, `to`, `adjusted_price`, request ID만 제공한다.
  API는 Sam에게 DB 자격증명, 내부 SQL, Naver 원본 secret을 전달하지 않는다.
- Sam은 한 번에 한 업무를 claim하고 결과를 반환한다. `processing` lease가 만료되면
  기존 결과를 덮어쓰지 않고 request를 재시도 후보로 되돌린다.
- HTTP 429, Kiwoom rate limit, 인증 실패, 빈 응답, 부분 결과, 최신 거래일 불명확은
  성공으로 바꾸지 않는다. 429는 `crawl_repair_attempts`에 기록하고 승인된 backoff와
  `next_attempt_at` 이후에만 새 시도로 처리한다.
- Repair API는 request ID·claim token·idempotency를 검증하고, 결과의 날짜 범위,
  필수 OHLC, `adjusted_price`, 최신 거래일, 행 수, source와 executor를 검증한다.
- API 검증을 통과한 결과만 request를 `completed`로 바꾸고, autobot reconciler가
  다시 Naver와 비교한다. 충돌이면 canonical 값을 덮어쓰지 않고 `conflict` 또는
  `review_required`로 기록한다.
- Kiwoom의 계정·앱키·시크릿·IP 허용 정책은 Sam 실행 환경의 Secret 관리 체계에만
  두고 로그와 리포트에 인증정보를 남기지 않는다.
- CLI가 내부적으로 사용하는 Kiwoom API ID/TR은 canary 전에 공식 계약과 실제 응답으로
  검증한다. 문서·코드·CLI 사이에 일봉/주봉 매핑 불일치가 있으면 canary를 중단한다.

파일 브리지는 목표 운영 경로가 아니다. 기존 파일 브리지 문서는 전환 전 진단·회귀용
legacy 계약으로만 유지하며, `KIWOOM_FALLBACK_TRANSPORT=file`은 기본값으로 사용하지
않는다.

### FR-08. PostgreSQL repair 업무 API를 제공한다

기존 Hermes read-only API와 별도로 내부 Repair API를 추가한다. API 서버가 DB 쓰기를
담당하고 Sam은 제한된 service token으로 업무를 요청·완료·실패 보고만 한다.

필수 endpoint:

```text
POST /internal/v1/repair/requests/claim
POST /internal/v1/repair/requests/{request_id}/complete
POST /internal/v1/repair/requests/{request_id}/fail
GET  /internal/v1/repair/requests/{request_id}
```

필수 scope는 `repair:claim`, `repair:submit`, `repair:fail`이며, Hermes의
`rs:read`, `stock:read`, `status:read` token과 분리한다. claim은 DB transaction 안에서
`SELECT ... FOR UPDATE SKIP LOCKED`와 lease를 사용한다. 완료·실패 제출은 동일
`claim_token`과 request version을 요구해 중복 제출과 오래된 claim의 덮어쓰기를 막는다.

요청 및 결과 계약은 다음을 따른다.

- 초기에는 요청당 한 종목·한 날짜 범위로 제한한다. `symbol`은 6자리 코드이며,
  `from`·`to`는 ISO 날짜로 전달한다.
- 성공 제출에는 정규화된 행, `latest_date`, `row_count`, `data_complete`,
  `adjusted_price`, executor, tool, mode, result hash를 포함한다.
- 실패 제출에는 `error_code`, `retryable`, HTTP/API 상태, 시도 횟수와 제한된 오류
  메시지만 포함한다. token, secret, 계좌번호, 원본 응답 전문은 허용하지 않는다.
- API는 성공 여부를 request 상태와 application 상태에 반영하되, canonical 가격을
  직접 변경하지 않는다.

### FR-09. autobot이 repair 결과를 검증·반영한다

- `completed` request를 별도 reconciler가 claim하고 결과 행을 재검증한다.
- request의 job/target/date와 결과의 symbol/date가 일치하지 않으면 `rejected`로
  기록하고 canonical DB를 변경하지 않는다.
- Naver 값이 없는 실패 종목은 가격·이력·stale·OHLC 품질 게이트를 통과한 Kiwoom
  결과만 `daily_prices`와 `crawl_target_results`에 idempotent하게 반영한다.
- Naver 값이 이미 있거나 재수집 결과와 충돌하면 자동 덮어쓰지 않고 두 공급자의
  fingerprint와 비교 결과를 보존한다.
- 반영 transaction이 중단되어도 다음 실행에서 `application_status`를 기준으로
  안전하게 재개할 수 있어야 한다. `applied`가 아닌 결과는 RS 계산 입력으로 사용하지
  않는다.
- repair 결과의 source lineage는 `naver`와 `kiwoom`을 구분해 리포트와 Agent API에서
  조회 가능해야 한다.

Kiwoom 폴백 지표는 `kiwoom_fallback_targets`, `kiwoom_recovered_targets`,
`kiwoom_conflicts`, `kiwoom_rate_limit_errors`, `kiwoom_latency_seconds`로 분리한다.
repair queue는 `repair_pending`, `repair_processing`, `repair_completed`,
`repair_failed`, `repair_expired`, `repair_applied`, `repair_conflicts`,
`repair_queue_age_seconds`, `repair_claim_latency_seconds`를 추가한다.

## 8. 운영 지표와 알림

성공률 하나만 사용하지 않고 다음 지표를 분리한다.

| 지표 | 정의 |
|---|---|
| 기술적 수집 성공률 | 유효 응답·저장 완료 종목 / 수집 대상 종목 |
| 데이터 가용률 | `fetched + no_new_data` / eligible |
| RS 유효 입력률 | 품질 게이트 통과 종목 / 데이터 가용 종목 |
| 재처리 복구율 | 재처리 후 복구 종목 / 재처리 대상 종목 |
| 반복 실패율 | 2회 이상 연속 실패 종목 / eligible |
| 실패 이벤트율 | 실패 이벤트 / 전체 시도 횟수 |

권장 알림 조건:

- 활성 `daily_full` 배치가 2개 이상
- 최신 배치가 `completed_with_errors` 또는 `failed`
- 리포트 집계 불변식 위반
- 같은 종목·reason code가 3개 배치 연속 반복
- RS 유효 입력률이 기준선보다 급락
- HTTP 상태·재시도·공급자 응답시간 메타데이터가 비정상적으로 누락

99% 목표는 `expected_empty`를 기술적 실패로 계산할지 결정한 뒤 적용한다. 신규상장,
거래정지 등 정상적으로 데이터가 부족한 종목까지 실패로 계산하면 지표가 왜곡된다.

## 9. 구현 단계

### Phase 0 — 데이터 및 리포트 정합성 확인

- job 58을 단일 `job_id/as_of` 기준으로 재집계한다.
- 표의 결측·`close=0` 수치와 본문 수치를 원본 응답에 대조한다.
- 실패 1,604건의 유형 합계와 중복 종목 수를 분리한다.
- 현재 성공률·`completed_jobs`의 정의를 문서화한다.

### Phase 1 — P0 운영 정합성

- 최종 종목 결과와 failure attempt 집계를 분리한다.
- 배치 단일 실행 락과 stale recovery를 추가한다.
- failure 저장 트랜잭션과 checkpoint 상태 저장을 보강한다.
- 리포트 invariant 검증을 추가한다.

### Phase 2 — 실패 분류와 선택적 재처리

- reason code와 retryable 계약을 코드·DB·API에 연결한다.
- 지수 백오프, 재시도 예산, 보류 큐를 적용한다.
- 실패 종목 전용 replay 명령과 복구율 리포트를 제공한다.
- Naver 실패 종목을 PostgreSQL `crawl_repair_requests`에 idempotent하게 등록한다.
- repair request·attempt·result migration, repository, 상태 전이와 lease를 구현한다.
- 현재 완성된 Sam `kiwoom-ohlc-query` 스킬을 단일 `daily_chart` 업무 계약에 연결한다.
- 100~300개 실패 종목을 대상으로 하기 전에 단일 종목 DB/API round trip을 검증한다.

### Phase 3 — RS 품질 게이트

- 기준일·stale·이력 길이·0 가격·OHLC 검증을 RS 입력에 적용한다.
- `missing_reason`과 품질 메타데이터를 Agent/RS API에 추가한다.
- 최소 3회 배치를 `report_only`로 관측한 뒤 enforce 전환 여부를 결정한다.

### Phase 4 — 운영 자동화

- 지표를 Prometheus/OpenTelemetry 또는 영속 로그로 내보낸다.
- 반복 실패, 중복 실행, 품질 급락 알림을 연결한다.
- 주간 분석 리포트를 자동 생성하고 기준선과 비교한다.

### Phase 5 — Sam Repair API와 Kiwoom 복구 전환

- 읽기 전용 Hermes Agent API와 분리된 Repair API의 인증·scope·IP 정책을 구현한다.
- Sam이 `claim → kiwoom-ohlc-query → complete/fail` 한 업무를 수행하도록 API 계약을
  적용한다. 상시 실행 모드나 공유 폴더 polling을 제품 요구사항으로 만들지 않는다.
- autobot reconciler가 completed 결과를 검증하고 `applied`, `conflict`, `rejected`로
  분류한다. canonical DB와 RS는 `applied` 결과만 사용한다.
- Kiwoom CLI의 일봉 API 매핑, 수정주가, 기준일, rate limit과 결과 완전성을 단일 종목
  canary에서 검증한다.
- 단일 종목 → 5~10종목 → 실제 실패 100~300종목 순서로 확대하고 각 단계에서
  coverage, 충돌률, rate limit, queue age, 반영 건수를 저장한다.

## 10. 성공 기준

- 모든 eligible 종목이 최종 상태 하나를 가진다.
- 종목 실패 수와 실패 이벤트 수를 API와 리포트에서 별도로 확인할 수 있다.
- 1,604건의 실패 이벤트가 reason code별로 누락 없이 분류된다.
- job 58의 336개 실패 종목과 441개 실패 이벤트가 서로 다른 지표로 재현된다.
- 같은 `daily_full/target_date`의 동시 실행이 차단된다.
- Naver가 주 공급자로 기록되고, Kiwoom은 실패 종목에만 사용된다.
- Naver 실패가 idempotent repair request로 남고, request·attempt·result를 잃지 않는다.
- Sam은 DB credential이나 공유 폴더 없이 제한된 Repair API로 한 건의 읽기 전용 업무를
  수행할 수 있다.
- Kiwoom canary 3회에서 복구율·충돌률·rate-limit 오류율·queue latency를 측정할 수 있다.
- completed 결과와 applied 결과가 분리되고, conflict/rejected 결과가 canonical DB를
  덮어쓰지 않는다.
- `close=0`, stale 입력, 이력 부족 종목이 RS에서 조용히 사용되지 않는다.
- 리포트 표와 본문 수치가 동일한 스냅샷에서 생성된다.
- 실패 종목만 재처리할 수 있고 복구율을 측정할 수 있다.
- 기존 배치 동작을 깨지 않도록 최소 3회 report-only 검증 후 enforce 여부를 승인한다.

## 11. 미결정 사항

1. 빈 응답을 `expected_empty`로 인정할 수 있는 종목 상태와 공급자 증거의 기준은 무엇인가?
2. 기준일 RS의 stale 허용 범위를 거래일 기준 몇 일로 둘 것인가?
3. Repair API를 내부망에서만 노출할지, mTLS까지 요구할지 결정한다.
4. Sam 업무 결과의 최대 행 수와 API 요청 본문 크기 한도를 결정한다.
5. `completed_with_errors`를 운영 대시보드의 완료 작업에 포함하되, 성공 작업과 어떤 방식으로
  분리 표시할 것인가?
6. `close=0`을 모든 공급자에서 invalid로 고정할 것인가, 공급자별 계약으로 둘 것인가?
7. 실패 이벤트와 repair attempt 보존 기간, 원본 응답 metadata의 저장 한도는 얼마로 둘 것인가?

권장 기본값은 빈 응답과 stale 입력을 먼저 `report_only`로 관측하고, 품질 게이트는
원인별 false positive가 확인된 뒤 enforce하는 것이다.

## 12. 관련 문서

- [RS Scanner 크롤링 개선 및 Hermes 연동 로드맵](roadmap_crawling.md)
- [크롤링 신뢰성 및 Hermes Agent 데이터 API PRD](prd-crawling-reliability-hermes.md)
- [RS 데이터 품질 검증 파이프라인 PRD](prd-data-quality-pipeline.md)
- [운영 지표 계약](operations_metrics.md)
- [Hermes Agent API 운영 계약](agent_api.md)
- [Kiwoom REST API 가이드](https://openapi.kiwoom.com/m/guide/apiguide)
