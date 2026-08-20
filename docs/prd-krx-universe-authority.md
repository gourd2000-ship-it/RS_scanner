# PRD: KRX 기준 유니버스와 가격 대상 정합성 복구

문서 상태: Draft<br>
작성일: 2026-08-19<br>
대상 시스템: RS Scanner<br>
선행 문서: [크롤링 신뢰성 개선 PRD](prd-crawling-reliability-hermes.md), [데이터 품질 검증 PRD](prd-data-quality-pipeline.md)

## 1. 결론과 우선순위

현재 가격 크롤링 성공률 저하의 첫 번째 원인은 가격 공급자 자체보다 **가격 대상
유니버스가 완전하고 식별 가능한 최신 스냅샷으로 확정되지 않는 것**이다. 이 PRD는
KRX를 상장 종목의 기준 원장(authoritative master)으로 도입하고, Naver는 가격
공급자와 심볼 매핑 검증 공급자로 유지한다.

구현은 아래 우선순위를 따른다.

| 우선순위 | 단계 | 목적 | 배포 판단 |
|---|---|---|---|
| P0 | 유니버스 긴급 복구 | 잘린 코드·40페이지 상한으로 생긴 잘못된 대상을 제거 가능한 상태로 만든다 | KRX 없이도 즉시 시행 |
| P1 | KRX master 동기화 | 상장·상장폐지·시장·상품유형의 기준 데이터를 확보한다 | KRX 인증키·fixture 승인 후 |
| P2 | 적격성/심볼 매핑 분리 | 상장 여부, 당일 가격 대상, RS 대상 및 Naver 식별자를 분리한다 | P1 canary 통과 후 |
| P3 | 운영 전환 | KRX snapshot을 daily 기준으로 전환하고 지표·롤백을 운영한다 | 5거래일 shadow 비교 통과 후 |

이 PRD는 Kiwoom 전종목 수집, 가격 공급자 교체, RS 산식 변경을 포함하지 않는다.

## 2. 배경 및 확인된 기준선

2026-08-19의 최신 품질 리포트(job 65)와 DB를 기준으로 확인한 사실은 다음과 같다.

| 항목 | 관측값 | 의미 |
|---|---:|---|
| 가격 크롤링 대상 | 4,086 | `is_active=True`인 주식·ETF·ETN 전체 |
| 성공 또는 신규 데이터 없음 | 3,742 | 현 success-rate 분자 |
| 실패 | 344 | 현 coverage 91.581%의 직접 원인 |
| 최신 Naver snapshot 관측 종목 | 3,821 | 가격 대상보다 265개 적음 |
| 최근 snapshot 상태 | 모두 `partial` | KOSPI가 `max_symbol_pages=40`에 도달 |
| 형식이 깨진 active 코드 | 171 | 과거 숫자 전용 parser가 영숫자 코드를 잘라 저장 |
| 깨진 코드의 job 65 실패 | 171 | 모두 `fchart response has no data rows` |
| 최신 snapshot에 있는 유효 코드의 실패 | 138 | 대다수 `OHLC fields must be positive` |

예를 들어 실제 식별자 `0005A0`, `00088K`가 이전에는 `0005`, `00088`로 저장됐다.
현재 parser는 영숫자 식별자를 보존하도록 수정돼 있지만, 기존 `symbols` 행은 자동으로
수정 또는 비활성화되지 않는다. 잘린 171개만 올바르게 제외 또는 정정해도 현 정의의
성공률은 약 95.6%까지 회복할 수 있다. 남는 실패는 거래정지·상장상태·Naver OHLC
정합성을 별도 판정해야 한다.

## 3. 문제 정의

현재 `symbols.code` 한 필드는 다음 네 가지 역할을 동시에 가진다.

1. 상장 종목의 정체성
2. Naver 요청용 심볼
3. 가격 수집 대상의 키
4. RS 결과의 식별자

