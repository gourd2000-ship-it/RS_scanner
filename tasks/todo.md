# KRX 기준 유니버스 작업 목록

기준 PRD: [docs/prd-krx-universe-authority.md](../docs/prd-krx-universe-authority.md)
상위 계획: [tasks/plan.md](plan.md)
검증 기본 명령: `TELEGRAM_ENABLED=false NOTIFICATION_ENABLED=false .venv/bin/pytest -q` 및 `git diff --check`

## P0 — 안전한 Naver 유니버스 복구

## Task T01: Naver 페이지 완료 조건과 상한 경보

**상태:** 구현 완료 · 운영 snapshot 검증 대기

**설명:** KOSPI/KOSDAQ universe가 고정 40페이지에서 항상 partial이 되는 문제를 제거한다.
빈/반복 페이지는 정상 완료로 처리하고, 별도 설정 hard cap 도달은 명시적인 partial과 경보로 남긴다.

**Acceptance criteria:**
- [ ] 페이지 종료·반복·요청 오류·hard cap의 snapshot 상태가 구분된다.
- [ ] 현재 시장 규모에서 completed snapshot을 생성할 수 있다.
- [ ] hard cap은 환경 설정으로 조정 가능하며 도달 사실이 metric/log에 남는다.

**Verification:**
- [ ] `pytest -q tests/unit/test_naver_universe_source.py tests/unit/test_universe_snapshot.py`
- [ ] fixture 기반으로 completed/partial 페이지 경로를 확인한다.

**Dependencies:** 없음
**Files likely touched:** `app/core/config.py`, `app/crawler/sources/naver.py`, `tests/unit/test_naver_universe_source.py`, `tests/unit/test_universe_snapshot.py`
**Estimated scope:** M

## Task T02: 공급자 식별자 계약과 parser 회귀 방어

**상태:** 구현 완료

**설명:** Naver code를 숫자로 축소하지 않고 정확한 영숫자 문자열로 유지한다. 4/5자리 legacy
코드는 새 ingest에서 받아들이지 않고 관측 가능한 invalid 후보로 분류한다.

**Acceptance criteria:**
- [ ] `0005A0`, `00088K`, 선행 0이 있는 식별자가 변형 없이 저장된다.
- [ ] 길이/형식 오류는 snapshot을 silent success로 만들지 않는다.
- [ ] ETF endpoint 실패가 기존 확정 유형을 `stock`으로 덮어쓰지 않는다.

**Verification:**
- [ ] `pytest -q tests/unit/test_parsers.py tests/unit/test_naver_universe_source.py tests/unit/test_universe_snapshot.py`
- [ ] parser fixture에 영숫자·잘린 legacy·중복 code 사례가 있다.

**Dependencies:** 없음
**Files likely touched:** `app/crawler/parsers/symbols.py`, `app/services/batch/sync_symbols.py`, `tests/unit/test_parsers.py`, `tests/unit/test_universe_snapshot.py`
**Estimated scope:** M

## Task T03: Legacy/stale universe audit dry-run CLI

**상태:** 구현 및 completed snapshot 기준 운영 DB dry-run 완료 · 운영자 승인 대기

**설명:** DB를 변경하지 않고 invalid legacy, prefix collision, stale active, latest snapshot 누락
후보를 JSON/CSV report로 생성한다. job 65 기준선과 후보 수를 재현 가능하게 만든다.

**Acceptance criteria:**
- [ ] CLI는 write 없이 후보별 원래 code, 후보 code, 증거, reason code를 출력한다.
- [ ] 6자리 계약 위반과 last completed snapshot 누락을 서로 다른 reason으로 집계한다.
- [ ] 출력에는 기준 snapshot/job ID와 생성 시각이 포함된다.

**Verification:**
- [ ] `pytest -q tests/unit/test_universe_audit.py`
- [ ] staging 복원 DB에서 CLI를 실행해 후보 수와 report schema를 확인한다.

**Dependencies:** T01, T02
**Files likely touched:** `app/services/universe_audit.py`, `scripts/audit_universe.py`, `tests/unit/test_universe_audit.py`
**Estimated scope:** S

