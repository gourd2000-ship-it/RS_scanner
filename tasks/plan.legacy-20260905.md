> 보관 문서 (2026-09-05 개정 전). 아래 내용은 구현/운영 이력이며 현재 실행 지시가 아닙니다.
> 현재 우선순위와 요구사항은 [개정 문서](plan.md)를 따릅니다. 원문의 체크 상태와 증거를 보존했습니다.

# Implementation Plan: KRX 기준 유니버스 전환

## Overview

이 계획은 [KRX 기준 유니버스 PRD](../docs/prd-krx-universe-authority.md)를 15개의
검증 가능한 작업으로 분해한다. P0에서 현재의 잘린 코드와 불완전 Naver snapshot 문제를
안전하게 복구한 뒤, P1에서 KRX 기준 데이터를 shadow mode로 수집한다. P2에서 canonical
identity와 target builder를 전환하고, P3에서 canary와 5거래일 관측을 거쳐 운영 전환한다.

작업의 상세 acceptance criteria와 검증 명령은 [tasks/todo.md](todo.md)를 단일 작업
목록으로 사용한다. 이 문서는 설계 결정과 작업 순서만 관리한다.

## Architecture Decisions

- KRX는 `instrument`의 기준 원장이고, Naver는 가격 공급자 및 provider symbol mapping
  검증 공급자다. 한 공급자의 code를 canonical identity로 재사용하지 않는다.
- 모든 신규 schema migration은 additive다. 기존 `symbols`, `daily_prices`, `rs_scores`의
  FK와 가격 이력은 P2에서 삭제·in-place code 변경하지 않는다.
- 가격 target은 현재 active 집합이 아니라 마지막 `completed` authoritative snapshot에서
  한 번 생성한 immutable set이다. partial/failed snapshot은 기존 completed set을 바꾸지 않는다.
- legacy correction과 deactivation은 dry-run → 승인 → 적용의 세 단계다. 자동 `DELETE`는 없다.
- P1의 KRX 작업은 shadow write만 한다. target selection은 P3 canary 전까지 기존 경로를
  유지한다.
- 성공률은 `price_eligibility=eligible`만 분모에 넣고, 거래정지·미매핑·정책 제외는 별도
  reason code로 보고한다.

## Dependency Graph

```text
T01 Naver 페이지 완료 ──> T03 legacy/stale audit ──> T04 승인 반영
T02 code contract ─────────┘

T05 KRX 계약/fixture ──> T06 KRX snapshot schema ──> T07 KRX source/parser
                                                     └─> T08 shadow batch ──> T09 diff observability

T06 ──> T10 canonical identity schema ──> T11 reconciliation ──> T12 target builder ──> T14 canary
T09 ────────────────────────────────────────┘                            │
T13 operations API/report ───────────────────────────────────────────────┤
                                                                            └─> T15 operating decision
```

## Task List

### Phase P0 — 안전한 Naver 복구

- [x] T01: Naver universe pagination 완료 조건과 상한 경보를 설정한다.
- [x] T02: provider code 계약과 parser 회귀 테스트를 고정한다.
- [x] T03: legacy/stale 후보를 읽기 전용으로 산출하는 audit CLI를 만든다.
- [x] T04: 승인된 legacy correction/deactivation을 audit trail과 함께 적용하고 재검증한다. (운영 적용 대기)

### Checkpoint P0

- [ ] 최신 Naver snapshot이 `completed`다.
- [ ] active 형식 오류 코드와 legacy 가격 요청이 0건이다.
- [ ] price target count와 `crawl_target_results` count가 일치한다.

### Phase P1 — KRX shadow master

- [ ] T05: KRX 외부 계약·secret·fixture를 승인한다. (공개 계약 문서화 완료 · 운영 승인 대기)
- [ ] T06: KRX snapshot과 membership 저장 구조를 추가한다.
- [ ] T07: KRX universe source/parser를 구현한다.
- [ ] T08: daily batch에 shadow KRX ingestion을 연결한다.
- [ ] T09: KRX/Naver count·mapping diff를 리포트와 metrics로 노출한다.

### Checkpoint P1

- [ ] 최근 5거래일 KRX snapshot이 모두 `completed`다.
- [ ] 시장/유형별 count 차이와 미매핑 항목이 운영자에게 설명·승인됐다.
- [ ] shadow mode가 기존 active/price target을 변경하지 않는다.

### Phase P2 — canonical identity와 대상 확정

- [ ] T10: instrument/provider symbol/exclusion의 additive schema를 추가한다.
- [ ] T11: KRX↔Naver reconciliation과 legacy mapping 후보를 생성한다.
- [ ] T12: immutable price/RS target builder와 lineage를 연결한다.
- [ ] T13: universe/reconciliation/eligibility 운영 조회를 제공한다.

### Checkpoint P2

