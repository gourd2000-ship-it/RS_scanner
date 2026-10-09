# 도메인 규칙

## 목적과 책임 범위

결과는 개인 연구용 RS 분석 데이터다. 매수·매도 추천, 주문 실행, 투자 자문, 수익 보장을 제공하지 않는다. 모든 화면과 결과 해석은 이 제한을 유지한다.

## 종목·유니버스

`Instrument`는 종목의 역사적 정체성이고, provider symbol·시장·상장 상태는 기간별 사실이다. 현재 코드·현재 상장 여부만으로 과거 lifecycle을 합치거나 분리하지 않는다. 상장·상폐·시장 이전의 근거가 없으면 `unknown`으로 남기며, 가격의 첫·마지막 날짜를 이벤트 날짜로 추론하지 않는다.

사용자 결정에 따라 상장폐지 이벤트가 있는 lifecycle은 백테스트 대상에서 제외한다. 이는 생존편향이 없는 시장 재현을 뜻하지 않으며, 상장폐지 가격·정리매매·현금청산 데이터를 확보하기 전까지 그 사실을 주장해서는 안 된다. identity 미확인 lifecycle도 대상에 넣지 않는다.

## OHLCV 품질

기대 행은 선택된 종목 lifecycle과 거래일의 곱이다. 각 기대 행은 `valid`, `missing`, `invalid`, `review_required` 중 하나 이상의 판정 근거를 가진다. 0 또는 음수 가격, OHLC 순서 모순, 음수 거래량은 유효 입력이 아니다. 결측을 보간하거나 극단 수익률을 자동 보정하지 않는다.

극단 수익률·장기 동일 가격·출처 충돌은 검토 신호다. 기업행위·정지·조정 기준의 근거가 확인되기 전까지 `valid`로 승격하지 않는다. 서로 다른 공급자 또는 수정 기준의 가격을 이어 붙이지 않으며, source·adjustment policy·관측 시각을 보존한다.

## RS와 백테스트 입력

날짜 D의 RS는 D까지 이용 가능한 적격 가격과 D의 적격 유니버스로 계산한다. 미래 날짜의 가격·상장 상태·상폐 사실을 D의 매수 후보 선정에 사용해서는 안 된다. 충분한 준비 이력이 없으면 RS는 null이며, 0점으로 대체하지 않는다.

백테스트 dataset은 요청 범위의 가격, RS, 유니버스 상태, 품질 판정, 정책 버전과 watermark를 함께 고정한다. 현재 발행 조건은 **모든 기대 행이 valid인 `complete` 종목·연도 구간만 포함**이다. `partial`, `unavailable`, `review_required`, `missing`, `invalid`이 하나라도 있는 구간은 결과를 표시하거나 입력으로 내보내지 않는다.

백테스트 시뮬레이터는 구현됐다. 종가에서 조건 신호를 판정하고 다음 거래일 시가에 가상 체결하며, 수수료·슬리피지·보유 포지션·손절/익절·종료일 전량 청산을 계산해 결과를 저장한다. 실행 요청 API와 결과 조회 API도 구현돼 있다. 별도 워커의 운영 연결과 실제 발행 dataset을 이용한 종단 간 운영 검증은 남아 있다. 상장폐지 lifecycle은 입력에서 제외하므로 상폐 청산 시뮬레이션은 지원하지 않는다.

2026-10-02 감사 기준에서 2013-01-01~2026-09-04 생존 lifecycle 집합은 유효 5,080,047행, 결측 2,493행, 검토 565행이었다. 097870의 2013~2023 구간은 공급자 미지원으로 `unavailable`이며, 이 구간을 다른 출처로 대체하려면 조정 정책 검증이 선행되어야 한다.

## EMA 입력과 계산

EMA는 종가만 사용하며 기간은 5, 20, 50, 200 거래일로 고정한다. 첫 적격 종가를
초기값으로 두고, `alpha = 2 / (N + 1)`,
`EMA[t] = alpha × close[t] + (1 - alpha) × EMA[t-1]`로 계산한다. 계산은 고정
정밀도의 `Decimal`로 수행하며 표시 또는 저장을 위한 반올림값을 다음 거래일 계산에
사용하지 않는다.

각 기간은 N번째 **연속 적격** 거래일부터 `available`이다. 그 전의 계산값은
`warming_up`으로 보존할 수 있으나 조건이나 백테스트 입력에는 사용할 수 없다. 결측,
무효, 검토 필요, identity 미확정, 공급자 또는 조정 기준의 단절은 보간·이월하지 않는다.
그 날짜와 이후 값은 정정된 입력으로 새 계산 버전이 완성될 때까지
`data_unavailable`이다. 휴장과 근거가 확정된 거래정지는 관측 수에 넣지 않으며, 해당
날짜에는 값이 없다. 다음 적격 거래일은 거래정지 전의 내부 계산 상태를 이어받는다.