**운영 증거 (2026-08-20):** completed Naver snapshot 14(4,299건)를 기준으로 읽기 전용
report를 생성했다. 후보는 206건이며 `invalid_legacy` 171건, `prefix_collision` 38건,
`missing_from_latest_snapshot`·`stale_active` 각 206건이다. 단일 대체 code가 확인된
legacy 후보는 38건이다. report는 `reports/universe_audit/universe_audit_20260820_024945.*`에
저장했으며, 이 단계에서는 DB를 변경하지 않았다.

## Task T04: 승인 기반 legacy correction/deactivation과 P0 재검증

**상태:** 구현·운영자 승인·반영 완료 · 다음 가격 배치 target/result 재검증 대기

**설명:** T03 report의 승인된 항목만 별도 audit record와 함께 비활성화 또는 mapping 후보로
표시한다. 가격·RS 이력은 삭제하지 않고 target-only 재실행 후 품질 report를 비교한다.

**Acceptance criteria:**
- [ ] 적용 명령은 승인 run ID 없이는 write하지 않는다.
- [ ] legacy 행의 원래 값, 결정, reason, 적용 시각이 영속화된다.
- [ ] active 형식 오류와 legacy Naver 가격 요청이 0건이며 P0 전후 quality report가 비교된다.

**Verification:**
- [ ] `pytest -q tests/unit/test_universe_audit.py tests/unit/test_universe_snapshot.py tests/unit/test_price_sync_results.py`
- [ ] staging DB에서 dry-run → approved apply → target-only replay를 수행한다.

**Dependencies:** T03
**Files likely touched:** `alembic/versions/<revision>_add_universe_audit_runs.py`, `app/models/universe_audit.py`, `app/repositories/universe_audit_repository.py`, `scripts/apply_universe_audit.py`, `tests/unit/test_universe_audit.py`
**Estimated scope:** M

**운영 증거 (2026-08-20):** audit run 1에서 snapshot 14 기준 206개 decision을 사용자 승인으로
적용했다. 적용 뒤 active universe는 4,299개, active 형식 오류는 0개, snapshot 14 밖 active는
0개다. 비활성화된 종목의 `daily_prices` 25,949행과 `rs_scores` 744행은 보존됐다. post-apply
dry-run report는 0개 후보를 반환했다.

## Checkpoint P0

- [x] T01~T04 focused tests와 `git diff --check`가 통과한다.
- [x] 최신 Naver snapshot은 `completed`이고 active 형식 오류는 0이다.
- [ ] price target count = prices 단계 `crawl_target_results` count를 확인한다.
- [x] 운영자가 P0 후보 적용을 승인하고 audit trail로 반영했다.

**다음 가격 배치 검증 명령:** `TELEGRAM_ENABLED=false NOTIFICATION_ENABLED=false .venv/bin/python scripts/verify_price_target_results.py`
(`target_count_matches_results: true`가 P0 마지막 count gate의 통과 조건이다.)

## P1 — KRX master shadow ingestion

## Task T05: KRX 외부 계약, secret, fixture 승인

**상태:** KOSPI/KOSDAQ membership API 선정 · 운영 호출/독립 대조 및 ETF/ETN 검증 대기

**설명:** 구현 전에 KRX 서비스 ID, 인증·호출 제한·라이선스·응답 필드를 확정하고 비밀값을
secret store에 등록한다. 실제 response를 민감정보 없이 fixture로 고정한다.

**Acceptance criteria:**
- [ ] KOSPI/KOSDAQ 주식·ETF·ETN의 source contract와 기준일 필드가 문서화된다.
- [ ] 인증키는 repository와 report에 노출되지 않는다.
- [ ] 정상/빈/오류/기준일 불일치 fixture가 승인된다.

**Verification:**
- [ ] 운영 계정으로 허용된 sample request를 실행하고 status/field contract를 기록한다.
- [ ] secret scanner와 fixture review에서 credential이 검출되지 않는다.

