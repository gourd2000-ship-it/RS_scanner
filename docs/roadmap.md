# RS Scanner 개발 로드맵

## 1. 개요

이 문서는 RS Scanner 프로젝트의 향후 개발 로드맵을 정의한다.

### 개발 원칙

1. **구조 우선** — 스키마, 인터페이스, 쿼리 모델 등 구조를 먼저 확정한 뒤 구현에 들어간다.
2. **기반 → 공통기능 → 개별기능** — 인프라와 공통 모듈을 먼저 만들고, 그 위에 개별 기능을 올린다.
3. **기존 기능 충돌 확인 후 조치** — 매 Task마다 기존 코드와의 충돌 가능성을 사전 점검한다.

### 현재 상태 요약

| 영역 | 상태 | 완성도 |
|------|------|--------|
| 크롤러 (client, parsers, sources) | 완전 구현 | 100% |
| 배치 서비스 (sync_*, calculate_rs) | 완전 구현 | 100% |
| RS 계산 엔진 (calculator, policy) | 완전 구현 | 100% |
| ORM 모델 (7개 테이블) | 완전 구현 | 100% |
| 레포지토리 (symbol, benchmark, price, rs) | 완전 구현 | 100% |
| 테스트 (단위 6 + 통합 2 + fixture 8) | 완전 구현 | 100% |
| 품질 게이트 + GC 하네스 | 완전 구현 | 100% |
| API 엔드포인트 (health, rankings 기본만) | **부분 구현** | 25% |
| crawl_jobs/failures (모델만 존재, repo 없음) | **부분 구현** | 30% |
| PostgreSQL E2E 테스트 | **미구현** | 0% |
| Next.js 프론트엔드 | **미구현** | 0% |

---

## 2. Phase 0 — 기반 인프라

> DB 마이그레이션 도구를 도입하여 스키마 변경을 안전하게 관리할 수 있는 기반을 마련한다.

### Task 0-1: Alembic 초기 설정

- `pyproject.toml`에 `alembic` 의존성 추가
- `alembic init` 실행, `alembic/env.py`에서 `app.core.database.Base.metadata` 연결
- 기존 7개 모델에 대한 초기 마이그레이션 생성
- `APP_ENV`에 따라 `create_all` / Alembic 분기 처리

**관련 파일:**
- `pyproject.toml`
- `app/core/database.py`
- `app/models/__init__.py`
- 신규: `alembic.ini`, `alembic/env.py`, `alembic/versions/`

**충돌 확인:**
- `app/core/database.py`의 `init_db()` 내 `create_all`은 Alembic과 충돌 가능 → `APP_ENV` 분기로 해소

**선행 조건:** 없음

### Task 0-2: 인덱스 최적화 마이그레이션

- 아키텍처 문서에 정의된 복합 인덱스 추가:
  - `daily_prices(symbol_id, trade_date DESC)`
  - `benchmark_daily_prices(benchmark_id, trade_date DESC)`
  - `rs_scores(trade_date DESC, market, rs_rating DESC)`
  - `symbols(market, is_active)`
- 기존 단일 컬럼 인덱스와 중복 여부 확인 후 정리

**관련 파일:**
- `app/models/daily_price.py`
- `app/models/benchmark_daily_price.py`
- `app/models/rs_score.py`
- `app/models/symbol.py`

**충돌 확인:**
- `rs_scores` 모델에 이미 단일 인덱스가 존재 → 복합 인덱스 추가 후 쿼리 플랜 확인, 불필요 인덱스 정리

**선행 조건:** Task 0-1

---

## 3. Phase 1 — API 스키마 및 쿼리 모델 확정

> 구현 전에 인터페이스를 먼저 고정하여, 프론트엔드 개발과 병행할 수 있는 기반을 만든다.

### Task 1-1: API 쿼리 모델 정의

엔드포인트별 쿼리 파라미터 스키마를 정의한다.

