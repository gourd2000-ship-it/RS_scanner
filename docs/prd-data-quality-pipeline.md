# RS 데이터 품질 검증 파이프라인 PRD

상태: Phase 1~3 핵심 기반 구현 완료 · SAM 제외 후 운영 검증 진행 중
작성일: 2026-08-11  
대상 저장소: RS Scanner

구현 범위 메모: Hermes/SAM skill과 외부 reference provider 연동은 이 작업에서
구현하지 않는다. 대신 SAM이 나중에 읽을 수 있는 구조화된 validation case와
승인 전 correction/exclusion 저장소까지 준비한다.

## 구현 완료 내역 (2026-08-11)

- `validation_runs`, `validation_cases` 및 observation/correction/exclusion/corporate-action
  테이블과 Alembic migration을 추가했다.
- `scripts/validate_data_quality.py --job-id <id>`로 외부 재수집 없이 persisted job을
  replay할 수 있다. 기본 모드는 `report_only`다.
- coverage, ingest failure, persisted OHLC, benchmark, RS input freshness, extreme return,
  market-level coverage를 deterministic rule로 기록한다.
- 신규 가격/benchmark 저장 시 append-only observation과 payload hash를 남긴다.
- `v_daily_prices_validated`, `v_rs_input_prices`와 동일 정책을 사용하는 validated
  read repository를 추가하고, RS 계산에 input policy를 연결했다.
- `rs_runs`, `rs_input_snapshots`, `rs_scores.rs_run_id`로 RS 입력 lineage를 기록한다.
- `enforce` 모드에서는 blocked validation 결과가 RS 계산을 차단하며, 실패 대상은
  `scripts/retry_failed_targets.py --job-id <id>`로 bounded retry 후 다시 검증한다.

Job 56 replay 결과는 fresh coverage `2519/2837 (88.79%)`,
`NAVER_EMPTY_RESPONSE` 190건, `INVALID_PRICE` 128건, `RS_INPUT_STALE` 147건으로
재현됐다. 이 결과는 현재 threshold에서 `blocked (report_only)`로 기록되며,
report-only 모드에서는 기존 RS 계산을 중단하지 않는다.

## 1. 결론

제안한 방향은 채택한다. 단, 현재 구현과 맞지 않는 전제를 바로잡고 아래 순서로
도입해야 한다.

1. 크롤링 결과와 데이터 품질을 분리한 deterministic validator 및 audit record를 먼저
   추가한다.
2. 보고 전용 모드에서 과거 및 신규 배치를 재현·관측해 threshold와 RS 입력 신선도
   정책을 확정한다.
3. 불변 원본 관측 저장소와 clean layer를 만든 뒤 RS 입력을 전환한다.
4. validation gate를 강제한다.
5. 그 뒤에만 Hermes/SAM과 외부 기준가격 공급자를 예외 감사 용도로 연결한다.

첫 PR에서 SAM, 증권사 API, 자동 보정, RS 계산식 재작성은 구현하지 않는다.

## 2. 현재 상태 감사

### 2.1 확인한 사실