**Dependencies:** 없음 (외부 승인 필요)
**Files likely touched:** `docs/krx-universe-source-contract.md`, `tests/fixtures/krx/`, `.env.example`
**Estimated scope:** S
**Blocker:** `stk_bydd_trd`/`ksq_bydd_trd`의 서비스 활용 승인, 운영 응답 fixture, KRX 화면과의 count/code 대조

**기준 결정 (2026-08-20):** KRX 공식 설명이 “상장되어 있는 주권”의 매매정보라고 명시한
`stk_bydd_trd`와 `ksq_bydd_trd`를 주식 membership 기준으로 사용한다. `stk_isu_base_info`,
`ksq_isu_base_info`는 ISIN/상장일/명칭 보강용이다. membership 변경은 최근 마감 거래일 호출과
KRX 전종목 시세·KIND 상장종목현황의 count/code 대조 후에만 활성화한다. ETF/ETN은 동일 대조를
통과하기 전까지 shadow 관측으로 유지한다. Open API의 비상업적 이용조건도 운영 전 확인한다.
KOSPI/KOSDAQ 일별매매 응답 fixture도 확보했다. 코스닥 membership API ID는 `ksq_bydd_trd`다.

## Task T06: KRX snapshot과 membership 저장 기반

**상태:** 구현 완료 · migration 적용 및 schema/revision 정합성 확인 완료

**설명:** KRX 기준일 master를 재현 가능한 snapshot과 membership으로 저장하는 additive schema,
ORM, repository를 만든다. 아직 기존 `symbols`나 price target은 변경하지 않는다.

**Acceptance criteria:**
- [x] snapshot에는 provider, as-of date, 상태, 시장/유형별 count/hash, 오류가 저장된다.
- [x] membership은 snapshot별 instrument 식별과 listing/trading 상태를 재현한다.
- [x] completed snapshot만 current 후보로 조회되고 partial/failed는 승격되지 않는다.

**Verification:**
- [x] `pytest -q tests/unit/test_krx_universe_snapshot.py`
- [x] 기존 DB backup 이후 KRX schema/revision 정합성을 확인한다. (기존 테이블·index·constraint를 검증하고 Alembic revision `c9d0e1f2a3b4`로 stamp)

**Dependencies:** T05
**Files likely touched:** `alembic/versions/<revision>_add_krx_universe_snapshots.py`, `app/models/krx_universe_snapshot.py`, `app/models/krx_universe_membership.py`, `app/repositories/krx_universe_repository.py`, `tests/unit/test_krx_universe_snapshot.py`
**Estimated scope:** M

**구현 결과 (2026-08-20):** `krx_universe_snapshots`와 `krx_universe_memberships`는 기존
`symbols`, `daily_prices`, `rs_scores`를 수정하지 않는 additive schema다. migration revision은
`c9d0e1f2a3b4`이며, source 수집·batch 연결은 T07/T08에서 수행한다.

## Task T07: KRX universe source와 parser

**상태:** parser/source 구현 완료 · 운영 endpoint 및 서비스 승인 연결 확인 완료

**설명:** 승인된 KRX contract와 fixture를 사용해 시장·상품유형별 목록을 요청하고 typed result로
반환한다. 오류·빈 응답·기준일 불일치는 completed 결과가 될 수 없다.

**Acceptance criteria:**
- [x] KOSPI/KOSDAQ stock fetch 결과가 market/type/as-of metadata를 보존한다. (ETF/ETN은 shadow 확장 대기)
- [x] code/name/listing status의 필수값 검증이 있다. (ISIN은 T06 저장 시 기본정보와 보강)
- [x] transport/응답 schema 오류는 `complete=False` 결과로 분리된다.

**Verification:**
- [x] `pytest -q tests/unit/test_krx_universe_source.py tests/unit/test_krx_universe_parser.py`
- [x] T05 fixture를 replay한다.
- [x] `KRX_API_BASE_URL`과 `stk_bydd_trd`/`ksq_bydd_trd` 활용 승인을 확인한 실호출이 `complete=True`다. (2020-04-14, 2,329종목)

