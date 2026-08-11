# Operations metrics 계약

`GET /api/v1/crawl/metrics`는 최신 배치의 품질 지표와 자동 감지된 alert 조건을
반환한다. 배치 target result와 universe snapshot은 DB에서 재계산하므로 프로세스
재시작 후에도 최신 배치 값이 유지된다.

지표 이름:

- `crawl_eligible_total`: 최신 가격 단계 대상 수
- `crawl_fetched_total`: 유효 신규 데이터를 저장한 종목 수
- `crawl_no_new_data_total`: 응답은 유효하지만 신규 거래일이 없는 종목 수
- `crawl_partial_total`: 일부 행만 유효하거나 일부 저장된 종목 수
- `crawl_failed_total`: 최종 실패 종목 수
- `crawl_skipped_total`: 요청 예산·canary·정책으로 건너뛴 종목 수
- `crawl_coverage_rate`: fetched + no_new_data + checkpoint skipped 비율
- `symbols_deactivated_total`: 최신 completed universe snapshot의 비활성화 후보 수
- `crawl_failure_record_error_total`: failure record 저장 실패 counter
- `crawl_parser_error_total`: typed parser error counter
- `crawl_provider_request_total`: provider logical request counter
- `crawl_provider_latency_seconds`: provider 호출 누적 시간(초)
- `crawl_duration_seconds`: 마지막 가격 단계 실행 시간(초)
- `hermes_api_errors_total`: agent API 4xx/5xx와 rate-limit 응답 counter

provider별 세부 counter도 `crawl_provider_request_total.<provider>`,
`crawl_provider_success_total.<provider>`, `crawl_provider_error_total.<provider>`,
`crawl_provider_retry_total.<provider>`, `crawl_provider_latency_seconds.<provider>` 형태로
process-local registry에 기록한다. 현재 registry는 외부 exporter 없이 동작하므로 운영 배포 시
Prometheus/OpenTelemetry exporter 연결이 필요하다.

자동 alert:

- `coverage_below_threshold`: coverage가 99.5% 미만
- `latest_job_not_clean`: 최신 배치가 `completed_with_errors` 또는 `failed`
- `latest_dataset_stale`: 최신 배치 종료 시각이 Agent freshness 한도를 초과
- `repeated_failure_detected`: 최근 3개 배치에 같은 종목·오류 조합이 반복

`crawl_failure_record_error_total`과 `hermes_api_errors_total`은 현재 프로세스
메모리 counter다. 운영 전환 시 이 값을 Prometheus/OpenTelemetry 또는 로그 수집기로
전달하고, 프로세스 재시작 시 counter reset을 허용하지 않는 exporter를 연결해야 한다.
