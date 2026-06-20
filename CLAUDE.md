# CLAUDE.md

> **필수**: 모든 응답과 작업 시 반드시 `rules.md`의 규칙을 준수하십시오.

## Project Overview

RS Scanner is an IBD-style Relative Strength scanner for Korean stocks (KOSPI/KOSDAQ). It crawls Naver Finance for price data, computes relative strength ratings per market, and exposes results via a FastAPI API.

- **Language**: Python 3.12+
- **Framework**: FastAPI + SQLAlchemy 2.x + Pydantic
- **Database**: PostgreSQL + TimescaleDB
- **Crawler target**: Naver Finance (네이버증권)

## Commands

### Run API server

```bash
uvicorn app.main_api:app --reload
```

### Run batch pipeline

```bash
python -m app.main_batch
```

### Run tests

```bash
pytest
```

Install dev dependencies first: `pip install -e ".[dev]"`

### Quality gate

```bash
python3 -m app.ops.quality.cli hook
```

### Garbage collector scan

```bash
python3 -m app.ops.quality.cli gc
```

## Project Structure

```
app/
  api/v1/endpoints/     # FastAPI route handlers (health, rankings)
  core/                 # Config, database, logging, exceptions
  crawler/
    client.py           # HTTP client with rate limiting
    rate_limiter.py     # Request throttling (0.8-2.5s delay)
    retry.py            # Exponential backoff retry logic
    parsers/            # HTML parsers for symbols, prices, benchmarks
    sources/            # Data source adapters (base, naver)
  models/               # SQLAlchemy ORM models
  repositories/         # DB access layer (+ in-memory implementations for testing)
  schemas/              # Pydantic schemas
  services/
    batch/              # Batch orchestration (sync_symbols, sync_prices, etc.)
    rs/                 # RS calculation engine
    validation/         # Data quality validation
  ops/quality/          # Quality gate, auto-fix loop, garbage collector
  main_api.py           # API entrypoint
  main_batch.py         # Batch entrypoint
tests/
  fixtures/             # Saved Naver HTML for replay testing
  harness/              # fake_source.py, replay_source.py
  unit/                 # Parser tests, RS calculator tests
  integration/          # Replay source tests, batch harness tests
```

## Architecture Notes

### RS Calculation

- KOSPI stocks are rated against the KOSPI benchmark only
- KOSDAQ stocks are rated against the KOSDAQ benchmark only
- Weighted score: `0.40 * 3M + 0.20 * 6M + 0.20 * 9M + 0.20 * 12M` (relative returns vs benchmark)
- Winsorize: 점수 계산 전 기간별 상대수익률을 시장 분포의 1~99 퍼센타일로 클리핑 (극단치가 가중합을 왜곡하는 문제 방지, `RS_WINSORIZE_LOWER_PCT`/`RS_WINSORIZE_UPPER_PCT`로 조정 가능)
- Percentile within same market → RS Rating 1-99

### Crawler

- Rate limited: 0.8-2.5s random delay between requests
- Max 5 retries with exponential backoff
- Circuit breaker on consecutive 403/429 or high failure rate
- Incremental collection: only fetches pages after last stored date

### Repository Pattern

- Each model has a repository interface in `app/repositories/`
- In-memory implementations (`memory_*_repository.py`) exist for testing
- Real implementations use SQLAlchemy async sessions

### Testing Strategy

- **Unit tests**: Parser correctness, RS formula math
- **Integration tests**: Replay source (HTML fixtures as data source), batch harness (full pipeline with fake source)
- HTML fixtures in `tests/fixtures/` guard against Naver HTML structure changes

## Conventions

- All documentation and code comments are in Korean (한국어) where they exist
- Config via environment variables (see `app/core/config.py`): `DATABASE_URL`, `APP_ENV`, `NAVER_REQUEST_TIMEOUT`, etc.
- Batch execution order: `sync_symbols → sync_benchmarks → sync_daily_prices → calculate_rs`
- Quality reports are written to `.codex/reports/`

## Current Status

Phase 1~7 구현 완료:

- **API**: health, rankings, stocks (detail/rs-history/prices), crawl monitoring 엔드포인트 + 캐싱 + 페이지네이션
- **Batch**: sync_symbols → sync_benchmarks → sync_daily_prices → calculate_rs 파이프라인 + BatchOrchestrator (체크포인트, 트랜잭션 격리)
- **RS Engine**: 2-pass 계산 (윈저라이즈 클리핑 → 가중합 → 퍼센타일 순위)
- **Crawler**: Naver Finance 크롤러 + 증분 수집 + 회로 차단기
- **Frontend**: Next.js 대시보드 (RS 랭킹, 종목 상세, 운영 모니터링)
- **Testing**: 단위/통합/E2E 테스트 (17개 RS calculator 테스트 포함)
- **Infra**: Docker, GitHub Actions CI, Slack/Discord/Telegram 알림