**Dependencies:** T05, T06
**Files likely touched:** `app/crawler/sources/krx.py`, `app/crawler/parsers/krx.py`, `app/crawler/sources/base.py`, `tests/unit/test_krx_universe_source.py`, `tests/unit/test_krx_universe_parser.py`
**Estimated scope:** M

**구현 결과 (2026-08-20):** source는 `AUTH_KEY` header와 `basDd`만 사용하며 인증키를 URL,
fixture, 오류 메시지에 남기지 않는다. KOSPI 또는 KOSDAQ 중 하나라도 오류·빈 응답·시장/기준일
불일치면 `complete=False`다. KRX 개발 명세서의 운영 base URL을 `KRX_API_BASE_URL`로 주입해야
실호출을 시작한다.

## Task T08: Daily batch KRX shadow ingestion

**상태:** 구현 완료 · 운영 migration 적용 및 첫 daily completed snapshot 관측 완료 · 5거래일 관측 대기

**설명:** Naver 가격/target 경로를 바꾸지 않은 채, daily batch에 KRX snapshot 생성과 complete
validation을 연결한다. 실패는 batch 관측으로 남기되 기존 active 상태는 건드리지 않는다.

**Acceptance criteria:**
- [x] KRX shadow 단계는 crawl job과 연결된 snapshot을 남긴다.
- [x] partial/failed KRX fetch는 기존 Naver active/price target을 변경하지 않는다.
- [x] shadow 단계 실패가 price 단계 실행 여부를 바꾸지 않는 정책이 테스트된다.

**Verification:**
- [x] `pytest -q tests/integration/test_batch_harness.py tests/unit/test_krx_universe_snapshot.py tests/unit/test_krx_universe_sync.py`
- [x] fake KRX source로 completed/partial 배치 경로를 재생한다.

**Dependencies:** T06, T07
**Files likely touched:** `app/services/batch/sync_krx_universe.py`, `app/services/batch/context.py`, `app/services/batch/orchestrator.py`, `tests/integration/test_batch_harness.py`, `tests/unit/test_krx_universe_sync.py`
**Estimated scope:** M

## Task T09: KRX/Naver shadow diff report와 metrics

**상태:** 구현 완료 · 첫 운영 reconciliation report 생성 완료 · 5거래일 관측 대기

**설명:** 최신 completed KRX snapshot과 Naver snapshot의 시장/유형별 count, exact code match,
unmatched, ambiguous, legacy candidate를 운영자가 조회할 수 있게 한다.

**Acceptance criteria:**
- [x] diff report에는 두 snapshot ID, as-of date, count, reason별 sample이 있다.
- [x] mapping rate 급감과 KRX snapshot partial은 metric/alert로 노출된다.
- [x] report 생성은 active, price target, mapping 데이터를 변경하지 않는다.

**Verification:**
- [x] `pytest -q tests/unit/test_universe_reconciliation_report.py tests/unit/test_crawl_metrics.py`
- [x] approved fixture로 exact/ambiguous/unmatched 결과를 확인한다.

**Dependencies:** T08
**Files likely touched:** `app/services/monitoring/universe_reconciliation.py`, `app/services/monitoring/crawl_metrics.py`, `scripts/report_universe_reconciliation.py`, `tests/unit/test_universe_reconciliation_report.py`
**Estimated scope:** M

**운영 증거 (2026-08-20):** job 69에서 KRX snapshot 2가 2026-08-19 기준으로
`completed`(2,763 주식)됐고 Naver snapshot 17과 exact mapping 2,763건,
mapping rate 100%를 기록했다. 범위 밖 ETF/ETN 1,534건과 범위 내 Naver-only 2건은
legacy 후보와 분리해 보고한다. reconciliation run 1은 운영자 검토 전
`pending_review` 상태다.

## Checkpoint P1

- [ ] T05~T09 focused tests와 migration smoke test가 통과한다.
- [ ] 최근 5거래일 KRX snapshot이 모두 completed다.
- [ ] 운영자가 market/type count, unmatched, ambiguous diff를 검토·승인했다.
- [ ] shadow ingestion이 기존 price target을 변경하지 않았음을 확인한다.

