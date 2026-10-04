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

## 백테스트 조건 입력 화면

`/backtests`에서 운영자 비밀번호로 접속한다. JSON 대신 시장, 보유 종목 수, 종목별 비중, 거래 비용을 입력하고 매수·매도 조건의 지표·비교·기준값을 선택한다. `조건 추가`와 `AND/OR 묶음 추가`로 조건을 조합한다. 기간 수익률은 계산 기간도 거래일로 지정한다.

비율 입력은 모두 % 단위다. 예를 들어 슬리피지 `0.1`은 0.1%, 손절 `5`는 5% 손실 기준이다. 손절·익절·최대 보유 기간은 빈칸이면 적용하지 않는다.

`전략 저장` 후 시작일·종료일을 선택해 실행 요청한다. 저장된 전략과 버전을 불러올 수 있으며, 조건을 수정하면 `새 버전으로 저장`해야 실행할 수 있다. 실행 기록에서 상태와 데이터 부족 사유를 확인한다. 실행 요청 화면의 제공이 워커 가동이나 결과 상세 화면의 완료를 뜻하지는 않는다.

입력 변환 회귀 테스트: `cd frontend && node --experimental-strip-types --test tests/backtest-form.test.mjs` (Node 22.6 이상).

## EMA 운영자 조회

EMA 결과는 브라우저에서 백테스트 운영자 로그인 세션을 가진 경우에만 조회한다. `GET /api/v1/backtests/indicators/ema`에 `code`, `start`, `end`를 넣고, 코드가 과거 여러 `Instrument`에 연결될 수 있으면 응답의 409 사유를 확인한 뒤 `instrument_id`를 함께 넣는다. 코드만으로 역사 identity를 임의 선택하지 않는다.

응답은 현재 generation의 거래일 오름차순 page이며, 매 거래일마다 EMA 5·20·50·200을 모두 반환한다. `value`는 Decimal 정밀도를 보존하는 문자열이고, `status`와 `reason_code`를 함께 확인해야 한다. `warming_up`과 `data_unavailable` 값은 조건 또는 백테스트 입력으로 사용하면 안 된다. `as_of`는 현재 generation의 최신 거래일, `calculated_at`은 그 generation의 마지막 완료 계산 시각이다.

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
