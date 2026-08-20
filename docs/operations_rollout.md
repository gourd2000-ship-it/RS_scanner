# 운영 전환·rollback runbook

> 2026-08-15 전환: 이 문서의 종목별 repair canary 절차는 legacy 기록이다. 현행 운영은
> [Sam 주간 크롤링 품질 분석과 Codex 개선 루프 PRD](prd-weekly-crawl-quality-analysis.md)를
> 따른다. 일일 batch는 Sam·Kiwoom·repair queue를 자동 호출하지 않는다.

## Universe

첫 배포에서는 `GET /api/v1/crawl/universe-snapshots/{snapshot_id}/dry-run`으로
비활성화 후보를 확인한다. 응답의 `eligible_for_reconcile`가 `true`인 completed
snapshot만 실제 reconcile 대상으로 허용한다. partial/failed snapshot이면 기존
active 상태를 유지하고 다음 정상 snapshot을 기다린다.

## Price provider canary

Naver를 주 공급자로 유지하고, Kiwoom 복구는 PostgreSQL repair queue와 Sam 전용
Repair API를 통해 한 번에 한 업무씩 제한한다. Sam은 `kiwoom-ohlc-query` 스킬로
읽기 전용 조회를 수행하며 PostgreSQL 또는 canonical DB에 직접 접근하지 않는다.
공유 폴더 파일 브리지는 전환 전 legacy 진단 경로이며 신규 canary의 기본 경로로
사용하지 않는다. 상세 계약은 [크롤링 분석 후속 PRD](prd-crawl-analysis-followup.md)를
따른다.

1. synthetic request로 queue 상태 전이와 Repair API 인증·lease를 확인한다.
2. Naver 실패 종목 중 한 종목만 Sam 업무로 전달하고, Kiwoom 응답의 기준일·조정주가·
   completeness·출처 충돌을 확인한다.
3. coverage 99.5% 이상, 가격 단계 30분 이내, rate-limit 오류 허용 범위 조건을
   단일 종목 → 5~10종목 → 100~300종목 단계에서 3회 연속 확인한다.
4. 조건을 만족하면 fallback 대상 범위를 확대하고, 실패하면 Repair API와 Kiwoom을 끄고
   pending queue를 보류·재시도 정책에 따라 처리한다.

Repair API를 활성화한 배치에서는 기존 직접 Kiwoom fallback을 함께 켜지 않는다. 애플리케이션이
중복 경로를 자동 차단하지만, 운영 설정에서도 `KIWOOM_FALLBACK_ENABLED=false`를 유지한다.

completed 결과 반영은 다음 명령으로 bounded하게 실행한다.

```bash
python scripts/apply_repair_results.py --limit 100
```

이 명령은 autobot DB 세션에서만 실행되며, Naver 값과 충돌하거나 품질 계약을 벗어난
결과는 `conflict`/`rejected`로 남기고 `daily_prices`를 수정하지 않는다.

canary 범위는 `KIWOOM_FALLBACK_CODES=005930,000660,...` allowlist와
`KIWOOM_FALLBACK_ENABLED`로 제한한다. 초기 canary에서는 allowlist를 반드시 설정한다.
rate limiter가 허용된 호출량을 넘지 않도록 하며, canary controller는 마지막 관측과
연속 성공 횟수를 원자적으로 저장하고 rollback 시 Kiwoom 업무 enqueue/claim을
비활성화한다.

현재 저장소에는 Kiwoom credential을 커밋하지 않는다. 사용 등록·계정·IP 정책과 데이터
사용 범위를 확인하기 전에는 adapter를 주입하지 않는다. 실제 3회 연속 관측 및 rollback
리허설은 PostgreSQL staging과 활성화된 Kiwoom REST 계정이 필요하다.

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
