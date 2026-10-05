# 외부 계약

## HTTP 공통 규약

공개 조회 API는 `/api/v1` 아래에 있다. 내부 자동화 읽기 API는 `/api/v1/agent/v1` 및 `/api/v1/agent/v2` 아래에 있으며 Bearer token과 해당 `*:read` scope가 필요하다. 내부 읽기 응답은 request ID, dataset ID, data status, coverage를 header 또는 응답 meta로 제공한다. 유효하지 않은 입력은 422, 인증 누락·불일치는 401, scope/IP 거부는 403, 비활성 내부 기능은 404, 사용 불가 dataset은 503이다.

## 읽기 API

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /api/v1/agent/v1/status` | `status:read` | 서비스·dataset 상태 envelope | 401, 403 |
| `GET /api/v1/agent/v1/briefing` | `rs:read`, `size` 1~50 | 기준일과 상위 RS | 401, 403, 503 |
| `GET /api/v1/agent/v1/rankings/rs` | `rs:read`, market/page/size | 시장별 RS page | 401, 403, 422, 503 |
| `GET /api/v1/agent/v1/stocks/{code}` 및 `/history` | `stock:read`, history limit | 종목 snapshot 또는 가격 이력 | 401, 403, 404, 503 |
| `GET /api/v1/agent/v2/backtest/dataset` | `backtest:read`, start/end, markets, cursor, dataset_id, strict, page_size | 가격·RS·유니버스·품질·coverage가 고정된 page | 401, 403, 404, 409, 410, 422 |
| `GET /api/v1/backtests/indicators/ema` | 현재 백테스트 운영자 session, code, start/end, 선택 instrument_id/page/size | 현재 EMA generation의 일자별 5·20·50·200, availability 근거 | 401, 404, 409, 422 |

backtest 요청의 `start`와 `end`는 포함 범위다. cursor는 요청 필터와 dataset ID에 묶이며, 데이터가 바뀌어 일관된 page를 보장할 수 없으면 409를 반환한다. `strict` 결과도 `complete` 구간 조건을 완화하지 않는다. 가격 없는 기대 행, `partial` 구간, 상장폐지 lifecycle은 현재 발행 대상이 아니다.

EMA 운영자 조회는 code가 여러 역사 Instrument에 연결되면 409를 반환하며, 호출자는 유효한 `instrument_id`를 명시해야 한다. 한 Instrument에 source policy 변경으로 여러 current EMA series가 있으면 완료 시각이 가장 최근인 series 하나를 선택하고, 동률은 generation ID와 series ID 내림차순으로 결정한다. 결과는 거래일 오름차순으로 page를 나누고, `as_of`와 `calculated_at`은 조회 범위와 무관하게 선택된 current generation의 최신 입력·계산 시각을 나타낸다. 각 거래일에는 5·20·50·200 결과를 모두 포함한다. `value`는 JSON number가 아닌 Decimal 문자열이며, `status`와 `reason_code`는 값의 사용 가능 여부를 함께 나타낸다.

## 공급자·파일 입력

Naver, KRX, Kiwoom, EOD 공급자 입력은 각 client/parser의 검증 schema를 통과해야 한다. 허용된 역사 상장·상폐 파일 import는 canonical `instrument_id`, source record key, event type, effective date, evidence state를 요구한다. 이름 또는 현재 code만으로 lifecycle을 연결하지 않는다. 공급자 이용·보관·재배포 조건은 `docs/krx-universe-source-contract.md`와 개별 공급자 계약을 따른다.

## EMA 입력 계약

EMA 일일 입력 계약의 버전은 `validated-observation-close-v3`이다. 이 계약은 DB 조회
결과가 아니라 계산 전에 복사한 불변 input snapshot을 계산기에 전달한다. snapshot은
다음 필드를 가진다.

| 구분 | 필드 |
|---|---|
| identity | instrument ID, source symbol ID, 선택 PriceObservation ID, observation identity snapshot ID, ProviderSymbol mapping ID·상태·유효기간, provider/provider symbol, resolver 버전·확정 시각 |
| 관측 | 거래일, adjustment type, parser version, 종가, 거래량, `observed_at`, payload hash |
| 품질 근거 | 승인 보정 ID 목록, validation case ID·상태·결정, 입력 상태와 사유 |
| 정책 | `validated-observation-close-v3`, provider, adjustment type, 허용 parser version 집합, UTC observation cutoff |

선택기는 policy 후보 중 `(observed_at, PriceObservation ID)` 오름차순의 마지막 관측을
선택한다. close의 승인 보정은 ID 오름차순에서 마지막 유효 보정을 사용한다. 열린
validation case는 `open_validation_case`로, 비수치 또는 비유한 승인 보정은
`invalid_approved_correction`으로 확정한다. identity snapshot의 mapping 상태가
`matched`가 아니거나 한 mapping을 증명하지 못하면 현재 Symbol이나 DailyPrice로 추정하지
않고 사용 불가로 둔다. mapping 유효 범위는 `[valid_from, valid_to)`이므로 `valid_to`와
같은 거래일에는 그 mapping을 사용하지 않는다. source policy, UTC cutoff 또는
`observed_at`이 없거나 cutoff 뒤인 행은 `missing_selected_source`의 사용 불가 행으로
기록한다. 계산기는 이 근거가 없는 행을 정상 입력으로 취급하거나 예외를 내지 않는다.

행 fingerprint는 위 snapshot 전체를 canonical JSON으로 직렬화해 SHA-256으로 계산한다.
canonical JSON은 키를 정렬하고 공백 없이 직렬화하며, Decimal은 유한한 고정 소수 문자열,
날짜는 ISO 8601 날짜, 시각은 UTC RFC 3339 `Z` 문자열로 표현한다. prefix hash는
`{"previous_prefix_hash": ..., "row_fingerprint": ...}`의 canonical JSON SHA-256이다.
따라서 기존 마지막 prefix 뒤에 새 날짜만 추가되면 증분이며, 과거 행 fingerprint의 변경,
삭제 또는 순서 변경은 재계산이 필요한 revision이다. 결과 hash는 기간·거래일 순서의
`period`, `trade_date`, `status`, `value`, `reason_code`, `available_observations`,
`input_prefix_hash`를 같은 방식으로 hash한다.

EMA 행 사유 코드는 아래 값만 허용한다. `warming_up`은 계산 결과이고 나머지는 입력을
사용할 수 없거나 거래정지임을 나타낸다.

`warming_up`, `missing_selected_source`, `identity_unavailable`,
`ambiguous_identity_mapping`, `conflicting_observations`, `approved_exclusion`,
`approved_validation_exclusion`, `open_validation_case`, `invalid_approved_correction`,
`invalid_ohlcv`, `provider_or_adjustment_discontinuity`, `confirmed_trading_halt`.

## 거래량 MA50 내부 저장 계약

거래량 MA50은 공개 API 계약이 아니다. 내부 저장값은 `volume_sma` 종류와 period 50으로 식별한다. 각 입력 거래일에는 결과 하나만 존재한다. `available`은 Decimal 문자열로 표현 가능한 평균값과 null 사유를, `warming_up`은 null 값과 `warming_up` 사유를, `data_unavailable`은 null 값과 입력 불가 사유를 가진다. history input policy는 `validated-observation-ohlcv-v1`이며, 동일 policy·instrument·거래일의 동일 evidence는 재사용하고 달라진 evidence는 새 generation으로만 기록한다.

## ATR14 내부 저장 계약

ATR14 저장값은 `atr` 종류와 period 14, `high-low-close` 입력, `wilder-atr-14-v1` 계산 버전으로 식별한다. 공개 API나 백테스트 dataset에는 아직 연결하지 않는다. 입력 정책은 거래량 MA50과 같은 `validated-observation-ohlcv-v1`이며, 선택기의 불변 high·low·close와 identity·source·품질·보정 근거를 공용 evidence에 함께 보존한다.

같은 순서의 evidence는 완료 결과를 재사용하고, 기존 입력의 순서와 근거를 유지한 날짜 추가는 같은 generation의 새 incremental run에 suffix만 저장한다. 과거 근거 변경·삭제는 새 generation의 rebuild이며, 완료 후에만 이전 current를 superseded로 바꾼다. 각 run은 evidence prefix hash와 해당 run의 정확한 Decimal 계산값·상태·사유·관측 수의 canonical JSON SHA-256 결과 hash를 보존한다. 실패한 시도는 출력과 입력 참조를 롤백한 뒤 예외 종류만 기록하며 이전 current를 유지한다. 호출자가 성공 또는 실패 시도를 자신의 transaction에서 commit한다.