Naver HTML을 40페이지까지만 수집해 만든 partial snapshot에서는 비활성화를 막는다.
이는 정상 종목의 오삭제 방지에는 맞지만, 과거의 잘린 코드·상장폐지·더 이상 관측되지
않는 종목도 active로 남기는 결과를 낳는다. 또한 상장돼 있어도 거래정지 또는 당일
시세가 없는 종목을 가격 실패와 동등하게 세고 있다.

목표 상태는 다음과 같다.

```text
KRX instrument master (상장 기준 원장)
  -> 완전성 검증된 KRX universe snapshot
  -> instrument status + provider symbol mapping
  -> price-eligible universe (Naver 요청 대상)
  -> RS-eligible universe (가격·이력·정책 통과 대상)
```

Naver 수집 결과는 KRX master를 덮어쓰지 않는다. Naver에만 존재하거나 심볼이 맞지
않는 항목은 명시적으로 `unmatched`로 기록하고 운영 검토 대상으로 남긴다.

## 4. 목표와 성공 기준

### 4.1 제품 목표

1. KOSPI·KOSDAQ 주식과, 가격 수집 정책에 포함되는 ETF·ETN의 당일 기준 목록을
   KRX master에서 재현 가능하게 만든다.
2. 공급자별 심볼을 instrument identity와 분리하여, 한 공급자의 코드 형식 변경이
   종목 정체성을 훼손하지 않게 한다.
3. `listed`, `price_eligible`, `rs_eligible`을 구분하여 성공률의 분모를 설명 가능하게
   만든다.
4. 완전성 검증된 snapshot에서만 active 상태와 유니버스 변경을 반영한다.
5. 과거 잘린 코드와 stale active 항목을 감사 가능하고 되돌릴 수 있게 정리한다.

### 4.2 정량 완료 기준

| 지표 | P0 완료 | P3 운영 전환 완료 |
|---|---:|---:|
| active 중 길이/형식 오류 코드 | 0 | 0 |
| KRX snapshot `completed` 비율 | 해당 없음 | 최근 5거래일 100% |
| 최신 completed snapshot 밖 active 대상 | 0 (승인된 예외 제외) | 0 |
| KRX↔Naver 매핑률 | 측정만 | price-eligible의 99.5% 이상 |
| 원인 불명 Naver 빈 응답 | 기준선 대비 80% 이상 감소 | 지속 감시 |
| 가격 대상 성공률 | 95% 이상을 목표로 관측 | `eligible` 정의와 함께 보고 |

성공률 95%는 품질 목표이지, 거래정지/상장폐지/휴장 종목을 성공으로 위장해 달성하는
지표가 아니다. 이들은 별도 제외 사유와 개수로 반드시 노출한다.

## 5. 범위와 비범위

### 범위

- KRX Open API 또는 계약된 KRX export를 통한 기준 종목 master ingestion
- KOSPI, KOSDAQ, ETF, ETN의 시장·상품유형·상장 상태 동기화
- Naver 심볼 매핑, 형식 검증, shadow 비교
- universe snapshot 확장, price/RS 적격성 정책, 운영 API·리포트
- 기존 잘린 코드 및 stale active 레코드의 dry-run, 승인, 재처리

### 비범위

- KRX 가격 데이터를 일일 가격의 새 주 공급자로 바꾸는 작업
- Kiwoom 자동 폴백 또는 전종목 수집
- KONEX, ELW, 채권, 파생상품을 RS universe에 추가하는 작업
- 원본 가격값을 자동 수정하거나 기존 price history를 삭제하는 작업
- RS 산식과 랭킹 화면의 재설계

## 6. 외부 계약 및 데이터 원칙

KRX Open API는 인증키 신청과 서비스별 활용 신청·승인이 필요하다. 구현 전 운영
계정으로 필요한 서비스의 이용 권한, 호출 한도, 재배포 조건을 확인한다.

- KRX는 유가증권·코스닥 종목기본정보 및 ETF/ETN 관련 서비스를 제공한다.
- 인증키·이용 승인 절차는 [KRX Open API 이용 방법](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp)을 따른다.
- 서비스 선택은 [KRX Open API 서비스 목록](https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd)에서 확정한다.

