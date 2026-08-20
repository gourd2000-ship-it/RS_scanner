# KRX 기준 유니버스 실행 로드맵

상태: P0 반영 완료 · P1~P2 구현 및 운영 migration 적용 완료 · P1 첫 daily shadow completed 관측 완료 · P3 Naver 가격 경로의 시장별 canary 연결/runbook 준비 완료, 5거래일 운영 관측 및 승인 대기<br>
작성일: 2026-08-20<br>
기준 PRD: [KRX 기준 유니버스와 가격 대상 정합성 복구](prd-krx-universe-authority.md)<br>
상세 작업 목록: [tasks/todo.md](../tasks/todo.md)<br>
구현 설계·의존성: [tasks/plan.md](../tasks/plan.md)

## 1. 목표

Naver 가격 수집은 유지하되 KRX를 종목 정체성과 상장 상태의 기준 원장으로 삼는다.
각 가격 배치는 마지막 `completed` 기준 snapshot에서 만들어진 불변 target set을 사용해야
하며, legacy 코드·거래정지·공급자 미매핑은 성공률과 별도의 사유로 집계한다.

## 2. 실행 순서

```text
P0 Naver 복구
  T01 페이지 완료 보장 ──> T02 식별자 검증 ──> T03 audit dry-run
                                                └─> T04 승인 반영/재검증

P1 KRX shadow
  T05 외부 계약 확정 ──> T06 snapshot 저장소 ──> T07 KRX source
                                                └─> T08 daily shadow 실행 ──> T09 차이 관측

P2 canonical/eligibility
  T10 identity schema ──> T11 reconciliation ──> T12 immutable target builder ──> T13 운영 API

P3 canary
  T14 feature flag/canary ──> T15 5거래일 운영 검증 및 전환 결정
```

T05는 KRX 인증키·서비스 승인·사용 조건이라는 외부 선행조건이므로, 실제 source 호출과
batch 연결(T07~T08)은 승인된 서비스의 무비밀 fixture를 확보한 뒤 진행한다. T06의 additive
저장소는 기존 Naver target 경로와 분리되어 있어 먼저 구현할 수 있다.

## 3. Phase별 결과와 게이트

| Phase | 작업 | 산출물 | 다음 단계 게이트 |
|---|---|---|---|
| P0 | T01~T04 | completed snapshot·승인 반영 완료 · 다음 가격 배치 재검증 대기 | active 형식 오류 0, target/result 수 일치 |
| P1 | T05~T09 | KRX snapshot, membership, fixture, shadow diff report | completed snapshot 5거래일, 차이 설명·승인 가능 |
| P2 | T10~T13 | canonical identity, provider mapping, target lineage, 운영 조회 API | legacy 요청 0, target builder shadow 결과 승인 |
| P3 | T14~T15 | canary 설정, daily dashboard, rollback runbook, 전환 결정 | KRX authority 5거래일 안정·매핑률 99.5% 이상 |

각 phase 게이트를 통과하기 전에는 다음 phase의 쓰기 경로를 production에서 활성화하지
않는다. 특히 P1은 shadow write만 허용하고, P2 전까지 기존 가격 target을 변경하지 않는다.

## 4. 핵심 운영 지표

| 지표 | P0 기준 | P3 목표 | 경보/조치 |
|---|---:|---:|---|
| active 형식 오류 코드 | 171 | 0 | 즉시 target 제외 후보 보고 |
| latest snapshot 밖 active | 265 | 0 (승인 예외 제외) | reconcile 차단 및 검토 |
| KRX snapshot completed 비율 | 미측정 | 최근 5거래일 100% | last completed fallback |
| KRX↔Naver price 매핑률 | 미측정 | 99.5% 이상 | mapping 급감 alert |
| 원인 불명 Naver 빈 응답 | 171 legacy 포함 | 기준선 대비 80% 이상 감소 | legacy/policy 재분석 |
| price eligible coverage | 91.581% | 95% 이상 관측 | reason별 quality case 생성 |

## 5. 롤백 원칙

- 롤백 대상은 feature flag와 target-builder 선택뿐이다.
- KRX snapshot, mapping, audit 기록과 기존 가격/RS 이력은 삭제하지 않는다.
- KRX snapshot이 partial/failed이거나 mapping rate가 급감하면
  `naver_last_completed` target set으로 돌아간다.
- 자동 비활성화와 KRX canary 선택은 `completed` KRX snapshot과 승인된 reconciliation run이 있을 때만 허용한다.

## 6. 구현 전 결정 필요 사항

1. KRX Open API의 정확한 서비스 ID, 인증키 발급, 호출 한도, 재배포 조건을 운영 계정으로 확인한다.
2. ETF/ETN을 기본 price target에 계속 포함할지, 별도 feature flag로 분리할지 결정한다.
3. 거래정지·신규상장·상장폐지 진행 종목을 `expected_no_trade`로 처리하는 정책을 승인한다.
4. KRX 기준일이 Naver 가격 기준일보다 늦게 도착할 때의 허용 지연과 fallback 기간을 결정한다.