- [ ] target builder shadow 결과가 승인됐다.
- [ ] legacy code의 Naver 가격 요청은 0건이다.
- [ ] 대상 snapshot, instrument, eligibility reason을 job별로 재현할 수 있다.

### Phase P3 — canary와 운영 전환

- [ ] T14: authority feature flag, 시장별 canary, fallback을 구현한다.
- [ ] T15: 5거래일 운영 검증과 전체 전환/롤백 결정을 기록한다.

### Checkpoint Complete

- [ ] KRX authority snapshot이 5거래일 연속 `completed`다.
- [ ] mapping rate가 price-eligible 기준 99.5% 이상이다.
- [ ] partial/outage/mapping 급감에서 자동 비활성화 없이 fallback과 alert가 동작한다.
- [ ] PRD의 수용 기준과 quality gate가 모두 통과했다.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| KRX 인증·서비스 승인이 지연됨 | High | T05를 즉시 시작하고, P0만 먼저 release한다. |
| KRX와 Naver 심볼이 다름 | High | ISIN 우선, 이름 단독 매칭 금지, `ambiguous`는 수동 승인한다. |
| partial snapshot을 active 변경에 사용 | High | completed snapshot만 승격하고 last-completed fallback을 테스트한다. |
| legacy 연결이 가격 이력을 훼손 | High | additive FK, audit trail, DELETE 금지, staging restore 검증을 사용한다. |
| 거래정지 정책이 불명확 | Medium | P2 전 product decision을 받고 `review_required`가 기본값이다. |
| ETF/ETN 범위가 바뀜 | Medium | price와 RS eligibility를 분리하고 feature flag로 설정한다. |

## Open Questions

- KRX에서 사용할 정확한 종목기본정보/ETF/ETN 서비스 ID와 response field는 무엇인가?
- KRX API 대신 계약된 일일 export가 사용될 경우 delivery time과 schema version은 무엇인가?
- `expected_no_trade`의 사유와 재확인 주기는 누가 승인하는가?
- P0의 legacy correction 적용 권한자는 누구이며, 승인 기록은 어느 운영 계정으로 남길 것인가?

---

# Implementation Plan: 역사적 시점 유니버스와 생존편향 없는 백테스트

## Overview

현재의 KRX snapshot·canonical instrument 기반을 확장해, 과거 특정 거래일에 실제로
상장·거래 가능했던 종목 집합을 재현한다. 가격을 대량으로 먼저 채우지 않고, 역사적
유니버스와 source provenance를 먼저 확정한다. 이 순서는 현재 상장 종목만으로 과거를
백필하는 생존편향과, 현재 상태를 과거에 소급하는 look-ahead bias를 막는다.

## Architecture Decisions

- `instruments`를 안정적인 식별자로 유지하고, provider code는 유효기간을 가진
  `provider_symbols`로만 연결한다. 재사용된 종목코드를 동일 instrument로 합치지 않는다.
- 상장, 상폐, 시장 이전, 거래정지, 재상장 이벤트와 기준일 membership을 additive schema로
  보관한다. 현재 `symbols.is_active`는 역사적 백테스트의 입력으로 사용하지 않는다.
- 근거가 있는 상태는 `observed`, 가격의 최초/최종 거래일 등으로만 유추한 상태는
  `inferred`, 근거가 없으면 `unknown`으로 구분한다. strict backtest는 `unknown`을 제외한다.
- 키움은 가격 보강·교차검증 공급자로 사용하되, 일봉 TR 계약·연속조회·조정주가·호출 제한을
  canary에서 검증하기 전에는 전종목 bulk source로 승격하지 않는다.
- 원본 응답의 checksum, source, 수집 시각, validation 결과를 보존한다. 충돌 가격은
  자동 덮어쓰기 대신 검토 가능한 observation/case로 남긴다.

## Dependency Graph

```text
HB01 범위·공급자 계약 ──> HB02 lifecycle schema ──> HB03 KRX/KIND event ingest
                                                     └─> HB04 point-in-time membership
HB01 키움 canary ───────────────────────────────────> HB05 historical OHLC backfill
HB03 + HB04 + HB05 ──> HB06 validation/coverage ──> HB07 strict backtest dataset
                                                        └─> HB08 replay/canary sign-off
```

## Task List

### Phase HB0 — 범위와 계약을 먼저 고정

- [ ] HB01: 목표 기간, 종목 범위(KOSPI/KOSDAQ·보통주·상폐 종목 포함 여부), 조정주가·상폐수익
  처리 규칙을 승인하고 KRX/KIND·키움 source contract를 sample fixture로 고정한다.

### Phase HB1 — 역사적 유니버스 기반

- [ ] HB02: listing lifecycle event·근거·신뢰도와 point-in-time membership interval을 위한
  additive schema와 repository를 추가한다.