다음 규칙은 필수다.

- 종목코드는 숫자로 변환하지 않고 원문 문자열로 저장한다. 선행 0과 영숫자 문자를 보존한다.
- code의 유효성은 `^[0-9A-Za-z]{6}$` 같은 **공급자 계약별 규칙**으로 검증한다. 숫자 6자리만 강제하지 않는다.
- KRX 단축코드와 Naver 심볼은 우연히 같더라도 독립 필드로 저장한다.
- KRX 응답의 기준일·수집 시각·응답 hash·파서 버전을 snapshot에 보존한다.
- KRX 연결 실패나 불완전 snapshot은 기존 completed universe를 변경하지 않는다.

## 7. 데이터 설계

### 7.1 새/변경 엔터티

기존 `symbols`는 API·가격 이력 FK와의 호환을 위해 당장 제거하지 않는다. P2에서
`instruments`를 canonical identity로 도입하고, 점진적으로 소비자를 전환한다.

| 엔터티 | 핵심 필드 | 용도 |
|---|---|---|
| `instruments` | `id`, `krx_short_code`, `isin`, `name`, `market`, `security_type`, `listed_at`, `delisted_at`, `listing_status` | KRX 기준 종목 정체성 |
| `provider_symbols` | `instrument_id`, `provider`, `provider_symbol`, `valid_from`, `valid_to`, `mapping_status`, `evidence_snapshot_id` | Naver 등 공급자별 심볼 |
| `instrument_universe_snapshots` | `provider=krx`, `as_of_date`, `status`, 시장별 count/hash, 원본 hash, 오류 | KRX master 수집 단위 |
| `instrument_snapshot_memberships` | `snapshot_id`, `instrument_id`, `market`, `security_type`, `listing_status`, `trading_status` | 해당 기준일의 재현 가능한 구성 |
| `universe_reconciliation_runs` | `krx_snapshot_id`, `naver_snapshot_id`, counts, diff, decision, approved_by | shadow 비교·승인 기록 |
| `universe_exclusions` | `instrument_id`, `scope`, `reason_code`, `valid_from/to`, evidence | 가격/RS 정책 제외 사유 |

`symbols`에는 전환 기간에 `instrument_id` nullable FK, `legacy_code`, `legacy_state`를
추가한다. 기존 `daily_prices.symbol_id`와 `rs_scores.symbol_id`는 유지한다. 과거 코드를
다른 코드로 in-place 변경하지 않는다. 올바른 instrument와의 연결을 만든 후 명시적인
마이그레이션으로만 사용 경로를 전환한다.

### 7.2 상태 계약

| 상태 | 값 예시 | 소유자 | 가격 성공률 분모 포함 |
|---|---|---|---|
| `listing_status` | listed, delisted, suspended, unknown | KRX master | `listed`만 후보 |
| `mapping_status` | matched, unmatched, ambiguous, invalid_legacy | reconciliation | `matched`만 후보 |
| `price_eligibility` | eligible, expected_no_trade, excluded, review_required | policy | `eligible`만 포함 |
| `rs_eligibility` | eligible, insufficient_history, stale, excluded | RS/validator | RS 후보만 포함 |

`expected_no_trade`는 거래정지·상장 당일·정책상 가격이 없는 상태를 나타낸다. 이 상태는
Naver 요청을 생략하거나 별도 관측으로 남기며 `fetched`나 `no_new_data`로 위장하지 않는다.

## 8. 기능 요구사항

### FR-01. Naver 유니버스 수집의 즉시 복구

1. `max_symbol_pages=40`을 고정 안전 한도로 사용하지 않는다. 페이지의 빈 결과 또는
   반복 페이지를 정상 종료 조건으로 사용하며, 별도 hard cap은 설정값과 alert로 둔다.