| 엔드포인트 | 쿼리 파라미터 |
|-----------|-------------|
| `GET /api/v1/symbols` | `market`, `is_active`, `search`, `page`, `size` |
| `GET /api/v1/rankings/rs` | `market`, `trade_date`, `min_rs`, `max_rs`, `sort_by`, `order`, `page`, `size` |
| `GET /api/v1/symbols/{code}/prices` | `start_date`, `end_date`, `limit` |
| `GET /api/v1/symbols/{code}/rs` | `start_date`, `end_date`, `limit` |

공통 페이지네이션 스키마: `PaginationParams`, `PaginatedResponse[T]`

**관련 파일:**
- `app/schemas/market_data.py` (기존 스키마 확인)
- 신규: `app/schemas/query.py`
- 신규: `app/schemas/response.py`

**충돌 확인:**
- 기존 `SymbolPayload`, `RsResultPayload`는 크롤러/배치 내부에서도 사용 중 → API 응답용 스키마를 별도 분리하여 결합도를 낮춤

**선행 조건:** 없음 (Phase 0과 병행 가능)

### Task 1-2: API 응답 스키마 정의

| 응답 모델 | 용도 |
|----------|------|
| `SymbolListResponse` | 종목 목록 (페이지네이션) |
| `RsRankingResponse` | RS 랭킹 목록 (페이지네이션) |
| `SymbolDetailResponse` | 종목 상세 (메타 + 가격 + RS + 벤치마크) |
| `PriceSeriesResponse` | 가격 시계열 (차트 데이터) |
| `RsSeriesResponse` | RS 시계열 (차트 데이터) |
| `JobStatusResponse` | 배치 실행 상태 |

**관련 파일:**
- `app/schemas/market_data.py`
- 신규: `app/schemas/response.py`
- `app/api/v1/endpoints/rankings.py` — dict 응답을 Pydantic 모델로 교체

**충돌 확인:**
- `rankings.py`의 기존 응답 `{"market", "count", "items"}` → 새 `PaginatedResponse`에 `market`, `total_count`, `page`, `size`, `items` 포함하여 상위 호환 유지. 현재 프론트엔드가 없으므로 안전하게 변경 가능.

**선행 조건:** Task 1-1

---

## 4. Phase 2 — crawl_jobs / crawl_failures 영속화 배선

> 이미 존재하는 모델을 실제로 사용할 수 있도록 레포지토리를 만들고 배치에 연결한다.

### Task 2-1: CrawlJob / CrawlFailure 레포지토리 구현

- `crawl_job_repository.py` — `create_job`, `finish_job`, `get_latest`
- `crawl_failure_repository.py` — `record_failure`, `list_by_job`
- 메모리 구현체 — `memory_crawl_job_repository.py`, `memory_crawl_failure_repository.py`

**관련 파일:**
- `app/models/crawl_job.py` (이미 존재)
- `app/models/crawl_failure.py` (이미 존재)
- 기존 패턴 참고: `app/repositories/symbol_repository.py`
- 신규: `app/repositories/crawl_job_repository.py`
- 신규: `app/repositories/crawl_failure_repository.py`
- 신규: `app/repositories/memory_crawl_job_repository.py`
- 신규: `app/repositories/memory_crawl_failure_repository.py`

**충돌 확인:** 없음 (신규 파일만 추가)

**선행 조건:** 없음 (Phase 0/1과 병행 가능)

### Task 2-2: BatchContext에 레포지토리 추가

- `BatchContext` 데이터클래스에 `crawl_job_repository`, `crawl_failure_repository` 필드 추가
- `build_db_batch_context()`, `build_memory_batch_context()` 함수 수정

**관련 파일:**
- `app/services/batch/context.py`

**충돌 확인:**
- 기존 `build_memory_batch_context()`를 사용하는 테스트에서 새 필드에 대한 처리 필요 → 기본값을 `None`으로 설정하거나 메모리 구현체를 함께 제공

**선행 조건:** Task 2-1