## P2 — canonical identity와 immutable target

## Task T10: Canonical instrument·provider symbol·exclusion schema

**상태:** 구현 및 운영 DB migration 적용 완료

**설명:** KRX instrument identity, 공급자 심볼, 정책 제외 사유를 additive schema로 도입하고
기존 `symbols`에 nullable instrument FK만 추가한다.

**Acceptance criteria:**
- [ ] instrument는 KRX code/ISIN와 market/type/listing 상태를 저장한다.
- [ ] provider symbol은 provider별 유효기간과 mapping 상태를 보존한다.
- [ ] 기존 `symbols`, `daily_prices`, `rs_scores` 조회와 FK가 깨지지 않는다.

**Verification:**
- [ ] `pytest -q tests/unit/test_instrument_repository.py`
- [ ] `alembic upgrade head`와 기존 API integration test를 실행한다.

**Dependencies:** T06
**Files likely touched:** `alembic/versions/<revision>_add_instruments.py`, `app/models/instrument.py`, `app/models/provider_symbol.py`, `app/models/universe_exclusion.py`, `tests/unit/test_instrument_repository.py`
**Estimated scope:** M

## Task T11: KRX↔Naver reconciliation과 legacy mapping 후보

**상태:** 구현 및 운영 DB migration 적용 완료

**설명:** exact code → ISIN → 시장/유형/정규화 name 순으로 후보를 만들되, 이름 단독 매칭은
자동 반영하지 않는다. 결과는 approval 가능한 reconciliation run으로 저장한다.

**Acceptance criteria:**
- [ ] exact, matched, unmatched, ambiguous, invalid_legacy 상태가 구분된다.
- [ ] strict prefix legacy 후보는 evidence와 함께 제안만 하고 자동 적용하지 않는다.
- [ ] reconciliation은 idempotent하며 동일 snapshot 조합을 재실행해도 결과가 일관된다.

**Verification:**
- [ ] `pytest -q tests/unit/test_universe_reconciliation.py`
- [ ] code 충돌·이름 중복·ISIN match fixture를 확인한다.

**Dependencies:** T09, T10
**Files likely touched:** `app/services/universe_reconciliation.py`, `app/repositories/provider_symbol_repository.py`, `app/repositories/universe_reconciliation_repository.py`, `tests/unit/test_universe_reconciliation.py`
**Estimated scope:** M

## Task T12: Immutable price/RS target builder와 lineage

**상태:** target builder/lineage 및 Naver 가격 batch 연결 완료 · completed snapshot 쌍의 shadow 관측/승인 대기

**설명:** 마지막 completed KRX member, matched Naver symbol, listing/eligibility 정책으로 price
target을 한 번 생성한다. RS target은 stock과 history/freshness 규칙을 추가로 적용한다.

**Acceptance criteria:**
- [ ] partial/failed KRX snapshot은 last completed target set을 유지한다.
- [ ] `expected_no_trade`, `excluded`, `review_required`는 분모와 이유가 재현된다.
- [ ] `crawl_target_results`에서 job의 target snapshot, instrument, eligibility를 추적한다.

**Verification:**
- [ ] `pytest -q tests/unit/test_universe_target_builder.py tests/unit/test_price_sync_results.py tests/integration/test_batch_harness.py`
- [ ] 기존 `list_price_targets()`와 shadow 결과의 차이를 report로 확인한다.

**Dependencies:** T10, T11
**Files likely touched:** `app/services/universe_target_builder.py`, `app/services/batch/sync_prices.py`, `app/repositories/symbol_repository.py`, `app/models/crawl_target_result.py`, `tests/unit/test_universe_target_builder.py`
**Estimated scope:** M

## Task T13: Universe/reconciliation/eligibility 운영 조회

**상태:** 읽기 전용 API 및 운영 DB migration 적용 완료

**설명:** 운영자가 KRX/Naver snapshot, mapping 상태, exclusion reason, job target lineage를
읽기 전용 API와 일일 report에서 확인할 수 있게 한다.