2. hard cap 도달 시 snapshot은 `partial`이며, price 단계는 마지막 completed universe를
   사용한다. partial snapshot의 혼합 active 목록을 새 기준으로 사용하지 않는다.
3. parser는 `code` query parameter 전체를 보존하고, 길이 6이 아닌 코드는
   `invalid_legacy_candidate`로 기록한다.
4. Naver ETF endpoint 실패는 ETF 유형을 stock으로 바꾸는 근거가 될 수 없다. 유형은
   마지막 확정 KRX master 또는 `unknown`으로 보존한다.

### FR-02. KRX master ingestion

1. scheduler는 장 마감 후 KRX의 기준일 master를 수집한다.
2. KOSPI/KOSDAQ 주식, ETF, ETN을 독립 fetch하고, market/security type별 결과를 기록한다.
3. 필수값은 KRX 식별자, 종목명, 시장, 상품유형, 상장 상태, 기준일이다. API가 제공하면
   ISIN, 상장/상장폐지일, 거래정지 상태를 포함한다.
4. 개별 feed의 오류·빈 응답·기준일 불일치가 있으면 snapshot은 `partial/failed`다.
5. 이전 completed snapshot 대비 시장·유형별 증감률, 중복 code/ISIN, 형식 오류,
   비정상 대량 신규/삭제를 검증한다.
6. snapshot이 `completed`일 때만 member set을 current KRX universe로 승격한다.

### FR-03. KRX↔Naver mapping 및 reconciliation

1. 1차 key는 정확한 코드 문자열, 2차 후보는 ISIN, 시장·상품유형·정규화한 종목명이다.
2. 이름만 일치하는 경우 자동 매핑하지 않는다. `ambiguous` 또는 `review_required`로 남긴다.
3. legacy code가 올바른 6자리 코드의 strict prefix이고 이름·시장·유형이 일치하면
   자동 정정 후보로 제시할 수 있으나, 적용은 dry-run 보고서와 승인 뒤에만 한다.
4. active이지만 KRX snapshot에 없는 행은 `stale_active_candidate`로 생성한다. 상장폐지로
   즉시 단정하지 않고 KRX 상태와 마지막 관측일을 증거로 저장한다.
5. KRX에는 있으나 Naver에 없는 price-eligible 항목은 Naver 요청하지 않고
   `provider_symbol_unavailable`로 분류·집계한다.

### FR-04. 적격성 기반 가격·RS 대상 확정

가격 수집 직전에 immutable target set을 생성한다.

```text
price target
 = latest completed KRX member
   AND listing_status = listed
   AND mapping_status = matched
   AND price_eligibility = eligible
```

RS target은 위 집합 중 `security_type=stock`과 최소 가격 이력·freshness 규칙을 통과한
항목이다. ETF/ETN은 price history 수집 여부를 별도 feature flag로 결정하며 기본 RS
대상에는 포함하지 않는다.

`crawl_target_results`에는 대상이 된 기준 snapshot ID, instrument ID, 적격성 결정과
제외 사유를 기록한다. 이렇게 해야 이후 success-rate의 분모를 재현할 수 있다.

### FR-05. 운영 관측 및 API

운영 API와 일일 report는 아래를 제공한다.

- latest KRX snapshot 및 Naver snapshot 상태, 기준일, 시장·유형별 count
- KRX-only, Naver-only, matched, ambiguous, invalid legacy code 수
- price eligible / expected no trade / excluded / RS eligible 수와 사유별 count
- deactivation·legacy correction 후보의 dry-run 목록과 승인 상태
- job별 target snapshot ID와 coverage를 함께 포함한 성공률

기존 `/api/v1/crawl/universe-snapshots`를 유지하고, KRX snapshot과 reconciliation을
표현할 새 read-only endpoint를 추가한다. 수정·승인 endpoint는 별도의 운영 권한과
감사 로그를 요구한다.

## 9. 구현 계획

### P0 — 유니버스 긴급 복구 (1~2일)