| 제안의 전제 | 현재 확인 결과 | PRD 반영 |
|---|---|---|
| PostgreSQL 기반 OHLC 저장소 | 사용 중이다. TimescaleDB extension은 설치되어 있으나 hypertable은 없다. | 기존 PostgreSQL/Alembic/SQLAlchemy 위에서 구현한다. |
| OHLC RAW는 불변 | 불일치. daily_prices와 benchmark_daily_prices는 같은 종목·일자 행을 upsert해 값이 갱신된다. source와 created_at은 있으나 관측 시각, 원본 payload hash, crawl job lineage가 없다. | daily_prices를 당분간 canonical price table로 부르고, P2에서 append-only observation store를 추가한다. |
| OHLC validator가 없다 | 부분적으로만 맞다. 저장 전 validate_prices()가 빈 목록, 중복 날짜, 양수 가격, OHLC 범위, 음수 거래량을 검사한다. 배치 단위 검증 run/case/audit/gate는 없다. | 기존 행 검증을 재사용하고, persisted data와 crawl failure를 함께 보는 batch validator를 추가한다. |
| crawler 완료와 RS 가능 여부가 분리되지 않았다 | 맞다. crawl job에는 completed_with_errors가 있으나 RS 계산은 가격 동기화 직후 무조건 실행된다. | validation_status와 gate 상태를 별도로 도입한다. |
| RS가 benchmark에 의존한다 | 제품 문서상 KOSPI/KOSDAQ benchmark를 사용해야 하나, 현재 calculate_rs()는 calculate_combined_rs()를 사용하며 benchmark series를 읽지 않는다. RsScore에는 benchmark_id만 저장된다. | benchmark 의존성을 제품 계약으로 확정하는 선행 결정을 P0에 넣는다. 확정 전에는 benchmark rule을 report-only로만 적용한다. |
| Hermes용 API가 없다 | 소스에는 인증된 읽기 전용 agent facade와 Hermes adapter가 있으나, 실행 중 API는 해당 route를 제공하지 않아 status endpoint가 404다. audit decision write endpoint는 없다. | SAM은 DB/MCP가 아니라 배포된 좁은 Agent API를 사용한다. P4의 선행조건은 Agent API 배포·비밀 설정·contract test다. |
| 다른 기준가격 공급자가 없다 | 운영상 맞다. EOD adapter는 있으나 EOD_PROVIDER_ENABLED 기본값은 false이고 실제 계약된 공급자는 없다. | reference API와 REPAIR는 공급자 계약 후의 후속 범위다. |

현재 관련 테이블은 symbols, daily_prices, benchmarks, benchmark_daily_prices, rs_scores,
crawl_jobs, crawl_failures, crawl_target_results, batch_checkpoints,
symbol_universe_snapshots이다. validation table, clean view, correction/exclusion table은 없다.

### 2.2 Job 56 기준선

2026-08-11 Job 56은 completed_with_errors 상태다.

| 항목 | 확인 값 |
|---|---:|
| 가격 수집 대상 | 2,837 |
| 가격 단계 성공/최신 행 보유 | 2,519 |
| 가격 단계 실패 | 318 |
| 기준일 가격 coverage | 88.79% |
| KOSPI/KOSDAQ benchmark 기준일 행 | 각각 존재 |
| RS 결과 | 2,548건: KOSPI 856, KOSDAQ 1,692 |

실패 이벤트는 daily_price 빈 fchart 응답 190건, daily_price 양수 가격 검증 실패
128건, corporate_action 재수집 양수 가격 검증 실패 29건, 재수집 후에도 기업 이벤트가
남은 경우 76건이다. 따라서 제안서의 “비정상 가격 157”은 두 가격 검증 실패
128 + 29를 합친 수치로 해석해야 하며, 서로 다른 단계의 이벤트와 고유 종목 수를
혼동해서는 안 된다.

“저장 가격 2,519건인데 RS 2,548건”의 29건 차이는 단순한 행 수 불일치가 아니다.
실제 RS input lineage를 확인한 결과, RS 2,548건 중 2,423건만 기준일 가격을 사용했고
125건은 이전 가격을 사용했다. 그중 116건은 하루 이전, 나머지 9건은 12~64일 이전
가격이다. 반대로 기준일 가격이 있어도 최소 253개 가격 이력 부족 또는 기업 이벤트
정책 등으로 RS가 생성되지 않는 종목이 있다.

따라서 P0의 최우선 검증 대상은 단순 coverage보다 더 구체적인 “RS input freshness와
as-of lineage”다.

### 2.3 구현 가능성 판정

