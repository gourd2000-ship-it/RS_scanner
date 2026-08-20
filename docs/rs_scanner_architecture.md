# RS Scanner Architecture

## 1. 목표

이 문서는 `IBD-style Relative Strength` 컨셉의 국내 주식 RS 스캐너를 구현하기 위한 권장 아키텍처를 정의한다.

핵심 요구사항은 다음과 같다.

- 종목 리스트는 네이버증권 크롤링으로 수집한다.
- 가격 데이터도 네이버증권 크롤링으로 수집한다.
- 매일 장 종료 후 `17:00 Asia/Seoul` 기준으로 업데이트한다.
- 크롤링 차단 방지를 위해 `rate-limiting`, `retry`, `backoff`를 포함한다.
- RS 계산은 시장별 벤치마크를 분리한다.
- `KOSPI` 종목은 `KOSPI` 대비 RS를 계산한다.
- `KOSDAQ` 종목은 `KOSDAQ` 대비 RS를 계산한다.
- 전체 구현 언어는 `Python`을 기준으로 한다.

정확한 IBD RS 공식은 공개되어 있지 않으므로, 본 프로젝트에서는 `IBD-style approximation`을 사용한다.

---

## 2. 권장 기술 스택

### Backend

- `Python 3.12+`
- `FastAPI`
- `SQLAlchemy 2.x`
- `Pydantic`
- `httpx` 또는 `requests`
- `BeautifulSoup4` + `lxml`

### Database

- `PostgreSQL`
- `TimescaleDB`

선정 이유:

- 일봉 가격 데이터와 RS 시계열을 저장하기에 적합하다.
- 종목 메타데이터, 배치 실행 로그, 에러 로그를 한 DB에서 함께 관리할 수 있다.
- 시계열 조회와 최근 데이터 스냅샷 조회가 쉽다.
- 초기 MVP부터 운영 단계까지 무난하게 확장 가능하다.

### Frontend

- `Next.js`
- `React`
- 차트 라이브러리: `Apache ECharts` 권장

선정 이유:

- 종목 검색, 랭킹 테이블, 조건 필터, 상세 차트, 상태 대시보드를 구현하기 좋다.
- 서버 렌더링과 API 연동이 자연스럽다.
- 이후 사용자용 서비스로 확장하기 쉽다.

### Scheduler

- OS `crontab`

선정 이유:

- 요구사항 기준으로 매일 1회 배치면 충분하다.
- Redis/Celery Beat 없이도 운영이 단순하다.
- 실패 로그와 재실행 정책만 잘 갖추면 MVP와 초기 운영에 적합하다.

---

## 3. 전체 아키텍처

권장 구조는 `배치 수집기 + 계산기 + API + 웹 프론트엔드` 형태의 분리형 모놀리식이다.

```text
+------------------+      +---------------------+
|     crontab      | ---> | Python Batch Runner |
+------------------+      +---------------------+
                                   |
                                   v
                        +-----------------------+
                        | Naver Finance Crawler |
                        +-----------------------+
                                   |
                                   v
                        +-----------------------+
                        | PostgreSQL/Timescale  |
                        +-----------------------+
                                   |
                 +-----------------+-----------------+
                 |                                   |
                 v                                   v
        +-------------------+              +-------------------+
        |   FastAPI API     |              |  Admin/Ops Logs   |
        +-------------------+              +-------------------+
                 |
                 v
        +-------------------+
        |   Next.js UI      |
        +-------------------+
```

### 구성 요소

#### 3.1 Batch Runner

배치 러너는 하루 1회 실행되며 아래 순서로 동작한다.

1. 종목 리스트 수집
2. 종목 메타데이터 upsert
3. 벤치마크 지수 데이터 수집
4. 종목별 일봉 가격 수집
5. 데이터 정합성 검증
6. RS 계산
7. 랭킹 스냅샷 생성
8. 실행 결과 및 실패 로그 저장

#### 3.2 Crawler

크롤러는 네이버증권 HTML 구조를 파싱해 데이터를 수집한다.

수집 대상:

- 시장별 종목 리스트
- 종목 코드
- 종목명
- 시장 구분(`KOSPI`, `KOSDAQ`)
- 종목별 일봉 시세
- 벤치마크 지수 일봉

#### 3.3 API

FastAPI는 프론트엔드와 운영 화면에 필요한 데이터를 제공한다.

예상 API:

- `/api/v1/symbols`
- `/api/v1/rankings/rs`
- `/api/v1/symbols/{code}`
- `/api/v1/symbols/{code}/prices`
- `/api/v1/symbols/{code}/rs`
- `/api/v1/jobs/latest`
- `/api/v1/health`

