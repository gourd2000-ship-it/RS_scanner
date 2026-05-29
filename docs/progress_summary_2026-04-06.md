# Progress Summary

작성일: `2026-04-06`

## 현재까지 완료된 작업

### 1. 아키텍처 문서화

- `Python + FastAPI + PostgreSQL/TimescaleDB + Next.js + crontab` 기준 권장 아키텍처 문서 작성
- `KOSPI 종목은 KOSPI 대비`, `KOSDAQ 종목은 KOSDAQ 대비` RS 계산 정책 반영
- 크롤링 rate-limiting, retry, backoff, circuit breaker 전략 문서화

관련 파일:

- [docs/rs_scanner_architecture.md](/home/autobot/dev/rs_scanner/docs/rs_scanner_architecture.md)

### 2. 프로젝트 기본 골격 생성

- Python 패키지 구조 생성
- FastAPI 진입점 추가
- Batch 진입점 추가
- SQLAlchemy 모델 추가
- Pydantic schema 추가
- service / repository / crawler / ops 디렉터리 분리

주요 파일:

- [pyproject.toml](/home/autobot/dev/rs_scanner/pyproject.toml)
- [app/main_api.py](/home/autobot/dev/rs_scanner/app/main_api.py)
- [app/main_batch.py](/home/autobot/dev/rs_scanner/app/main_batch.py)

### 3. DB persistence 연결

- in-memory repository에서 실제 SQLAlchemy 기반 repository 구조로 확장
- `symbols`, `benchmarks`, `daily_prices`, `benchmark_daily_prices`, `rs_scores`, `crawl_jobs`, `crawl_failures` 모델 작성
- DB 세션 스코프 및 `init_db()` 추가

주요 파일:

- [app/core/database.py](/home/autobot/dev/rs_scanner/app/core/database.py)
- [app/repositories/symbol_repository.py](/home/autobot/dev/rs_scanner/app/repositories/symbol_repository.py)
- [app/repositories/benchmark_repository.py](/home/autobot/dev/rs_scanner/app/repositories/benchmark_repository.py)
- [app/repositories/price_repository.py](/home/autobot/dev/rs_scanner/app/repositories/price_repository.py)
- [app/repositories/rs_repository.py](/home/autobot/dev/rs_scanner/app/repositories/rs_repository.py)

### 4. RS 계산 엔진 구현

- 시장별 벤치마크 정책 구현
- 3M, 6M, 9M, 12M 수익률 계산
- 벤치마크 대비 relative return 계산
- percentile 기반 `1~99` RS Rating 계산

주요 파일:

- [app/services/rs/policy.py](/home/autobot/dev/rs_scanner/app/services/rs/policy.py)
- [app/services/rs/calculator.py](/home/autobot/dev/rs_scanner/app/services/rs/calculator.py)

### 5. 배치 오케스트레이션 구현

- `sync_symbols`
- `sync_benchmarks`
- `sync_prices`
- `calculate_rs`
- `run_daily_job`

주요 파일:

- [app/services/batch/sync_symbols.py](/home/autobot/dev/rs_scanner/app/services/batch/sync_symbols.py)
- [app/services/batch/sync_benchmarks.py](/home/autobot/dev/rs_scanner/app/services/batch/sync_benchmarks.py)
- [app/services/batch/sync_prices.py](/home/autobot/dev/rs_scanner/app/services/batch/sync_prices.py)
- [app/services/batch/calculate_rs.py](/home/autobot/dev/rs_scanner/app/services/batch/calculate_rs.py)
- [app/services/batch/run_daily_job.py](/home/autobot/dev/rs_scanner/app/services/batch/run_daily_job.py)

### 6. 네이버증권 크롤링 구조 구현

- 네이버 HTTP client
- rate limiter
- retry helper
- parser 분리
- source adapter 구조화

주요 파일:

- [app/crawler/client.py](/home/autobot/dev/rs_scanner/app/crawler/client.py)
- [app/crawler/rate_limiter.py](/home/autobot/dev/rs_scanner/app/crawler/rate_limiter.py)
- [app/crawler/retry.py](/home/autobot/dev/rs_scanner/app/crawler/retry.py)
- [app/crawler/sources/naver.py](/home/autobot/dev/rs_scanner/app/crawler/sources/naver.py)
- [app/crawler/parsers/symbols.py](/home/autobot/dev/rs_scanner/app/crawler/parsers/symbols.py)
- [app/crawler/parsers/prices.py](/home/autobot/dev/rs_scanner/app/crawler/parsers/prices.py)
- [app/crawler/parsers/benchmarks.py](/home/autobot/dev/rs_scanner/app/crawler/parsers/benchmarks.py)

### 7. 페이지네이션 및 증분 수집 구현

- 종목 리스트 다중 페이지 수집 구조 추가
- 종목 가격 다중 페이지 순회 구조 추가
- 벤치마크 가격 다중 페이지 순회 구조 추가
- repository에서 마지막 수집일 조회
- `since_date` 기준 증분 수집 연결

주요 파일:

- [app/crawler/sources/base.py](/home/autobot/dev/rs_scanner/app/crawler/sources/base.py)
- [app/crawler/sources/naver.py](/home/autobot/dev/rs_scanner/app/crawler/sources/naver.py)
- [app/repositories/price_repository.py](/home/autobot/dev/rs_scanner/app/repositories/price_repository.py)

### 8. 하네스 체계 구축

#### 테스트/개발 하네스

- memory source 하네스
- replay source 하네스
- RS 계산 테스트
- 배치 통합 테스트

관련 파일:

- [tests/harness/fake_source.py](/home/autobot/dev/rs_scanner/tests/harness/fake_source.py)
- [tests/harness/replay_source.py](/home/autobot/dev/rs_scanner/tests/harness/replay_source.py)
- [tests/unit/test_rs_calculator.py](/home/autobot/dev/rs_scanner/tests/unit/test_rs_calculator.py)
- [tests/integration/test_batch_harness.py](/home/autobot/dev/rs_scanner/tests/integration/test_batch_harness.py)

#### 운영 하네스

- 저장 전 품질 게이트
- 자동 교정 루프
- auto-fix command 템플릿
- 가비지 컬렉션 에이전트
- git hook 템플릿

관련 파일:

- [app/ops/quality/hook_runner.py](/home/autobot/dev/rs_scanner/app/ops/quality/hook_runner.py)
- [app/ops/quality/auto_fix_loop.py](/home/autobot/dev/rs_scanner/app/ops/quality/auto_fix_loop.py)
- [app/ops/quality/auto_fix_command.py](/home/autobot/dev/rs_scanner/app/ops/quality/auto_fix_command.py)
- [app/ops/quality/garbage_collector.py](/home/autobot/dev/rs_scanner/app/ops/quality/garbage_collector.py)
- [scripts/install_hooks.sh](/home/autobot/dev/rs_scanner/scripts/install_hooks.sh)
- [.githooks/pre-commit](/home/autobot/dev/rs_scanner/.githooks/pre-commit)

### 9. Parser fixture 및 회귀 테스트 추가

- 네이버 HTML 샘플 fixture 저장
- parser 단위 테스트 추가
- replay source 통합 테스트 추가

관련 파일:

- [tests/fixtures/naver/symbols_kospi.html](/home/autobot/dev/rs_scanner/tests/fixtures/naver/symbols_kospi.html)
- [tests/fixtures/naver/symbols_kosdaq.html](/home/autobot/dev/rs_scanner/tests/fixtures/naver/symbols_kosdaq.html)
- [tests/fixtures/naver/benchmark_kospi.html](/home/autobot/dev/rs_scanner/tests/fixtures/naver/benchmark_kospi.html)
- [tests/fixtures/naver/benchmark_kosdaq.html](/home/autobot/dev/rs_scanner/tests/fixtures/naver/benchmark_kosdaq.html)
- [tests/unit/test_parsers.py](/home/autobot/dev/rs_scanner/tests/unit/test_parsers.py)
- [tests/integration/test_replay_source.py](/home/autobot/dev/rs_scanner/tests/integration/test_replay_source.py)

## 현재 동작 상태

### 가능한 것

- Python 프로젝트 구조는 준비됨
- DB 모델과 repository 구조는 준비됨
- batch orchestration 구조는 준비됨
- RS 계산 엔진은 동작 가능한 상태
- 네이버 크롤링 adapter 구조는 준비됨
- 페이지네이션/증분 수집 구조는 준비됨
- 품질 게이트와 가비지 컬렉터는 실행 가능
- fixture 기반 parser 회귀 테스트 구조는 준비됨

### 아직 미완성인 것

- 실제 PostgreSQL 연결 후 end-to-end 실행 검증
- 실제 네이버 HTML로 수집 성공 여부 검증
- `crawl_jobs`, `crawl_failures` 실제 persistence 연결
- 종목 상세 API
- 차트 API
- 랭킹 API 고도화
- API 조회 최적화
- 프론트엔드 구현
- cron 설치/운영 자동화 보강

## 최근 검증 상태

실행한 검증:

- `python3 -m compileall app tests`
- `python3 -m app.ops.quality.cli hook`
- `python3 -m app.ops.quality.cli gc`

결과:

- 모두 통과

제약:

- 현재 환경에는 `pytest`가 설치되어 있지 않아 실제 test runner 실행은 아직 못 함

## 다음 우선순위

다음 작업 후보는 아래 순서를 권장한다.

1. API 조회 모델과 쿼리 최적화 구현
2. `crawl_jobs` / `crawl_failures` persistence 연결
3. RS 상세/차트 API 구현
4. 실제 PostgreSQL 환경 연결
5. 실제 네이버 HTML 샘플 갱신 및 parser fixture 강화
6. Next.js 프론트엔드 골격 추가

## 메모

- 하네스는 현재 `개발 하네스`와 `운영 하네스` 두 축으로 나뉘어 있음
- 가비지 컬렉터는 현재 false positive를 줄인 상태이며 기본 통과
- 자동 교정 루프는 `CODEX_AUTO_FIX_COMMAND`를 연결하면 실제 수정 워커와 연결 가능
- git hook은 파일이 생성되어 있으나 설치는 별도로 `bash scripts/install_hooks.sh` 실행 필요