| 기능 | 판정 | 근거와 선행조건 |
|---|---|---|
| validation_runs / validation_cases | 즉시 가능 | 기존 Alembic, SQLAlchemy model/repository, crawl job·target result·failure 데이터가 있다. |
| deterministic validator와 Job 56 replay | 즉시 가능 | 저장 전 validate_prices(), monitoring baseline, 재현 가능한 DB 데이터가 있다. |
| daily quality report / report-only | 즉시 가능 | 기존 scripts, config, metrics 구조를 확장하면 된다. |
| validation gate | 가능하나 후순위 | scheduler 삽입은 작지만 threshold와 stale/benchmark 제품 계약을 먼저 확정해야 한다. |
| clean view와 correction/exclusion | 가능하나 P2 이후 | 현재 ORM이 daily_prices를 직접 읽으므로 read repository 전환과 immutable observation 설계가 필요하다. |
| 완전한 RAW 불변성 | 신규 설계 필요 | 현재 upsert 테이블에는 과거 관측 이력이 없으므로 append-only observation store가 필요하다. |
| SAM audit | 가능하나 현재 운영 준비 미완료 | source에는 read-only facade가 있지만 실행 중 API route가 없고 audit write contract가 없다. |
| reference provider 기반 REPAIR | 외부 의존성으로 보류 | 실제 provider 계약, 데이터 권리, credential wrapper가 아직 없다. |

## 3. 문제 정의와 제품 목표

현재 pipeline은 다음과 같다.

    Scheduler
        -> Naver crawler
        -> daily_prices / benchmark_daily_prices
        -> RS calculator
        -> rs_scores

이 구조에서는 다음 질문에 일관되게 답할 수 없다.

- 해당 crawl job의 수집 성공률과 기준일 가격 coverage는 무엇인가?
- 특정 RS 결과가 기준일 가격, 이전 가격, 보정값 중 무엇을 사용했는가?
- 저장 전 검증에서 거절된 데이터와 저장 후 발견된 이상은 무엇인가?
- RS 계산을 중단해야 하는 데이터 문제인지, 사람이 검토할 개별 예외인지?

목표 상태는 아래와 같다.

    Crawler
        -> canonical price data
        -> deterministic validator
        -> validation run / cases / daily report
        -> report-only or enforce gate
        -> validated RS input
        -> RS run / RS scores

    Unknown anomaly
        -> future SAM audit through restricted API
        -> proposed correction or exclusion
        -> approved clean layer

핵심 제품 원칙은 다음과 같다.

1. crawl_status와 validation_status, rs_publish_status를 독립적으로 기록한다.
2. 명백한 오류는 코드가 판정한다. LLM은 known rule을 대체하지 않는다.
3. validation의 결과는 원본 가격 행을 직접 수정하지 않고 evidence와 policy로 남긴다.
4. RS가 “기준일” 결과라면 사용 가격의 as-of와 허용 stale 정책을 명시한다.
5. 인간 또는 SAM의 판정은 구조화된 값과 증거를 남긴다.
6. 반복된 예외만 테스트를 갖춘 deterministic rule로 승격한다.

## 4. 범위와 비범위

### P0/P1 범위

- crawl job 별 validation run 및 anomaly case 저장
- deterministic batch validator
- coverage, benchmark, persisted OHLC, ingest failure, freshness, 시장 단위 검사
- Job 56 재현 명령과 일일 품질 보고서
- report-only gate와 설정 가능한 정책
- historical replay 및 false-positive 분석

### 후속 범위

- append-only price observation 저장소
- correction/exclusion/corporate action 정책과 clean view
- RS input repository 및 RS input snapshot
- enforce gate와 scheduler 연동
- 배포된 Agent API를 통한 SAM read/audit decision API
- 계약된 외부 기준가격 공급자 wrapper
- Codex의 주기적 rule proposal PR

### 비범위

- SAM의 DB 직접 UPDATE/DELETE
- broker account, holdings, order, cancel API
- broker credential을 SAM에 노출하는 구조
- 자동 보정의 즉시 승인
- ML anomaly detector
- production branch 자동 merge
- 이 PR에서 RS 산식 전체를 재작성하는 작업

## 5. 데이터 계약

### 5.1 상태를 분리한다

| 상태 | 소유자 | 의미 |
|---|---|---|
| crawl_status | crawler | 요청·파싱·저장 단계가 끝났는가 |
| validation_status | validator | 해당 job/date 입력이 정책을 통과했는가 |
| rs_publish_status | RS gate | 새 RS snapshot을 계산·공개해도 되는가 |