일일 EMA 입력 정책 버전은 `validated-observation-close-v3`이다. 이 정책은
`PriceObservation`의 불변 관측과 그 관측 당시 확정한 identity snapshot을 함께 사용한다.
snapshot은 provider symbol, 역사 instrument, ProviderSymbol mapping ID와 유효기간,
resolver 버전·확정 시각을 보존해야 한다. 현재 `DailyPrice` 행이나 현재 `Symbol` 연결은
과거 identity의 근거가 아니며 이를 보완하거나 추정하는 데도 쓰지 않는다. 정확히 하나의
`matched` mapping을 증명하지 못한 관측은 사용 불가다.

EMA 입력을 고정 데이터셋이나 백테스트에 연결하는 기능, EMA 조건과 교차 판정은 아직
구현하지 않는다. 이후 백테스트가 EMA를 사용하려면 고정 데이터셋 가격, EMA 계산 버전,
입력 hash를 함께 고정해야 한다.

### 일일 EMA 운영 설정

일일 EMA는 기본 비활성(`EMA_ENABLED=false`)이다. 활성화하려면
`EMA_SOURCE_PROVIDER`, `EMA_ADJUSTMENT_TYPE`, `EMA_ALLOWED_PARSER_VERSIONS`을 실제로
축적된 불변 관측과 일치하게 고정한다. 이 세 값은 series 정책의 일부이므로 변경하면 기존
series를 이어 쓰지 않는다.

일일 실행은 관측 시각마다 cutoff를 앞으로 옮기지 않는다. 코드의 고정된 미래 수용 경계
아래에서 새 관측을 계속 선택하고, 각 계산 run에는 선택된 input snapshot·prefix hash·결과
hash를 불변으로 저장한다. 따라서 다음 거래일의 관측은 같은 series에 증분 추가되며, 과거
관측의 선택 근거가 바뀌면 새 generation으로 재계산한다. 운영자는 별도의
`EMA_OBSERVATION_CUTOFF`을 설정하거나 매일 갱신해서는 안 된다.

## 거래량 MA50 저장과 계산

거래량 MA50은 검증된 OHLCV의 거래량만 사용하며 기간은 50 거래일이다. 거래량 0은 정상 관측값으로 평균에 포함한다. 50개의 연속 적격 관측 전에는 `warming_up`, 결측·음수 거래량·identity 미확정·품질 검토·source 단절 뒤에는 `data_unavailable`이며 보간하거나 이전 값을 이월하지 않는다.

거래량 MA50의 입력 정책은 `validated-observation-ohlcv-v1`이다. 선택된 관측, 역사 identity, source/adjustment/parser, 품질·보정 근거와 입력·결과 hash, 계산 run과 generation을 append-only로 보존한다. 원천 근거가 바뀌면 기존 결과를 갱신하지 않고 새 generation으로 재계산한다. 기존 EMA 이력은 수정하지 않는다.

일일 거래량 MA50은 기본 비활성이다. 활성화하려면 source 정책을 명시해야 하며, 가격 수집과 품질 검증 결과가 확인된 뒤에만 실행한다. 값은 아직 백테스트 조건이나 화면 API에 연결하지 않는다.

## ATR14 저장과 계산

ATR14는 검증된 high·low·close로 Wilder 방식의 true range를 계산한다. 첫 적격 거래일의 true range는 `high - low`이고, 이후에는 `max(high-low, abs(high-previous_close), abs(low-previous_close))`를 사용한다. 14개의 연속 적격 true range의 산술 평균을 첫 ATR로 삼고, 이후에는 `(이전 ATR × 13 + 현재 true range) / 14`로 갱신한다.

결측·무효 OHLCV·identity 미확정·품질 검토·source 단절은 `data_unavailable`으로 기록하고 계산 상태를 초기화한다. 14개 연속 적격 입력 전에는 `warming_up`이며, 값 보간이나 이전 ATR 이월은 하지 않는다. high·low·close와 선택·identity·품질 근거는 `validated-observation-ohlcv-v1`의 append-only evidence로 저장한다. high 또는 low만 수정되어도 새 generation으로 rebuild한다.

ATR14 일일 실행은 기본 비활성(`ATR14_ENABLED=false`)이다. 활성화 시 `ATR14_SOURCE_PROVIDER`, `ATR14_ADJUSTMENT_TYPE`, `ATR14_ALLOWED_PARSER_VERSIONS`을 명시하고 validation 완료 뒤에만 실행한다. ATR14 값은 아직 백테스트 조건이나 화면 API에 연결하지 않는다.