1. `NaverPriceSource.max_symbol_pages`를 설정화하고 페이지 종료 기반으로 변경한다.
2. parser·`SymbolPayload`에 code 형식 검증을 추가하고, 영숫자 6자리 회귀 fixture를
   확대한다.
3. DB audit CLI를 만든다. 결과는 `invalid_legacy`, `prefix_collision`,
   `stale_active`, `missing_from_latest_snapshot`별 CSV/JSON dry-run으로 저장한다.
4. job 65와 최신 Naver full snapshot을 대조하여 잘린 171개 코드의 정정/비활성화 후보를
   만든다.
5. 운영자 승인 후에만 legacy 행을 `is_active=False`로 전환하고 reason·원래 값을
   audit table에 보존한다. 가격·RS 이력은 삭제하지 않는다.
6. 새 completed Naver snapshot을 만든 뒤, 대상 전용 가격 재실행과 quality validation을
   수행한다.

완료 조건: 최근 Naver snapshot이 `completed`, active 형식 오류가 0, 가격 대상과 target
result 수가 일치한다.

### P1 — KRX master ingestion과 shadow mode (3~5일)

1. KRX 서비스 신청, secret 등록, sample response 고정(fixture) 및 호출량 계약을 확인한다.
2. `KrxUniverseSource`와 typed response/parser를 구현한다.
3. KRX snapshot·membership migration/model/repository를 추가한다.
4. daily 배치에서 Naver 기존 sync와 병렬로 KRX snapshot을 **쓰기만** 수행한다. active와
   price target은 변경하지 않는다.
5. 시장·유형별 count, code/ISIN 중복, KRX↔Naver mapping diff를 `reports/`와 운영 API에
   기록한다.

Gate: 5거래일 동안 KRX snapshot이 모두 completed이고, 미매핑·이상 증감이 운영자에게
설명 가능해야 한다.

### P2 — canonical identity와 적격성 전환 (4~6일)

1. `instruments`, `provider_symbols`, `universe_exclusions`, reconciliation audit migration을
   추가한다.
2. 현 `symbols`를 KRX instrument에 연결한다. 자동 연결되지 않는 행은 legacy 상태로
   남기며 수동 승인 목록을 만든다.
3. price/RS target builder를 구현하고, 기존 `list_price_targets()`와 결과를 shadow 비교한다.
4. `crawl_target_results`와 validation report에 instrument/snapshot/eligibility lineage를
   기록한다.
5. trading status와 zero OHLC를 `expected_no_trade`, `provider_invalid_row`,
   `review_required`로 분류한다.

Gate: shadow target의 차이가 승인됐고, legacy 코드의 가격 요청이 0건이며, 신규 target
builder의 전체 수와 target result 수가 일치한다.

### P3 — 운영 전환 및 정리 (2~3일 + 5거래일 관찰)

1. feature flag `UNIVERSE_AUTHORITY=krx`를 canary 환경에서 켠다.
2. KOSPI 또는 KOSDAQ 한 시장부터 2거래일 canary 적용 후 전체로 확장한다.
3. 5거래일 동안 coverage, mapping rate, exclusion reason, stale count, KRX snapshot 상태를
   매일 검토한다.
4. 기준 미달 시 `UNIVERSE_AUTHORITY=naver_last_completed`로 즉시 롤백한다. schema와
   historical audit record는 유지한다.
5. 안정화 후, 승인된 stale/invalid legacy 행만 비활성화하고 legacy 목록을 보존한다.

## 10. 마이그레이션 및 안전 절차

1. DB migration은 additive로 시작한다. `symbols.code` unique 제약과 기존 FK를 첫 배포에서
   변경하지 않는다.
2. legacy 정리는 `DELETE`가 아니라 `is_active=False`, `legacy_state`, reason, run ID를
   기록하는 방식으로 한다.
3. 자동 비활성화의 입력은 항상 `completed` KRX snapshot이어야 하며, 해당 snapshot과
   reconciliation run의 hash를 저장한다.