예를 들어 crawl_status가 completed_with_errors여도 validation_status가
passed_with_warnings일 수 있다. 반대로 crawler가 completed여도 benchmark, freshness,
market-wide anomaly 때문에 validation_status가 blocked일 수 있다.

### 5.2 기준일 및 freshness 계약

validator는 trade_date 하나를 명시적으로 선택한다. 기본은 crawl job의 가격 target
result와 benchmark 날짜에서 결정하며, 불명확하면 CRITICAL로 처리한다.

각 활성 stock에 대해 아래를 분리해 기록한다.

- expected: 해당 배치의 가격 수집 대상이었다.
- observed_on_date: 기준일 가격 행이 있다.
- latest_observed_date: 기준일 이하의 가장 최신 가격 날짜다.
- stale_lag_days: 기준일과 latest_observed_date의 차이다.
- rs_eligible: 최소 이력과 기업 이벤트 정책을 통과했다.
- rs_input_status: fresh, allowed_stale, stale, excluded 중 하나다.

P0에서는 stale을 자동 제외하지 않는다. 다만 다음 두 개의 coverage를 항상 함께
보고한다.

    fresh coverage = observed_on_date / expected
    RS fresh-input coverage = fresh RS inputs / RS candidate inputs

enforce 전에는 시장 휴장, 거래정지, 신규 상장, 상장폐지, 증권 코드 변경을 어떻게
구분할지 정책을 확정해야 한다. 달력상 하루 차이만으로 정상이라고 간주하지 않는다.

### 5.3 RAW라는 용어를 바로잡는다

현재 daily_prices는 immutable RAW가 아니다. 동일 key의 값이 다음 수집에서 변경될 수
있으므로, P0에서는 “현재 canonical price table”로 정의한다.

진짜 불변 원본이 필요한 P2부터 아래를 추가한다.

- price_observations: source response에서 정규화한 append-only 관측 행
- benchmark_observations: benchmark용 append-only 관측 행
- raw_artifact_ref 또는 payload_hash: 원문/압축 artifact의 위치 또는 해시
- observed_at, provider, crawl_job_id, request metadata, parser version

legacy daily_prices의 과거 행은 관측 이력을 복원할 수 없다. 새 observation 저장소가
도입된 뒤의 수집부터 불변성을 보장한다.

## 6. 기능 요구사항

### FR-01 Validation Run

각 validator 실행은 validation_runs에 한 행을 만든다. daily job, replay, historical
backtest를 구분한다. 한 crawl job을 다른 validator version으로 다시 평가할 수 있어야
하므로 crawl_job_id만 unique로 두지 않는다.

필수 필드:

- id
- crawl_job_id nullable FK
- trade_date
- run_kind: daily, replay, backtest
- validator_version
- mode: report_only, enforce
- started_at, completed_at
- expected_symbols, fresh_symbols, stale_symbols, rs_candidate_symbols
- pass_count, warning_count, error_count, critical_count
- coverage_rate, rs_fresh_input_coverage_rate
- validation_status: running, passed, passed_with_warnings, blocked, failed
- policy_snapshot JSONB
- metrics JSONB
- created_at

P0에서는 PostgreSQL enum 대신 String + application validation + CHECK constraint를
사용한다. migration rollback과 향후 reason code 확장을 단순하게 유지하기 위함이다.

### FR-02 Validation Case

anomaly 한 건은 validation_cases에 기록한다. 정상 행마다 PASS case를 만들지 않는다.

필수 필드:

- id, validation_run_id FK
- subject_type: daily_price, benchmark, crawl_target, market, rs_input
- symbol_id nullable FK, benchmark_id nullable FK, target_key nullable
- trade_date nullable
- rule_id, severity, reason_code
- case_status: open, auto_resolved, review, approved, rejected
- decision nullable: PASS, REPAIR, EXCLUDE, BLOCK, REVIEW
- confidence nullable
- evidence JSONB
- validator_version
- created_at, resolved_at