#### 3.4 Frontend

프론트엔드는 조회와 시각화에 집중한다.

핵심 화면:

- RS 랭킹 대시보드
- 시장별 랭킹(`KOSPI`, `KOSDAQ`)
- 종목 상세 페이지
- 가격 차트 + RS 라인
- 최근 업데이트 상태
- 수집 실패/지연 상태 표시

---

## 4. DB 설계

### 4.1 핵심 테이블

#### `symbols`

종목 마스터 테이블.

주요 컬럼:

- `id`
- `code` unique
- `name`
- `market` (`KOSPI`, `KOSDAQ`)
- `sector` nullable
- `industry` nullable
- `is_active`
- `listed_at` nullable
- `delisted_at` nullable
- `created_at`
- `updated_at`

#### `benchmarks`

벤치마크 마스터.

주요 컬럼:

- `id`
- `benchmark_code` unique
- `name`
- `market`

예시 데이터:

- `KOSPI_INDEX`
- `KOSDAQ_INDEX`

#### `daily_prices`

종목 일봉 저장 테이블.

주요 컬럼:

- `symbol_id`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `change_rate`
- `source`
- `created_at`

제약:

- unique(`symbol_id`, `trade_date`)

#### `benchmark_daily_prices`

벤치마크 지수 일봉 저장 테이블.

주요 컬럼:

- `benchmark_id`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `volume` nullable
- `change_rate`
- `created_at`

제약:

- unique(`benchmark_id`, `trade_date`)

#### `rs_scores`

일자별 RS 결과 저장 테이블.

주요 컬럼:

- `symbol_id`
- `trade_date`
- `market`
- `benchmark_id`
- `return_3m`
- `return_6m`
- `return_9m`
- `return_12m`
- `relative_return_score`
- `rs_percentile`
- `rs_rating`
- `rank_in_market`
- `created_at`

제약:

- unique(`symbol_id`, `trade_date`)

#### `crawl_jobs`

배치 실행 로그.

주요 컬럼:

- `id`
- `job_type`
- `started_at`
- `finished_at`
- `status`
- `symbols_total`
- `symbols_succeeded`
- `symbols_failed`
- `message`

#### `crawl_failures`

개별 요청 실패 로그.

주요 컬럼:

- `id`
- `job_id`
- `target_type`
- `target_key`
- `url`
- `http_status` nullable
- `error_class`
- `error_message`
- `retry_count`
- `created_at`

### 4.2 인덱스 권장안

- `daily_prices(symbol_id, trade_date desc)`
- `benchmark_daily_prices(benchmark_id, trade_date desc)`
- `rs_scores(trade_date desc, market, rs_rating desc)`
- `symbols(market, is_active)`

### 4.3 TimescaleDB 활용 포인트

다음 테이블은 hypertable 후보이다.

- `daily_prices`
- `benchmark_daily_prices`
- `rs_scores`

장점:

- 시계열 저장 및 조회 성능 개선
- retention, compression 등 운영 기능 활용 가능

---

## 5. RS 계산 방식

### 5.1 기본 원칙

정확한 IBD 공식은 비공개이므로 아래 방식으로 유사하게 계산한다.

1. 종목의 기간별 수익률을 계산한다.
2. 동일 시장 벤치마크의 기간별 수익률을 계산한다.
3. 종목 수익률에서 벤치마크 수익률을 차감한 `relative return`을 만든다.
4. 최근 구간에 더 높은 가중치를 둔 가중합 점수를 만든다.
5. 같은 시장 내 전체 종목에 대해 percentile을 계산한다.
6. percentile을 `1~99` 스케일의 `RS Rating`으로 변환한다.

### 5.2 시장별 벤치마크 매핑

- `KOSPI` 종목 -> `KOSPI_INDEX`
- `KOSDAQ` 종목 -> `KOSDAQ_INDEX`

즉, KOSPI 종목끼리는 KOSPI 기준으로 비교하고, KOSDAQ 종목끼리는 KOSDAQ 기준으로 비교한다.

### 5.3 기간별 수익률

권장 기준:

- `3M`: 최근 약 63거래일
- `6M`: 최근 약 126거래일
- `9M`: 최근 약 189거래일
- `12M`: 최근 약 252거래일

수식:

```text
return_n = (close_t / close_t-n) - 1
```

### 5.4 벤치마크 대비 상대 수익률

```text
relative_return_n = stock_return_n - benchmark_return_n
```

### 5.5 가중 점수 예시

최근 구간 비중을 높이는 예시:

