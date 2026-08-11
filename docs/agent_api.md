# Hermes Agent API 운영 계약

## Secret 주입

AGENT_SERVICE_TOKENS는 저장소에 커밋하지 않고 배포 Secret 또는 secret
manager에서 주입한다.

형식 예:

    current-token=rs:read,stock:read,status:read;next-token=status:read

세미콜론으로 여러 token을 동시에 활성화할 수 있다. rotation은 새 token을
추가해 배포한 뒤 Hermes client를 전환하고, 이전 token을 제거하는 순서로
진행한다. token 원문은 로그나 응답에 기록하지 않는다.

선택 설정:

- AGENT_ALLOWED_IPS: CIDR 목록. 비어 있으면 IP 제한을 적용하지 않는다.
- AGENT_API_ENABLED: emergency off용 feature flag.
- AGENT_FRESHNESS_MAX_AGE_HOURS: complete/partial dataset의 최대 freshness.
- AGENT_RATE_LIMIT: agent 경로의 분당 요청 한도.

허용 scope는 rs:read, stock:read, status:read이며, agent router에는
배치 실행·재수집 mutation endpoint를 포함하지 않는다.

## Versioned endpoints

모든 응답은 아래 envelope을 사용한다.

    {
      "data": {},
      "meta": {
        "dataset_id": "rs-123-2026-08-10",
        "trade_date": "2026-08-10",
        "as_of": "2026-08-11T08:00:00",
        "data_status": "complete",
        "coverage": 1.0,
        "request_id": "..."
      }
    }

제공 경로:

- GET /api/v1/agent/v1/status (status:read)
- GET /api/v1/agent/v1/briefing (rs:read)
- GET /api/v1/agent/v1/rankings/rs (rs:read)
- GET /api/v1/agent/v1/stocks/{code} (stock:read)
- GET /api/v1/agent/v1/stocks/{code}/history (stock:read)

data_status는 complete, partial, stale, unavailable 중 하나다.
unavailable인 데이터 조회는 503과 Retry-After를 반환한다.

## Conditional requests

응답에는 ETag, Last-Modified, X-Dataset-Id, X-Data-As-Of,
X-Data-Status, X-Coverage, X-Request-Id가 포함된다. 같은 dataset과
query를 If-None-Match로 재요청하면 304를 반환한다.