### Task 2-3: run_daily_job에 작업 추적 로직 배선

- 배치 시작 시 `create_job("daily_full")` 호출
- 각 단계 예외 발생 시 `record_failure()` 호출
- 완료 시 `finish_job()` 호출로 통계 기록

**관련 파일:**
- `app/services/batch/run_daily_job.py`
- `app/services/batch/sync_prices.py` (개별 종목 실패 시 기록)

**충돌 확인:**
- `run_daily_job`의 반환 타입 `dict[str, object]`에 `job_id` 키 추가는 하위 호환적
- 기존 통합 테스트에서 `crawl_job_repository`가 `None`인 경우를 대비한 방어 코드 필요

**선행 조건:** Task 2-2

---

## 5. Phase 3 — API 엔드포인트 확장

> 아키텍처 문서에 정의된 전체 API를 구현한다.

### Task 3-1: rankings/rs 엔드포인트 고도화

- 쿼리 모델 적용 (`trade_date`, `min_rs`, `max_rs`, `sort_by`, `order`, `page`, `size`)
- `RsRepository.list_market()` 확장: 필터링, 정렬, 오프셋/리밋
- 응답을 `PaginatedResponse[RsRankingItem]`으로 변경
- `RsRankingItem`에 `name`, `close`, `change_rate` 포함 (Symbol + DailyPrice 조인)

**관련 파일:**
- `app/api/v1/endpoints/rankings.py`
- `app/repositories/rs_repository.py` — `list_market()` 확장

**충돌 확인:**
- `list_market()`의 새 파라미터는 모두 기본값을 가지므로 기존 내부 호출에 영향 없음

**선행 조건:** Task 1-2

### Task 3-2: symbols 엔드포인트 신규 구현

| 엔드포인트 | 기능 |
|-----------|------|
| `GET /api/v1/symbols` | 종목 목록 (시장 필터, 검색, 페이지네이션) |
| `GET /api/v1/symbols/{code}` | 종목 상세 (메타 + 최신 가격 + 최신 RS) |
| `GET /api/v1/symbols/{code}/prices` | 가격 시계열 |
| `GET /api/v1/symbols/{code}/rs` | RS 시계열 |

**관련 파일:**
- 신규: `app/api/v1/endpoints/symbols.py`
- `app/main_api.py` — 라우터 등록
- `app/repositories/symbol_repository.py` — `get_by_code()`, `list_filtered()` 추가
- `app/repositories/rs_repository.py` — `get_symbol_rs_series()` 추가
- `app/repositories/price_repository.py` — 날짜 범위 필터 추가

**충돌 확인:**
- `PriceRepository.get_symbol_prices()`에 `start_date`, `end_date` 옵션 파라미터 추가 → 기존 호출에 영향 없음
- URL 경로 `/rankings/rs`와 `/symbols/{code}/rs`는 구조가 달라 충돌 없음

**선행 조건:** Task 1-2

### Task 3-3: jobs 엔드포인트 신규 구현

- `GET /api/v1/jobs/latest` — 최근 배치 실행 상태 조회
- `CrawlJobRepository.get_latest()` 활용

**관련 파일:**
- 신규: `app/api/v1/endpoints/jobs.py`
- `app/main_api.py` — 라우터 등록

**충돌 확인:** 없음 (신규 파일)

**선행 조건:** Task 2-1

### Task 3-4: health 엔드포인트 고도화

- DB 연결 확인 로직 추가
- 최근 배치 성공 시각 표시
- 응답에 `db_connected`, `last_batch_at`, `last_batch_status` 필드 추가

**관련 파일:**
- `app/api/v1/endpoints/health.py`

**충돌 확인:**
- 기존 `{"status": "ok"}` 응답에 필드를 추가하는 것은 하위 호환적

**선행 조건:** Task 2-1

---

## 6. Phase 4 — 테스트 강화

> 새로 추가된 모듈에 대한 테스트와 PostgreSQL E2E 테스트를 도입한다.

