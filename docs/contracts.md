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

backtest 요청의 `start`와 `end`는 포함 범위다. cursor는 요청 필터와 dataset ID에 묶이며, 데이터가 바뀌어 일관된 page를 보장할 수 없으면 409를 반환한다. `strict` 결과도 `complete` 구간 조건을 완화하지 않는다. 가격 없는 기대 행, `partial` 구간, 상장폐지 lifecycle은 현재 발행 대상이 아니다.

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
않고 사용 불가로 둔다.

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
