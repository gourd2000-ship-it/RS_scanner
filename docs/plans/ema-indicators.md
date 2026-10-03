# EMA 5·20·50·200 DB 누적 구현계획

작성: 2026-10-03 · 상태: 승인 대기

## 목표와 범위

검증된 일봉 종가로 EMA 5·20·50·200을 계산해 PostgreSQL에 보존한다. 최초 과거 구간을 계산한 뒤, 매일 가격 수집과 검증이 끝난 후 새 거래일 값만 누적한다. 값·입력 가격·계산 규칙·계산 버전을 함께 보존해 OHLCV가 정정되어도 기존 백테스트 근거를 잃지 않는다.

이번 범위는 EMA 저장 구조, 계산기, 과거 계산, 일일 누적, 운영자 조회와 운영 절차다. EMA 조건, 가격·EMA 교차, 백테스트 실행 연결, 조건 편집 화면은 후속 작업이다. 따라서 이번에 만든 일일 EMA를 현재 백테스트가 임의로 사용하지 않는다.

## 확정된 계산과 데이터 규칙

- 종가 기준 EMA만 계산하며 기간은 5, 20, 50, 200 거래일로 고정한다.
- 첫 번째 적격 종가를 초기값으로 사용한다. `alpha = 2 / (N + 1)`이고 이후 값은 `EMA[t] = alpha × close[t] + (1 - alpha) × EMA[t-1]`로 계산한다.
- 각 EMA는 해당 기간 N개의 연속 적격 거래일이 쌓인 날부터 `available` 상태다. 그 전에는 계산값을 저장하되 `warming_up` 상태로 남기며 조회·조건·백테스트에 사용하지 않는다.
- 휴장일과 근거 있는 거래정지일은 관측 수에 넣지 않는다. 결측·무효·검토 필요 가격, 근거 없는 공급자·수정 기준 변경은 보간하거나 건너뛰지 않는다. 해당 지점부터는 `data_unavailable` 상태로 두고 정정된 입력으로 새 버전이 완성될 때까지 사용하지 않는다.
- 일일 EMA는 `validated-observation-close-v3`가 선택한 종가만 사용한다. `DailyPrice`의 현재 행이나 현재 Symbol 값은 identity 근거로 쓰지 않는다. `PriceObservation`마다 당시 provider symbol·instrument·ProviderSymbol mapping을 보존한 identity snapshot을 먼저 확정하고, 이 근거가 없는 과거 관측은 추정하지 않고 사용 불가로 둔다. 선택 관측·identity snapshot·보정·품질 판정·관측 기준 시각을 불변 input snapshot으로 복사하고 행 및 누적 입력 hash를 저장한다.
- 과거 OHLCV가 정정되면 영향을 받는 종목·기간의 새 EMA 버전을 처음부터 재계산한다. 새 버전이 검증과 전체 계산을 통과하면 최신 일일 조회 대상으로 자동 전환한다. 기존 값과 이전 백테스트가 참조한 값은 변경하지 않는다.
- 백테스트가 나중에 EMA를 사용할 때는 해당 고정 데이터셋의 가격으로 계산한 EMA와 입력 해시를 함께 고정한다. 일일 EMA를 종목코드·날짜만으로 찾아 연결하지 않는다.

OHLCV 정정은 공급자 과거 데이터 변경, 수정주가 반영, 늦은 데이터 수신, 승인된 품질 보정·제외 등으로 일어날 수 있다. 종가 하나의 정정도 그 날짜 이후 EMA 전체를 바꾸므로 버전 분리가 필요하다.

## 저장 구조

`daily_prices`에 EMA 열을 추가하지 않는다. 별도 지표 저장 구조를 만들어 최신 일일 값과 과거 계산 버전을 함께 보관한다.

| 저장 대상 | 보관 내용 |
|---|---|
| 관측 identity snapshot | PriceObservation별 당시 provider symbol, instrument, ProviderSymbol mapping과 resolver 근거; 새 수집 시 함께 저장하고 기존 관측은 증거가 있을 때만 운영자가 materialize |
| 지표 시리즈 | 종목의 역사적 식별자, EMA, 종가 기준, source 정책, 입력 정책·계산 규칙 버전; 네 기간을 한 묶음으로 관리 |
| 계산 generation | series, 증가하는 version, 부모 version·교체 사유, `building`·`current`·`superseded`·`failed`, 현재 사용 여부 |
| 계산 실행 | generation, `backfill`·`incremental`·`rebuild`, 대상 범위·관측 기준 시각, 입력·결과 hash, 처리·제외 수량, `running`·`completed`·`failed` |
| 입력 snapshot | calculation run·generation·거래일, 선택 PriceObservation·ProviderSymbol 식별자, 종가·거래량, source·보정·품질 근거, 행/prefix hash |
| 일자별 값 | calculation run·generation·EMA 기간·거래일, 계산값, `warming_up`·`available`·`data_unavailable` 상태와 사유, 적격 관측 수, 정확한 다음 계산 상태 |

