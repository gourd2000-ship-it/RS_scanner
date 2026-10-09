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
DATABASE_URL=sqlite:// APP_ENV=production .venv/bin/pytest -m "not integration and not api"
DATABASE_URL=sqlite:// APP_ENV=development .venv/bin/pytest tests/integration/api -q
DATABASE_URL=sqlite:// APP_ENV=production .venv/bin/pytest tests/integration/test_backtest_worker_postgres.py -q
python -m compileall app scripts
git diff --check
```

테스트 marker는 `tests/integration`·`tests/e2e` 경로와 API 테스트 이름에서 자동 적용한다. PostgreSQL 테스트는 기본 DB 설정을 사용하지 않고 `TEST_DATABASE_URL`의 전용 `localhost:5433/rs_scanner_test`만 허용하며, 임시 schema를 만들고 실행 후 삭제한다. API 통합 suite도 해당 테스트 DB에 임시 schema를 만들어 테스트 테이블을 준비한다. schema 변경은 위 검증과 별도로 빈 schema 및 기존 표본이 있는 격리 PostgreSQL에서 migration upgrade와 재구성을 확인한다. 프런트엔드 변경은 `cd frontend && npm run lint && npm run build`를 실행한다.

## 백테스트 조건 입력 화면

`/backtests`에서 운영자 비밀번호로 접속한다. JSON 대신 시장, 보유 종목 수, 종목별 비중, 거래 비용을 입력하고 매수·매도 조건의 지표·비교·기준값을 선택한다. `조건 추가`와 `AND/OR 묶음 추가`로 조건을 조합한다. 기간 수익률은 계산 기간도 거래일로 지정한다.

비율 입력은 모두 % 단위다. 예를 들어 슬리피지 `0.1`은 0.1%, 손절 `5`는 5% 손실 기준이다. 손절·익절·최대 보유 기간은 빈칸이면 적용하지 않는다.

`전략 저장` 후 시작일·종료일을 선택해 실행 요청한다. 저장된 전략과 버전을 불러올 수 있으며, 조건을 수정하면 `새 버전으로 저장`해야 실행할 수 있다. 실행 기록에서 상태·데이터 부족 사유·사용한 MA50/ATR14 snapshot ID/hash를 확인한다. 실행 요청이 `queued`가 되어도 별도 워커를 명시적으로 실행하기 전까지 계산은 시작하지 않는다. 주문·거래·자산 곡선 상세는 `GET /api/v1/backtests/runs/{run_id}` API로 조회한다.

입력 변환 회귀 테스트: `cd frontend && node --experimental-strip-types --test tests/backtest-form.test.mjs` (Node 22.6 이상).

## 백테스트 실행 워커

백테스트 HTTP 요청은 실행을 queue에 넣고 결과만 읽는다. 계산은 승인된 배치 서비스 환경에서 명시적으로 별도 프로세스를 실행할 때만 시작한다. 기본 명령은 큐에서 최대 한 건을 처리하고 종료한다.

```bash
APP_ENV=production .venv/bin/python scripts/run_backtest_worker.py
```

검토된 실행 묶음에 한해 `--max-runs N`으로 한 번의 프로세스가 처리할 최대 건수를 지정할 수 있다. 큐가 비면 더 일찍 종료한다. 이 명령은 API 시작 시 자동 실행되지 않으며 cron·systemd·컨테이너 자동 시작 설정도 이 단계에서 추가하지 않는다.

워커는 DB의 기존 단일 실행 claim을 커밋해 `running` 상태를 표시한 다음, 고정된 전략 버전·complete 데이터셋·RS 결과·필요한 지표 snapshot을 사용해 시뮬레이션한다. 결과 행과 완료 상태는 한 트랜잭션에 둔다. 계산 예외가 나면 savepoint에서 부분 결과를 롤백하고 `failed`와 `simulation_failed`를 기록한다. 실행 트랜잭션에서 실패 상태를 기록할 수 없는 예외는 새 세션에서 저장을 시도한다. 실패 처리가 끝나기 전에 워커가 강제 종료되거나 실패 상태 저장 자체가 실패하면, 부분 결과는 롤백되고 앞서 커밋한 claim은 `running`으로 남는다. 이 상태는 자동으로 다시 실행되지 않으며, unique running 제약 때문에 다음 run도 claim되지 않는다.

중단된 run을 정리하기 전에는 실행 호스트에서 해당 워커 프로세스가 종료된 것을 확인한다. 그 다음 아래 명령으로 run 상태가 여전히 `running`이고 저장된 결과 행이 없을 때만 `failed/worker_interrupted`로 바꿀 수 있다. 이 명령은 재실행하지 않는다. 원인을 확인한 뒤 필요하면 운영자가 새 실행 요청을 만든다.

```bash
APP_ENV=production .venv/bin/python scripts/run_backtest_worker.py \
  --fail-stale-run '<run-id>' --confirm-worker-stopped