- [ ] HB03: KRX Data Marketplace/KIND에서 상장·상폐·시장 이전 원문을 ingest하고 current
  instrument와 코드 재사용을 reconciliation한다.
- [ ] HB04: 이벤트에서 거래일별 membership을 materialize하고 `observed`/`inferred`/`unknown`
  coverage report를 만든다.

### Checkpoint HB1

- [ ] 표본 상장·상폐·재상장 종목의 유니버스 포함 구간이 원문 근거와 일치한다.
- [ ] `unknown` 상태를 현재 `is_active`로 대체하는 경로가 없다.

### Phase HB2 — 가격과 품질 보강

- [ ] HB05: 키움 일봉 contract canary 후, 날짜 범위가 제한된 historical OHLC backfill을
  checkpoint·재개·source lineage와 함께 구현한다.
- [ ] HB06: 가격 누락·정지·OHLC 이상치·기업행위·공급자 충돌을 validation case와 exclusion
  policy로 마킹하고 coverage를 산출한다.

### Phase HB3 — 재현 가능한 백테스트

- [ ] HB07: backtest dataset API를 membership·가격·RS input lineage에 연결하고 strict/observed
  coverage 정책과 dataset version을 노출한다.
- [ ] HB08: 알려진 상폐 종목과 시장 이전 종목으로 historical replay를 수행하고, 기존
  survivor-only 결과와의 차이를 승인한다.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| 상폐 종목 code 재사용 | ISIN/법인 정보와 유효기간을 기준으로 reconcile하고 자동 병합 금지 |
| 키움의 TR·수정주가·history depth 불일치 | 5~10종목 canary와 공식 contract fixture를 통과한 뒤 범위 확대 |
| 원문 부재 구간을 현재 상태로 채움 | `unknown`을 유지하고 strict backtest에서 제외 |
| 대량 backfill 중 source throttle·부분 실패 | checkpoint, request budget, 재개 cursor, 실패 목록, chunk별 commit |
| 상폐 수익을 마지막 가격으로 단순화 | 상폐 사유별 return policy를 명시하고 기본값을 보고서에 포함 |

## Open Questions

- 최초 지원 백테스트 시작일은 언제인가? (예: 2000-01-01 또는 2010-01-01)
- 상폐·합병·현금청산 수익은 어떤 경제적 가정으로 계산할 것인가?
- KRX 원문을 직접 수집할지, 라이선스가 있는 상용 historical master를 사용할지 결정됐는가?

---

# Implementation Plan: Batch Determinism and Canary Gate Corrections

## Overview

리뷰에서 확인한 세 가지 필수 품질 문제를 수정한다. 배치 테스트가 현재 날짜에 의존하지
않도록 실행 기준일을 주입하고, 오케스트레이터가 한 작업 안에서 기준일을 재계산하지
않도록 고정한다. 또한 KRX canary 확장은 현재 결정일 이전의 continue 결정만 근거로
허용한다.

## Architecture Decisions

- 프로덕션 기본 동작은 현행 Seoul 기준 거래일을 유지하되, 호출자가 명시한 기준일은
  덮어쓰지 않는다.
- `BatchOrchestrator`는 시작 시 결정한 하나의 거래일을 모든 단계의 컨텍스트에 전달한다.
- canary 확장 게이트는 immutable decision의 `trade_date`를 기준으로 과거 결정만 센다.

## Task List

### Phase 1 — 결정적 배치 실행

- [x] R01: legacy batch runner가 주입된 거래일을 보존하도록 하고 주말에도 fixture 기반
  전체 흐름을 재현하는 회귀 테스트를 추가한다.
- [x] R02: orchestrator가 시작 거래일을 고정해 KRX/가격 단계에 전달하는 자정 경계
  회귀 테스트를 추가한다.

### Checkpoint: Batch determinism

- [x] 새 단위 테스트와 기존 E2E·통합 테스트가 고정 거래일에서 통과한다.

### Phase 2 — Canary 확장 게이트

- [x] R03: 미래 continue 결정이 과거 expand를 승인하지 못하는 회귀 테스트를 추가하고
  쿼리를 현재 snapshot 날짜 이전으로 제한한다.

### Checkpoint: Complete

- [x] 전체 pytest 및 compileall이 통과한다.
- [x] `git diff --check`가 통과한다.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| 테스트 전용 날짜가 운영 기본 동작을 바꿈 | 명시적으로 주입된 값만 보존하고, 기본값은 기존 calendar 함수로 유지한다. |
| 단계별 날짜 전달이 validation/RS lineage를 깨뜨림 | 가격·KRX 단계에만 고정 기준일을 전달하고 focused batch tests로 검증한다. |
| 늦게 기록한 과거 운영 결정이 확장 게이트를 우회 | 현재 snapshot 날짜보다 이른 continue만 SQL에서 집계한다. |