evidence에는 검사 당시의 OHLC, 이전/다음 가격, target result 상태, failure metadata,
coverage 분자·분모, rule parameter를 넣는다. 이 방식은 rule마다 original_open,
original_high 등의 새 column을 추가하는 것보다 audit와 migration을 안정적으로 만든다.
원문 response나 credential은 evidence에 저장하지 않는다.

초기 reason_code는 아래의 제한된 vocabulary로 시작한다.

    NAVER_EMPTY_RESPONSE
    NAVER_CRAWL_ERROR
    MISSING_ROW
    STALE_DATA
    DUPLICATE_ROW
    INVALID_OHLC
    INVALID_PRICE
    INVALID_VOLUME
    BENCHMARK_MISSING
    BENCHMARK_DATE_MISMATCH
    COVERAGE_BELOW_POLICY
    MARKET_WIDE_ANOMALY
    EXTREME_RETURN
    CORPORATE_ACTION_SUSPECTED
    RS_INPUT_STALE
    REFERENCE_CONFLICT
    NEW_PATTERN

### FR-03 Deterministic Rules

P0 validator는 기존 저장 전 validate_prices()를 대체하지 않는다. 해당 함수를 공유하거나
rule adapter로 감싸서 저장 전 검사와 저장 후 검사의 의미가 달라지지 않게 한다.

| Rule group | P0 동작 | 기본 severity |
|---|---|---|
| persisted OHLC | NULL, 비유한 수, 0 이하 가격, high/low/open/close 관계, 음수 거래량 | ERROR |
| duplicate | canonical table의 unique constraint 위반 여부와 source observation 도입 후 중복 관측 여부 | ERROR |
| ingest failure | crawl_target_results와 crawl_failures의 빈 응답·파싱·검증 실패 | WARNING 또는 ERROR |
| coverage | expected 대비 fresh date 행, market 별 비율, target result 분포 | WARNING/CRITICAL |
| benchmark | 정책상 필요한 KOSPI_INDEX/KOSDAQ_INDEX 존재, 날짜 일치, OHLC 논리 | CRITICAL 후보 |
| freshness | 기준일보다 오래된 RS input, lag 분포, 장기 stale | WARNING/CRITICAL 후보 |
| market level | 전일·최근 baseline 대비 대상 수, fresh coverage, 오류 급증 | WARNING/CRITICAL 후보 |
| extreme return | 이전 종가 대비 급변을 anomaly로 기록 | WARNING |
| stale pattern | 동일 OHLC/volume 반복 | WARNING |

extreme return과 stale pattern은 오류 확정이 아니다. P0에서는 corporate action,
거래정지, 실제 급등락과 구분하지 않고 REVIEW 후보만 만든다.

### FR-04 Benchmark 계약 결정

현재 RS 구현은 benchmark series를 계산에 읽지 않는다. 반면 제품 문서와 데이터 모델은
시장별 benchmark를 핵심 의존성으로 표현한다. 다음 중 하나를 P0 design review에서
명시적으로 선택해야 한다.

1. benchmark-relative RS가 제품 계약이다. 그 경우 calculate_rs를 해당 계약에 맞게
   정렬하고, 두 benchmark의 기준일 부재·불일치는 enforce 시 BLOCK이다.
2. absolute-return combined RS가 제품 계약이다. 그 경우 benchmark validation은
   데이터 품질 보고에는 남기되 RS gate의 필수 차단 조건이 아니다. RsScore의
   benchmark_id 의미도 재정의하거나 제거한다.

이 결정 없이 “benchmark missing은 항상 RS BLOCK”을 강제하지 않는다. 현재 코드가
사용하지 않는 의존성으로 정상 배치를 차단하는 모순을 피하기 위함이다.

### FR-05 Replay와 Daily Quality Report

프로젝트의 기존 scripts 스타일에 맞춰 다음 명령을 제공한다.

    python scripts/validate_data_quality.py --job-id 56

이 명령의 replay는 외부 Naver 요청을 다시 보내는 기능이 아니다. 현재 DB에 보존된
crawl job, target result, failure, price, benchmark, RS score를 같은 validator version으로
재평가하는 기능이다.

