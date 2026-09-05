# 백테스트 데이터 구축 TODO

개정일: 2026-09-05<br>
기준: [PRD](../docs/prd-krx-universe-authority.md), [로드맵](../docs/roadmap_krx_universe.md), [계획](plan.md)<br>
현재 최우선: BT02. BT00·BT01 외 항목은 이 개정으로 구현 완료 처리하지 않는다.

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

- [ ] 기간별 코드로 과거 종목을 식별하는 경로

기존 Instrument/ProviderSymbol을 재사용하여 코드 재사용과 재상장을 표현할 최소 식별자 변경을 구현한다.

**완료 기준**

- [ ] 동일 코드의 서로 다른 종목/상장 구간이 자동 병합되지 않으며 이름만으로 연결하지 않는다.
- [ ] krx_short_code 전역 unique와 symbol 기반 FK의 변경/보존 경로를 migration에서 검증한다.
- [ ] 선행 0·영숫자를 보존하고 중복/겹치는 provider code 유효기간을 거절하거나 ambiguous로 기록한다.

**검증:** 신규 tests/unit/test_historical_identity.py 및 기존 canonical migration/materialization 테스트; 복원 테스트 DB에서 migration과 기존 가격 FK 보존 검사.

**의존성:** BT01 · **크기:** M

**예상 파일:** `app/models/instrument.py`, `app/services/canonical_universe.py`, `alembic/versions/<revision>_historical_identity.py (신규)`, `tests/unit/test_historical_identity.py (신규)`.

## BT03: 상장·상폐 이벤트 import

- [ ] 출처와 정정 이력을 가진 역사 명부

BT01에서 검증한 한 가지 파일/API 경로부터 원문 근거가 있는 역사 이벤트를 저장한다. 추가 공급자 connector는 같은 계약을 재사용한다.

**완료 기준**

- [ ] 상장·상폐·시장 이전·정지/재개·코드변경에 effective 시점, published_at(없으면 unknown), observed_at, 출처/hash를 저장한다.
- [ ] 같은 자료 재입력은 중복을 만들지 않고 정정/충돌은 이전 버전을 보존한다.
- [ ] 현재 명부 누락이나 첫/마지막 가격을 확정 상폐/상장 근거로 쓰지 않는다.

**검증:** 신규 tests/unit/test_listing_history.py 및 tests/integration/test_listing_history.py; 상폐 효력일/마지막 거래일이 다른 fixture replay.

**의존성:** BT02 · **크기:** M

**예상 파일:** `app/models/listing_event.py (신규)`, `alembic/versions/<revision>_listing_events.py (신규)`, `scripts/import_listing_history.py (신규)`, `tests/unit/test_listing_history.py (신규)`, `tests/integration/test_listing_history.py (신규)`.

### CP1: 역사 명부

- [ ] 상폐 표본·코드 재사용·원문 정정 및 미확인 coverage가 설명된다.

## BT04: 시점 유니버스와 기대 거래일

- [ ] 날짜별 membership와 가격 수집 대상 manifest

상장 구간을 거래 캘린더와 결합해 가격 유무와 무관한 날짜별 기대 대상과 수집 manifest를 생성한다.

**완료 기준**

- [ ] 상장/상폐/시장 이전 경계일, 정리매매, 정지 후 재개를 [from,to) 규칙으로 재현한다.
- [ ] 현재 is_active와 미래 상폐 사실로 과거 후보를 제외하지 않으며 당시 시장으로 필터링한다.
- [ ] observed/inferred/unknown, 유형 제외, 명부 완전성, 기대 거래일 분모를 출력한다. unknown을 제외한 집합을 전체라고 표시하지 않는다.

**검증:** 신규 tests/unit/test_historical_universe.py; 가격 없는 상폐 종목도 manifest에 나타나는 fixture 확인.

**의존성:** BT03 · **크기:** M

**예상 파일:** `app/services/historical_universe.py (신규)`, `app/repositories/listing_history_repository.py (신규)`, `tests/unit/test_historical_universe.py (신규)`.

## BT05: 기간 제한 키움 페이지 수집

- [ ] 전체 이력을 메모리에 누적하지 않는 기간 수집기

기존 KiwoomRestClient 위에 요청 기간과 준비 기간을 처리하는 bounded iterator를 추가한다.

**완료 기준**

