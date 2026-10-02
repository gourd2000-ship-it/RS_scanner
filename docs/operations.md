# 운영 절차

## 로컬 개발

Python 3.12와 PostgreSQL이 필요하다. 의존성을 설치한 뒤 DB를 기동하고 migration을 적용한다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d postgres
alembic upgrade head
uvicorn app.main_api:app --reload
```

`DATABASE_URL`은 필수다. 공급자 키, 알림 token, 내부 Bearer token은 환경 변수 또는 secret store에서만 주입한다. Kiwoom fallback과 EOD provider는 기본 비활성 상태이며, 켜기 전에 공급자 계약·권한·canary 결과를 확인한다. repair·analysis 쓰기 API는 `OPERATOR_*` 설정으로 승인된 사람 운영자에게만 열며, `AGENT_SERVICE_TOKENS`로는 호출할 수 없다.

## 검증

```bash
pytest -m "not integration and not api"
pytest tests/integration/api -q
python -m compileall app scripts
git diff --check
```

schema 변경은 위 검증과 별도로 격리 PostgreSQL에서 `alembic upgrade head`를 적용하고 downgrade 또는 재구성 절차를 확인한다. 프런트엔드 변경은 `cd frontend && npm run lint && npm run build`를 실행한다.

## 일상 배치와 감사

일상 수집은 `python -m app.main_batch`로 실행한다. 명부만 갱신할 때는 `--symbols-only`를 사용한다. 배치 실패는 재시도 대상·오류 원인을 보존하며, 실패를 정상 거래일로 기록하지 않는다.

역사 OHLCV의 기준선 감사는 읽기 전용으로 실행한다.

```bash
APP_ENV=production .venv/bin/python scripts/audit_historical_ohlcv.py \
  --start 2013-01-01 --end 2026-09-04 \
  --selection-as-of 2026-10-01 \
  --observation-cutoff 2026-10-02T08:40:00Z \
  --adjustment-policy kiwoom:1 --exclude-delisted --read-only \
  --output reports/cleansing/baseline_v5_2013_20260904
```

결과의 manifest, summary, assessment, gaps, anomalies, source conflicts, excluded universe를 함께 보관한다. 현재 기준선에서 dataset 생성 전에는 `complete` 판정만 선택한다. `scripts/create_clean_backtest_dataset.py --create`는 운영 DB에 쓰므로 감사 결과와 발행 범위를 사람이 검토한 뒤에만 실행한다.

## 배포

이미지는 `docker compose up -d` 또는 운영 오케스트레이터로 기동한다. 배포 전 migration 호환성, 비밀값 주입, 내부 자동화 token의 읽기 scope, health endpoint를 확인한다. 배포 후에는 최근 batch의 상태·coverage·인증 거부 로그를 확인한다. 비밀값 노출 의심 시 배포를 계속하지 말고 token/키 교체 후 연결 설정을 갱신한다.
