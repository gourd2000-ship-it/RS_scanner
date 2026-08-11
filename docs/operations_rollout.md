# 운영 전환·rollback runbook

## Universe

첫 배포에서는 `GET /api/v1/crawl/universe-snapshots/{snapshot_id}/dry-run`으로
비활성화 후보를 확인한다. 응답의 `eligible_for_reconcile`가 `true`인 completed
snapshot만 실제 reconcile 대상으로 허용한다. partial/failed snapshot이면 기존
active 상태를 유지하고 다음 정상 snapshot을 기다린다.

## EOD provider canary

공급자 계약이 승인된 뒤에도 한 번에 전체 시장으로 전환하지 않는다.

1. 한 시장 또는 명시된 종목 집합만 EOD adapter에 연결한다.
2. bulk 파일의 기준일·checksum·coverage·저장 건수를 확인한다.
3. coverage 99.5% 이상, 가격 단계 30분 이내 조건을 3회 연속 확인한다.
4. 조건을 만족하면 다음 시장을 추가하고, 실패하면 provider 연결을 끄고 Naver
   fallback queue만 실행한다.

canary 범위는 `EOD_CANARY_MARKETS` 또는 `EOD_CANARY_CODES`로 제한하고,
`EOD_PROVIDER_ENABLED=false`로 EOD 경로를 즉시 끌 수 있다. `EodCanaryPolicy`가
허용되지 않은 종목을 fallback queue로 보내며, `EodCanaryController`는 마지막 관측과
연속 성공 횟수를 원자적으로 저장하고 `rollback()` 호출 시 provider를 비활성화한다.

현재 저장소에는 특정 공급자 credential이나 자동 시장 전환을 넣지 않았다. 따라서
계약 승인 전에는 EOD source를 주입하지 않는 것이 provider feature flag off 절차다.
실제 3회 연속 관측 및 rollback 리허설은 PostgreSQL staging과 계약된 공급자가 필요하다.

## Agent traffic rollback

- `AGENT_API_ENABLED=false`를 Secret/config에 반영하고 배포한다.
- Hermes client는 `GET /api/v1/agent/v1/status`에서 `unavailable` 또는 `stale`을
  확인한 뒤 새 브리핑 생성을 중단한다.
- 마지막 정상 dataset은 DB에 남겨 두되, freshness metadata를 complete로 덮어쓰지
  않는다.
- 인증 문제가 해결되면 새 service token을 추가 배포하고, Hermes 전환 후 이전 token을
  제거한다.

## 대량 비활성화·dataset 불일치

1. 해당 배치 job과 universe snapshot ID를 기록한다.
2. dry-run 후보 수가 평소 범위를 벗어나면 reconcile을 중지한다.
3. provider를 off하고 마지막 정상 dataset을 stale로 제공한다.
4. DB 백업/운영 절차에 따라 잘못된 inactive 변경을 복구한 뒤, 새 snapshot을
   재수집하고 target result와 coverage를 재검증한다.

실제 provider canary와 rollback 리허설은 PostgreSQL staging 및 계약된 공급자 없이는
완료 처리하지 않는다.