```text
relative_return_score =
    0.40 * relative_return_3m +
    0.20 * relative_return_6m +
    0.20 * relative_return_9m +
    0.20 * relative_return_12m
```

이 가중치는 운영 중 실험을 통해 조정 가능하다.

### 5.6 RS Rating 변환

동일 시장 내 `relative_return_score`를 기준으로 오름차순 정렬 후 percentile을 계산한다.

예시:

```text
rs_percentile = 종목의 백분위
rs_rating = clamp(round(rs_percentile * 98 + 1), 1, 99)
```

설명:

- 하위권은 `1`에 가깝다.
- 상위권은 `99`에 가깝다.
- 동일 시장 안에서만 비교한다.

### 5.7 보조 지표

함께 저장하면 좋은 값:

- `price_vs_52w_high`
- `52w_high`
- `52w_low`
- `50d_ma`
- `150d_ma`
- `200d_ma`
- `volume_ratio`

이 값들은 향후 `CAN SLIM` 스타일 스크리닝 확장에 유용하다.

---

## 6. 네이버증권 크롤링 전략

### 6.1 수집 전략

#### 종목 리스트

네이버증권 시장별 목록 페이지에서 수집한다.

수집 항목:

- 종목코드
- 종목명
- 시장구분

필요 시 다중 페이지를 순회한다.

#### 일봉 가격

종목별 일봉 페이지를 순회해 수집한다.

수집 항목:

- 날짜
- 시가
- 고가
- 저가
- 종가
- 거래량
- 등락률

#### 벤치마크 지수

KOSPI, KOSDAQ 지수 일봉 페이지를 별도 수집한다.

### 6.2 차단 방지 전략

필수 요소:

- 고정 간격 대신 `random jitter`
- 요청당 `timeout`
- 공통 `session` 재사용
- `User-Agent` 헤더 지정
- 요청 빈도 제한
- 재시도 정책
- 실패 누적 시 중단

권장 설정 예시:

- 기본 딜레이: `0.8 ~ 2.5초`
- 페이지 단위 추가 지연: `2 ~ 5초`
- 동시성: 초기에는 `1~2 worker` 수준
- timeout: `10초`
- retry 횟수: `최대 5회`

### 6.3 Retry / Backoff 정책

재시도 대상:

- 네트워크 오류
- `429`
- `403`
- `5xx`
- 파싱 실패 중 일시 오류로 판단되는 경우

예시 정책:

```text
delay = base_delay * (2 ** retry_count) + random_jitter
```

예:

- 1차 실패: 2초 + jitter
- 2차 실패: 4초 + jitter
- 3차 실패: 8초 + jitter
- 4차 실패: 16초 + jitter

### 6.4 Circuit Breaker

아래 조건 중 하나를 만족하면 해당 배치 실행을 중단한다.

- 연속 `403` 또는 `429`가 임계치 초과
- 전체 실패율이 일정 비율 초과
- HTML 구조가 크게 바뀌어 파싱 실패율 급증

이 경우:

- 전일 데이터는 유지
- 배치는 `failed` 또는 `degraded` 상태로 기록
- 운영 알림 발송

### 6.5 캐시 및 중복 요청 최소화

- 종목 마스터는 매일 1회만 갱신
- 가격 데이터는 마지막 저장일 이후의 페이지만 수집
- 최신 데이터가 이미 존재하면 불필요한 과거 페이지 탐색 중단

---

## 7. 배치 스케줄링

### 7.1 실행 시각

- 타임존: `Asia/Seoul`
- 실행 시각: 매일 `17:00`

### 7.2 crontab 예시

```cron
CRON_TZ=Asia/Seoul
0 17 * * 1-5 /usr/bin/python3 /opt/rs_scanner/app/main_batch.py >> /var/log/rs_scanner/batch.log 2>&1
```

설명:

- 평일만 실행
- 장 종료 후 데이터 반영 시점에 맞춤
- stdout/stderr를 로그 파일로 저장

### 7.3 실행 순서

```text
sync_symbols
  -> sync_benchmarks
  -> sync_daily_prices
  -> validate_data
  -> calculate_rs
  -> refresh_snapshots
  -> notify_result
```

### 7.4 재실행 전략

- 당일 실패 시 운영자가 수동 재실행 가능
- 특정 종목만 부분 재수집 가능
- RS 계산 단계만 재실행 가능

---

## 8. Python 프로젝트 구조 제안

