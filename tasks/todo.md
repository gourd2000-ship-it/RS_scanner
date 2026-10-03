# EMA 5·20·50·200 이전 작업 목록

이 목록의 EMA01~EMA13은 2026-10-03 검토 전 초안이며 실행하지 않는다. 승인 대기 중인 현재 범위와 기준은 [EMA DB 누적 구현계획](../docs/plans/ema-indicators.md)을 따른다. 특히 사용 가능 시점은 5N이 아니라 각 EMA 기간 N개 관측 후이며, EMA 조건·백테스트 화면은 후속 작업이다.

## EMA01: 계산·입력·조건 계약 확정

**설명:** 기간, seed, 준비 이력, Decimal 정책, 결측·정지, lineage, 조건 v2 및 legacy 호환 계약을 명문화한다.

**완료 기준:**
- [ ] 5/20/50/200, 첫 종가 seed, 5N 준비와 사용 가능 구간 감소를 명시한다.
- [ ] daily/dataset 입력 경계, 3값 조건 평가, 교차 전일 정의 및 고정 입력 참조를 문서화한다.
- [ ] 수작업 수열과 seed/준비 경계 검증 fixture를 준비한다.

**검증:** fixture를 독립 재귀 계산과 대조하고 계약 예제의 기존 전략 호환성을 검토한다.
**의존성:** 없음 · **크기:** M
**예상 파일:** docs/plans/ema-indicators.md, docs/business-rules.md, docs/contracts.md, tests/fixtures/ema_cases.json(신규).

## EMA02: 지표 저장 모델과 migration

**설명:** indicator_series/runs/values 및 입력 세대·관측 참조·정확한 재개 상태를 저장한다.

**완료 기준:**
- [ ] 유일성/FK/상태·value CHECK 및 날짜 범위 조회 인덱스를 구현한다.
- [ ] 신규 revision으로만 변경하고 기존 가격·RS·백테스트 데이터를 수정하지 않는다.
- [ ] 완료 결과 덮어쓰기 차단과 미완료 run 비노출을 저장 계층에서 지원한다.

**검증:** 빈 격리 PostgreSQL 및 기존 데이터 fixture DB에서 upgrade, 중복·참조 오류·상태 제약 테스트.
**의존성:** EMA01 · **크기:** M
**예상 파일:** app/models/indicator.py(신규), app/models/__init__.py, alembic/versions/<new>_indicator_storage.py, tests/integration/test_indicator_storage.py(신규).

## EMA03: 백테스트 지표 입력 참조 저장

**설명:** 백테스트 실행이 사용하는 지표 세대/결과와 범위 hash를 불변으로 고정할 저장 기반을 만든다.

**완료 기준:**
- [ ] run과 indicator 참조를 FK·범위·결과 hash로 연결한다.
- [ ] EMA 없는 기존 실행은 그대로 유효하고 완료 실행 참조는 변경 불가다.
- [ ] 참조된 지표 결과 삭제 및 다른 dataset 결과 연결을 차단한다.

**검증:** 격리 DB upgrade 및 기존 실행 재현/완료 후 mutation 거부 테스트.
**의존성:** EMA02 · **크기:** M
**예상 파일:** app/models/backtest_run.py, app/repositories/backtest_repository.py, alembic/versions/<new>_backtest_indicator_refs.py, tests/integration/test_backtest_execution_storage_postgres.py.

### 관문 A: 구조

- [ ] 신규 migration 모두 격리 DB 통과, 기존 데이터/전략 호환 유지, seed/준비 정책과 사용 가능 구간 제한이 검토 가능하다.

## EMA04: 적격 가격 입력과 구간 선택

**설명:** 일일 관측 및 고정 dataset을 같은 계산 입력으로 변환하되 출처 경계를 유지한다.

**완료 기준:**
- [ ] lifecycle·provider·수정 기준·cutoff와 선택 가격/관측 근거를 고정한다.
- [ ] 품질 결측 및 공급자 단절은 구간을 분리하고 정지/휴장과 구분한다.
- [ ] dataset 준비 구간에서도 complete 제한을 유지하고 조용한 canonical fallback을 금지한다.

**검증:** 혼합 소스, 수정 기준 변경, 코드 재사용, 미래 관측, 결측/휴장/정지 fixture 단위 테스트.
**의존성:** EMA01~EMA02 · **크기:** M
**예상 파일:** app/services/indicators/inputs.py(신규), app/repositories/indicator_input_repository.py(신규), tests/unit/test_indicator_inputs.py(신규).

## EMA05: EMA 순수 계산기

**설명:** 네 기간을 한 순회에서 계산하고 준비/단절 상태와 정확한 재개 상태를 반환한다.

**완료 기준:**
- [ ] 수작업 기대값과 일치하고 5N-1/5N 경계가 네 기간 모두 정확하다.
- [ ] 전체·일별·중간 재개 결과가 정의한 반올림 후 동일하다.
- [ ] 미래 가격 수정은 과거 결과를 바꾸지 않으며 단절 뒤 재준비한다.

**검증:** `.venv/bin/pytest tests/unit/test_ema_calculator.py -q`; 수작업/독립 구현 비교, Decimal 상태 직렬화 왕복.
**의존성:** EMA01, EMA04 · **크기:** S
**예상 파일:** app/services/indicators/ema.py(신규), tests/unit/test_ema_calculator.py(신규).

## EMA06: 저장·증분·재계산 서비스

**설명:** 동일 입력은 재사용하고 새 날짜를 누적하며 교정은 별도 세대로 재계산한다.

**완료 기준:**
- [ ] 같은 run 재시도·중복 worker에서 중복 row 또는 다른 값 덮어쓰기가 없다.
- [ ] 날짜 추가와 과거 revision/품질 변경을 구분하고 새 세대는 완성 후 전환한다.
- [ ] 실패/재개, 정확한 checkpoint, prefix 근거 hash 및 성공/제외 수량을 보존한다.

**검증:** 장애 주입·동시 실행·같은 가격 ID의 내용 변경·새 세대 전환 통합 테스트, 구 세대 불변 확인.
**의존성:** EMA02, EMA04~EMA05 · **크기:** M
**예상 파일:** app/repositories/indicator_repository.py(신규), app/services/indicators/calculation.py(신규), tests/integration/test_indicator_calculation.py(신규).

### 관문 B: 공통기능

- [ ] 입력·계산·저장 통합 테스트 통과, 교정 전후 결과가 구분되고 재개 결과가 전체 계산과 같다.

## EMA07: 과거 계산 CLI와 dry-run 보고서

**설명:** 범위를 고정해 과거 EMA를 계산하고 처리 규모/사용 가능 날짜를 먼저 보여준다.

**완료 기준:**
- [ ] 기본 dry-run은 DB에 쓰지 않으며 기간·시장·종목·정책·cutoff를 manifest로 남긴다.
- [ ] EMA별 최초 사용 가능일, 준비 부족/품질 제외 및 예상 4배 행 수·용량을 보고한다.
- [ ] 명시적 적용·resume 모드에서 제한된 chunk로 처리하고 동일 실행을 재현한다.

**검증:** `.venv/bin/pytest tests/unit/test_indicator_backfill.py -q`; 격리 DB 표본 backfill/재실행 및 메모리·시간 측정. 운영 대량 쓰기는 포함하지 않는다.
**의존성:** EMA06 · **크기:** M
**예상 파일:** scripts/backfill_ema.py(신규), app/services/indicators/report.py(신규), tests/unit/test_indicator_backfill.py(신규), docs/operations.md.

## EMA08: 두 일일 배치 경로 연결

**설명:** 완료 가격으로 EMA를 누적하고 실패·재시도·기능 flag를 기존 배치 관리에 연결한다.

**완료 기준:**
- [ ] 일반 daily job과 orchestrator 모두 같은 EMA service/대상일·checkpoint 규칙을 사용한다.
- [ ] validation block과 RS 도중 가격 변경을 반영해 입력이 확정되기 전 publish하지 않는다.
- [ ] 기능 off/RS-only 호환을 유지하고 EMA 실패는 배치 부분 실패로 집계한다.

**검증:** `.venv/bin/pytest tests/integration/test_batch_harness.py tests/unit/test_batch_ema.py -q`; 정상/차단/지연 가격/실패 재개 양쪽 진입점 테스트.
**의존성:** EMA06~EMA07 · **크기:** M
**예상 파일:** app/services/batch/run_daily_job.py, app/services/batch/orchestrator.py, app/services/batch/context.py, app/core/config.py, tests/unit/test_batch_ema.py(신규). 실제 context 경로는 구현 전 확인한다.