current generation에는 새 거래일을 새 immutable incremental run으로만 INSERT하고, 완료된 run의 값·snapshot은 수정하지 않는다. 한 run은 대상 날짜의 EMA5·20·50·200 행과 input/result hash를 모두 쓴 단일 transaction에서만 completed가 될 수 있다. 각 series에는 current generation이 하나만 있어야 한다. series row lock과 running calculation run 제약으로 동시 계산을 막고, rebuild가 완료된 transaction에서 네 기간을 함께 최신 generation으로 전환한다. 재시도는 동일 input hash의 완료 run을 재사용한다. 이전 버전 중 백테스트가 참조한 것은 계속 보존한다. 참조되지 않은 이전 버전은 최신 버전 전환 뒤 30일 보관하고 정리 대상으로 표시한다. 정리 작업은 실행 기록과 참조 관계를 다시 확인해 참조된 데이터를 삭제하지 않아야 한다.

## 구현 순서

### 1. 구조

1. EMA 계산 계약과 상태·입력 근거 계약을 코드와 문서에 고정한다.
2. 지표 시리즈, 계산 generation, 계산 실행, 입력 snapshot, 일자별 값을 위한 모델과 append-only migration을 추가한다.
3. 백테스트가 미래에 EMA를 사용할 때 필요한 고정 참조 구조를 설계하되, 이번 범위에서는 전략·시뮬레이터를 변경하지 않는다.

### 2. 공통기능

1. 이번 범위에서는 승인된 일일 가격만 읽는 입력 선택기를 만든다. 고정 데이터셋 EMA는 미래 백테스트 확장의 계약으로만 남긴다.
2. 종목별 가격을 한 번 순회해 네 EMA를 계산하는 순수 계산기를 만든다. 전체 계산, 일일 증분, 중단 후 재개 결과가 같아야 한다.
3. 입력 해시를 비교해 새 거래일·지연 입력·과거 정정·품질 판정 변경을 구분한다. 정정 시 새 버전 계산을 시작하고, 완료 전에는 최신 값을 바꾸지 않는다.
4. 계산 실행과 최신 버전 전환을 원자적으로 처리하고 중복 실행·부분 결과 노출을 막는다.

### 3. 개별기능

1. 기본 dry-run 과거 계산 명령을 만든다. 대상 수, EMA별 최초 사용일, 준비 중·사용 불가 수량, 예상 행 수·저장량·처리 시간, 정정으로 인한 재계산 대상을 보고한다. 실제 쓰기는 명시적 `--apply`에서만 수행한다.
2. 가격 수집과 clean-price 입력 확인 뒤 EMA를 누적하는 공통 batch adapter를 두 기존 일일 배치 진입점에 연결한다. adapter는 기존 checkpoint 상태로 skip을 `completed_with_errors`와 metadata의 `outcome=skipped`로 기록한다. 기능 기본값은 비활성이며, adapter가 기록한 skip 또는 계산 실패는 기존 RS를 지우지 않고 batch의 `completed_with_errors`와 재개 사유로 남긴다. 다음 batch는 새 job으로 시작하되 마지막 성공 input prefix부터 안전하게 누적한다.
3. 운영자 조회 `GET /api/v1/backtests/indicators/ema`에서 code/start/end/periods/page/size와 선택 instrument_id를 검증하고 종목·기간·날짜 범위별 EMA 값, 상태·사유, `as_of`(마지막 입력 거래일), `calculated_at`(마지막 완료 실행 시각), 계산·입력 버전을 제한된 페이지로 보여 준다. 재사용된 code가 여러 historical instrument에 해당하면 409 또는 명시 instrument로 처리한다. 존재하지 않는 종목은 404, 잘못된 입력은 422, 계산되지 않은 종목은 200과 규정된 사용 불가 사유를 반환한다. 내부 자동화 도구에는 쓰기 권한이나 새 권한을 추가하지 않는다.
4. 성능·용량·복구 절차를 기록한다. 운영 적용은 격리 DB 검증과 dry-run 보고서 검토 뒤 사람이 실행한다.

## 검증 기준

- 수작업 가격 수열로 첫 종가 초기화, EMA5·20·50·200의 N일 경계, 상승·하락을 검증한다.
- 준비 중 값은 저장되지만 사용 가능 값으로 조회되지 않는다.
- 전체 계산, 신규 날짜 증분 계산, 중단 뒤 재개 계산이 같은 결과와 해시를 만든다.
- 결측·무효·공급자 또는 수정 기준 단절에서 값이 이어지지 않는다.
- 과거 종가·보정·품질 판정이 바뀌면 새 버전이 만들어지고, 이전 버전과 이를 참조한 백테스트 입력은 변하지 않는다.
- 새 버전은 성공적으로 완성된 뒤 자동 전환되며, 실패한 버전은 최신 조회 결과에 나타나지 않는다.
- 빈 DB와 기존 데이터가 있는 격리 PostgreSQL에서 migration을 적용하고, 관련 단위·통합 테스트, `python -m compileall app scripts`, `git diff --check`를 통과한다.

## 운영 적용과 복구

순서는 격리 migration → 대표 표본 계산 → dry-run/용량 보고 검토 → 운영 backup과 migration → 과거 계산 → 수량·해시 검증 → 일일 단계 활성화다. 운영 DB migration과 대량 backfill은 이 문서만으로 실행하지 않으며 별도 운영 결정이 필요하다.

문제가 발생하면 EMA 기능을 비활성화하고 마지막 성공 버전을 계속 조회한다. 실패한 계산 실행은 원인과 재개 지점을 보존한다. EMA 테이블·원본 OHLCV·참조된 이전 버전은 삭제하지 않는다.
