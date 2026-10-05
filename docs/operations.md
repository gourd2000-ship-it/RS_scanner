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

## 역사 EMA 계산

EMA 5·20·50·200은 검증된 관측 원본과 당시의 identity snapshot만 사용한다. 먼저 격리 PostgreSQL에서 migration과 대표 종목 계산을 확인한 뒤, 운영에서는 같은 범위·공급자·조정 기준·parser version·UTC cutoff를 명시한 dry-run 보고서를 만든다. 기본 명령은 DB에 series, run, input snapshot, value를 하나도 쓰지 않는다.

```bash
APP_ENV=production .venv/bin/python scripts/backfill_ema.py \
  --start 2013-01-01 --end 2026-09-04 \
  --provider kiwoom --adjustment-type 1 --parser-version kiwoom-v2 \
  --observation-cutoff 2026-10-02T08:40:00Z \
  --chunk-size 25 --output reports/ema/plan_2013_20260904.json
```

보고서에서 대상 종목, 각 EMA 최초 `available` 일자, `warming_up`·`data_unavailable` 수, 예상 input/value 행·저장량·시간, `rebuild` 대상을 검토한다. `report_hash`와 입력 정책을 운영 기록에 남긴다. dry-run의 대상은 KRX 거래일과 cutoff 이전의 정책 일치 immutable identity 관측으로 결정되며, `--instrument-id`를 반복해 표본이나 재처리 대상을 고정할 수 있다.

운영 적용은 backup, migration 상태, dry-run 보고서를 검토한 뒤에만 같은 인수에 `--apply`를 추가해 실행한다. 명령은 종목별로 완료된 불변 run을 커밋하므로 중단 뒤에는 같은 인수와 `--apply --resume`으로 재개한다. 이미 완료된 같은 input hash는 재사용하며 기존 run·입력 snapshot·EMA value를 수정하지 않는다. 과거 입력의 hash가 바뀐 대상만 새 `rebuild` generation을 만들고, 이전 generation은 보존한다.

```bash
APP_ENV=production .venv/bin/python scripts/backfill_ema.py \
  --start 2013-01-01 --end 2026-09-04 \
  --provider kiwoom --adjustment-type 1 --parser-version kiwoom-v2 \
  --observation-cutoff 2026-10-02T08:40:00Z \
  --chunk-size 25 --apply --resume \
  --output reports/ema/apply_2013_20260904.json
```

적용 결과에서는 plan/application report hash, 종목별 run ID와 input/result hash, created/reused 수를 보관한다. 오류가 나면 범위나 cutoff를 넓히지 말고 실패 원인과 마지막 완료 종목을 확인한 뒤 같은 고정 인수로 재개한다. EMA 값은 아직 백테스트 dataset이나 조건 입력에 연결하지 않는다.

## 거래량 50일 평균 보고서

거래량 50일 평균은 현재 읽기 전용 검토 도구다. DB 값을 만들거나 수정하지 않으며, 0 거래량은 정상 관측값으로 평균에 포함한다. 다음 명령은 대상·준비 중·사용 불가·사용 가능 수와 종목별 결과 hash를 JSON으로 남긴다.

```bash
.venv/bin/python scripts/plan_volume_sma50.py \
  --start 2013-01-02 --end 2026-09-04 \
  --provider kiwoom --adjustment-type 1 --parser-version kiwoom-history-v1 \
  --observation-cutoff 9999-12-31T23:59:59Z \
  --instrument-id 5 --output reports/volume_ma50/sample.json
```

## 배포

이미지는 `docker compose up -d` 또는 운영 오케스트레이터로 기동한다. 배포 전 migration 호환성, 비밀값 주입, 내부 자동화 token의 읽기 scope, health endpoint를 확인한다. 배포 후에는 최근 batch의 상태·coverage·인증 거부 로그를 확인한다. 비밀값 노출 의심 시 배포를 계속하지 말고 token/키 교체 후 연결 설정을 갱신한다.