출력은 console 요약과 JSON report를 제공한다.

    Validation Job 56
    Trade date: 2026-08-11
    Fresh coverage: 2519 / 2837 (88.79%)
    RS inputs: fresh=2423, stale=125
    Cases: warning=..., error=..., critical=...
    Validation status: BLOCKED (report_only)

P0의 Job 56 acceptance fixture는 아래 네 가지를 안정적으로 분류해야 한다.

- 190건의 NAVER_EMPTY_RESPONSE 신호
- 128건의 daily_price INVALID_PRICE 신호
- corporate action 재수집 단계의 29 + 76 실패 신호
- 125건의 RS_INPUT_STALE 신호와 stale lag 분포

같은 종목의 여러 신호는 별도 case일 수 있다. 일일 report의 합계는 “failure event”,
“anomaly case”, “unique symbol”을 명확히 구분해 표시한다.

### FR-06 Report-only Gate

초기 설정은 아래처럼 한다.

    validation:
      mode: report_only
      coverage:
        warning: 0.97
        block: 0.90

이 수치는 시작점일 뿐 운영 threshold가 아니다. 현재 monitoring의 99.5% crawl alert도
곧바로 publish block threshold로 재사용하지 않는다. historical replay와 최소 10개
거래일의 report-only 관측 후 정책 승인으로 확정한다.

report_only에서 blocked 판정은 기록·알림·report에만 반영하고 기존 RS 계산 및 공개
동작은 바꾸지 않는다.

### FR-07 Enforce Gate와 실패 처리

enforce 모드에서 scheduler는 가격 동기화 후 validator를 실행하고, 승인된 validation
result만 RS 단계에 넘긴다.

즉시 BLOCK 후보:

- validator 자체가 실패하여 결과를 신뢰할 수 없음
- 기준일을 결정할 수 없음
- benchmark-relative 계약을 선택한 뒤 필수 benchmark가 없거나 기준일이 다름
- policy가 정한 fresh coverage 미만
- persisted OHLC corruption이 정책 한도를 초과

BLOCK 시 새 RS snapshot을 만들거나 기존 rs_scores를 덮어쓰지 않는다. API/Hermes에는
가장 최근의 검증된 snapshot과 stale/blocked 상태를 명시한다. 실패 대상 재수집은
기존 retry_failed_price_targets()를 scheduler 또는 운영 CLI에서 호출할 수 있게
연결하되, validator가 transient data failure에 대해 무제한 재시도하지는 않는다.

### FR-08 Clean Layer와 Historical Lineage

live SQL view만으로는 과거 RS 결과를 완전히 재현할 수 없다. 이후 correction이나
exclusion이 변경되면 같은 view가 과거에 읽은 결과도 바꾸기 때문이다.

P2/P3에서 다음을 추가한다.

| 목적 | 권장 이름 |
|---|---|
| 불변 정규화 가격 관측 | price_observations, benchmark_observations |
| 승인 전/후 보정 제안 | ohlc_corrections |
| 제외 정책 | ohlc_exclusions |
| 기업 이벤트 evidence | corporate_actions |
| 정상화된 가격 read model | v_daily_prices_validated |
| RS 전용 가격 read model | v_rs_input_prices |
| RS 실행 metadata/snapshot | rs_runs, rs_input_snapshots |

제안서의 v_ohlc_validated와 v_ohlc_rs는 현재 이름보다
v_daily_prices_validated와 v_rs_input_prices가 실제 schema를 더 잘 설명한다. 외부
문서 호환이 필요하면 alias view를 나중에 제공할 수 있다.

RS calculator는 view를 직접 SQL로 흩뿌리지 않는다. PriceRepository와 분리된
RsInputRepository 또는 동등한 query abstraction을 통해 validated input을 읽는다.
RS run에는 validation_run_id, input policy version, target date, snapshot hash를 기록하고
RsScore는 rs_run_id를 참조해야 lineage를 복원할 수 있다.

### FR-09 Hermes/SAM과 Reference Provider

SAM은 P0/P1의 선행조건이 아니다. 도입 시 다음을 지킨다.

