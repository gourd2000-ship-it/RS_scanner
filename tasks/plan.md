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