- [ ] start/end와 RS 준비 기간을 구분하고 기준일·조정정책·거래소를 고정한다.
- [ ] 페이지 단위 메모리, 속도/총 요청 예산, 기간 도달 종료, 반복/빈 페이지·429·타임아웃을 처리한다.
- [ ] 상폐/미지원 응답을 명시적으로 반환하고 파서 탈락 행의 수/사유를 보존한다.

**검증:** 기존 kiwoom 테스트 + 신규 tests/unit/test_kiwoom_history.py; 가짜 다중 페이지 응답에서 호출 상한·반복 종료·메모리 크기 검사.

**의존성:** BT01, BT04 · **크기:** M

**예상 파일:** `app/crawler/sources/kiwoom_history.py (신규)`, `app/crawler/kiwoom_client.py`, `app/crawler/parsers/kiwoom.py`, `tests/unit/test_kiwoom_history.py (신규)`.

## BT06A: 수집 실행·checkpoint 저장

- [ ] 재개에 필요한 실행 manifest와 저장 상태

수집 manifest와 확정 chunk 진행 상태를 저장할 최소 스키마를 추가한다.

**완료 기준**

- [ ] run_id에 대상 명부/기간/조정 기준/예산을 고정하고 resume 요청의 설정 불일치를 거절한다.
- [ ] 종목별 확정 구간과 재시도/실패 상태를 보존하며 단순 token 보관에만 의존하지 않는다.
- [ ] additive migration으로 기존 가격·배치·관측 이력을 보존한다.

**검증:** 신규 tests/unit/test_backfill_state.py; 테스트 DB migration/reload 후 동일 checkpoint 확인.

**의존성:** BT05 · **크기:** M

**예상 파일:** `app/models/historical_backfill_run.py (신규)`, `alembic/versions/<revision>_historical_backfill_runs.py (신규)`, `tests/unit/test_backfill_state.py (신규)`.

### CP2a: 기간 수집 기반

- [ ] 시점 대상·페이지/요청 제한·manifest/checkpoint가 테스트로 검증된다.

## BT06B: 관측 보존 upsert와 재개 CLI

- [ ] dry-run과 실제 적재를 구분하는 재개 가능한 작업

BT05의 페이지를 기존 PriceRepository/observation 구조에 연결하고 chunk 저장과 checkpoint를 구성한다.

**완료 기준**

- [ ] start/end·종목/시장·dry-run·run_id/resume·요청 예산을 제공하고 insert/update/unchanged/conflict/failed/unsupported를 구분한다.
- [ ] chunk commit과 checkpoint의 일관성을 지키고 강제 종료/만료 cursor 뒤 재시도해도 canonical 중복이나 완료 구간 누락이 없다.
- [ ] provider·조정기준·원본 hash·run_id를 보존한다. 충돌은 case 후보로 남기고 갱신 정책을 벗어난 덮어쓰기를 거절한다.

**검증:** 신규 tests/integration/test_backfill_resume.py; 격리 PostgreSQL에서 동일 입력 2회 및 commit 경계 강제 중단 후 결과 비교.

**의존성:** BT06A · **크기:** M

**예상 파일:** `scripts/backfill_historical_prices.py (신규)`, `app/services/historical_backfill.py (신규)`, `app/repositories/price_repository.py`, `tests/integration/test_backfill_resume.py (신규)`.

### CP2b: 저장 재개

- [ ] 중단·재실행·충돌 fixture에서 가격/관측/진행 상태가 일치한다.

## BT07: 기간 결측 검증

- [ ] 결측을 숨기지 않는 기간 coverage와 case

기대 종목·거래일과 실제 관측을 비교해 가격 행이 전혀 없는 종목까지 validation case를 만든다.

**완료 기준**

- [ ] 휴장/상장 전/상폐 후와 기대 거래일의 결측, 확인된 정지, 요청 실패/미지원, 신규상장 준비 기간 부족을 구분한다.
- [ ] 가격 없는 종목·날짜/연속 구간에도 reason/evidence/version을 저장한다.
- [ ] 명부·유니버스·가격·유효가격 coverage를 시장/연도/상폐 여부별 분자·분모와 함께 내고 미확인 명부 분모는 unknown 처리한다.

**검증:** 신규 tests/unit/test_historical_gaps.py; 행이 0개인 상폐 종목, 휴장, 정지, 신규상장 fixture.

**의존성:** BT04, BT06B · **크기:** M

