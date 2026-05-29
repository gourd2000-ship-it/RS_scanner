# RS Scanner

[![CI](https://github.com/yourusername/rs_scanner/workflows/CI/badge.svg)](https://github.com/yourusername/rs_scanner/actions)
[![codecov](https://codecov.io/gh/yourusername/rs_scanner/branch/main/graph/badge.svg)](https://codecov.io/gh/yourusername/rs_scanner)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

국내 주식용 `IBD-style Relative Strength` 스캐너의 Python 프로젝트입니다.

KOSPI와 KOSDAQ 종목의 상대 강도를 계산하고, FastAPI를 통해 제공합니다.

## 주요 기능

### API (FastAPI)
- ✅ **Rankings API**: KOSPI/KOSDAQ 시장별 RS 랭킹 조회
- ✅ **Stocks API**: 종목 상세 정보, RS 이력, 가격 데이터
- ✅ **Crawl API**: 크롤링 작업 모니터링, 실패 내역 조회
- ✅ **Health API**: 서비스 상태 확인, 캐시 통계
- ✅ 쿼리 최적화 (JOIN, Window Function)
- ✅ 캐싱 레이어 (TTL 기반 in-memory)
- ✅ 통일된 에러 처리

### 크롤러
- ✅ **Naver Finance** 가격 데이터 수집
- ✅ Rate Limiting (0.8-2.5초 랜덤 지연)
- ✅ 지수 백오프 재시도 (최대 5회)
- ✅ 증분 수집 (마지막 수집 이후 데이터만)
- ✅ Circuit Breaker (연속 실패 시 중단)

### RS 계산 엔진
- ✅ **IBD-style RS Rating** (1~99)
- ✅ 시장별 벤치마크 (KOSPI, KOSDAQ)
- ✅ 가중 평균 (3M 40%, 6M 20%, 9M 20%, 12M 20%)
- ✅ 백분위 기반 순위

### 테스트 & 품질
- ✅ **37개 통합 테스트** (100% 통과)
- ✅ Fixture/Replay 기반 회귀 테스트
- ✅ 품질 게이트 (pytest, compileall)
- ✅ 자동 교정 루프
- ✅ 가비지 컬렉터

## 추천 실행 방식

### API

```bash
uvicorn app.main_api:app --reload
```

### Batch

```bash
python -m app.main_batch
```

### Test

```bash
# 전체 테스트
pytest

# API 통합 테스트만
pytest tests/integration/api/ -v

# 커버리지 측정
pytest tests/integration/api/ --cov=app/api --cov-report=html
```

## 하네스 구조

- `tests/harness/fake_source.py`
  - 메모리 기반 배치 통합 테스트용
- `tests/harness/replay_source.py`
  - 저장된 HTML fixture 재생용
- `tests/unit/test_parsers.py`
  - 네이버 HTML parser 회귀 테스트용
- `tests/integration/test_replay_source.py`
  - fixture 묶음을 source처럼 재생하는 통합 테스트용
- `tests/unit/test_rs_calculator.py`
  - RS 계산 로직 회귀 테스트용
- `tests/integration/test_batch_harness.py`
  - 배치 오케스트레이션 통합 테스트용
- `app/ops/quality/hook_runner.py`
  - 저장 전 또는 커밋 전 품질 게이트 실행
- `app/ops/quality/auto_fix_loop.py`
  - 품질 게이트 실패 시 자동 교정 루프 수행
- `app/ops/quality/garbage_collector.py`
  - 나쁜 코드 패턴 누적 여부를 주기적으로 스캔

## 운영 하네스

### 1. 자동 강제 시스템

- `python3 -m app.ops.quality.cli hook`
  - `compileall`, `pytest`를 실행하고 `.codex/reports/quality-gate.json`에 결과 저장
- `python3 -m app.ops.quality.cli auto-fix`
  - 검사 실패 시 `CODEX_AUTO_FIX_COMMAND`를 호출해 자동 교정 루프 수행
- `python3 -m app.ops.quality.auto_fix_command`
  - 실제 AI 연동 전에도 붙여둘 수 있는 기본 자동 수정 커맨드 템플릿
- `.githooks/pre-commit`
  - 커밋 전에 자동 교정 루프를 실행하는 기본 훅 템플릿

설치:

```bash
bash scripts/install_hooks.sh
```

자동 교정 커맨드 예시:

```bash
export CODEX_AUTO_FIX_COMMAND="bash scripts/run_auto_fix_command.sh"
```

이 설정을 두면 자동 교정 루프가 실패 리포트와 프롬프트 템플릿을 `.codex/reports/` 아래에 생성한다.

### 2. 가비지 컬렉션 에이전트

- `python3 -m app.ops.quality.cli gc`
  - `print(`, 남은 `TODO`/`FIXME`, 주석 처리된 코드, `import *`, `except:`, `breakpoint(` 등을 스캔
  - 결과를 `.codex/reports/garbage-collector.json`에 저장

운영 예시:

- 매주 1회 cron으로 `scripts/run_garbage_collector.sh` 실행
- 결과 리포트를 보고 정리 대상 PR 생성

## 개발 현황

### 완료
- ✅ PostgreSQL + TimescaleDB 데이터베이스 설정
- ✅ Alembic 마이그레이션
- ✅ FastAPI 9개 엔드포인트 구현
- ✅ 쿼리 최적화 (평균 15-20ms)
- ✅ 캐싱 레이어 추가
- ✅ 37개 통합 테스트 (100% 통과)
- ✅ CI/CD 파이프라인 (GitHub Actions)

### 진행 중
- 🔄 실시간 크롤링 (591/2,400 종목, 24.6%)
- 🔄 Docker 컨테이너화

### 예정
- ⏳ Next.js 프론트엔드
- ⏳ 프로덕션 배포
- ⏳ 실시간 데이터 업데이트 스케줄러

## 문서

- [쿼리 최적화 보고서](docs/query_optimization_report.md)
- [테스트 보고서](docs/test_report.md)
- [배포 가이드](docs/deployment.md) (작성 예정)
