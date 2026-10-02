# OHLCV 클렌징 구현 계획

개정: 2026-10-02 · 상태: 클렌징 구현 및 읽기 전용 운영 감사 진행 중<br>
작업 목록: [CL01~CL12](todo.md#ohlcv-클렌징-cl01cl12)<br>
적용 스킬: spec-driven-development, planning-and-task-breakdown

## 목적과 범위

상폐 데이터 확보와 매매 엔진 구현 없이, 보유한 일봉 OHLCV가 실제로 사용 가능한지
전수 감사하고 검증된 역사 데이터셋을 만든다. 운영 DB 감사는 읽기 전용으로 수행하며,
운영 보정 반영과 데이터셋 발행은 격리 검증 및 감사 결과 확인 뒤 별도 단계로 둔다.
아래의 기존 DBG/BT 기록은 보존한다. 이번 클렌징에서 상폐 가격 확보 및 전체 시장 생존편향 제거를
완료 조건으로 삼았던 과거 계획은 적용하지 않는다. 기존 완료 체크는 클렌징 검증 통과를 뜻하지 않는다.

기본 제안 범위는 KOSPI/KOSDAQ 보통주, 2013-01-01~2026-09-04이다. 범위는 실행 인자로
고정하고, 최신일까지의 확장은 별도 실행 버전으로 관리한다. 대상 선정 기준일(selection_as_of)과
데이터 관측 기준시각(observation_cutoff)을 별도로 저장한다. 확인된 상폐 lifecycle은 전체 기간에서
제외한다. 기준일 현재 상장 근거와 역사 identity를 확인할 수 없는 대상은 unknown으로 남긴다.
상폐 이력이 있는 옛 lifecycle과 같은 코드를 쓰는 새 lifecycle을 함께 제외하지 않는다.

이 집합은 기준일 생존 종목 중심의 연구 집합이다. 과거 전체 시장을 대표하거나 당시 알 수 있었던
정보만으로 대상을 선택했다고 주장하지 않는다. 해당 범위에서는 정돈된 OHLCV로 백테스트를
구현할 수 있지만, 수집되지 않은 값은 클렌징만으로 복원할 수 없다.

## 기존 기반과 확인된 빈틈

| 재사용 기반 | 이번 보완 |
|---|---|
| Instrument / ListingEvent / ProviderSymbol | 고정된 제외 정책, lifecycle별 대상 및 미확인 목록 |
| PriceObservation / ValidationRun / ValidationCase | 종목·날짜 전수 감사, 선택한 입력 revision과 근거 고정 |
| inspect_ohlc_row / historical_gaps / historical_policy | 거래량 정수성, 소스 계약, 준비구간, 거래일 달력·정지 근거 검증 |
| OhlcCorrection / OhlcExclusion / ValidatedPriceRepository | 승인된 보정·제외를 역사 데이터셋까지 동일하게 적용 |
| BacktestDataset / backtest_snapshot | 실제 수정주가 정책 적용, 일관된 DB snapshot, OHLCV lineage/hash |
| historical_rs / backtest API | 고정 identity, 품질 의미, 페이지 hash; RS 정합성은 별도 후속 단계 |

현재 snapshot은 DailyPrice를 직접 읽고 adjustment_type을 None으로 복사한다. 기존 검증을
통과한 dataset이라는 의미가 없다. fchart는 change_rate를 0으로 채우며 일부 parser는 volume을
int로 변환하므로 원자료의 소수 거래량이 사라질 수 있다. 값이 그럴듯한지 검사하는 것과
공급자 원자료를 정확히 옮겼는지 확인하는 것을 분리한다.

## 설계와 처리 순서

대상·입력 고정 → 읽기 전용 품질 감사 → 보정 후보·격리 → clean reader → 고정 dataset → 전 페이지 검수.
RS는 OHLCV 완료 후 선택적으로 검증한다. 이번 단일 데이터 클렌징 기능의 단계이며 별도 서비스나
새로운 범용 validation framework를 만들지 않는다.

### 1. 대상과 분모 고정

- universe manifest에 포함/상폐 제외/유형 제외/identity 미확인 수량과 근거 revision을 저장한다.
- 상장일 이후 요청 구간의 거래일을 기대값으로 만든다. 시장 이전은 일자별 시장을 사용한다.
  기존 달력에 임시 휴장과 역사 예외를 반영하고 달력 버전을 고정한다. 가격이 없다는 이유로 휴장·정지를 추론하지 않는다.
- 확인된 정지 기간은 expected_tradable과 별도로 집계한다. 정지 중 관측행도 감사하고 임의 체결 가능 행으로 보지 않는다.
- 제외 전 대상 수, 정책상 포함된 대상 수, 매매 가능 기대 행 수, 관측 행 수, 유효 행 수를 각각 보존한다.
  identity unknown은 가격 결측과 별도 집계하며 분모에서 조용히 제거하지 않는다.

### 2. 읽기 전용 전수 감사

| 검사 축 | 검사 및 판정 |
|---|---|
| 식별·날짜 | lifecycle 매핑, 종목·날짜 유일성, 상장 전/구간 밖/미래 날짜, 시장 이전, 완료 일봉 여부 |
| O/H/L/C | null·NaN·무한대·0 이하, low <= open/close <= high, low <= high |
| 거래량 | null·음수·소수·단위, 파싱 전 정수성; 0 거래량은 별도 상태이며 단독 오류로 확정하지 않음 |
| 완전성 | 가격이 전혀 없는 종목, 기대일 대비 누락, 연속 결측, 최초/최종 유효일, RS 준비구간 |
| 연속성 | 급격한 가격 비율, 장기 동일 OHLC, 공급자 변경 경계, 거래량 단위 급변을 경고로 분류 |
| 원자료 일치 | 보존 observation과 OHLCV 전 필드 대조; 동일 공급자·조정기준·관측 revision 조건에서 비교 |
| 조정 정책 | adjusted/raw/unknown, 기준일, OHLC 동시 조정 여부, 거래량 조정·배당 포함 의미의 알려진 범위 |

논리 검사를 통과해도 원자료와 일치한다는 증거가 없으면 source_verified와 구분한다.
보존 원자료가 없는 정상형 숫자는 '정확함 증명'으로 처리하지 않는다. 구조 오류는 invalid,
근거 부족한 급등락·소스 충돌은 review_required로 남긴다. 임의의 30% 기준을 역사 전체의
법정 가격제한으로 사용하지 않는다. 가격제한 관련 정책을 구현할 때는 해당 기간 공식 근거를 확인한다.

산출물: reports/cleansing/<run_id>/ 아래 manifest.json, summary.json, symbol_year_coverage.csv,
gaps.csv, anomalies.csv, source_conflicts.csv, excluded_universe.csv, unresolved_identity.csv.
각 종목·연도에 expected/observed/valid/missing/quarantined, 연속 결측 길이, 준비구간 상태를 기록한다.
보고서 자체에는 비밀·토큰·인증 URL을 저장하지 않는다.

### 3. 가격 선택·보정·격리

- DailyPrice와 기존 observation을 삭제하거나 일괄 덮어쓰지 않는다. 보정은 기존 correction/exclusion
  구조와 선택된 observation lineage로 적용한다. 복원 근거 없는 오류는 격리한다.
- 공급자 이름만으로 조정 정책을 추정하지 않는다. 종목별 연속 구간에 provider, adjustment_type,
  adjustment_base_date 또는 unknown, volume_basis, source contract/parser version을 고정한다.
- 시계열 중간에 공급자·조정기준이 달라지면 겹치는 구간의 모든 OHLC와 거래량 의미를 확인한다.
  호환성을 확인하기 전에는 날짜별 '최신 값'을 임의로 섞지 않는다. adjusted OHLC와 raw volume은
  공급자 계약에 따라 명시할 수 있으나 하나의 공통 조정값이라고 표시하지 않는다.
- 승인된 correction/exclusion을 재사용하고 수치·dtype 정규화는 계약상 손실 없는 경우만 허용한다.
  최신 관측이라는 이유만으로 충돌 후보를 채택하지 않는다. 행의 일부를 고칠 때도 OHLC 전체 불변식을 재검사한다.
- 결측을 전일 종가·0·선형보간으로 채우지 않는다. change_rate의 공급자 원값과 종가로 계산한
  파생 수익률은 구분하며, 직전 거래일이 없으면 일간 수익률을 만들지 않는다.
- 추가 확인이 필요한 현재 상장 종목의 소규모 재조회는 선택 사항이다. 감사 기본 네트워크 예산은 0이다.
  필요 시 기존 가용 공급자에서 대상·요청 상한·중단 조건을 정한 repair manifest를 만든다.
  상폐 소스 구매·상폐 재수집은 하지 않는다. 재조회 불가능하면 해당 구간을 미확보로 종료할 수 있다.

### 4. 검증된 데이터셋과 조회 계약

- canonical 직접 복사를 clean reader로 교체한다. 원본/보정/제외/소스 선택 근거와 정책 revision을
  함께 동결한다. 입력의 fingerprint 산출과 복사는 동일한 읽기 snapshot에서 수행한다.
  대용량에서는 종목/날짜 청크로 처리하고 전체 ORM relation을 메모리에 올리지 않는다.
- 모든 기대 종목·날짜의 상태를 유지한다: valid / missing / invalid / review_required /
  non_tradable. 가격의 존재만으로 quality=validated를 반환하지 않는다.
- code와 별도로 instrument_id를 항상 반환하고 결측 행의 code도 고정된 metadata에서 가져온다.
- 백테스트 소비 경로는 명시적 materialized dataset_id를 요구한다. 기존 가변 조회는 호환 경로로
  남길 수 있으나 재현 가능한 dataset이라고 표시하지 않는다.
- OHLCV 엄격 조회는 RS 유무와 분리한다. OHLCV 준비 완료가 253개 RS 관측을 요구하지 않도록 한다.
  전체 대상 coverage, 필터 제외 수, 페이지 coverage를 별도 제공하며 엄격 필터가 분모를 숨기지 않는다.
- ETag는 입력 cursor/범위/시장/품질 필터/페이지 크기 및 고정 버전 또는 응답 hash를 포함한다.
  기존 dataset은 수정하지 않고 새 버전을 발행한다.

## 완료 판정

**OHLCV 사용 가능 판정(CL01~CL10)**

1. 요청 범위의 대상과 모든 기대 행이 분류돼야 한다. 가격 0건 종목도 보고서에서 찾을 수 있다.
2. valid로 공개하는 행은 OHLCV 구조 오류, unresolved source/adjustment conflict, 승인된 제외 위반이 0건이다.
   unknown 조정기준은 검증 완료로 승격하지 않는다. 원자료 대조 가능 비율을 따로 명시한다.
3. 각 구간은 complete / partial / unavailable로 판정한다. complete는 그 구간의 기대 거래행 전부가 valid인 경우다.
   임의의 전체 coverage 99%를 통과선으로 삼지 않는다. 부분 구간도 사유와 마스크를 제공할 수 있다.
4. 동일 입력과 정책으로 OHLCV/상태/lineage/hash가 재현되고, 원본 갱신 후 기존 dataset은 변하지 않는다.
5. 결과에는 상폐 제외 기준과 제외 규모가 명시된다. '전체 시장 백테스트 가능' 판정은 만들지 않는다.

**RS 전략 입력 추가 판정(CL11~CL12, 후속)**

동률·반올림·시장별 순위와 PostgreSQL/Python 결과가 같고, D 이후 가격이 D 신호를 바꾸지 않아야 한다.
준비구간에서 빠진 거래일을 지운 뒤 253개 행을 임의로 이어 붙이지 않는다. calendar window/정지 처리 정책을
먼저 고정하고 insufficient_history와 missing_in_lookback을 구분한다. 실제 RS 결과값을 해싱한다.

## 검증과 실행 경계

- 구현은 기존 Python 3.12 / SQLAlchemy / pytest와
  dataclass·Decimal·repository 구조를 따른다. 새 라이브러리 도입은 우선 필요하지 않다.
- 단위 검사: lifecycle 재사용, 승인 보정/제외, 소수 거래량, 결측, 정지, 분할 전후, 공급자 교체,
  장중/마감 revision, 원자료 부호 표기, 페이지 경계 fixture를 사용한다.
- 통합 검사: 검증용 PostgreSQL에서 실제 migration, 일관 snapshot, 대량 streaming,
  중단·재개·재실행, 전 페이지 hash 검사를 한다. migration 실패를 create_all로 숨기지 않는다.
- 운영 감사는 read-only 트랜잭션으로 입력 기준을 고정하고 결과 파일만 쓴다. 감사 규모 측정 후
  처리량·메모리·디스크 예산을 산출한다. 보정 반영과 새 dataset 생성은 별도 실행 단계다.
- 유효 구간만 사후 선별해도 선택 편향이 추가될 수 있으므로 탈락 목록과 필터를 모두 보존한다.
- 매매 엔진, 프론트엔드 섹터 수정,
  유료 데이터 도입, 역사 universe의 완전성 확대는 이 작업의 선행조건이 아니다.

현재 실행 가능한 회귀 명령:

```bash
APP_ENV=production DATABASE_URL=sqlite:// .venv/bin/python -m pytest tests/unit tests/integration --ignore=tests/integration/api -q --disable-warnings
```

실행 순서와 체크포인트는 TODO가 단일 기준이다. 최초 산출물은 '클렌징 완료' 선언이 아니라
현재 상장 범위 OHLCV 감사 보고서와 종목·구간별 복구/격리 목록이다.

---

# 크롤링 장애 디버깅 계획

개정: 2026-10-01 · 네이버 수집 경로 기준<br>
적용: debugging-and-error-recovery, planning-and-task-breakdown<br>
실행 상태와 검증 명령: [TODO의 DBG01~DBG08](todo.md#크롤링-장애-디버깅-dbg01dbg08)

## 목표와 이번 범위

KRX 수집 중단 상태를 유지하면서 네이버 명부 → 지수·종목 일봉 → 검증 → RS → API 조회를 복구한다.
네이버 지수/가격 날짜 경계, 현재 명부 API 및 ETF·ETN 목록 연결, 명부 실패 checkpoint,
결과 이력 메모리 누적 방지와 안전한 batch lock을 구현했다. 2026-10-01 job 128에서
운영 명부·지수·가격·검증 단계까지 실제 실행하고 가격 33,053행을 반영했다.
RS는 약 9.4GB RSS 관측 뒤 안전 정지했고 API 이미지는 DB revision 불일치로 미기동이다.
실행 결과: [크롤링 복구 보고서](../reports/crawl_recovery_result.md).
문서 아래 기존 백테스트 계획은 보존하고, 일일 크롤링 복구와 역사 데이터 구축을 구분한다.

## 판단 기준과 현재 증거

아래 최초 장애 증거는 이전 조사 결과이며, 2026-10-01 실행 결과는 복구 보고서에 따로 기록한다.
원자료: [진단 보고서](../reports/crawl_debug_baseline.md),
[종목별 공백](../reports/crawl_debug_symbol_coverage_20260930.csv).

| 영역 | 확보된 증거 | 현재 판단 / 남은 검증 |
|---|---|---|
| KRX | production shadow=false, job 128의 krx_shadow=pending | 이번 실행에서 KRX 경로 미호출 확인 |
| 지수 | 구 URL 410, 새 모바일 JSON endpoint; SQLite canary 재실행 통과 | 운영 DB benchmark 최신일 10/1, 1,676행으로 반영 |
| 명부 | 30/30 pages, 4,306 unique; snapshot 76 completed | 기존 active 4,315 대비 34 deactivation 후보와 25 신규/복귀 코드가 남아 사유 분류 필요 |
| 종목 가격 | Naver fchart SQLite canary 및 운영 job 128 통과 | 4,340 대상 중 4,146 성공/194 OHLC 실패; 최신일 10/1, 33,053행 순증 |
| 작업 상태 | 명부 snapshot failed인데 symbols checkpoint completed였음 | snapshot partial/failed 시 checkpoint도 completed_with_errors로 기록하고 재개 시 재시도하도록 수정 |
| RS | RS checkpoint는 9/4 이후 미갱신. job 128은 RSS 9.4GB 관측 뒤 중단 | full-history 입력 누적이 강한 원인 후보. 254행 입력 제한을 구현/격리 테스트했으나 운영 RS는 미검증 |
| API | 이미지 migration이 DB revision `o8b9c0d1e2f3`를 찾지 못해 재시작 | 이미지 재빌드·재배포 필요. 이번 범위에서는 수행 안 함 |
| 데이터 | 운영 가격·지수 최신일 10/1, RS 9/4 | 194 가격 실패·34 명부 후보·RS/API 공백이 남아 전체 복구 미완료 |

기존 지수 테스트는 합성 JSON을 사용한다. 실사이트 응답 확인과 합성 데이터의 격리 저장 성공을
실제 수신 데이터 전체의 품질·완전성 검증으로 확대 해석하지 않는다.

## 디버깅 방향

1. **명부 요청 계약부터 확인한다.** 네이버 화면에서 KOSPI/KOSDAQ 전환과 다음 페이지 요청을
   관찰하고 URL·매개변수·시장 metadata·종목 코드·유형·전체 건수의 관계를 기록한다.
   정적 HTML로 보이지 않으면 브라우저 네트워크 또는 해당 화면의 배포 JS를 읽는다.
   확인한 요청을 재현한 뒤 전체 페이지 계약을 고정한다.
2. **새 지수 경로의 빈틈을 닫는다.** 첫 페이지부터 비어 있는 응답과 정상적인 이력 종료를
   구분한다. 반복 페이지·순서 변경·페이지 상한 도달로 일부 이력만 받은 경우를 검증한다.
   실시간 내부 API의 공개 명세 부재를 기록하고 실제 응답 표본을 테스트 자료로 추가한다.
3. **완료된 거래일과 장중 값을 구분한다.** 새 지수 응답에 장중 당일 행이 포함됐고,
   현 source는 저장된 마지막 날짜 이하를 제외한다. sync_benchmarks는 target_date 상한을
   적용하지 않는다. 장중 값이 먼저 저장되면 마감 값 갱신이 빠질 수 있다는 코드상 가설을
   재현한다. 종목 일봉에도 같은 날짜 재조회 문제가 있는지 확인한다.
   완료된 거래일을 기본 검증 기준으로 정하고 장중 실행/마감 실행의 저장·갱신 정책을 고정한다.
4. **수집 성공을 먼저 작은 범위에서 증명한다.** 명부 실패 시 과거 목록을 사용했다는 상태를
   보존하고, 격리 DB에서 실제 네이버 응답의 지수·소수 종목 저장과 재실행을 검증한다.
   이 단계에서 RS 전체 계산을 돌리지 않아도 수집 경로의 복구 여부를 확인할 수 있다.
5. **RS 자원 문제와 API 배포 문제를 각각 해결한다.** RS는 종료 증거와 규모별 측정으로
   수정 범위를 정한다. API는 전체 migration chain을 포함한 이미지로 검증한다.
6. **전체 경로 검증 뒤 실제 결측을 복구한다.** 날짜별 기대 대상과 실제 저장 내역을 대조하고,
   실행 예산·중단/재개·중복 실행 방지를 갖춘 뒤 복구 및 다음 정규 배치를 확인한다.

## 실행 순서와 의존성

| 순서 | 작업 | 완료 산출물 |
|---|---|---|
| 0 | DBG01 기준선 재사용 / 실행 직전 상태 갱신 | 현재 실행·설정·DB·코드 차이 기록 |
| 1 | DBG02B/C 지수 경계·날짜 정책 + DBG03A/B Naver 명부 경로 | 코드/fixture 검증 및 전체 명부 4,306행 메모리 SQLite snapshot — 완료. KST 운영 정책·기존 명부 대조는 남음 |
| 2 | DBG06A 명부 출처/잔존 상태 + DBG07A 지수·가격 canary | 실제 수집·저장 복구 완료. 기존 명부 차이/가격 실패 분류는 남음 |
| 3 | DBG04A RS 원인 측정 → DBG04B 원인 수정 → DBG06B 중단 상태 | RSS 9.4GB 위험 관측, 254행 입력 수정과 격리 테스트 완료; 운영 RS 재계산은 남음 |
| 별도 | DBG05 API 이미지/DB 정합성 | 격리 DB migration·기동·조회 성공 |
| 5 | DBG07B 전체 경로 통합 | 네이버 수집 → 검증 → RS → API 일관성 |
| 6 | DBG08A 복구 실행안 → DBG08B 복구·예약 검증 | 날짜/대상별 결측 보고 및 자동 실행 결과 |

DBG07A의 격리 canary와 운영 수집은 실행했다. D1의 KST 장중/마감 정책 및 기존 명부 개별 차이,
194 가격 응답 실패 사유는 남아 있다. D2 수집 경로는 확인됐지만 RS/API를 포함한 D3/D4는 미완료다.
DBG05의 운영 이미지 migration 수정/기동 및 대표 API 조회는 완료했다.
DBG04B 운영 규모 RS 검증을 완료한 뒤 전체 경로를 재실행한다.
DBG07B는 DBG07A·DBG04B·DBG05·DBG06B 완료 후, DBG08은 DBG07B 이후 진행한다.
이 의존성은 작업 순서 설명이며 별도 에이전트 실행을 요구하지 않는다.

## 검증 체크포인트

| 지점 | 통과 조건 |
|---|---|
| D1: 공급 계약 | 두 시장/유형별 명부 완전성, 지수 페이지·날짜·장중 갱신 정책 검증 |
| D2: 수집 저장 | 격리 SQLite 실응답 재실행 및 운영 job 128에서 명부·지수·가격·검증 완료. 194 실패는 미확보로 분리 |
| D3: 서비스 경로 | 운영 규모에 준하는 RS 자원 검증, 격리 API migration·기동, 전체 경로 일치 |
| D4: 운영 복구 | 대상/날짜별 복구·제외·미확보 설명, 중복 없는 다음 예약 배치와 조회 최신성 |

HTTP 200, 테스트 개수, 최대 저장 날짜, 종료 코드 0 하나만으로 복구 완료를 판정하지 않는다.
종목 명부의 totalCount도 시장·유형 범위가 같은지 확인한 뒤 고유 코드 수와 비교한다.
장중 순위 변동으로 페이지 경계가 바뀌면 중복 제거만으로 완전성을 인정하지 않는다.

## 실행 원칙과 제한

- KRX 승인·신규 KRX API 연동은 이번 복구의 선행조건에서 제외한다. 휴장일 계산 함수의
  KRX 이름과 실제 KRX 외부 API 호출을 구분한다. 일일 source·명부 권한·선택적 EOD 경로를 함께 확인한다.
- 명부 불완전 수집 시 기존 종목의 일괄 비활성화를 막는다. 과거 명부를 사용한 실행은
  관측된 목록 날짜·수량·누락 위험을 표시하고 전체 명부 복구 완료로 집계하지 않는다.
- 상장 전·거래정지·유형 제외·공급자 미지원·실제 결측을 구분한다. 네이버의 역사 명부 범위가
  부족하면 그 공백을 기록하며 기존 역사 백테스트 계획을 임의로 확대하지 않는다.
- 운영 크기 시험 전 요청 수·최대 동시성·시간·메모리 예산과 중단 조건을 정한다.
  429/반복 5xx/동일 페이지 반복은 무제한 요청하지 않고 원인별 중단/재개 결과를 기록한다.
- host 예약 배치는 수정된 작업 트리를 읽으며 wrapper에 `flock`을 추가했다. API 이미지는 별도이며
  DB revision 불일치는 2026-10-01 복구 이미지 배포로 해결했다. 이후 실행 전 프로세스·예약·lock 상태를 확인한다.
- SQLite는 파서/저장 검증에 사용한다. PostgreSQL E2E는 검증된 격리 DB에서만 수행하고,
  migration 실패 후 create_all 대체 성공을 migration 검증으로 인정하지 않는다.
- 미커밋 백테스트 변경과 migration 파일을 보존한다. 공유 파일을 수정할 때 기존 diff와 충돌을 확인한다.
- 설정 확인은 필요한 비밀 아닌 항목만 출력한다. 앞서 출력된 KRX 인증값의 폐기/재발급 여부는
  별도로 확인하며, KRX를 사용하지 않는 네이버 복구의 진행 조건으로 두지 않는다.

상세 작업별 완료 조건·실행 명령·예상 파일은 TODO가 단일 기준이다.
이번 문서 개정은 계획 내용·상호 링크·기존 백테스트 부분 보존·문서 diff를 검증한다.

---

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