**예상 파일:** `app/services/validation/historical_gaps.py (신규)`, `app/services/validation/data_quality.py`, `app/services/validation/report.py`, `tests/unit/test_historical_gaps.py (신규)`.

## BT08: 이상치·기업행위 검증

- [ ] 기간별 정책에 근거한 quality flags

기존 OHLC 검사를 재사용하고 날짜별 정책 및 기업행위 근거로 수익률 이상과 공급자 충돌을 분류한다.

**완료 기준**

- [ ] OHLC/거래량 오류와 극단수익률 경고를 구분하며 공급자 부호 표기·분할·병합·배당락 fixture를 포함한다.
- [ ] 과거 제도 변경/정리매매 예외를 정책 버전으로 다루고 오늘의 가격제한이나 0거래량만으로 자동 제외하지 않는다.
- [ ] 관측·검증 case·제외/보정 결정을 보존하며 같은 입력/정책 replay의 판정이 동일하다.

**검증:** 기존 tests/unit/test_data_quality_validation.py + 신규 tests/unit/test_historical_anomalies.py; 기업행위 정상 급변과 잘못된 가격의 분리 검증.

**의존성:** BT06B · **크기:** M

**예상 파일:** `app/services/validation/rules.py`, `app/services/validation/historical_policy.py (신규)`, `app/services/validation/clean_layer.py`, `tests/unit/test_historical_anomalies.py (신규)`.

### CP3: 품질

- [ ] 가격 없는 종목과 정지/기업행위를 구분하고 판정이 replay된다.

## BT09: 불변 데이터셋 버전 저장

- [ ] 기존 데이터를 다시 읽을 수 있는 불변 manifest

기존 관측/event revision을 고정하는 manifest와 immutable 참조 또는 export를 만든다.

**완료 기준**

- [ ] 가격·membership revision·조정 기준·정책·준비 기간·범위·coverage·watermark·hash를 manifest에 고정한다.
- [ ] 같은 canonical 행을 update하고 신규 관측을 넣어도 이전 dataset의 가격/유니버스는 변하지 않는다.
- [ ] 보존기간·만료와 historical_reconstructed/as_known_at 가능 범위를 명시한다. 최대 ID만으로 불변성을 주장하지 않는다.

**검증:** 신규 tests/integration/test_backtest_snapshot.py; 공개 직후 동일 가격 행 upsert/이벤트 정정 전후 기존 snapshot hash 비교.

**의존성:** BT07, BT08 · **크기:** M

**예상 파일:** `app/models/backtest_dataset.py (신규)`, `alembic/versions/<revision>_backtest_datasets.py (신규)`, `app/services/backtest_snapshot.py (신규)`, `tests/integration/test_backtest_snapshot.py (신규)`.

## BT10: 날짜별 역사 RS 재계산

- [ ] 날짜별 RS와 재현 가능한 input lineage

고정된 가격과 당시 유니버스를 현 RS 계산기에 연결하고 결과 lineage를 dataset의 최종 manifest에 고정한다.

**완료 기준**

- [ ] D까지의 가격과 D의 적격 집합만 사용하며 미래 가격 추가가 D의 RS를 바꾸지 않는다.
- [ ] 253개 관측 준비 기간 및 신규상장/결측 부족을 처리하고 RS null 사유·이용 가능 시각을 남긴다.
- [ ] 산식/quality/universe 버전과 RS run을 고정하며 기존 rs_scores를 무검증 재사용하지 않는다.

**검증:** 기존 tests/unit/test_rs_calculator.py + 신규 tests/unit/test_historical_rs.py; 날짜별 집합과 미래 입력 불변 fixture.

**의존성:** BT09 · **크기:** M

**예상 파일:** `app/services/historical_rs.py (신규)`, `app/services/rs/calculator.py`, `app/services/backtest_snapshot.py (신규)`, `tests/unit/test_historical_rs.py (신규)`.

## BT11: 백테스트 API 계약 완성

- [ ] 가격·RS·유니버스·품질이 결합된 재현 가능한 기간 API

기존 v2 기간 API를 역사 dataset에 연결하고 가격 없는 기대 행 및 보존 버전 재조회를 제공한다.

**완료 기준**