### Task 4-1: 신규 레포지토리 단위 테스트

- crawl_job/failure 메모리 구현체 테스트
- `list_market()` 확장 파라미터 테스트
- `get_by_code()`, `list_filtered()` 테스트
- 날짜 범위 필터 테스트

**관련 파일:**
- 신규: `tests/unit/test_crawl_repositories.py`
- 신규: `tests/unit/test_repository_queries.py`

**선행 조건:** Task 2-1, Task 3-1, Task 3-2

### Task 4-2: API 엔드포인트 테스트

- FastAPI `TestClient` 기반 통합 테스트
- 각 엔드포인트 정상 응답, 에러 케이스, 페이지네이션 검증

**관련 파일:**
- 신규: `tests/integration/test_api_endpoints.py`

**선행 조건:** Task 3-1 ~ 3-4

### Task 4-3: PostgreSQL E2E 통합 테스트

- Docker Compose로 PostgreSQL + TimescaleDB 테스트 컨테이너 구성
- 전체 배치 파이프라인 E2E: `sync_symbols → sync_benchmarks → sync_prices → calculate_rs`
- API E2E: DB 적재 후 API 조회 검증
- `@pytest.mark.e2e` 마커로 일반 테스트와 분리

**관련 파일:**
- 신규: `docker-compose.test.yml`
- 신규: `tests/e2e/conftest.py`
- 신규: `tests/e2e/test_batch_e2e.py`
- 신규: `tests/e2e/test_api_e2e.py`

**선행 조건:** Task 0-1, Task 2-3, Task 3-1 ~ 3-4

---

## 7. Phase 5 — Next.js 프론트엔드

> RS 대시보드, 종목 상세, 운영 상태 페이지를 구현한다.

### Task 5-1: Next.js 프로젝트 초기화

- `frontend/` 디렉토리에 Next.js 프로젝트 생성 (App Router, TypeScript, Tailwind CSS)
- Apache ECharts 의존성 추가
- API 클라이언트 유틸리티 (fetch 래퍼, 타입 정의)
- 백엔드 OpenAPI 스펙 기반 타입 동기화 방법 결정

**선행 조건:** Task 3-1 ~ 3-4 (API 스펙 확정 필요)

### Task 5-2: RS 랭킹 대시보드

- KOSPI / KOSDAQ 탭 전환
- RS 랭킹 테이블 (정렬, 필터, 페이지네이션)
- RS Rating 구간 필터 슬라이더
- 종목 검색, 데이터 기준일 표시

**관련 API:** `GET /api/v1/rankings/rs`, `GET /api/v1/symbols`

**선행 조건:** Task 5-1

### Task 5-3: 종목 상세 페이지

- 종목 기본 정보 표시
- ECharts 일봉 캔들 차트
- 벤치마크 대비 RS 라인 오버레이
- RS Rating 추이, 기간별 수익률

**관련 API:** `GET /api/v1/symbols/{code}`, `.../prices`, `.../rs`

**선행 조건:** Task 5-1

### Task 5-4: 운영 상태 페이지

- 최근 배치 실행 상태, 성공/실패 건수
- 실패 종목 목록, 마지막 업데이트 시각

**관련 API:** `GET /api/v1/jobs/latest`, `GET /api/v1/health`

**선행 조건:** Task 5-1, Task 3-3

---

## 8. Phase 6 — 운영 안정화

> 프로덕션 배포를 위한 마무리 작업.

### Task 6-1: CORS 및 보안 설정

- `main_api.py`에 CORS 미들웨어 추가
- API 응답 캐싱 전략 수립

**선행 조건:** Task 5-1

### Task 6-2: Docker Compose 운영 환경

- PostgreSQL + TimescaleDB, FastAPI, Next.js 포함
- 환경변수 관리 (`.env.production`)
- crontab 배치 스케줄러 설정

**선행 조건:** Phase 5 완료

### Task 6-3: 알림 연동