## EMA09: EMA 읽기 조회 계약

**설명:** 운영자에게 값과 사용 가능 상태·기준일·근거 버전을 제공한다.

**완료 기준:**
- [ ] 종목·기간·날짜 범위와 페이지 제한을 검증하고 저장된 완료 결과만 반환한다.
- [ ] warming_up/품질 제외/null 사유와 오래된 기준일을 표시한다.
- [ ] 기존 운영자 인증을 유지하고 자동화 쓰기 scope 또는 계산 POST API를 추가하지 않는다.

**검증:** 미인증 거부, 권한, pagination, null 상태, 다른 dataset 선택 방지 API 테스트.
**의존성:** EMA06 · **크기:** M
**예상 파일:** app/schemas/indicator.py(신규), app/api/v1/endpoints/backtest_execution.py, app/repositories/indicator_repository.py, tests/unit/test_indicator_api.py(신규).

### 관문 C: DB 누적 기능

- [ ] 네 EMA 과거/일일 저장·재실행·조회가 격리 환경에서 동작한다. dry-run의 EMA200 준비 부족 영향과 저장 공간 추정이 검토 가능하다.

## EMA10: 지표 비교·교차 조건 평가

**설명:** 기존 상수 비교를 유지하며 양쪽 지표와 EMA 기간, 상향/하향 돌파를 추가한다.

**완료 기준:**
- [ ] legacy 전략 hash/의미를 보존하고 새 schema에서 네 기간 외 입력을 거부한다.
- [ ] 가격/EMA 및 EMA/EMA 비교·교차의 전일/당일·동률 조건이 정확하다.
- [ ] unavailable을 구분하는 AND/OR와 필요한 EMA/전일 의존성을 수집한다.

**검증:** `.venv/bin/pytest tests/unit/test_ema_conditions.py tests/unit/test_backtest_simulator.py -q`; nested AND/OR와 기존 전략 회귀.
**의존성:** EMA01, EMA05 · **크기:** M
**예상 파일:** app/services/backtest/strategy.py, app/services/backtest/conditions.py(필요 시 신규), app/schemas/backtest_execution.py, tests/unit/test_ema_conditions.py(신규).

## EMA11: 백테스트 고정 입력과 실행 연결

**설명:** 전략이 요구하는 EMA를 같은 dataset의 완료 결과로 고정하고 simulator에 공급한다.

**완료 기준:**
- [ ] 입력 선택 시 dataset/정책/기간/hash 일치를 확인하고 일일 최신 EMA fallback을 차단한다.
- [ ] 준비 구간에는 매매하지 않고 unavailable 종목·날짜 사유를 보존한다.
- [ ] 이후 일일 계산/가격 교정에도 저장 실행의 신호·결과가 동일하게 재현된다.

**검증:** 고정 입력 통합 fixture에서 종가 신호→다음 시가 체결, 매도 우선·마지막 청산 회귀, 지표 미준비·hash 불일치·미래 데이터 변경 검사.
**의존성:** EMA03, EMA06, EMA10 · **크기:** M
**예상 파일:** app/services/backtest/input_selection.py, run_preparation.py, execution.py, simulator.py, tests/integration/test_backtest_ema_inputs.py(신규); 앞 네 파일은 같은 backtest 디렉터리다.

## EMA12: 선택형 조건 UI

**설명:** EMA 기간과 비교 대상을 선택하고 기존 전략 버전을 불러와 수정할 수 있게 한다.

**완료 기준:**
- [ ] EMA5/20/50/200 선택, 가격/EMA·EMA/EMA 비교·교차 및 AND/OR 묶음을 지원한다.
- [ ] 새 조건 저장/불러오기 왕복과 기존 전략 유지, 수정 후 실행 잠금이 동작한다.
- [ ] 사용 불가 사유를 숨기지 않고 모바일/키보드 입력과 잘못된 값 안내가 동작한다.

**검증:** form-model 회귀 및 브라우저 흐름 테스트, `npm run lint`, `npm run build`. 기존 unrelated lint 실패와 새 변경 오류를 구분해 기록한다.
**의존성:** EMA09~EMA11 · **크기:** M
**예상 파일:** frontend/app/(dashboard)/backtests/form-model.ts, condition-editor.tsx, page.tsx, frontend/tests/backtest-form.test.mjs; 앞 세 파일은 같은 backtests 디렉터리다.

### 관문 D: 백테스트 연결

- [ ] 대표 EMA 조건 전략을 저장·조회·실행하고 고정 결과를 재현한다. 기존 비 EMA 전략 테스트와 운영자 인증 테스트가 통과한다.

## EMA13: 운영 전환 보고서와 문서

**설명:** 표본 성능·기존 데이터 호환성과 운영 적용/복구 절차를 정리한다.

**완료 기준:**
- [ ] 표본 계산값/hash·수량·처리 시간·peak memory·DB 용량을 보고하고 운영 범위로 추정한다.
- [ ] 운영 적용 전 dry-run, 백업, flag off 복구, 과거 결과 보존 절차를 제공한다.
- [ ] 현재 코드에 맞게 관련 문서를 갱신하고 DB 누적·조건 지원·워커 운영 완료 상태를 분리해 기록한다.

**검증:** 관련 단위·통합 회귀, `python -m compileall app scripts`, `git diff --check`; 신규 migration 격리 검증과 프런트 build 증거 검토. 운영 DB 적용은 저장소의 사람 운영자 절차에 따른다.
**의존성:** EMA07~EMA12 · **크기:** M
**예상 파일:** docs/operations.md, docs/contracts.md, docs/business-rules.md, docs/tracking/status.md, docs/plans/ema-indicators.md.

### 관문 E: 완료 판정

- [ ] 구현·회귀·복구 절차와 실제 운영 적용 여부를 각각 기록한다. 준비 미완료/품질 제외 값이 조건에 사용되지 않으며 과거 백테스트 입력을 보존한다.

---

# OHLCV 클렌징 CL01~CL12