```text
app/
  api/
    v1/
      endpoints/
  core/
    config.py
    logging.py
    database.py
  models/
    symbol.py
    daily_price.py
    benchmark.py
    rs_score.py
    crawl_job.py
  schemas/
  services/
    crawler/
      client.py
      rate_limiter.py
      retry.py
      parsers/
        symbols.py
        prices.py
        benchmarks.py
    batch/
      sync_symbols.py
      sync_prices.py
      sync_benchmarks.py
      calculate_rs.py
    ranking/
      rs_formula.py
  repositories/
  main_api.py
  main_batch.py

scripts/
  run_batch.sh
  install_cron.sh

docs/
  rs_scanner_architecture.md
```

### 구성 의도

- `crawler`는 외부 수집 책임만 가진다.
- `batch`는 실행 순서를 조합한다.
- `ranking`은 RS 계산 로직만 담당한다.
- `api`는 읽기 전용 서비스에 집중한다.

---

## 9. 프론트엔드 구현 방향

### 9.1 주요 페이지

#### RS 대시보드

표시 요소:

- 오늘 기준 시장별 상위 종목
- `KOSPI` / `KOSDAQ` 탭
- RS Rating 정렬
- 거래량, 등락률, 52주 고점 대비 상태

#### 종목 상세 페이지

표시 요소:

- 종목 기본 정보
- 일봉 차트
- 벤치마크 대비 RS 라인
- 최근 RS Rating 추이
- 최근 수집 상태

#### 운영 상태 페이지

표시 요소:

- 최근 배치 실행 시간
- 성공/실패 건수
- 실패 종목 목록
- 마지막 업데이트 시각

### 9.2 권장 UI 구성

- 표: 랭킹 및 필터링
- 선 차트: 가격, RS score 추이
- 배지: 시장 구분, 상태 표시
- 검색: 종목명/코드
- 필터: 시장, RS 구간, 거래대금, 이동평균 조건

### 9.3 UX 포인트

- 최신 업데이트 시각을 명확히 표시
- 장 마감 후 데이터 기준일을 함께 표시
- 시장별 비교 범위가 다르다는 점을 UI에 안내

예:

`KOSPI 종목은 KOSPI 내에서, KOSDAQ 종목은 KOSDAQ 내에서 RS Rating이 계산됩니다.`

---

## 10. API 초안

### `GET /api/v1/rankings/rs`

쿼리 예시:

- `market=KOSPI`
- `trade_date=2026-04-06`
- `min_rs=80`
- `limit=100`

응답 예시 필드:

- `code`
- `name`
- `market`
- `close`
- `change_rate`
- `rs_rating`
- `rank_in_market`
- `return_3m`
- `return_6m`
- `price_vs_52w_high`

### `GET /api/v1/symbols/{code}`

응답:

- 종목 메타
- 최신 가격
- 최신 RS
- 벤치마크 정보

### `GET /api/v1/symbols/{code}/chart`

응답:

- 일봉 시계열
- 벤치마크 시계열
- RS 시계열

### `GET /api/v1/jobs/latest`

응답:

- 최근 배치 상태
- 처리 건수
- 실패 건수
- 마지막 성공 시각

---

## 11. 운영 및 모니터링

### 필수 운영 요소

- 구조화 로그
- 배치별 실행 ID
- 실패 종목 로그
- 알림 연동(`Slack`, `Discord`, `Email` 중 택1)
- 헬스체크 엔드포인트

### 권장 알림 조건

- 배치 전체 실패
- 실패율 임계치 초과
- 연속 `403` 또는 `429`
- 벤치마크 데이터 미수집
- RS 계산 대상 종목 수 급감

### 장애 시 기본 정책

- 전일 RS 데이터는 유지
- 최신 배치 상태만 실패로 표시
- 사용자 화면에는 `마지막 성공 기준일`을 노출

---

## 12. 기타 필요한 요소

### 12.1 데이터 품질 관리

- 중복 데이터 방지
- 거래일 누락 감지
- 숫자 파싱 검증
- 상장폐지/거래정지 종목 관리
- 비정상 급등락 데이터 검증

### 12.2 테스트

권장 테스트 구성:

- parser 단위 테스트
- RS 계산 단위 테스트
- DB upsert 테스트
- 배치 통합 테스트
- 실패 재시도 테스트
- 저장 전 품질 게이트 테스트
- 가비지 컬렉션 정책 테스트
- HTML fixture 기반 replay 테스트

### 12.2.1 자동 강제 시스템 하네스

저장 또는 커밋 이전에 자동으로 코드를 검사하는 하네스를 둔다.

권장 구성:

- `compileall`
- `pytest`
- 필요 시 `ruff`, `mypy` 추가
- 실패 리포트 JSON 저장
- 자동 교정 루프 연계

자동 교정 루프 원칙:

- 검사 실패 시 리포트를 생성한다.
- 외부 AI 또는 Codex 실행 명령이 설정되어 있으면 자동 수정 시도를 수행한다.
- 자동 수정기에는 품질 리포트와 프롬프트 템플릿 경로를 함께 전달한다.
- 수정 후 품질 게이트를 재실행한다.
- 정해진 횟수 내 실패 시 저장 또는 커밋을 차단한다.

이 하네스는 `저장 전 강제`, `커밋 전 강제`, `CI 품질 게이트`로 확장 가능하다.

### 12.2.2 가비지 컬렉션 하네스

나쁜 코드 패턴이 누적되지 않도록 주기적으로 스캔하는 청소 에이전트를 둔다.

초기 스캔 대상 예시:

- 임시 `print`
- 추적되지 않는 `TODO`
- 추적되지 않는 `FIXME`
- 주석 처리된 죽은 코드
- `import *`
- `except:`
- `breakpoint()`
- 오래된 디버그 분기
- 미사용 fixture 후보

운영 방식:

- 주간 cron 실행
- 리포트 산출
- 정리 대상 PR 생성 또는 수동 정리

향후 확장:

- 중복 코드 탐지
- 불필요한 의존성 탐지
- 미사용 API 탐지
- 오래된 크롤러 파서 분기 정리

### 12.2.3 Parser Fixture 전략

네이버증권 HTML 구조 변경에 대비하기 위해 parser는 fixture 기반 회귀 테스트를 반드시 둔다.

권장 방식:

- 시장별 종목 목록 HTML fixture 저장
- 종목별 일봉 HTML fixture 저장
- 벤치마크 지수 HTML fixture 저장
- replay source로 fixture를 source adapter처럼 재생
- parser 변경 시 fixture 테스트와 replay 테스트를 함께 실행

효과:

- HTML 셀렉터 변경 감지
- 파싱 회귀 조기 발견
- 네트워크 없이도 안정적인 테스트 가능

### 12.3 설정 관리

환경변수 예시:

- `DATABASE_URL`
- `APP_ENV`
- `NAVER_REQUEST_TIMEOUT`
- `NAVER_MIN_DELAY_MS`
- `NAVER_MAX_DELAY_MS`
- `NAVER_MAX_RETRIES`
- `KIWOOM_FALLBACK_ENABLED`
- `KIWOOM_API_BASE_URL`
- `KIWOOM_APP_KEY` / `KIWOOM_SECRET_KEY`
- `KIWOOM_REQUESTS_PER_SECOND`
- `KIWOOM_MAX_REQUESTS_PER_BATCH`
- `KIWOOM_FALLBACK_CODES`
- `SLACK_WEBHOOK_URL`

### 12.4 법적/운영 리스크 관리

네이버증권 크롤링은 사이트 정책 변경이나 차단 정책에 영향을 받을 수 있다.

따라서 다음을 권장한다.

- 요청량 최소화
- 캐시 적극 활용
- 대체 데이터 소스 준비
- 파서 변경 가능성을 고려한 모듈 분리

Kiwoom REST는 Naver 실패 종목만 대상으로 하는 일봉 폴백으로 제한하고, 인증정보는
환경변수 또는 Secret Manager에서 주입한다. 주 공급자 전환은 canary와 데이터 사용
범위 검토 없이 수행하지 않는다.

---

## 13. 최종 권장안

이 프로젝트의 권장 구현안은 다음과 같다.

### 기술 조합

- Backend: `Python + FastAPI`
- Batch: `Python batch runner`
- Scheduler: `crontab`
- Database: `PostgreSQL + TimescaleDB`
- Frontend: `Next.js + React + ECharts`

### RS 정책

- `KOSPI` 종목은 `KOSPI` 대비 RS 계산
- `KOSDAQ` 종목은 `KOSDAQ` 대비 RS 계산
- 동일 시장 내 percentile 기반 `1~99` RS Rating 계산
- 최근 3개월 구간에 더 높은 가중치 부여

### 운영 정책

- 매일 `17:00 Asia/Seoul` 배치 실행
- rate-limiting + retry + backoff + circuit breaker 적용
- 실패 시 전일 데이터 유지
- 운영 로그와 알림 체계 포함

---

## 14. 다음 단계

다음 구현 순서를 권장한다.

1. DB 스키마 작성
2. 네이버증권 크롤러 구현
3. 일봉 적재 배치 구현
4. RS 계산 로직 구현
5. FastAPI 조회 API 구현
6. Next.js 대시보드 구현
7. cron 등록 및 운영 로그 구성

이 문서를 기준으로 바로 MVP 구현을 시작할 수 있다.
