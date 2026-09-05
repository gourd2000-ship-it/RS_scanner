# Implementation Plan: 백테스트 데이터 구축 우선

개정일: 2026-09-05<br>
요구사항: [PRD](../docs/prd-krx-universe-authority.md)<br>
단계/게이트: [로드맵](../docs/roadmap_krx_universe.md)<br>
완료 기준·예상 파일·검증: [TODO](todo.md)

## 계획 원칙

계획 수립에는 planning-and-task-breakdown 스킬을 적용했다.
핵심 순서는 역사 명부 → 기간 OHLC 수집 → 결측/이상치 검증 → 역사 RS/불변 dataset이다.
최신 유니버스의 대규모 운영 전환을 먼저 끝내야 한다는 이전 순서를 폐기한다.
각 작업은 fixture 또는 작은 표본으로 확인할 수 있는 결과를 남긴다.

이 문서는 설계와 의존성의 기준이고 TODO가 유일한 실행 체크리스트다.
문서 개정 자체는 크롤러 실행·대량 upsert·schema 변경을 수행하지 않는다.
사용자의 기존 지시에 따라 전체 적재는 실측 시간과 범위가 확정된 BT12 실행안 승인 후 수행한다.

## 기존 구현의 재사용과 빈틈

- KiwoomRestClient와 ka10081 인증/일봉 1페이지 조회를 완료 기반으로 사용한다.
  새 인증 서버·Sam 중계·repair queue는 필요하지 않다.
- Instrument/ProviderSymbol, KRX snapshot, 기존 observation 및 validation case를 재사용한다.
  단, 현재 코드 전역 unique와 symbol FK의 역사적 코드 재사용 문제는 BT02에서 검증한다.
- 현 validator의 양수/유한성/OHLC 범위/거래량 검사를 재사용하고, 날짜 구간의 기대 관측과
  당시 제도/기업행위 판단만 보강한다.
- v2 API 골격을 확장한다. 현재 가격 중심 조회는 가격 없는 종목을 누락할 수 있고,
  현재 시장 필터는 시장 이전을 반영하지 못하며 max-ID watermark는 in-place 갱신을 고정하지 못한다.

## 설계 결정

1. 최초 범위는 KOSPI/KOSDAQ 보통주와 해당 기간의 상폐 종목이다. 기타 유형은
   분류와 제외 사유를 보존한다. 기간 상한을 코드로 제한하지 않으며 최초 bulk 범위는 BT12에서 고정한다.
2. 상장 구간 [from,to), 거래 상태, 공급자 code 구간을 구분한다.
   historical_reconstructed와 as_known_at의 정보 시점 보장도 구분한다.
3. 기대 대상은 가격 존재 여부나 현재 is_active로 정하지 않는다.
   unknown/공급자 미지원 종목도 명부·coverage·품질 보고서에서 추적한다.
4. 원본 관측을 보존하고 검증된 가격만 명시된 갱신 정책으로 upsert한다.
   재현성은 선택 관측/revision을 고정하는 manifest로 확보한다.
5. 날짜 D의 RS는 D 당시 적격 집합과 D까지의 가격을 사용한다.
   시작일 이전 준비 기간과 종가 RS의 이용 가능 시각을 공개한다.
6. 1차 운영 도구는 앱 내부 CLI와 기존 API다. 일일 자동화·운영 화면 확장은 후순위다.

## 의존성

```text
BT00 완료: 키움 인증 + 일봉 1페이지
  → BT01 공급 범위 표본
  → BT02 역사 identity → BT03 이력 import → CP1
  → BT04 시점 유니버스 → BT05 기간 수집 → BT06A 실행 저장 → CP2a
  → BT06B upsert/resume
      ├→ BT07 결측
      └→ BT08 이상치 → CP3
  → BT09 불변 dataset → BT10 역사 RS → BT11 기간 API → CP4
  → BT12 실측 실행안·사용자 승인 → BT13 적재/replay → CP5
  → BT14 최신 이력 증분 유지 (후순위)
```