- SAM에 PostgreSQL credential, Supabase MCP, generic SQL execution 권한을 주지 않는다.
- 현재 Agent API source를 실제 API container에 배포하고 service token/IP/scope 설정과
  contract test를 완료한다.
- 새 scope는 validation:read와 validation:write로 분리한다.
- POST decision endpoint는 case_id 단위의 structured body만 받고, raw table이나
  scheduler, RS calculator를 수정하지 않는다.
- REPAIR는 ohlc_corrections의 PROPOSED를 만들 뿐 APPROVED가 되지 않는다.
- 외부 reference provider는 내부 wrapper가 credential을 보관한다.
- provider가 없거나 SAM이 unavailable이면 known PASS data는 계속 처리하고,
  unresolved anomaly에 대한 publish 정책만 BLOCK 또는 이전 verified snapshot 유지로
  결정한다.

SAM decision vocabulary는 PASS, REPAIR, EXCLUDE, BLOCK, REVIEW로 고정한다. 초기
reason_code를 벗어난 사례는 NEW_PATTERN으로 기록한다.

## 7. 구현 로드맵

### Phase 0 — 계약 확정과 fixture 동결

완료 조건:

- benchmark-relative RS와 absolute-return RS 중 실제 제품 계약을 결정한다.
- trade_date 선택 방식, market holiday, 거래정지, 허용 stale policy를 문서화한다.
- Job 56의 DB-derived baseline JSON과 expected case summary를 regression fixture로
  동결한다.
- P0 migration이 기존 migration head와 충돌하지 않는지 확인한다.

### Phase 1 — First PR: deterministic validator와 audit 구조

구현 범위:

- ValidationRun, ValidationCase ORM model/repository/Alembic migration
- versioned ValidationRule interface와 rule registry
- persisted OHLC, crawl failure, coverage, benchmark, freshness, market-level MVP rules
- validation service와 report serializer
- scripts/validate_data_quality.py --job-id 명령
- Job 56 replay test, rule unit test, PostgreSQL integration test
- report_only configuration과 daily report artifact

변경하지 않는 것:

- daily_prices의 upsert 의미
- 기존 crawler source/parsers
- RS calculator input query
- production scheduler의 enforce behavior
- Hermes/SAM/reference provider

삽입 위치는 가격 동기화 완료 후 RS 계산 직전이다. report_only에서는 validation step이
실패하더라도 기존 RS behavior를 변경하지 않지만, validator process failure 자체는
crawl job과 구분해 반드시 기록한다.

### Phase 2 — 불변 관측 저장소와 clean data layer

구현 범위:

- 신규 수집부터 append-only observation record와 source evidence reference 저장
- crawler/canonical writer/validator/RS reader role 분리
- ohlc_corrections, ohlc_exclusions, corporate_actions
- 승인된 policy만 반영하는 validated 및 RS input read model
- legacy history의 provenance limitation을 API/report에 표시

완료 조건:

- RAW라고 부르는 데이터는 application role로 UPDATE/DELETE할 수 없다.
- canonical price 갱신과 observation append의 차이가 테스트된다.
- correction/exclusion이 원본 행을 변경하지 않는다.

### Phase 3 — RS input 전환과 enforce gate

구현 범위:

- RsInputRepository와 v_rs_input_prices 사용
- raw/canonical input과 validated input 병렬 RS 비교
- rs_runs 및 rs_input_snapshots lineage
- validation_mode: report_only, enforce
- scheduler gate, alert, blocked snapshot fallback

전환 조건:

- historical replay와 연속 운영에서 false positive가 허용 범위다.
- parallel RS difference가 설명 가능하고 승인됐다.
- Job 56 유형이 의도대로 BLOCK 또는 REVIEW로 분류된다.
- rollback은 mode를 report_only로 되돌리고 기존 input repository를 사용하도록 한다.

### Phase 4 — Hermes/SAM 및 기준가격 provider

구현 범위:

- 실행 환경에 Agent API 배포
- validation context read endpoint와 case decision write endpoint
- audit-only service token, IP policy, rate limit, request log
- 계약된 첫 reference provider의 최소 OHLC/symbol/corporate-action wrapper
- SAM structured decision 및 manual approval workflow

전환 조건:

- read/write scope 분리가 security test로 검증된다.
- SAM은 raw/canonical/RS/scheduler를 변경할 수 없다.
- provider credential이 agent process 또는 prompt에 노출되지 않는다.

### Phase 5 — 개선 루프

매주 최근 validation case를 집계한다. Codex는 반복 패턴을 분석해 rule, unit test,
regression fixture, migration 필요성을 제안하는 PR만 만든다. human review와 CI를
통과한 뒤에만 merge한다.

자동화 승격 기준은 사례 수만으로 정하지 않는다. 동일 rule이 historical replay,
false-positive review, provider conflict 검증을 통과해야 한다.

## 8. 테스트와 운영 기준

### 테스트

- Unit: 각 deterministic rule의 정상/경계/오류 사례
- Integration: validation run/case migration, transaction rollback, report serialization
- Replay: Job 56과 실제 익명화 사례 fixture
- Regression: SAM/사람 판정에서 deterministic rule로 승격된 사례
- Contract: Agent API scope, schema, idempotent decision write
- Parallel: raw/canonical RS와 validated RS의 결과·입력 membership 비교

### 관측 지표

- crawl expected/fetched/no_new_data/partial/failed
- fresh coverage와 RS fresh-input coverage
- validator severity/rule/reason 분포
- stale lag distribution
- benchmark completeness
- validation duration, blocked count, report-only would-block count
- RS candidate, fresh input, excluded, calculated count
- SAM invocation, decision, unknown, reference conflict 비율

### MVP 성공 기준

- 모든 새 daily crawl job에 validation run을 만들 수 있다.
- RAW 불변성 미구현 상태를 숨기지 않고 canonical limitation을 명시한다.
- 명백한 OHLC 오류, crawl failure, coverage, benchmark, freshness를 재현 가능하게
  탐지한다.
- Job 56 report가 88.79% fresh coverage와 RS stale input을 드러낸다.
- report_only에서 기존 batch/RS 동작을 깨지 않는다.
- 특정 validation case가 rule version, evidence, crawl job으로 역추적된다.

## 9. 위험과 의사결정

| 위험 | 영향 | 대응 |
|---|---|---|
| daily_prices를 RAW로 오인 | 수정 이력과 증거가 사라짐 | observation store 전에는 RAW 불변성 claim을 하지 않는다. |
| 최신성 없는 RS를 기준일 RS로 공개 | ranking 신뢰도 저하 | rs input freshness를 별도 gate metric으로 만든다. |
| benchmark 계약과 코드가 다름 | 잘못된 BLOCK 또는 잘못된 RS 의미 | Phase 0에서 제품 계약을 확정한다. |
| coverage threshold를 성급히 강제 | 정상 배치 불필요 차단 | historical replay와 report-only 기간 후 승인한다. |
| view만 사용해 lineage를 주장 | 과거 RS 재현 불가 | rs_runs/input snapshot을 추가한다. |
| SAM에 DB 또는 broker 권한 부여 | 보안·운영 위험 | restricted Agent API와 provider wrapper만 사용한다. |
| 실제 provider 없이 REPAIR 설계 착수 | 복잡도만 증가 | Phase 4까지 REPAIR는 PROPOSED 설계로 제한한다. |

## 10. 승인 요청

이 PRD의 First PR 범위는 Phase 1으로 제한한다. 구현을 시작하기 전에 아래 두 정책만
승인하면 된다.

1. RS가 benchmark-relative여야 하는지, 현재 absolute-return combined 방식을 제품
   계약으로 인정할지.
2. 기준일 RS에 대한 stale input 허용 정책: 기본 제안은 report-only에서 stale을 모두
   가시화하고, enforce 기준은 관측 결과를 보고 정한다.

그 외의 SAM, reference provider, correction auto-approval은 Phase 1의 완료 및
운영 데이터 검증 이후에 결정한다.
