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