BT07과 BT08의 규칙 작업은 동일 계약이 고정된 뒤 독립적으로 진행할 수 있다.
이 계획은 서브에이전트 실행을 요구하지 않는다.
CP2b에서 BT06B의 중단/재개 결과를 검증한 뒤 품질 단계로 진행한다.
CP1~CP4는 테스트/표본 검증이며 별도의 반복 승인 절차가 아니다.

## 체크포인트

| 게이트 | 확인할 결과 |
|---|---|
| CP1 (BT01~03) | 상폐 표본 포함, source coverage 미확인 구간 명시, 코드 재사용/이력 정정 보존 |
| CP2a (BT04~06A) | 현재 active 독립 대상, 고정 기준일, 요청/메모리 제한, 재개 상태 저장 |
| CP2b (BT06B) | 격리 DB에서 반복 upsert와 강제 중단 후 재개 결과 동일 |
| CP3 (BT07~08) | 기대 행 0건 누락 금지, 정지/결측/이상치 구분, 정책 replay 동일 |
| CP4 (BT09~11) | canonical 갱신 후 과거 dataset 전 페이지/RS 불변, 과거 시장 및 scope 계약 |
| CP5 (BT12~13) | 승인 범위 준수, coverage와 survivor-only 집합 차이, 최종 replay 보고 |

## 검증과 실행 예산

TODO의 신규 테스트 경로는 구현 시 만들 예정인 파일이다. 현재 존재하거나 통과한 것으로 간주하지 않는다.
구현마다 해당 focused pytest와 git diff --check를 수행하고, DB 테스트는 운영 DB와 분리한다.
API 연결 완료 때 관련 통합/회귀 테스트와 compileall을 실행한다.

BT01의 소량 read-only 표본과 BT12 dry-run에서 호출 지연/페이지 행 수/저장량을 측정한다.
전체 예상 시간은 수집뿐 아니라 검증·RS·snapshot 생성까지 포함한다.
한도 초과·디스크 부족 시 중단 조건과 재개 지점을 실행안에 적는다.
긴 수집의 승인은 준비 작업이 끝난 BT12의 마지막 단계다.

## 위험과 대응

| 위험 | 대응 |
|---|---|
| 키움에서 상폐/장기 이력 미지원 | BT01에서 조기 발견, 허용된 역사 공급자/import 경로와 미확보 coverage 기록 |
| 역사 명부 자체 누락 | 가격 coverage와 명부 완전성 분리. partial을 생존편향 제거 완료로 표현 금지 |
| 코드 재사용으로 가격 혼합 | 기간별 identity fixture, FK/unique migration 검증 |
| 수정주가 기준 또는 미래 정보 혼합 | base_dt·adjustment/published_at 정책 버전 고정, reconstructed/as-known 구분 |
| upsert/이력 정정으로 과거 dataset 변화 | append-only 관측/revision 참조 및 canonical 갱신 회귀 테스트 |
| 상폐 손익 자료 부재 | terminal_value_unknown과 소비자 정책 명시, 0 수익/무기한 가격 연장 금지 |
| 계획 재복잡화 | CLI→기존 validator→기존 API의 경로 우선. 신규 운영 계층은 P0 이후 |

## 기존 작업의 처리

T01~T04 심볼 복구/audit, T06~T13의 구현된 기반, R01~R03 결정성 수정은 재사용한다.
종전 체크 상태가 구현 완료/운영 미검증을 섞고 있으므로 이 기록을 새로운 작업의 완료로 복사하지 않는다.
T14~T15 authority canary와 운영 확대는 후순위다.
HB01~HB08은 BT01~BT13으로 대체하며 별도 진행하지 않는다.

원문 상태/증거는 [개정 전 계획](plan.legacy-20260905.md)과
[개정 전 TODO](todo.legacy-20260905.md)에 보존한다.
미확정인 최초 적재 기간, 역사 공급자 지원 범위, 상폐 청산 데이터 coverage는 BT01/BT12의
산출물로 해소한다. 단순 계획 작성을 위해 추가 사용자 응답을 기다리지 않는다.