- [ ] 필수 start/end, page_size 기본 1000/최대 5000, cursor, backtest:read를 유지하고 dataset_id로 과거 버전을 다시 조회한다.
- [ ] 가격 null·RS null 사유·당시 시장/상장/거래 상태·quality·coverage를 노출하며 엄격 모드의 제외와 partial을 설명한다.
- [ ] cursor를 snapshot/필터에 묶고 페이지별 ETag, 버전 만료 오류, 전 페이지 누락/중복 없음, 기존 365일 API 호환을 검증한다.

**검증:** tests/unit/test_backtest_api.py 확장 + 신규 tests/integration/test_backtest_replay.py; 2015~2025 예시와 상폐/시장 이전/결측 fixture로 전 페이지 비교.

**의존성:** BT10 · **크기:** M

**예상 파일:** `app/api/v1/endpoints/backtest.py`, `app/schemas/agent.py`, `tests/unit/test_backtest_api.py`, `tests/integration/test_backtest_replay.py (신규)`, `docs/agent_api.md`.

### CP4: 재현성

- [ ] 같은 canonical 행을 갱신한 뒤에도 이전 dataset의 전 페이지 및 RS가 동일하다.

## BT12: 실측 실행안과 대량 적재 승인

- [ ] 기간·비용·실행 명령이 고정된 승인 대상

표본과 dry-run을 바탕으로 사용자가 승인할 수 있는 단일 실행 manifest를 만든다.

**완료 기준**

- [ ] 목표/준비 기간, 대상 명부 버전, 시장/유형/상폐 종목 수, 제공 불가 구간, 갱신 정책을 확정한다.
- [ ] 페이지당 행 수·지연·재시도·저장/검증/RS 시간을 실측하여 예상 시간 범위와 추가 DB/관측/인덱스 용량 및 여유 공간을 계산한다.
- [ ] 명령·manifest hash·request/디스크 예산·중단/재개 방법과 함께 사용자의 실행 승인을 기록한다. 이전의 2~5시간 추정은 승인 근거로 재사용하지 않는다.

**검증:** backfill CLI dry-run 리포트/명령 옵션 대조; 신규 tests/unit/test_backfill_estimate.py; 운영 가격 쓰기 없는 예상안 검토.

**의존성:** BT11 · **크기:** M

**예상 파일:** `scripts/backfill_historical_prices.py (신규)`, `app/services/historical_backfill.py (신규)`, `tests/unit/test_backfill_estimate.py (신규)`, `docs/backtest_backfill_runbook.md (신규)`.

## BT13: 승인 범위 적재와 최종 replay

- [ ] 검수 가능한 역사 dataset와 적재/품질 보고서

BT12 승인 범위에 한해 수집·검증·RS·dataset 생성을 실행하고 결과를 검수한다.

**완료 기준**

- [ ] 승인 manifest와 실제 실행이 일치하며 완료/미확보/실패·재시도 수 및 전체 소요/용량을 보고한다.
- [ ] 상폐 종목이 과거 대상에 포함되고 survivor-only 대비 집합 차이와 명부/가격/RS coverage가 보고된다.
- [ ] 동일 dataset 전 페이지 hash/RS 재현, 결측·상폐 손익 미확인 표시, 기존 API 회귀를 통과한다. coverage 미확인은 partial로 공개한다.

**검증:** 검증용 PostgreSQL의 관련 통합 테스트 및 dataset replay; 운영 실행 결과와 승인안 대조.

**의존성:** BT12 · **크기:** M

**예상 파일:** `docs/backtest_backfill_runbook.md (신규)`, `reports/backtest/<run_id>/ (실행 산출물)`, `tasks/todo.md`.

### CP5: 운영 결과

- [ ] 승인 범위·대상/미확보 수·생존편향 관련 coverage·최종 dataset replay가 보고된다.

## 후순위 BT14: 최신 유니버스 증분 유지

- [ ] BT13 이후, 같은 역사 이벤트 import에 신규 상장·상폐·시장 이전 증분을 연결한다.
- [ ] partial 명부로 자동 상폐 처리하지 않고 마지막 검증 상태와 근거를 유지한다.
- [ ] 과거 이벤트 정정이 기존 dataset을 바꾸지 않고 새 revision을 만드는지 검증한다.

**의존성:** BT13. **검증:** listing history replay와 기존 daily universe 회귀.
세부 구현 파일은 BT13 결과를 보고 확정한다.

5거래일 authority 전환·운영 dashboard 확대·Sam repair 확대·ETF/ETN·RS 산식 개선은
후순위 backlog다. 백테스트 P0의 진행 게이트로 되살리지 않는다.