## 거래량 MA50 저장과 역사 백필

거래량 MA50은 DB 저장 전 계획 명령으로 대상·제외 사유·정책/정의 fingerprint·입력 sequence hash·예상 입력/결과 행·추정 저장량을 고정한다. 계획 명령은 읽기 전용이다.

```bash
APP_ENV=production .venv/bin/python scripts/plan_volume_sma50_storage.py \
  --start 2013-01-02 --end 2026-09-04 \
  --provider kiwoom --adjustment-type 1 \
  --parser-version kiwoom-history-v1 \
  --observation-cutoff 9999-12-31T23:59:59Z \
  --output reports/volume_ma50/plan.json
```

운영 적용은 migration 상태, 계획 보고서, 소규모 표본의 저장값·hash·상태 수량 대조와 저장량 검토가 끝난 뒤에만 한다. 적용은 manifest와 hash 및 `--apply`를 모두 요구하며, 종목별 checkpoint로 재개한다. manifest와 다른 최초 입력은 거부하고, 완료 뒤 원천 evidence가 바뀐 종목만 새 generation으로 rebuild한다. 전체 적용은 자동으로 시작하지 않는다.

```bash
APP_ENV=production .venv/bin/python scripts/backfill_volume_sma50.py \
  --manifest reports/volume_ma50/plan.json --manifest-hash '<계획 보고서의 manifest_hash>' \
  --checkpoint reports/volume_ma50/checkpoint.json --apply
```

중단된 실행은 이미 존재하는 같은 checkpoint 경로에만 `--resume`을 추가해 재개한다.

일일 실행은 `VOLUME_SMA50_ENABLED=false`가 기본이다. 활성화할 때 `VOLUME_SMA50_SOURCE_PROVIDER`, `VOLUME_SMA50_ADJUSTMENT_TYPE`, `VOLUME_SMA50_ALLOWED_PARSER_VERSIONS`을 명시한다. validation이 없거나 차단되면 값을 저장하지 않고 그 사유를 기록한다.

## ATR14 저장과 역사 백필

ATR14도 동일한 공용 OHLC evidence를 사용하지만, Volume MA50과 별도 series·generation·checkpoint를 보존한다. 다음 계획 명령은 읽기 전용이며 ATR true range 입력을 포함한 대상·제외 사유·정의/정책 fingerprint·입력 sequence hash·예상 행과 저장량을 고정한다.

```bash
APP_ENV=production .venv/bin/python scripts/plan_atr14_storage.py \
  --start 2013-01-02 --end 2026-09-04 \
  --provider kiwoom --adjustment-type 1 \
  --parser-version kiwoom-history-v1 \
  --observation-cutoff 9999-12-31T23:59:59Z \
  --output reports/atr14/plan.json
```

두 지표는 같은 유지보수 창에서 schema migration을 적용하되, 계획 보고서와 표본의 저장값·hash·상태 수량을 검토한 뒤 **Volume MA50 전체 백필을 먼저**, ATR14 전체 백필을 다음으로 순차 실행한다. 두 명령 모두 `--apply`, 검토한 manifest hash, 별도 checkpoint를 요구한다. 기존 checkpoint가 있을 때만 `--resume`을 사용한다.

```bash
APP_ENV=production .venv/bin/python scripts/backfill_atr14.py \
  --manifest reports/atr14/plan.json --manifest-hash '<계획 보고서의 manifest_hash>' \
  --checkpoint reports/atr14/checkpoint.json --apply
```

일일 ATR14는 `ATR14_ENABLED=false`가 기본이다. 활성화하려면 `ATR14_SOURCE_PROVIDER`, `ATR14_ADJUSTMENT_TYPE`, `ATR14_ALLOWED_PARSER_VERSIONS`을 명시한다. validation이 없거나 차단되면 값을 저장하지 않고 checkpoint에 사유만 남긴다.