4. production 적용 전 staging DB restore에서 audit CLI의 candidate 수, duplicate 영향,
   가격/RS 조회 회귀를 검증한다.
5. 롤백은 feature flag와 target builder 선택만 되돌린다. 이미 기록한 snapshot, mapping,
   audit 데이터는 삭제하지 않는다.

## 11. 테스트 계획

### 단위 테스트

- 숫자·영숫자 6자리 code 보존, 선행 0 보존, 4/5자리 legacy code 거절
- Naver 페이지의 empty/repeated/cap/error 종료 상태
- KRX response의 시장·유형·상태 parsing 및 기준일 검증
- KRX↔Naver exact match, prefix collision, 이름 중복, ambiguous 매핑
- eligibility 상태별 price/RS target 생성

### 통합 테스트

- partial KRX/Naver snapshot에서 active 상태와 target 기준이 변하지 않음
- completed snapshot에서만 stale candidate가 비활성화됨
- job target snapshot ID와 target-result count가 일치함
- legacy code 정리 후 기존 daily_prices/rs_scores FK와 API 조회가 유지됨
- feature flag 양쪽에서 동일 입력에 대해 재현 가능한 target 목록을 생성함

### 운영 검증

- job 65 replay: 171개의 invalid legacy Naver 요청이 사라졌는지 확인
- P0 재실행 뒤 quality report의 `NAVER_EMPTY_RESPONSE`, coverage, stale 수 비교
- P1 shadow 5거래일: 시장·유형별 count와 mapping diff 승인
- P3 canary: 기존 경로 대비 RS 후보 수, 기준일 coverage, API 응답 회귀 확인

## 12. 위험과 결정 필요 사항

| 위험/결정 | 영향 | 완화 또는 결정 시점 |
|---|---|---|
| KRX API 승인·한도·라이선스 | P1 일정과 데이터 사용 범위 | 구현 시작 전 서비스 신청과 계약 확인 |
| KRX와 Naver의 심볼 체계 차이 | 자동 mapping 오판 가능 | ISIN 우선, ambiguous 자동 적용 금지 |
| 거래정지 정의 부재 | 성공률 왜곡 또는 RS 누락 | P2 전에 product policy 승인 |
| ETF/ETN 가격 수집 필요성 | 분모와 실행 시간이 달라짐 | P2에서 product owner가 명시 결정 |
| KRX snapshot 지연/실패 | 잘못된 비활성화 위험 | last completed fallback과 feature flag |
| 과거 `symbols` 행 중복 | FK/이력 연결 오류 | additive mapping, delete 금지, staged approval |

## 13. 산출물 체크리스트

- [ ] KRX API 권한·secret·fixture·사용 조건 검증 문서
- [ ] Naver 페이지 상한/형식 검증 P0 patch 및 회귀 테스트
- [ ] legacy/stale audit CLI와 approval runbook
- [ ] KRX snapshot/membership migration·source·repository·tests
- [ ] KRX↔Naver reconciliation report/API
- [ ] instrument/provider symbol/eligibility migration과 target builder
- [ ] feature flags, canary dashboard, rollback runbook
- [ ] job 65 전후 coverage 및 failure reason 비교 보고서

## 14. 수용 기준

이 PRD는 다음을 모두 충족할 때 완료로 판단한다.

1. KRX 기준 snapshot이 5거래일 연속 completed다.
2. 가격 크롤링은 항상 마지막 completed authoritative snapshot의 immutable target set을
   사용한다.
3. active target에 6자리 계약을 만족하지 않는 legacy 코드가 없고, 해당 요청이 0건이다.
4. KRX↔Naver 미매핑·제외·거래정지 항목은 성공률과 별도로 reason code와 함께 조회된다.
5. partial snapshot, KRX outage, mapping 급감 시 자동 비활성화가 일어나지 않고 alert가
   발생한다.
6. canary와 전체 전환에서 기존 가격 이력·RS 조회 API·일일 배치의 재실행이 회귀 없이
   동작한다.