- 배치 실패 시 Slack/Discord 웹훅 알림
- `app/core/config.py`의 `SLACK_WEBHOOK_URL` 활용

**관련 파일:**
- 신규: `app/core/notification.py`
- `app/services/batch/run_daily_job.py`

**선행 조건:** Task 2-3

---

## 9. 의존 관계 및 병행 가능 영역

```text
┌─────────────────────────────────────────────────────────┐
│                    병행 가능 구간                         │
│                                                         │
│  Phase 0 (Alembic)   Phase 1 (스키마)   Phase 2 (영속화) │
│  Task 0-1 → 0-2      Task 1-1 → 1-2    Task 2-1 → 2-2  │
│                                               ↓         │
│                                          Task 2-3       │
└────────────┬──────────────┬─────────────────┬───────────┘
             │              │                 │
             ▼              ▼                 ▼
        ┌────────────────────────────────────────┐
        │        Phase 3 (API 확장)               │
        │  Task 3-1 ← Phase 1                    │
        │  Task 3-2 ← Phase 1                    │
        │  Task 3-3 ← Phase 2                    │
        │  Task 3-4 ← Phase 2                    │
        └──────────────────┬─────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │        Phase 4 (테스트 강화)           │
        │  Task 4-1 ← Phase 2, 3              │
        │  Task 4-2 ← Phase 3                 │
        │  Task 4-3 ← Phase 0, 2, 3           │
        └──────────────────┬───────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │        Phase 5 (프론트엔드)            │
        │  Task 5-1 ← Phase 3                 │
        │  Task 5-2, 5-3, 5-4 ← Task 5-1     │
        └──────────────────┬───────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │        Phase 6 (운영 안정화)           │
        │  Task 6-1 ← Task 5-1                │
        │  Task 6-2 ← Phase 5                 │
        │  Task 6-3 ← Task 2-3                │
        └──────────────────────────────────────┘
```

**핵심 병행 포인트:**
- Phase 0, 1, 2는 서로 독립적이므로 **동시 진행 가능**
- Phase 3은 Phase 1(스키마)과 Phase 2(레포지토리) 완료 후 시작
- Phase 5는 Phase 3(API 확정) 후 시작
- Task 6-3(알림)은 Phase 5를 기다리지 않고 Task 2-3 완료 후 바로 착수 가능

---

## 10. 충돌 위험 체크리스트

각 Phase에서 기존 코드와 충돌할 수 있는 지점과 대응 방안을 정리한다.

| Phase | 충돌 지점 | 위험도 | 대응 방안 |
|-------|----------|--------|----------|
| 0 | `init_db()`의 `create_all`과 Alembic 충돌 | 중 | `APP_ENV` 분기 처리 |
| 0 | 복합 인덱스와 기존 단일 인덱스 중복 | 하 | 쿼리 플랜 확인 후 불필요 인덱스 정리 |
| 1 | 내부용 페이로드와 API 응답 스키마 혼용 | 중 | 스키마를 내부용/API용으로 명확히 분리 |
| 1 | `rankings.py`의 응답 구조 변경 | 하 | 프론트엔드 미존재로 안전 변경 가능 |
| 2 | `BatchContext` 필드 추가 시 기존 테스트 | 중 | 새 필드 기본값 `None` + 방어 코드 |
| 2 | `run_daily_job` 반환값 변경 | 하 | `job_id` 키 추가만으로 하위 호환 |
| 3 | `list_market()` 파라미터 확장 | 하 | 새 파라미터 모두 기본값 보유 |
| 3 | `PriceRepository` 메서드 확장 | 하 | 옵션 파라미터 추가로 기존 호출 무영향 |
| 4 | `pyproject.toml`의 `testpaths` 설정 | 하 | `@pytest.mark.e2e` 마커로 분리 |
| 5 | 없음 (완전 신규 디렉토리) | — | — |
| 6 | `main_api.py` 미들웨어 추가 | 하 | 기존 라우터에 영향 없음 |