개정: 2026-10-02 · [구현 계획](plan.md#ohlcv-클렌징-구현-계획)<br>
상태: CL01·CL05 구현 및 격리 검증 완료, CL02~CL04·CL06~CL09 부분 구현,
CL10 실제 전 기간 읽기 전용 감사 완료. 운영 데이터셋은 미발행. 상폐 가격 확보·매매 시뮬레이션은 범위 밖이다.
이번 목표는 CL10까지의 OHLCV 품질 판정이며 CL11~CL12는 RS 소비자를 위한 후속 작업이다.
아래 기존 DBG/BT 완료 이력은 보존하며 새 완료 판정을 대체하지 않는다.

## CL01: 검증 대상과 제외 manifest

- [x] 기준일·관측 cutoff·기간·보통주·상폐 제외 정책을 입력으로 고정한다.
- [x] 포함/상폐 제외/identity unknown을 lifecycle별로 남기고 코드 재사용을 구분한다.
- [x] 현재 활성 Symbol만으로 과거 시장·상장일을 추정하지 않는다.

**검증:** 기존 historical_universe 테스트 + 신규 tests/unit/test_cleansing_universe.py에서
상폐/재상장/코드 재사용/시장 이전/매핑 미확인 및 동일 manifest 재현 검사.
**의존성:** 없음 · **크기:** M
**파일:** app/services/historical_universe.py, app/services/validation/cleansing_policy.py(신규),
tests/unit/test_cleansing_universe.py(신규).

## CL02: 가격 없는 종목도 포함하는 감사 CLI

- [x] 고정 입력으로 expected/observed와 구간별 결측·정지·달력 예외를 읽기 전용 집계한다.
- [ ] source 원자료 대조율, 조정기준 unknown 및 종목·연도별 coverage 파일을 출력한다.
- [ ] 공급자 요청 0, DB 쓰기 0; 제한 메모리 청크 처리와 진행률/실행시간을 기록한다. (앞의 두 조건 검증, 진행률/자원 기록 보완 필요)

**검증:** 신규 tests/integration/test_ohlcv_audit.py의 가격 0건/내부 결측/임시 휴장/장중행 fixture.
**의존성:** CL01 · **크기:** M
**파일:** scripts/audit_historical_ohlcv.py(신규), app/services/validation/ohlcv_audit.py(신규),
app/services/validation/historical_gaps.py, tests/integration/test_ohlcv_audit.py(신규).
**구현된 CLI:** 실행 인자와 감사 결과는 [실행 기록](../docs/ohlcv_cleansing_runbook.md)에 보존한다.
날짜는 명시적 예시이며 실제 실행 때 사용할 입력 snapshot에 맞춰 고정한다.

### CP-CL1: 감사 기반

- [ ] manifest 재현, 전 기대 행 분류, DB 변경 0, 네트워크 요청 0을 확인한다.
- [x] 상폐 제외 이후 coverage를 실제 재계산한다. 과거 88.08%를 재사용하지 않는다.

## CL03: OHLCV 구조·원자료 변환 검사

- [ ] 기존 inspect_ohlc_row를 재사용하고 volume 정수성·단위·파서 탈락 근거를 보강한다.
- [ ] 공급자 부호 표기와 실제 음수 오류를 계약·fixture로 구분하며 무조건 abs 변환하지 않는다.
- [ ] source별 모든 OHLCV 필드 대조와 장중/마감 상태를 보고한다.

**검증:** 신규 tests/unit/test_ohlcv_source_contract.py + 기존 test_parsers.py/test_kiwoom_history.py.
**의존성:** CL02 · **크기:** M
**파일:** app/services/validation/rules.py, app/crawler/parsers/kiwoom.py,
app/crawler/parsers/fchart.py, tests/unit/test_ohlcv_source_contract.py(신규).

## CL04: 시계열 이상과 조정기준 충돌 분류

- [ ] 급변·장기 동일값·provider 전환·OHLC 조정 일관성을 탐지하고 evidence를 기록한다.
- [ ] confirmed corporate action/정지와 unexplained anomaly를 구분한다. 0거래량·급변만으로 삭제하지 않는다.
- [ ] 조정기준/volume_basis unknown 또는 충돌을 valid로 승격하지 않는다.

**검증:** 기존 test_historical_anomalies.py + 신규 tests/unit/test_adjustment_policy.py.
**의존성:** CL03 · **크기:** M
**파일:** app/services/validation/historical_policy.py, app/services/validation/cleansing_policy.py,
tests/unit/test_adjustment_policy.py(신규), tests/unit/test_historical_anomalies.py.

### CP-CL2: 오류와 정상 기업행위 분리

- [ ] 분할·거래정지·거래량 0 정상 사례와 오염 데이터가 서로 다른 상태로 나온다.
- [ ] 소스 대조가 불가능한 숫자는 '원자료 검증 완료'로 표시하지 않는다.

## CL05: 승인 보정·제외를 적용하는 역사 clean reader

- [x] 범위별 조회에 기존 APPROVED 보정·제외를 적용하고 observation 충돌 선택 정책을 고정한다.
- [x] 요청한 조정 정책과 실제 행이 다르면 명시적으로 격리한다. canonical 원값은 보존한다.
- [x] 선택된 source/보정/제외 revision을 반환하고 재검증한다.

**검증:** 신규 tests/integration/test_historical_clean_reader.py에서 승인 제외 0건,
보정값 적용, provider 혼합 거부, 원본 불변을 확인한다.
**의존성:** CL04 · **크기:** M
**파일:** app/services/validation/clean_layer.py, app/services/validation/historical_clean_reader.py(신규),
app/services/validation/cleansing_policy.py, tests/integration/test_historical_clean_reader.py(신규).

## CL06: 미확보 구간의 복구 계획과 잔여 상태

- [ ] 정상 상장 대상의 재조회 후보를 요청 수·중단 조건·근거와 함께 dry-run manifest로 만든다.
- [x] 기존 공급자만 사용하며 네트워크 기본 예산 0, 상폐 요청 0을 보장한다.
- [ ] 복구 불가/예산 없음은 missing·review_required로 남긴다. 보간·전일값 채우기를 하지 않는다.

**검증:** 신규 tests/unit/test_cleansing_repair_plan.py에서 요청 예산, 상폐 제외, 동일 plan hash 확인.
**의존성:** CL04 · **크기:** M
**파일:** app/services/historical_backfill.py, scripts/backfill_historical_prices.py,
tests/unit/test_cleansing_repair_plan.py(신규).
실제 재조회는 필수 통과 조건이 아니다. 최초 감사 결과로 필요 여부를 결정한다.

### CP-CL3: 입력 확정

- [ ] 원본 보존 및 보정·제외·충돌의 추적성을 검증한다.
- [ ] CL06의 잔여 항목도 상태·사유를 가진 채 dataset에 전달된다.

## CL07: dataset 품질·identity 계약 보강

- [x] membership에 고정 code/name과 품질 상태를 보존하고 instrument_id를 항상 노출한다.
- [ ] manifest에 원래 분모·상폐 제외 규모·선택 기준·조정정책·source/decision revision을 고정한다. (포함 분모와 제외 ID·row hash는 저장; 제외 전 기대 행수 보완 필요)
- [x] additive migration으로 기존 dataset을 보존하며 과거 dataset에 새 검증 완료 표식을 소급하지 않는다.

**검증:** 신규 tests/integration/test_cleansing_migration.py를 검증용 PostgreSQL에서 upgrade/reload로 검증.
**의존성:** CL05 · **크기:** M
**파일:** app/models/backtest_dataset.py, alembic/versions/<revision>_dataset_quality_lineage.py(신규),
app/schemas/agent.py, tests/integration/test_cleansing_migration.py(신규).
필드 저장 위치는 CL05 계약에 맞춰 최소화하며 범용 별도 품질 시스템을 신설하지 않는다.

## CL08: clean snapshot 생성과 OHLCV 해시

- [x] clean reader를 사용해 모든 기대 행의 상태와 검증된 OHLCV를 복사한다.
- [x] 입력 hash와 복사에 같은 읽기 snapshot을 사용하고 청크 처리한다.
- [ ] 동일 입력/정책 재실행과 canonical 동시 갱신 후 이전 dataset 불변을 검증한다. (재실행은 검증, 동시 갱신 사례 보완 필요)

**검증:** tests/integration/test_backtest_snapshot.py 확장 + 신규 tests/integration/test_clean_snapshot_postgres.py.
**의존성:** CL07, CL06(계획·잔여 상태만) · **크기:** M
**파일:** app/services/backtest_snapshot.py, tests/integration/test_backtest_snapshot.py,
tests/integration/test_clean_snapshot_postgres.py(신규).

### CP-CL4: 고정 데이터

- [ ] 논리 오류/승인 제외/미해결 조정 충돌이 valid 데이터에 0건이다.
- [ ] PostgreSQL snapshot 일관성과 행·상태·lineage 해시 재현을 확인한다.

## CL09: OHLCV 조회와 전 페이지 replay

- [ ] OHLCV 조회에서 RS 필수 조건을 분리하고 결측일에도 같은 identity를 반환한다.
- [ ] 전체 coverage와 현재 페이지 coverage/필터 제외 수를 구분한다.
- [ ] materialized dataset_id, cursor filter binding, ETag, 전 페이지 누락·중복을 검증한다.

**검증:** tests/unit/test_backtest_api.py 확장 + 신규 tests/integration/test_backtest_replay.py.
**의존성:** CL08 · **크기:** M
**파일:** app/api/v1/endpoints/backtest.py, tests/unit/test_backtest_api.py,
tests/integration/test_backtest_replay.py(신규), scripts/replay_backtest_dataset.py.

## CL10: 실제 범위 감사와 사용 가능 구간 판정

- [ ] 고정한 대상·기간을 전수 감사하고 before/after 수량과 구간별 complete/partial/unavailable를 보고한다. (전 기간·구간 판정 완료, 제외 전 기대 행수 미산출)
- [ ] 공급자·연도·기업행위·공백별 표본을 보존 observation과 대조하고 미검증 범위를 표시한다.
- [ ] 새 dataset 발행 시 전 페이지 replay/hash/원본 불변 및 자원 사용량을 기록한다.

**검증:** 읽기 전용 감사 보고서 → 격리 PostgreSQL clean snapshot → 전 페이지 replay.
운영 자료의 보정 결정 반영·신규 dataset 저장은 감사 및 격리 검증 후 별도 실행한다.
**의존성:** CL09 · **크기:** S
**파일:** reports/cleansing/<run_id>/(산출물), docs/ohlcv_cleansing_runbook.md(신규), tasks/todo.md.

### CP-CL5: OHLCV 완료

- [ ] 계획의 OHLCV 완료 조건 5개를 충족한다. 전체 100% 가격 확보를 강제하지 않는다.
- [ ] 사용 가능한 종목·기간, 불가능한 구간, 잔여 위험을 사용자가 확인할 수 있다.
- [ ] 이 판정에는 RS 계산이나 매매 엔진이 필요하지 않다.

## 후속 CL11: 역사 RS 의미 일치

- [ ] PostgreSQL/Python 동률·반올림·표시 정렬·시장별 순위를 일치시킨다.
- [ ] 결측을 제거한 253개 관측을 무조건 12개월로 해석하지 않고 lookback 정책을 고정한다.
- [ ] 실제 결과 전체와 결정적 정렬을 해싱하고 미래 입력 불변을 검사한다.

**검증:** test_historical_rs.py + 신규 tests/integration/test_historical_rs_postgres.py에서 동일 fixture 대조.
**의존성:** CL10 · **크기:** M
**파일:** app/services/historical_rs.py, app/services/rs/calculator.py,
tests/unit/test_historical_rs.py, tests/integration/test_historical_rs_postgres.py(신규).

## 후속 CL12: RS 데이터셋 재생성·검수

- [ ] 수정 산식은 새 formula_version/새 dataset에서 계산한다. 기존 배포 버전을 변경하지 않는다.
- [ ] OHLCV 품질과 RS 준비구간 품질을 따로 보고하고 날짜별 적격 집합을 고정한다.
- [ ] 전 페이지 RS 해시 및 동일 입력 재현을 보고한다.

**검증:** 검증용 PostgreSQL의 RS 전체 replay와 기존 API 회귀.
**의존성:** CL11 · **크기:** S
**파일:** reports/cleansing/<run_id>/(산출물), docs/ohlcv_cleansing_runbook.md, tasks/todo.md.

### CP-CL6: RS 후속 완료

- [ ] OHLCV 및 RS 각각의 가용 범위와 버전을 고정한다. 매매 성과 검증은 별도 작업이다.

---

# 크롤링 장애 디버깅 DBG01~DBG08

개정: 2026-10-01 · [계획](plan.md) · [증거 보고서](../reports/crawl_debug_baseline.md)<br>
현재 최우선: **DBG04B 운영 규모 RS 검증과 DBG05 API migration chain 복구**.
2026-10-01 job 128로 명부·지수·가격·검증을 운영 DB에 반영했다. 가격 최신일 10/1,
가격 4,146/4,340 성공. 194 가격 실패, 34 명부 후보 분류와 RS/API 갱신은 남는다.
세부: [복구 실행 결과](../reports/crawl_recovery_result.md).

## DBG01: 증거 기준선 — 완료, 실행 전 상태 갱신

- [x] 코드·배포·DB·실패 단계와 데이터 공백, 격리 테스트 경로를 기록했다.

**근거:** 진단 보고서, 종목별 공백 CSV, 읽기 전용 coverage SQL. 초기 격리 테스트 22개 통과.
**실행 전 확인:** 예약 시각·실제 프로세스·작업 상태·코드 diff·DB revision·네이버 선택 설정을
재조회한다. 9/17·9/4는 과거 조사값이며 복구 종료일과 대상별 공백을 다시 산출한다.
**검증:** 읽기 전용 상태/coverage 조회. 설정 전체나 인증값은 출력하지 않는다.
**의존성:** 없음 · **크기:** S · **산출물:** reports/crawl_debug_baseline.md.

## DBG02: 네이버 지수 복구 — 부분 완료

### DBG02A: 지수 URL 교체 및 KRX 중단 설정

- [x] 구 지수 URL의 410 재현 후 네이버 모바일 JSON source/파서를 연결했다.
- [x] KRX shadow=false, authority=naver_last_completed, canary 비움을 확인했다.
- [x] 두 시장 각 100행 실시간 파싱과 합성 응답의 SQLite 저장·재실행을 검증했다.

**기존 검증 명령 (26 passed):**
`.venv/bin/pytest -q tests/unit/test_parsers.py tests/unit/test_naver_index_source.py tests/unit/test_naver_universe_source.py tests/unit/test_universe_authority_flag.py tests/unit/test_universe_price_selection.py tests/integration/test_naver_benchmark_sync.py tests/integration/test_replay_source.py`
**범위:** 기본 구현 완료. 아래 DBG02B/C 및 실제 배치 복구는 별도다.
**의존성:** DBG01 · **크기:** M · **파일:** app/crawler/sources/naver.py,
app/crawler/parsers/benchmarks.py, tests/unit/test_naver_index_source.py,
tests/integration/test_naver_benchmark_sync.py, tests/unit/test_parsers.py.

### DBG02B: 지수 응답·페이지 완전성 검증 — 구현·격리 검증 완료, 운영 범위 미완료

- [x] 읽기 전용 실응답 두 시장 각 100행을 엄격 parser로 대조했다. 날짜는 8자리, 값은 유한/양수, OHLC 일관성을 검사한다. 원문 응답 fixture 보존은 미완료다.
- [x] 첫 페이지 빈 응답, 비정상 JSON, 반복/역순 페이지, 중복 경계 및 상한 도달을 재현했다.
  정상 이력 종료와 실패를 구분하고 불완전 수집을 정상 완료로 기록하지 않는다.
- [ ] 운영 요청 완료 거래일 구간의 기대 행과 저장 행을 비교하고, 저장된 오래된 지수 반환을
  최신 수집 성공으로 오인하지 않도록 결과를 검증한다.

**검증:** 관련 지수 parser/source/SQLite 테스트 통과. `.venv/bin/pytest -q tests/unit/test_parsers.py tests/unit/test_naver_index_source.py tests/integration/test_naver_benchmark_sync.py`; 실사이트 첫 페이지 읽기 전용 확인. 전체 저장 대조는 DBG07A에서 한다.
**의존성:** DBG02A · **크기:** M · **예상 파일:** app/crawler/sources/naver.py,
app/crawler/parsers/benchmarks.py, tests/unit/test_naver_index_source.py,
tests/integration/test_naver_benchmark_sync.py, tests/fixtures/naver/benchmark_daily_json.json (신규).

### DBG02C: 장중 값·기준일·같은 날짜 재조회 정책 — 코드·합성 재현 완료

- [x] 장중 D일 값 저장 → 마감 D일 값 수신 시나리오를 재현해 마지막 날짜 제외로 갱신이
  빠지는지 확인한다. 종목 일봉의 since_date+1 경로도 같은 방식으로 확인한다.
- [x] 배치 target_date 상한을 benchmark/price 경로로 전달하고 그 이후 행이 저장되지 않는지 합성 재현했다. KST 완료 거래일 선정의 운영 정책 검증은 남는다.
- [ ] KST 기준 완료 거래일, 장중 실행과 마감 실행의 저장/갱신 정책을 고정하고
  기준일 이후 데이터가 확정 일봉·RS 입력에 섞이지 않는지 검증한다.
- [x] 같은 날짜 재실행에서 마감 값 반영·중복 방지와 최신 날짜 재조회 경로를 합성 재현했다. 더 오래된 중간 결측 복구는 별도다.
  필요한 source/저장 변경은 재현된 범위에서만 수행한다.

**검증:** tests/integration/test_naver_benchmark_sync.py 및
tests/unit/test_market_calendar.py; 오전/마감 응답 쌍을 사용하는
tests/integration/test_daily_price_cutoff.py (신규).
**의존성:** DBG02A · **크기:** M · **예상 파일:** app/crawler/sources/naver.py,
app/services/batch/sync_benchmarks.py, app/services/batch/sync_prices.py,
tests/integration/test_naver_benchmark_sync.py, tests/integration/test_daily_price_cutoff.py (신규).

## DBG03: 네이버 명부 복구 — source 구현/실측 완료, 기존 목록 대조 미완료

### DBG03A: 실제 화면 요청과 제공 범위 확인 — 완료

- [x] 현재 Naver SPA의 Next.js 자산에서 목록 API/helper를 확인하고 실응답을 재현했다. 주식 API는 `listedAtDesc`, `exchangeType=KRX`, 0-based `index`/`size`, `totalCount`/`hasNext`를 반환했다.
- [x] 네이버 화면에서 양 시장 선택·다음 페이지 요청을 관찰해 URL/매개변수와
  응답 시장 metadata를 연결한다. 필요하면 해당 화면의 JS를 읽고 실제 요청을 재현한다.
- [x] 주식·ETF·ETN 범위를 별도 Naver 응답으로 확인했다. 실응답은 주식 2,768, ETF 1,171, ETN 367행이며 영숫자 코드는 파서 검증에 포함했다.
  별도 목록이 필요하면 합산/중복 제거 규칙과 출처를 정한다.
- [x] KOSPI/KOSDAQ 주식 전체 페이지에서 고유 코드·총건수를 확인했다.
- [ ] 기존 명부 대비 코드/시장/유형별 추가·누락 차이를 분류한다.
  이전 marketValue 매개변수 조합 실패를 KOSDAQ 데이터 제공 불가로 일반화하지 않는다.

**검증:** 실제 화면 요청과 소량 읽기 전용 응답 대조. HTTP 200만으로 채택하지 않는다.
기록: 확인 시각, 시장·유형, 대표 코드, totalCount, 페이지 경계. 인증정보는 제외한다.
**의존성:** DBG01 · **크기:** S · **예상 파일:** reports/naver_universe_contract.md (신규),
tests/fixtures/naver/의 실제 명부 표본 (신규).

### DBG03B: 명부 source·파서·완전성 보호 — 코드·읽기 전용 검증 완료

- [x] 확인한 주식·ETF·ETN API 계약으로 파서/페이지 순회 및 양 시장·유형 분류를 구현했다.
- [x] 페이지 중복/누락·totalCount 변경·상한·잘못된 시장·0건/부분 응답을 실패로 식별한다.
  같은 시장/유형 범위의 totalCount와 고유 코드 수를 대조해 완전성을 판단한다.
- [x] 불완전 응답에서는 기존 종목 비활성화 후보를 만들지 않도록 snapshot 보호를 유지했다.
- [ ] 기존 명부 대비 개별 추가/누락/시장·유형 변경 사유를 분류한다.
  과거 명부와의 차이는 점검 신호이며 과거 수량 자체를 최신 정답으로 취급하지 않는다.

**검증:** 관련 parser/source/snapshot 테스트 통과. 실시간 전체 명부를 임시 SQLite에 적재해 snapshot completed 및 4,306행 저장을 확인했다. 운영 DB에는 쓰지 않았다.
**의존성:** DBG03A · **크기:** M · **예상 파일:** app/crawler/sources/naver.py,
app/crawler/parsers/symbols.py, app/services/batch/sync_symbols.py,
tests/unit/test_naver_universe_source.py, tests/unit/test_universe_snapshot.py.

### 체크포인트 D1

- [ ] DBG03B·DBG02B·DBG02C 통과: 명부 완전성과 지수 수집 범위, 기준일/마감 값 갱신 정책 확정.

## DBG06A: 명부 실패와 과거 목록 사용 상태 — checkpoint 가드 부분 완료

- [ ] snapshot 실패+기존 DB 목록 반환을 신규 명부 수집 성공과 구분하고 사용한 목록의
  기준시각/수량/출처를 기록한다. 기존 반환값이 실제 마지막 완료 snapshot과 같은지도 검증한다.
- [ ] 오래된 목록 사용 허용 범위와 후속 가격 수집/RS 공개 조건을 명시하고 부분 실패를 보존한다.
- [x] snapshot partial/failed이면 symbols checkpoint가 completed로 표시되지 않고 completed_with_errors로 남으며 재개 시 재시도된다. 상태/id metadata와 실패 건수를 기록한다.
- [ ] 최종 작업 상태·조회/알림 및 이전 snapshot의 기준시각/수량/출처를 같은 제한 운용 결과로 나타낸다.

**검증:** `.venv/bin/pytest -q tests/unit/test_orchestrator_universe_checkpoint.py tests/unit/test_universe_snapshot.py tests/integration/test_batch_harness.py`;
0건·부분 시장·기존 명부 존재/부재 주입.
**의존성:** DBG03B · **크기:** M · **예상 파일:** app/services/batch/sync_symbols.py,
app/services/batch/orchestrator.py, tests/unit/test_batch_checkpoint_metadata.py,
tests/integration/test_batch_harness.py.

## DBG07A: 소규모 네이버 수집·저장 검증

- [x] 기준일 2026-09-30, 양 시장 주식·ETF·ETN·영숫자 코드 5종을 선택해 실응답을
  disposable SQLite에 저장하고 운영 job 128에서 명부·지수·가격·검증 단계까지 통과했다.
- [x] SQLite 저장소로 같은 canary를 재실행해 가격/지수 행 수가 중복 증가하지 않는 것을 확인했다.
  생산 배치 중단/재개 안전성은 별도 DBG06B로 남긴다.
- [x] production 설정 KRX shadow=false 및 job 128 krx_shadow=pending으로 KRX 미호출을 확인했다.
  실운영 가격은 4,340대상 중 4,146 성공, 194 OHLC 실패로 관측됐다.

**검증:** tests/integration/test_naver_benchmark_sync.py,
tests/integration/test_batch_harness.py 및 tests/integration/test_naver_crawl_canary.py (신규).
실사이트 검증은 별도 실행으로 수행하며 자동 테스트는 고정 응답을 사용한다.
**의존성:** D1, DBG06A · **크기:** S · **예상 파일:**
tests/integration/test_naver_crawl_canary.py, reports/naver_crawl_canary.md (신규).

### 체크포인트 D2

- [x] 격리 SQLite 실응답 경로의 재실행과 운영 job 128의 명부·지수·가격·검증 저장을 확인했다.
  수집 복구는 완료, RS/API 및 194 가격 실패의 완전 복구는 미완료로 분리 보고한다.

## DBG04A: RS 종료 원인과 자원 측정

- [ ] 작업/프로세스 종료시각에 맞춰 접근 가능한 kernel/cgroup/실행 제한/중복 실행 증거를 모은다.
  과거 OOM 증거가 없으면 exit 137의 원인을 미확정으로 남긴다.
- [ ] 고정 입력으로 표본 규모를 확대하며 최대 RSS·CPU·SQL 수·외부 기업행위 요청·시간을 측정한다.
  처음에는 외부 입력을 고정하고 이후 해당 요청 비용을 별도 측정한다.
- [ ] 측정 근거로 원인 후보를 좁히고 프로세스 메모리·시간·요청 예산 및 중단 기준을 정한다.

**검증:** 격리 부하/프로세스 측정. 접근 불가 로그 및 재현 한계를 결과에 기록한다.
**의존성:** DBG01; 수집 표본은 DBG07A 재사용 가능 · **크기:** S · **예상 파일:**
reports/rs_resource_diagnosis.md, scripts/profile_rs_batch.py (둘 다 신규).

**2026-10-01 운영 관측:** job 128의 전체 이력 RS에서 RSS가 약 9.4GB까지 상승해 OOM 전에
수동 정지했다. host journal에서 과거 exit 137 원인의 OOM 증거는 확인되지 않아 원인은 미확정이다.
가격 단계는 약 140–190MB RSS로 끝났으므로 기존 `PriceSyncResult` 전체이력 보관 문제와
RS 계산 전체이력 보관 문제를 구분한다. 254행 입력 제한을 구현·격리 테스트했으나 운영 RS 검증은 남음.

## DBG04B: 확인된 RS 원인 수정

- [ ] DBG04A의 재현에서 확인된 병목 또는 종료 원인만 수정한다.
- [ ] 같은 적격 집합·기준일의 RS 결과와 미래 데이터 배제 조건이 유지된다.
- [ ] 운영 규모에 준하는 격리 입력이 정한 자원 예산 안에서 완료된다.

**검증:** `.venv/bin/pytest -q tests/unit/test_rs_calculator.py tests/integration/test_batch_harness.py`;
tests/integration/test_rs_resource_regression.py (신규) 및 DBG04A와 같은 부하 비교.
**의존성:** DBG04A · **크기:** M · **예상 파일:** app/services/batch/calculate_rs.py,
확인된 원인 파일 1개, tests/integration/test_rs_resource_regression.py, reports/rs_resource_diagnosis.md.

## DBG06B: 강제 종료 후 잔존 running 상태 처리

- [ ] 실제 실행 중인 프로세스와 잔존 작업을 구분하는 근거·유예시간·판정 절차를 고정한다.
- [ ] 실행 중 작업을 오판하지 않고 중단 작업의 단계·실패 이유·재개 지점을 기록한다.
- [ ] 정상 완료·예외·강제 종료·휴장일 건너뛰기 결과가 DB/로그/조회에 일치한다.

**검증:** 격리 프로세스 종료 주입과 tests/unit/test_batch_checkpoint_metadata.py.
SIGKILL 후 자기 프로세스의 예외 처리에 의존하지 않는다.
**의존성:** DBG04A, DBG06A · **크기:** M · **예상 파일:** app/services/batch/orchestrator.py,
app/repositories/crawl_job_repository.py, tests/unit/test_batch_checkpoint_metadata.py,
scripts/reconcile_interrupted_jobs.py (필요 시 신규).

## DBG05: API 이미지·DB revision 정합성

- [ ] DB current와 호스트/이미지의 전체 migration chain 차이를 확정한다.
- [ ] 기존 작업 트리의 필요한 revision이 들어 있는 이미지를 만들고 동일 revision 상태의
  격리 PostgreSQL에서 migration 자체의 성공을 확인한다.
- [ ] API health·대표 가격/RS 조회 및 재시작 반복 해소를 확인한다.

**검증:** 이미지 migration 파일 목록, 격리 DB의 alembic current/heads/upgrade,
API 기동과 대표 조회. E2E의 create_all 대체는 이 검증의 성공으로 인정하지 않는다.
**의존성:** DBG01; 수집·RS 조사와 독립 · **크기:** M · **예상 파일:** Dockerfile,
docker-compose.yml, reports/api_revision_diagnosis.md (신규).
원인이 오래된 이미지뿐이면 불필요한 코드/DDL 수정 없이 재빌드 검증한다.

## DBG07B: 전체 경로 통합 검증

- [ ] 같은 기준일의 명부 → 지수/가격 → 품질 검증 → RS → API 값과 날짜가 일치한다.
- [ ] 재실행·부분 실패/재개·장중/마감 전환·휴장일이 작업 상태와 데이터에 일관되게 반영된다.
- [ ] PostgreSQL 저장 및 migration 결과, 운영 규모 RS 자원 결과를 함께 확인한다.
  표본 집합의 RS 순위를 운영 전체 집합의 순위와 직접 비교하지 않는다.

**검증:** 기존 batch_harness/replay_source, 신규 canary/날짜/자원 테스트,
격리 PostgreSQL 연결을 확인한 tests/e2e/test_batch_e2e.py, 대표 API 조회.
DATABASE_URL·TEST_DATABASE_URL·E2E_DATABASE_URL의 대상을 모두 확인한다.
**의존성:** DBG07A, DBG04B, DBG05, DBG06B · **크기:** S · **예상 파일:**
tests/e2e/test_batch_e2e.py, reports/crawl_recovery_canary.md (신규).

### 체크포인트 D3

- [ ] 전체 경로·자원 예산·실패/재개·API 기동 검증이 통과해 실제 복구 범위를 산출할 수 있다.

## DBG08A: 누락 복구 실행안

- [ ] 최신 DB를 다시 읽어 종목·지수·RS별 대상/날짜 공백을 산출한다.
  상장 전·정지·유형 제외·공급자 미지원·실제 결측과 판정 불가를 구분한다.
- [ ] 9/17 이후 가격/지수, 9/4 이후 RS는 조사 출발점으로만 사용한다.
  최신 날짜보다 앞선 구멍도 지정 수집할 수 있는지 확인하고 준비 이력까지 포함한다.
- [ ] 가격/지수 보완 → 품질 검증 → 날짜별 RS 계산 순서, 요청/시간/메모리 예산,
  배치 중복 방지·중단/재개·복구 방법과 배포 파일 집합을 구체화한다.

**검증:** coverage SQL, 읽기 전용 실행 예상 결과, DBG07A/04A 실측 기반 시간 산정.
기존 CLI가 기간 지정/재개를 지원하지 않으면 부족 기능을 별도 작은 작업으로 정의한다.
역사 적격 명부가 부족한 구간은 정확한 과거 RS 복구를 보장할 수 없음을 명시한다.
**의존성:** D3 · **크기:** S · **예상 파일:** docs/crawl_recovery_runbook.md,
reports/crawl_recovery_scope.md (둘 다 신규).

## DBG08B: 실제 복구 및 예약 실행 검증

- [ ] 확정된 실행 범위에 따라 수정 반영·결측 복구를 수행하고 기존 불변 백테스트 dataset을 보존한다.
- [ ] 대상/날짜별 완료·제외·미확보 결과와 API 최신성을 대조한다.
- [ ] 다음 예정 배치의 KRX 미호출·중복 없음·단계 완료·실제 신규 저장과 RS 생성을 확인한다.
  최대 날짜나 종료 코드만으로 성공 처리하지 않는다.

**검증:** 복구 전후 coverage, 날짜별 입력 대조, 대표 API 조회,
다음 예약 배치의 프로세스/요청/단계/종료/저장 결과.
**의존성:** DBG08A · **크기:** S · **예상 파일:** reports/crawl_recovery_result.md (신규),
docs/crawl_recovery_runbook.md, tasks/todo.md.
운영 실행 범위는 사용자 후속 요청에 따라 진행하되, 전체 완료는 D3/D4 게이트를 따른다.

2026-10-01 사용자 요청에 따라 DBG08B의 크롤러 부분을 선행 실행했다(job 128). 명부·지수·가격·
검증 결과는 복구 보고서에 있다. API 이미지 revision 불일치는 후속 복구 이미지 배포로
해결했고 health·종목·랭킹 HTTP 200을 확인했다. RS 계산 메모리 안전 정지 이후의 운영
재계산이 남아 DBG08B 전체 완료 조건은 아직 충족하지 않는다. 다음 예약 실행 성공도 아직 확인되지 않았다.

### 체크포인트 D4

- [ ] 네이버 기반 자동 수집과 RS/API 제공이 확인되고 설명되지 않는 결측이 남지 않는다.
  공급자 한계로 미확보한 구간이 있으면 그 범위를 공개하고 완전 복구와 구분한다.

---

# 백테스트 데이터 구축 TODO

개정일: 2026-09-05<br>
기준: [PRD](../docs/prd-krx-universe-authority.md), [로드맵](../docs/roadmap_krx_universe.md), [계획](plan.md)<br>
현재 최우선: BT06A. BT00~BT05의 구현과 단위/격리 DB 검증은 완료됐지만, 공급 범위는 여전히 partial이다.

## 완료 기반

- [x] BT00: 키움 REST 키 주입, API 기동, 인증 및 삼성전자 일봉 1페이지 조회 확인.
  2026-09-05 HTTP 200 / 600행 / 2024-03-19~2026-09-04 / continuation=true.
  장기/상폐 이력 및 upsert는 이 완료 범위에 포함하지 않는다.

기존 가격 upsert·관측·품질 case·v2 API 골격을 재사용한다.
종전 T/HB/R 상태와 운영 증거는 [보관 TODO](todo.legacy-20260905.md)에 보존했다.
신규로 표시된 파일/테스트는 구현 예정이며 아직 실행된 검증 결과가 아니다.
공통 검증은 해당 테스트에 `.venv/bin/pytest -q`를 사용하고,
`git diff --check`를 수행한다. DB 테스트는 격리된 테스트 PostgreSQL을 사용한다.

## BT01: 역사 공급 범위 표본 검증

- [x] 공급자별 source matrix와 익명화 fixture·표본 실측

키움 연동 완료 상태에서 상폐·장기 이력의 실제 제공 범위와 KRX/KIND 역사 명부 입수 경로를 확인한다.

**완료 기준**

- [x] 현재 상장·상폐·시장 이전·기업행위·2013년 이전 사례를 포함한 5~10개 표본에 응답 범위/미지원 사유와 출처를 기록한다. 6개 표본의 read-only 결과는 [source contract](../docs/backtest_source_contract.md#실측-결과)에 고정했다.
- [x] 연속조회 2페이지 이상, 중복 경계, 고정 base_dt와 수정주가 기준을 검증한다. 현재 상장 4개 표본이 고정 base_dt로 6페이지를 통과했고, 중복 경계 fixture도 계약 테스트로 검증했다.
- [x] 명부 완전성·자료 이용/보관 조건·대체 공급자 필요 여부를 보고한다. 결과는 partial이며, 상폐 OHLC·완전 역사 명부에는 BT03의 허용된 대체 import가 필요하다.

**검증:** 기존 tests/unit/test_kiwoom_client.py, test_kiwoom_source.py + 신규 tests/unit/test_historical_source_contract.py; 소량 read-only 표본 리포트 확인.

**의존성:** BT00 · **크기:** M

**예상 파일:** `docs/backtest_source_contract.md (신규)`, `scripts/probe_historical_sources.py (신규)`, `tests/unit/test_historical_source_contract.py (신규)`.

## BT02: 역사 종목 정체성과 코드 구간

- [x] 기간별 코드로 과거 종목을 식별하는 경로

기존 Instrument/ProviderSymbol을 재사용하여 코드 재사용과 재상장을 표현할 최소 식별자 변경을 구현한다.

**완료 기준**

- [x] 동일 코드의 서로 다른 종목/상장 구간이 자동 병합되지 않으며 이름만으로 연결하지 않는다.
- [x] krx_short_code 전역 unique와 symbol 기반 FK의 변경/보존 경로를 migration에서 검증한다.
- [x] 선행 0·영숫자를 보존하고 중복/겹치는 provider code 유효기간을 거절하거나 ambiguous로 기록한다.

**검증:** 신규 tests/unit/test_historical_identity.py 및 기존 canonical migration/materialization 테스트; 복원 테스트 DB에서 migration과 기존 가격 FK 보존 검사.

**의존성:** BT01 · **크기:** M

**예상 파일:** `app/models/instrument.py`, `app/services/canonical_universe.py`, `alembic/versions/<revision>_historical_identity.py (신규)`, `tests/unit/test_historical_identity.py (신규)`.

## BT03: 상장·상폐 이벤트 import

- [x] 출처와 정정 이력을 가진 역사 명부

BT01에서 검증한 한 가지 파일/API 경로부터 원문 근거가 있는 역사 이벤트를 저장한다. 추가 공급자 connector는 같은 계약을 재사용한다.

**완료 기준**

- [x] 상장·상폐·시장 이전·정지/재개·코드변경에 effective 시점, published_at(없으면 unknown), observed_at, 출처/hash를 저장한다.
- [x] 같은 자료 재입력은 중복을 만들지 않고 정정/충돌은 이전 버전을 보존한다.
- [x] 현재 명부 누락이나 첫/마지막 가격을 확정 상폐/상장 근거로 쓰지 않는다.

**검증:** 신규 tests/unit/test_listing_history.py 및 tests/integration/test_listing_history.py; 상폐 효력일/마지막 거래일이 다른 fixture replay.

**의존성:** BT02 · **크기:** M

**예상 파일:** `app/models/listing_event.py (신규)`, `alembic/versions/<revision>_listing_events.py (신규)`, `scripts/import_listing_history.py (신규)`, `tests/unit/test_listing_history.py (신규)`, `tests/integration/test_listing_history.py (신규)`.

### CP1: 역사 명부

- [x] 상폐 표본·코드 재사용·원문 정정 및 미확인 coverage가 설명된다. 실제 전체 명부 coverage는 BT12 전에도 partial로 유지한다.

## BT04: 시점 유니버스와 기대 거래일

- [x] 날짜별 membership와 가격 수집 대상 manifest

상장 구간을 거래 캘린더와 결합해 가격 유무와 무관한 날짜별 기대 대상과 수집 manifest를 생성한다.

**완료 기준**

- [x] 상장/상폐/시장 이전 경계일, 정리매매, 정지 후 재개를 [from,to) 규칙으로 재현한다.
- [x] 현재 is_active와 미래 상폐 사실로 과거 후보를 제외하지 않으며 당시 시장으로 필터링한다.
- [x] observed/inferred/unknown, 유형 제외, 명부 완전성, 기대 거래일 분모를 출력한다. unknown을 제외한 집합을 전체라고 표시하지 않는다.

**검증:** 신규 tests/unit/test_historical_universe.py; 가격 없는 상폐 종목도 manifest에 나타나는 fixture 확인.

**의존성:** BT03 · **크기:** M

**예상 파일:** `app/services/historical_universe.py (신규)`, `app/repositories/listing_history_repository.py (신규)`, `tests/unit/test_historical_universe.py (신규)`.

## BT05: 기간 제한 키움 페이지 수집

- [x] 전체 이력을 메모리에 누적하지 않는 기간 수집기

기존 KiwoomRestClient 위에 요청 기간과 준비 기간을 처리하는 bounded iterator를 추가한다.

**완료 기준**

- [x] start/end와 RS 준비 기간을 구분하고 기준일·조정정책·거래소를 고정한다.
- [x] 페이지 단위 메모리, 속도/총 요청 예산, 기간 도달 종료, 반복/빈 페이지·429·타임아웃을 처리한다.
- [x] 상폐/미지원 응답을 명시적으로 반환하고 파서 탈락 행의 수/사유를 보존한다.

**검증:** 기존 kiwoom 테스트 + 신규 tests/unit/test_kiwoom_history.py; 가짜 다중 페이지 응답에서 호출 상한·반복 종료·메모리 크기 검사.

**의존성:** BT01, BT04 · **크기:** M

**예상 파일:** `app/crawler/sources/kiwoom_history.py (신규)`, `app/crawler/kiwoom_client.py`, `app/crawler/parsers/kiwoom.py`, `tests/unit/test_kiwoom_history.py (신규)`.

## BT06A: 수집 실행·checkpoint 저장

- [x] 재개에 필요한 실행 manifest와 저장 상태

수집 manifest와 확정 chunk 진행 상태를 저장할 최소 스키마를 추가한다.

**완료 기준**

- [x] run_id에 대상 명부/기간/조정 기준/예산을 고정하고 resume 요청의 설정 불일치를 거절한다.
- [x] 종목별 확정 구간과 재시도/실패 상태를 보존하며 단순 token 보관에만 의존하지 않는다.
- [x] additive migration으로 기존 가격·배치·관측 이력을 보존한다.

**검증:** 신규 tests/unit/test_backfill_state.py; 테스트 DB migration/reload 후 동일 checkpoint 확인.

**의존성:** BT05 · **크기:** M

**예상 파일:** `app/models/historical_backfill_run.py (신규)`, `alembic/versions/<revision>_historical_backfill_runs.py (신규)`, `tests/unit/test_backfill_state.py (신규)`.

### CP2a: 기간 수집 기반

- [x] 시점 대상·페이지/요청 제한·manifest/checkpoint가 테스트로 검증된다.

## BT06B: 관측 보존 upsert와 재개 CLI

- [x] dry-run과 실제 적재를 구분하는 재개 가능한 작업

BT05의 페이지를 기존 PriceRepository/observation 구조에 연결하고 chunk 저장과 checkpoint를 구성한다.

**완료 기준**

- [x] start/end·종목/시장·dry-run·run_id/resume·요청 예산을 제공하고 insert/update/unchanged/conflict/failed/unsupported를 구분한다.
- [x] chunk commit과 checkpoint의 일관성을 지키고 강제 종료/만료 cursor 뒤 재시도해도 canonical 중복이나 완료 구간 누락이 없다.
- [x] provider·조정기준·원본 hash·run_id를 보존한다. 충돌은 case 후보로 남기고 갱신 정책을 벗어난 덮어쓰기를 거절한다.

**검증:** 신규 tests/integration/test_backfill_resume.py; 격리 PostgreSQL에서 동일 입력 2회 및 commit 경계 강제 중단 후 결과 비교.

**의존성:** BT06A · **크기:** M

**예상 파일:** `scripts/backfill_historical_prices.py (신규)`, `app/services/historical_backfill.py (신규)`, `app/repositories/price_repository.py`, `tests/integration/test_backfill_resume.py (신규)`.

### CP2b: 저장 재개

- [x] 중단·재실행·충돌 fixture에서 가격/관측/진행 상태가 일치한다.

## BT07: 기간 결측 검증

- [x] 결측을 숨기지 않는 기간 coverage와 case

기대 종목·거래일과 실제 관측을 비교해 가격 행이 전혀 없는 종목까지 validation case를 만든다.

**완료 기준**

- [x] 휴장/상장 전/상폐 후와 기대 거래일의 결측, 확인된 정지, 요청 실패/미지원, 신규상장 준비 기간 부족을 구분한다.
- [x] 가격 없는 종목·날짜/연속 구간에도 reason/evidence/version을 저장한다.
- [x] 명부·유니버스·가격·유효가격 coverage를 시장/연도/상폐 여부별 분자·분모와 함께 내고 미확인 명부 분모는 unknown 처리한다.

**검증:** 신규 tests/unit/test_historical_gaps.py; 행이 0개인 상폐 종목, 휴장, 정지, 신규상장 fixture.

**의존성:** BT04, BT06B · **크기:** M

**예상 파일:** `app/services/validation/historical_gaps.py (신규)`, `app/services/validation/data_quality.py`, `app/services/validation/report.py`, `tests/unit/test_historical_gaps.py (신규)`.

## BT08: 이상치·기업행위 검증

- [x] 기간별 정책에 근거한 quality flags

기존 OHLC 검사를 재사용하고 날짜별 정책 및 기업행위 근거로 수익률 이상과 공급자 충돌을 분류한다.

**완료 기준**

- [x] OHLC/거래량 오류와 극단수익률 경고를 구분하며 공급자 부호 표기·분할·병합·배당락 fixture를 포함한다.
- [x] 과거 제도 변경/정리매매 예외를 정책 버전으로 다루고 오늘의 가격제한이나 0거래량만으로 자동 제외하지 않는다.
- [x] 관측·검증 case·제외/보정 결정을 보존하며 같은 입력/정책 replay의 판정이 동일하다.

**검증:** 기존 tests/unit/test_data_quality_validation.py + 신규 tests/unit/test_historical_anomalies.py; 기업행위 정상 급변과 잘못된 가격의 분리 검증.

**의존성:** BT06B · **크기:** M

**예상 파일:** `app/services/validation/rules.py`, `app/services/validation/historical_policy.py (신규)`, `app/services/validation/clean_layer.py`, `tests/unit/test_historical_anomalies.py (신규)`.

### CP3: 품질

- [x] 가격 없는 종목과 정지/기업행위를 구분하고 판정이 replay된다.

## BT09: 불변 데이터셋 버전 저장

- [x] 기존 데이터를 다시 읽을 수 있는 불변 manifest

기존 관측/event revision을 고정하는 manifest와 immutable 참조 또는 export를 만든다.

**완료 기준**

- [x] 가격·membership revision·조정 기준·정책·준비 기간·범위·coverage·watermark·hash를 manifest에 고정한다.
- [x] 같은 canonical 행을 update하고 신규 관측을 넣어도 이전 dataset의 가격/유니버스는 변하지 않는다.
- [x] 보존기간·만료와 historical_reconstructed/as_known_at 가능 범위를 명시한다. 최대 ID만으로 불변성을 주장하지 않는다.

**검증:** 신규 tests/integration/test_backtest_snapshot.py; 공개 직후 동일 가격 행 upsert/이벤트 정정 전후 기존 snapshot hash 비교.

**의존성:** BT07, BT08 · **크기:** M

**예상 파일:** `app/models/backtest_dataset.py (신규)`, `alembic/versions/<revision>_backtest_datasets.py (신규)`, `app/services/backtest_snapshot.py (신규)`, `tests/integration/test_backtest_snapshot.py (신규)`.

## BT10: 날짜별 역사 RS 재계산

- [x] 날짜별 RS와 재현 가능한 input lineage

고정된 가격과 당시 유니버스를 현 RS 계산기에 연결하고 결과 lineage를 dataset의 최종 manifest에 고정한다.

**완료 기준**

- [x] D까지의 가격과 D의 적격 집합만 사용하며 미래 가격 추가가 D의 RS를 바꾸지 않는다.
- [x] 253개 관측 준비 기간 및 신규상장/결측 부족을 처리하고 RS null 사유·이용 가능 시각을 남긴다.
- [x] 산식/quality/universe 버전과 RS run을 고정하며 기존 rs_scores를 무검증 재사용하지 않는다.

**검증:** 기존 tests/unit/test_rs_calculator.py + 신규 tests/unit/test_historical_rs.py; 날짜별 집합과 미래 입력 불변 fixture.

**의존성:** BT09 · **크기:** M

**예상 파일:** `app/services/historical_rs.py (신규)`, `app/services/rs/calculator.py`, `app/services/backtest_snapshot.py (신규)`, `tests/unit/test_historical_rs.py (신규)`.

## BT11: 백테스트 API 계약 완성

- [x] 가격·RS·유니버스·품질이 결합된 재현 가능한 기간 API

기존 v2 기간 API를 역사 dataset에 연결하고 가격 없는 기대 행 및 보존 버전 재조회를 제공한다.

**완료 기준**

- [x] 필수 start/end, page_size 기본 1000/최대 5000, cursor, backtest:read를 유지하고 dataset_id로 과거 버전을 다시 조회한다.
- [x] 가격 null·RS null 사유·당시 시장/상장/거래 상태·quality·coverage를 노출하며 엄격 모드의 제외와 partial을 설명한다.
- [x] cursor를 snapshot/필터에 묶고 페이지별 ETag, 버전 만료 오류, 전 페이지 누락/중복 없음, 기존 365일 API 호환을 검증한다.

**검증:** tests/unit/test_backtest_api.py 확장 + 신규 tests/integration/test_backtest_replay.py; 2015~2025 예시와 상폐/시장 이전/결측 fixture로 전 페이지 비교.

**의존성:** BT10 · **크기:** M

**예상 파일:** `app/api/v1/endpoints/backtest.py`, `app/schemas/agent.py`, `tests/unit/test_backtest_api.py`, `tests/integration/test_backtest_replay.py (신규)`, `docs/agent_api.md`.

### CP4: 재현성

- [x] 같은 canonical 행을 갱신한 뒤에도 이전 dataset의 전 페이지 및 RS가 동일하다.

## BT12: 실측 실행안과 대량 적재 승인

- [x] 기간·비용·실행 명령이 고정된 승인 대상

표본과 dry-run을 바탕으로 사용자가 승인할 수 있는 단일 실행 manifest를 만든다.

**완료 기준**

- [x] 목표/준비 기간, 대상 명부 버전, 시장/유형/상폐 종목 수, 제공 불가 구간, 갱신 정책을 확정한다.
- [x] 페이지당 행 수·지연·재시도·저장/검증/RS 시간을 실측하여 예상 시간 범위와 추가 DB/관측/인덱스 용량 및 여유 공간을 계산한다.
- [x] 명령·manifest hash·request/디스크 예산·중단/재개 방법과 함께 사용자의 실행 승인을 기록한다. 이전의 2~5시간 추정은 승인 근거로 재사용하지 않는다.

**검증:** backfill CLI dry-run 리포트/명령 옵션 대조; 신규 tests/unit/test_backfill_estimate.py; 운영 가격 쓰기 없는 예상안 검토.

**의존성:** BT11 · **크기:** M

**예상 파일:** `scripts/backfill_historical_prices.py (신규)`, `app/services/historical_backfill.py (신규)`, `tests/unit/test_backfill_estimate.py (신규)`, `docs/backtest_backfill_runbook.md (신규)`.

## BT13: 승인 범위 적재와 최종 replay

- [x] 검수 가능한 역사 dataset와 적재/품질 보고서

BT12 승인 범위에 한해 수집·검증·RS·dataset 생성을 실행하고 결과를 검수한다.

**완료 기준**

- [x] 승인 manifest와 실제 실행이 일치하며 완료/미확보/실패·재시도 수 및 전체 소요/용량을 보고한다.
- [x] 상폐 종목이 과거 대상에 포함되고 survivor-only 대비 집합 차이와 명부/가격/RS coverage가 보고된다.
- [x] 동일 dataset 전 페이지 hash/RS 재현, 결측·상폐 손익 미확인 표시, 기존 API 회귀를 통과한다. coverage 미확인은 partial로 공개한다.

**검증:** 검증용 PostgreSQL의 관련 통합 테스트 및 dataset replay; 운영 실행 결과와 승인안 대조.

**의존성:** BT12 · **크기:** M

**예상 파일:** `docs/backtest_backfill_runbook.md (신규)`, `reports/backtest/<run_id>/ (실행 산출물)`, `tasks/todo.md`.

### CP5: 운영 결과

- [x] 승인 범위·대상/미확보 수·생존편향 관련 coverage·최종 dataset replay가 보고된다.

## 후순위 BT14: 최신 유니버스 증분 유지

- [ ] BT13 이후, 같은 역사 이벤트 import에 신규 상장·상폐·시장 이전 증분을 연결한다.
- [ ] partial 명부로 자동 상폐 처리하지 않고 마지막 검증 상태와 근거를 유지한다.
- [ ] 과거 이벤트 정정이 기존 dataset을 바꾸지 않고 새 revision을 만드는지 검증한다.

**의존성:** BT13. **검증:** listing history replay와 기존 daily universe 회귀.
세부 구현 파일은 BT13 결과를 보고 확정한다.

5거래일 authority 전환·운영 dashboard 확대·Sam repair 확대·ETF/ETN·RS 산식 개선은
후순위 backlog다. 백테스트 P0의 진행 게이트로 되살리지 않는다.