```

`cancelled` 상태의 queued run은 claim 대상이 아니며, 완료·실패 run은 자동 재시도하지 않는다.

현재 운영 품질 보고서 `job_137`은 `blocked`이므로 이 구현만으로 운영 워커를 가동하거나 백테스트 입력 데이터셋을 발행할 수 없다. 실행 전 품질 gate, migration 상태, 격리 DB 검증과 별도 운영 결정을 확인한다.

## EMA 운영자 조회

EMA 결과는 브라우저에서 백테스트 운영자 로그인 세션을 가진 경우에만 조회한다. `GET /api/v1/backtests/indicators/ema`에 `code`, `start`, `end`를 넣고, 코드가 과거 여러 `Instrument`에 연결될 수 있으면 응답의 409 사유를 확인한 뒤 `instrument_id`를 함께 넣는다. 코드만으로 역사 identity를 임의 선택하지 않는다.

응답은 현재 generation의 거래일 오름차순 page이며, 매 거래일마다 EMA 5·20·50·200을 모두 반환한다. `value`는 Decimal 정밀도를 보존하는 문자열이고, `status`와 `reason_code`를 함께 확인해야 한다. `warming_up`과 `data_unavailable` 값은 조건 또는 백테스트 입력으로 사용하면 안 된다. `as_of`는 현재 generation의 최신 거래일, `calculated_at`은 그 generation의 마지막 완료 계산 시각이다.

## 거래량 MA50·ATR14 운영자 조회

백테스트 운영자 session으로 다음 읽기 전용 경로를 호출한다.

```text
GET /api/v1/backtests/indicators/volume-sma50?code=005930&start=2026-01-01&end=2026-03-31
GET /api/v1/backtests/indicators/atr14?code=005930&start=2026-01-01&end=2026-03-31
```

필요한 경우 `instrument_id`와 `series_id`를 지정한다. 코드가 여러 역사 instrument에 연결되거나 current series가 모호하면 409 사유를 확인하고 올바른 ID를 넣는다. 결과는 현재 generation 기준의 오름차순 페이지이며 값은 Decimal 문자열이다. `status`와 `reason_code`를 같이 확인하고 `warming_up` 또는 `data_unavailable`을 조건값으로 해석하지 않는다. 현재 조회는 과거 run에 영향을 주지 않는다.

전략 조건에서 MA50·ATR14를 사용하려면 데이터셋에 고정된 snapshot이 필요하다. 요청 사전 점검은 매수 검토일과 매도 검토 거래일에 필요한 모든 값이 `available`인지 확인한다. snapshot·행·근거가 없거나 사용할 수 없는 경우 run은 queue에 들어가지 않고 `data_unavailable` 사유를 반환한다. 실행 기록의 snapshot ID/hash는 과거 실행 입력의 식별자다.

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

중단·재개 시에는 격리 셸의 `ps` 결과만으로 기존 writer의 종료를 판단하지 않는다.
호스트 PID namespace와 PostgreSQL 연결을 함께 확인하고, 같은 manifest·checkpoint
writer가 한 개일 때만 재개한다. 완료 후에는 원래 apply report와 checkpoint를
보존한 채 `scripts/reconcile_atr14_checkpoint.py`로 2,175개 대상의 승인 입력,
완료 run, 저장된 ATR 값 hash와 상태별 수량을 대조한다. `--apply`는 DB가 아닌
checkpoint의 검증된 실패 표기만 복구하며 별도 reconciliation report를 쓴다.

## 일일 Volume MA50·ATR14 실행

일일 지표는 `VOLUME_SMA50_ENABLED=false`, `ATR14_ENABLED=false`가 기본이다.
운영에서 켜기 전에는 별도 운영 결정, 현재 품질 보고서의 통과 판정, 격리 PostgreSQL의
계산·재시도·rebuild 검증이 모두 필요하다. 2026-10-08 보관 보고서 `job_137`은
`blocked`다. 대상 206건이 입력 validation에서 실패했고, 그 안에 양수 OHLC 위반
188건과 OHLC 순서 모순 18건이 있다. 보고서에는 원문 payload와 공급자 귀속 근거가
없으므로 공급자 오류로 단정하거나 가격을 보정하지 않는다. 이 보관 보고서는 운영
DB를 실시간 조회한 결과가 아니다.

두 지표는 일일 가격 단계 다음의 독립 단계다. `passed` 또는
`passed_with_warnings` validation에서만 해당 정책(provider, adjustment type, parser
version)을 명시한 계산을 시작한다. validation이 없거나 `blocked`이면 각 지표는
`validation_unavailable` 또는 `validation_gate_blocked` 사유로 건너뛰고 자신의
`volume_sma50` 또는 `atr14` checkpoint에 오류 상태를 남긴다. `report_only` 모드라도
판정 상태가 `blocked`이면 지표를 계산하지 않는다. 한 지표의 실패는 다른 지표, RS,
EMA 결과를 취소하지 않는다.

validation이 통과해도 지표 source policy에 맞는 `target_date` 관측이 하나도 없으면
이전 거래일 입력만 계산해 성공 처리하지 않는다. `target_date_observations_missing`으로
건너뛰고 해당 지표 checkpoint에 오류 상태를 기록한다.

같은 source evidence와 정책으로 다시 계산하면 기존 완료 run과 hash를 재사용한다.
새 거래일만 추가되면 현재 generation에 증분 run을 붙인다. 과거 evidence가 달라지면
새 rebuild generation을 완성한 뒤 current로 전환하고 이전 run·값·hash는 보존한다.
같은 series에는 DB lock으로 writer가 직렬화되므로 동일 종목·정책 범위의 추가 writer를
수동 기동하지 않는다. 실패 후 재개할 때는 실패 원인과 validation 결과를 먼저 확인하고,
같은 job checkpoint 상태와 해당 indicator series의 run ID·input/result hash를 대조한다.
과거 원본이나 lineage를 수정해 재개하지 않는다.
