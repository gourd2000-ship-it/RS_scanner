# E2E 테스트 가이드

## 개요

E2E (End-to-End) 테스트는 실제 PostgreSQL 데이터베이스를 사용하여 전체 시스템을 통합 테스트합니다.

- **배치 파이프라인**: `sync_symbols → sync_benchmarks → sync_prices → calculate_rs`
- **API 엔드포인트**: 모든 REST API 엔드포인트 검증
- **데이터 영속성**: PostgreSQL에 데이터가 올바르게 저장되고 조회되는지 검증

## 사전 요구사항

- Docker 및 Docker Compose 설치
- Python 3.12+
- 개발 의존성 설치: `pip install -e ".[dev]"`

## E2E 테스트 실행 방법

### 1. 테스트 DB 컨테이너 시작

```bash
docker-compose -f docker-compose.test.yml up -d
```

이 명령은 PostgreSQL + TimescaleDB 컨테이너를 시작합니다:
- 포트: `5433` (기존 개발 DB와 충돌 방지)
- 데이터베이스: `rs_scanner_test`
- 사용자: `rs_scanner_test`
- 비밀번호: `rs_scanner_test_pass`
- 데이터 저장: tmpfs (메모리, 빠른 테스트)

### 2. E2E 테스트 실행

```bash
# 모든 E2E 테스트 실행
pytest -m e2e

# verbose 모드로 실행
pytest -m e2e -v

# 특정 파일만 실행
pytest tests/e2e/test_batch_e2e.py -v

# 특정 테스트만 실행
pytest tests/e2e/test_batch_e2e.py::test_full_batch_pipeline_e2e -v
```

### 3. 테스트 DB 컨테이너 종료

```bash
docker-compose -f docker-compose.test.yml down
```

## E2E가 아닌 일반 테스트 실행

```bash
# E2E 테스트 제외하고 실행
pytest -m "not e2e"

# 모든 테스트 실행 (E2E 포함)
pytest
```

## 테스트 구조

```
tests/e2e/
├── __init__.py
├── conftest.py              # E2E 픽스처 (DB 세션, API 클라이언트 등)
├── test_batch_e2e.py        # 배치 파이프라인 E2E 테스트
└── test_api_e2e.py          # API 엔드포인트 E2E 테스트
```

## E2E 테스트 목록

### 배치 파이프라인 E2E (`test_batch_e2e.py`)

1. **전체 배치 파이프라인 E2E**
   - 전체 배치 실행 및 DB 저장 검증
   - Symbols, Benchmarks, Prices, RS Scores, CrawlJobs 테이블 검증

2. **증분 동기화 E2E**
   - 이미 저장된 데이터 재크롤링 방지 검증

3. **RS 계산 정확도 E2E**
   - 명확한 수익률 패턴으로 RS 계산 정확도 검증

4. **크롤링 작업 추적 E2E**
   - CrawlJob 레코드 생성 및 상태 추적 검증

5. **여러 시장 동시 처리 E2E**
   - KOSPI/KOSDAQ 독립적 랭킹 검증

### API 엔드포인트 E2E (`test_api_e2e.py`)

1. **Health 엔드포인트**
2. **Rankings API** (조회, 필터링, 정렬, 페이지네이션)
3. **종목 목록 API** (조회, 시장별 필터, 검색)
4. **종목 상세 API**
5. **종목 가격 이력 API** (날짜 범위 필터링)
6. **종목 RS 이력 API**
7. **크롤링 통계 API**
8. **전체 워크플로우** (배치 → API 조회 통합 시나리오)

## 환경 변수 설정

E2E 테스트는 기본적으로 `docker-compose.test.yml`의 설정을 사용하지만,
필요시 환경 변수로 오버라이드할 수 있습니다:

```bash
export E2E_DATABASE_URL="postgresql+psycopg://user:pass@localhost:5433/dbname"
pytest -m e2e
```

## CI/CD에서 E2E 테스트 실행

GitHub Actions 예시:

```yaml
- name: Start test database
  run: docker-compose -f docker-compose.test.yml up -d

- name: Wait for database
  run: sleep 5

- name: Run E2E tests
  run: pytest -m e2e -v

- name: Stop test database
  run: docker-compose -f docker-compose.test.yml down
```

## 트러블슈팅

### 1. 포트 충돌

**문제**: `bind: address already in use`

**해결**:
```bash
# 5433 포트를 사용하는 프로세스 확인
lsof -i :5433

# 기존 컨테이너 종료
docker-compose -f docker-compose.test.yml down
```

### 2. 마이그레이션 실패

**문제**: `Alembic migration failed`

**해결**: conftest.py에서 자동으로 대체 수단(create_all)을 사용하지만,
수동으로 마이그레이션이 필요한 경우:

```bash
export DATABASE_URL="postgresql://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test"
alembic upgrade head
```

### 3. 테스트 DB 데이터 정리

**문제**: 이전 테스트 데이터가 남아있음

**해결**:
```bash
# 컨테이너를 완전히 재시작 (tmpfs이므로 데이터 자동 삭제)
docker-compose -f docker-compose.test.yml down
docker-compose -f docker-compose.test.yml up -d
```

### 4. 테스트 격리 실패

**문제**: 테스트 간 데이터 충돌

**설명**: 각 테스트는 트랜잭션으로 격리되어 롤백됩니다.
테스트 간 데이터 공유가 필요하지 않으므로 격리가 보장됩니다.

## 모범 사례

1. **E2E 테스트는 느리므로 꼭 필요한 경우만 작성**
   - 단위 테스트로 커버 가능하면 단위 테스트 작성
   - 통합 테스트로 충분하면 통합 테스트 사용

2. **@pytest.mark.e2e 마커 반드시 추가**
   - 일반 테스트와 구분하여 선택적 실행 가능

3. **독립적인 테스트 작성**
   - 각 테스트는 다른 테스트에 의존하지 않아야 함
   - 테스트 순서에 무관하게 통과해야 함

4. **명확한 테스트 이름 사용**
   - `test_<feature>_e2e` 형식
   - 무엇을 테스트하는지 이름만으로 알 수 있어야 함

## 참고 자료

- [pytest markers](https://docs.pytest.org/en/stable/how-to/mark.html)
- [Docker Compose](https://docs.docker.com/compose/)
- [TimescaleDB](https://www.timescale.com/)
