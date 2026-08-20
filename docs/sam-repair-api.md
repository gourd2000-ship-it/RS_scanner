# Sam Repair API 업무 절차 (Legacy)

> 이 repair API와 종목별 자동 복구 흐름은 신규 배치 경로에서 사용하지 않습니다. 현재 Sam의 역할은 사용자가 명시적으로 생성한 주간 분석 요청을 수락하고, 제한된 Kiwoom 표본을 근거로 개선 제안을 제출하는 것입니다. 최신 계약은 [주간 크롤링 품질 분석 PRD](prd-weekly-crawl-quality-analysis.md)를 참고하세요.

이 문서는 Sam이 PostgreSQL이나 공유 폴더에 접근하지 않고 Kiwoom 읽기 업무를 처리하는
방법을 정의한다. `worker mode`나 상시 실행을 요구하지 않는다. autobot이 업무를 요청할
때마다 아래 순서로 한 건을 처리한다.

## 원칙

- 허용 업무는 국내주식 `daily_chart` 하나다.
- 허용 도구는 읽기 전용 `kiwoomcli domestic candles daily` 하나다.
- 주문, 계좌, 잔고, 토큰 발급, 임의 shell 명령, DB 직접 접근은 하지 않는다.
- 결과는 Repair API로만 제출한다. canonical `daily_prices`는 autobot reconciler만 수정한다.
- `data_complete=false`, 빈 결과, 부분 결과, HTTP 429, 인증 실패는 성공 제출로 바꾸지 않는다.

Repair API는 기본 비활성화다. staging canary 승인 뒤에만 `REPAIR_API_ENABLED=true`와
`repair:claim`, `repair:submit`, `repair:fail` scope를 가진 별도 service token을 사용한다.

## 한 업무 처리

1. 업무 요청

```http
POST /internal/v1/repair/requests/claim
Authorization: Bearer <repair-token>
Content-Type: application/json

{"claimed_by":"sam"}
```

응답에는 `request_id`, `claim_token`, `claim_version`, `symbol`, `from`, `to`,
`adjusted_price`가 포함된다. 응답이 `204`이면 대기 업무가 없으므로 완료한다.

2. Kiwoom 조회

업무 응답의 `symbol`, `to`, `adjusted_price`를 사용해 다음 명령만 실행한다.

```text
kiwoomcli domestic candles daily --code <symbol> --date <to:YYYYMMDD> --format json
```

반환 JSON에서 `from <= trade_date <= to`인 정규화된 행만 사용한다. 날짜 중복, OHLC
관계 오류, 양수 가격 위반, 요청 범위 밖 행이 있으면 성공 결과로 제출하지 않는다.

3. 성공 제출

성공할 때 claim 응답의 `claim_token`과 `claim_version`을 그대로 포함한다.

```http
POST /internal/v1/repair/requests/<request_id>/complete
Authorization: Bearer <repair-token>
Content-Type: application/json

{
  "claim_token": "<claim-token>",
  "claim_version": 1,
  "operation": "daily_chart",
  "symbol": "005930",
  "from": "2026-08-01",
  "to": "2026-08-14",
  "adjusted_price": true,
  "executor": "sam",
  "tool": "kiwoomcli",
  "mode": "demo",
  "latest_date": "2026-08-13",
  "row_count": 1,
  "data_complete": true,
  "rows": [
    {
      "symbol": "005930",
      "trade_date": "2026-08-13",
      "source": "kiwoom",
      "adjusted_price": true,
      "open": "70000",
      "high": "71000",
      "low": "69500",
      "close": "70500",
      "volume": 1000000,
      "change_rate": "0.71"
    }
  ]
}
```

`claim_version`은 claim 응답의 값을 사용한다. 오래된 claim 또는 이미 완료된 업무를
다시 제출하면 거부된다. API의 `completed`는 canonical 반영 완료가 아니다. autobot이
Naver 값과 비교한 뒤 `applied`, `conflict`, `rejected` 중 하나로 결정한다.

4. 실패 제출

429, 인증 실패, 빈 응답, 부분 결과, timeout은 다음처럼 제한된 정보만 제출한다.

```http
POST /internal/v1/repair/requests/<request_id>/fail
Authorization: Bearer <repair-token>
Content-Type: application/json

{
  "claim_token": "<claim-token>",
  "claim_version": 1,
  "error_code": "rate_limit",
  "error_message": "Kiwoom API rate limit",
  "retryable": true,
  "http_status": 429,
  "retry_after_seconds": 60
}
```

token, secret, 계좌번호, 원본 응답 전문은 오류 메시지나 `details`에 넣지 않는다.
lease가 만료된 업무는 새 claim을 기다리며, 이전 claim의 결과를 덮어쓰지 않는다.