**Acceptance criteria:**
- [ ] API는 pagination과 snapshot/job filter를 제공하며 민감한 source credential을 노출하지 않는다.
- [ ] report는 eligible과 excluded/expected-no-trade를 분리해 coverage를 계산한다.
- [ ] 기존 `/api/v1/crawl/universe-snapshots` 응답은 호환성을 유지한다.

**Verification:**
- [ ] `pytest -q tests/integration/api/test_crawl_api.py tests/unit/test_universe_operations_api.py`
- [ ] authorized/unauthorized 요청과 빈 결과를 확인한다.

**Dependencies:** T11, T12
**Files likely touched:** `app/api/v1/endpoints/crawl.py`, `app/schemas/universe.py`, `app/services/monitoring/crawl_metrics.py`, `tests/unit/test_universe_operations_api.py`, `tests/integration/api/test_crawl_api.py`
**Estimated scope:** M

## Checkpoint P2

- [ ] T10~T13 focused tests, migration smoke test, 기존 API integration tests가 통과한다.
- [ ] target-builder shadow 차이와 legacy mapping 후보가 운영자에게 승인됐다.
- [ ] legacy 코드의 Naver 가격 요청이 0건이며 job별 target lineage를 재현할 수 있다.

## P3 — canary와 운영 전환

## Task T14: Authority feature flag, 시장 canary, fallback

**상태:** authority/canary/fallback 정책 및 Naver 가격 batch 연결 완료 · reconciliation 승인 및 5거래일 운영 canary 대기

**설명:** KRX authoritative target builder를 market별로 제한 활성화하고, 실패 조건에서
`naver_last_completed`로 되돌리는 feature flag와 alert를 만든다.

**Acceptance criteria:**
- [ ] `UNIVERSE_AUTHORITY`와 canary market 설정은 안전한 기본값을 가진다.
- [ ] KRX partial/outage/mapping 급감에서 target set 변경과 자동 비활성화가 차단된다.
- [ ] canary 적용 market과 fallback 사유가 batch/job metadata에 남는다.

**Verification:**
- [ ] `pytest -q tests/unit/test_universe_authority_flag.py tests/integration/test_batch_harness.py`
- [ ] fake completed/partial/outage source로 KOSPI와 KOSDAQ canary를 재생한다.

**Dependencies:** T12, T13
**Files likely touched:** `app/core/config.py`, `app/services/universe_target_builder.py`, `app/services/batch/orchestrator.py`, `tests/unit/test_universe_authority_flag.py`, `tests/integration/test_batch_harness.py`
**Estimated scope:** M

## Task T15: 5거래일 운영 검증과 전환 결정

**상태:** runbook 준비 완료 · 5거래일 운영 관측 및 운영자 승인 대기

**설명:** canary 2거래일 후 전체 대상에 대해 5거래일 동안 snapshot 상태, mapping rate,
coverage, exclusion reason, rollback 여부를 검토하고 전환 또는 롤백 결정을 기록한다.

**Acceptance criteria:**
- [ ] 5거래일의 daily 운영 report와 decision log가 보존된다.
- [ ] KRX completed 100%, price-eligible mapping rate 99.5% 이상, legacy request 0건을 확인한다.
- [ ] 기준 미달 시 rollback 실행·원인·후속 작업이 기록된다.

**Verification:**
- [ ] 운영 runbook을 staging에서 한 번 연습한다.
- [ ] `git diff --check` 및 전체 quality gate를 실행한다.

**Dependencies:** T14
**Files likely touched:** `docs/runbook-krx-universe-canary.md`, `scripts/report_universe_reconciliation.py`, `reports/krx_universe/`
**Estimated scope:** S

## Checkpoint Complete

- [ ] T14~T15와 전체 quality gate가 통과한다.
- [ ] PRD 14절 수용 기준을 검토해 모두 충족했음을 decision log에 남긴다.
- [ ] 운영자가 KRX authority 전체 전환 또는 명시적 rollback을 승인한다.
