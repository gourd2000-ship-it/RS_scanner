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

## Data-quality validation rollout

초기 배포는 `VALIDATION_MODE=report_only`로 유지한다.

일일 스케줄 배치(`scripts/run_daily_batch.sh`)는 가격 동기화가 끝난 직후
deterministic validation을 실행하고, 완료되면 자동으로
`reports/data_quality/job_<job_id>.json`을 원자적으로 저장한다. 리포트 파일 쓰기에
실패하더라도 이미 DB에 저장된 validation run/case와 RS 실행을 되돌리지는 않고 로그로
알린다.

```bash
python scripts/validate_data_quality.py --job-id <job_id>
```

이 명령은 외부 요청을 다시 보내지 않고 저장된 crawl target/failure/price/benchmark
자료를 replay한다. `reports/data_quality/job_<id>.json`에 rule별 evidence와
fresh coverage, RS input freshness를 남긴다.

실패 대상만 bounded retry할 때는 다음 명령을 사용한다.

```bash
python scripts/retry_failed_targets.py --job-id <job_id>
```

재시도는 운영자가 필요할 때 별도로 실행하는 절차이며, 일일 스케줄 배치가 자동으로
호출하지 않는다. 재시도 후에는 validation을 다시 실행한다. `CRAWL_RETRY_MAX_ATTEMPTS`
이상 시도한 target은 자동으로 제외한다. `VALIDATION_MODE=enforce` 전환은 최소 10개 거래일 report-only
관측, false-positive 검토, benchmark/freshness 정책 승인을 완료한 뒤에만 진행한다.
enforce에서 blocked이면 새 RS를 생성하지 않고 RS checkpoint를 `blocked`로 기록한다.
