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

- AGENT_ALLOWED_IPS: CIDR 목록. 비어 있으면 애플리케이션 IP 제한을 적용하지 않는다.
  Compose 운영에서는 API port가 host loopback에만 publish되며, Docker NAT가 실제 caller를
  loopback으로 보지 않을 수 있으므로 container-visible source IP를 검증한 뒤에만 설정한다.
- AGENT_API_ENABLED: emergency off용 feature flag.
- AGENT_FRESHNESS_MAX_AGE_HOURS: complete/partial dataset의 최대 freshness.
- AGENT_RATE_LIMIT: agent 경로의 분당 요청 한도.
- ANALYSIS_API_ENABLED: 사용자 요청 기반 Sam 분석 API feature flag. 기본값은 false다.
- REPAIR_API_ENABLED 및 LEGACY_REPAIR_API_ENABLED: 보존된 repair API를 명시적으로 열 때만 함께 true로 둔다. 일일 batch의 기본 경로는 아니다.

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

## Sam 주간 분석 API (현행 내부 계약)

Sam은 일일 crawl 완료에 의해 자동 호출되지 않는다. 사용자가 operator token으로
`POST /internal/v1/crawl-analysis/requests`를 만들 때만 업무가 시작된다.

OpenAPI의 모든 internal analysis/Codex operation에는 `InternalBearerAuth` HTTP bearer
security scheme와 `x-required-scopes`가 표시된다. 이는 token 값이 아니라 해당 operation에
필요한 최소 scope를 나타낸다.

최소 scope:

- operator: `analysis:request`, `analysis:read`, `analysis:review`
- Sam: `analysis:read`, `analysis:accept`, `analysis:submit`
- Codex: `analysis:read`, `codex:request`, `codex:result`

token의 보관 위치는 분리한다. autobot API 서버의 `AGENT_SERVICE_TOKENS`에는 각 token과
scope 매핑이 있어야 하지만, gourd/Sam 실행 환경에는 Sam token만
`RS_SCANNER_SAM_ANALYSIS_TOKEN`으로 주입한다. operator/Codex token은 Sam profile에
복사하지 않는다.

제공 경로:

- `GET /internal/v1/crawl-analysis/quality-reports`, `/{report_id}`
- `GET /internal/v1/crawl-analysis/failures`, `/target-results`, `/stock-history/{symbol}`
  - `/target-results`는 `job_id`와 선택적 정확 일치 `target_key`, `step_name`을 받습니다.
    Sam은 전체 결과를 페이지 순회하지 않고 선정한 표본 종목·단계를 조회합니다.
- `POST /internal/v1/crawl-analysis/requests`, `/{request_id}/accept`, `/{request_id}/report-hash`, `/{request_id}/report`
- `GET /internal/v1/crawl-analysis/requests/{request_id}/quality-reports`
- `POST /internal/v1/codex-change-requests`, `/{id}/result`, `/{id}/review`

분석 요청은 `requested → accepted → report_ready → codex_reviewed`를 거쳐,
사용자 승인으로 `implemented`, `partially_implemented`, `deferred` 중 하나로 끝난다.
Sam은 API 읽기 데이터와 제한된 Kiwoom evidence만 사용하며 PostgreSQL과 canonical
가격 테이블에 접근하지 않는다.

autobot operator는 `scripts/get_crawl_analysis_request.py --request-id <id>`로 요청 상태와
API에 저장된 Markdown/JSON 보고서를 조회한다. 이 조회는 polling daemon이나 webhook이
아니며 사용자가 Codex 검토를 시작할 때 명시적으로 실행하는 확인 절차다.

## Legacy Sam Repair API (보존 전용)

Hermes Agent의 읽기 전용 데이터 API와 과거 Sam Kiwoom repair API는
서로 다른 서비스 경계와 token scope를 사용한다. endpoint와 contract test는 구현되어
있지만 `REPAIR_API_ENABLED=false`와 `LEGACY_REPAIR_API_ENABLED=false`가 기본값이므로
새 운영 경로에서는 활성화하지 않는다.

허용 scope:

- `repair:claim`: 대기 중인 repair 업무 한 건 조회 및 claim
- `repair:submit`: claim한 업무의 성공 결과 제출
- `repair:fail`: claim한 업무의 제한된 실패 결과 제출

Hermes token(`rs:read`, `stock:read`, `status:read`)에는 위 scope를 추가하지 않는다.
Sam은 PostgreSQL credential, generic SQL, canonical 가격 수정 권한을 받지 않는다.

### 업무 흐름

```text
POST /internal/v1/repair/requests/claim
  → request_id, claim_token, claim_version, symbol, from, to, adjusted_price
  → Sam의 kiwoom-ohlc-query 스킬 실행
  → complete 또는 fail 제출
  → autobot reconciler가 applied/conflict/rejected 결정
```

endpoint 계약:

- `POST /internal/v1/repair/requests/claim`: `SELECT ... FOR UPDATE SKIP LOCKED`와
  짧은 lease를 사용한다. 초기에는 한 종목·한 기간 요청만 반환한다.
- `POST /internal/v1/repair/requests/{request_id}/complete`: claim token과
  `claim_version`(request version), 정규화된 OHLC 행, `latest_date`, `row_count`, `data_complete`, executor,
  tool, mode, result hash를 요구한다.
- `POST /internal/v1/repair/requests/{request_id}/fail`: claim token, claim version,
  `error_code`, `retryable`,
  API/HTTP 상태, 제한된 오류 메시지를 저장한다. 429와 빈 결과를 성공으로 바꾸지 않는다.
- `GET /internal/v1/repair/requests/{request_id}`: 상태·시도·반영 결과를 운영자가
  확인할 때 사용한다. 원본 secret과 응답 전문은 반환하지 않는다.

repair request 상태(`pending`, `processing`, `completed`, `failed`, `expired`)와
반영 상태(`not_applied`, `applied`, `conflict`, `rejected`)를 분리한다. `completed`는
canonical DB 반영 완료를 뜻하지 않는다.

## Conditional requests

응답에는 ETag, Last-Modified, X-Dataset-Id, X-Data-As-Of,
X-Data-Status, X-Coverage, X-Request-Id가 포함된다. 같은 dataset과
query를 If-None-Match로 재요청하면 304를 반환한다.
