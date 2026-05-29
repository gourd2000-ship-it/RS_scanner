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

Backend core (crawler, RS engine, batch orchestration, test harness) is implemented. Remaining work:

1. API query models and query optimization
2. crawl_jobs/crawl_failures persistence wiring
3. RS detail/chart API endpoints
4. PostgreSQL E2E integration testing
5. Next.js frontend (not yet started)
