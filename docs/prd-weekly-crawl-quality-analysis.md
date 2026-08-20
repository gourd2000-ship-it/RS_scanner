# PRD: Sam 주간 크롤링 품질 분석과 Codex 개선 루프

- 상태: autobot 구현·배포 검증 완료 / Sam token 주입 및 gourd 측 실행 절차 적용 대기
- 작성일: 2026-08-15
- 대상: RS Scanner (autobot), Hermes Sam (gourd), 사용자 실행 Codex
- 선행 문서: [크롤링 신뢰성 및 Hermes PRD](prd-crawling-reliability-hermes.md), [기존 repair 후속 PRD](prd-crawl-analysis-followup.md)

## 1. 결정 요약

RS Scanner는 매 크롤링 뒤에 성공·실패 기록과 품질 보고서만 남긴다. 크롤링 실패나
성공 자체는 Sam을 호출하는 사유가 아니다. 사용자가 주간 분석을 명시적으로 요청할
때에만 Sam이 제한된 표본을 Kiwoom과 RS Scanner의 읽기 전용 데이터로 비교하고,
크롤러 개선 제안 보고서를 제출한다.

Kiwoom은 가격 복구 공급자나 canonical 데이터의 자동 대체원이 아니다. 분석의 가설을
검증하는 증거 표본에만 사용하며, Sam은 어떤 경우에도 RS Scanner DB를 직접 수정하지
않는다. Codex는 사용자가 선택·승인한 제안만 구현하고 검증 결과를 남긴다.

이 문서는 기존 `crawl_repair_requests` 기반의 종목별 자동 복구 흐름을 새 기본 경로로
사용하지 않는다. 기존 테이블·파일 브리지·결과는 파괴적으로 삭제하지 않고 legacy로
보존한다.

## 2. 확정된 운영 결정

| 항목 | 확정 내용 |
|---|---|
| 분석 요청 생성 | 사용자가 autobot 계정에서 실행하는 감사 가능한 로컬 CLI가 API를 호출한다. UI, 배치 자동 생성, webhook은 초기 범위에서 제외한다. |
| 기본 분석 범위 | 요청 시점 이전의 **완료된 최근 7개 일일 배치**. 기간이 불연속이어도 완료된 배치만 포함한다. 사용자는 `ad_hoc`으로 범위를 바꿀 수 있다. |
| 계정 간 통신 | 같은 호스트의 `127.0.0.1`에 publish된 내부 API만 사용한다. Sam, 사용자/운영자, Codex는 서로 다른 bearer token과 최소 scope를 사용한다. |
| 보고서·evidence 보관 | API DB에 Markdown과 구조화 JSON을 1년 보관한다. Kiwoom 원시 행·응답 전문은 저장하지 않고, 조회 범위·행 수·해시·비교 요약만 보관한다. |
| Codex 승인 | 사용자가 proposal을 `approved`로 만들고 최종 `implemented`/`deferred`를 결정한다. Codex는 코드·테스트를 수행해 `verified`와 결과만 기록한다. |
| 기존 repair request | 기존 pending request는 삭제하지 않고 `legacy_hold`로 이동한다. claim 대상 및 일반 queue 지표·알림에서 제외한다. |

## 3. 목표와 비목표

### 목표

1. 모든 crawl job에 사람이 읽고 API로 조회 가능한 품질 보고서 하나를 남긴다.
2. 종목 성공 수와 failure event 수를 분리하고, 오류 분포·반복 실패·이상치·coverage를 같은 스냅샷으로 보존한다.
3. 사용자가 만든 분석 요청에 대해 Sam의 수락과 보고서 제출 여부를 API 상태로 확인한다.
4. Sam의 Kiwoom 비교를 오류 유형별 제한 표본으로 한정하고, 증거와 가설을 구분한다.
5. Codex가 실제 저장소와 테스트로 제안을 재검증하고, 사용자 승인 경계를 넘지 않게 한다.

### 비목표

- 크롤링 완료 후 Sam을 자동 호출하거나 Sam이 정기적으로 요청을 탐색하게 하지 않는다.
- 실패 종목마다 Kiwoom을 재조회하거나 Kiwoom을 Naver의 자동 폴백으로 사용하지 않는다.
- Sam에게 PostgreSQL, canonical `daily_prices`, RS 결과의 쓰기 권한을 주지 않는다.
- Codex가 사용자 승인 없이 코드를 변경하거나 운영 반영하지 않는다.
- 주문·계좌·잔고·토큰 발급 기능, 공유 폴더 기반 새 업무 흐름은 만들지 않는다.

## 4. 목표 흐름

```text
[autobot 일일 크롤링]
  crawl_jobs / crawl_target_results / crawl_failures 기록
              ↓
  crawl_quality_reports 생성
              ↓
  종료: Sam 호출 없음, Kiwoom 호출 없음

[사용자의 주간 분석 요청]
  audited local CLI → Analysis API → crawl_analysis_requests(requested)
                                      ↓
                            Sam이 accept API 호출
                                      ↓
                품질 보고서·오류 표본·가격 이력 읽기 전용 조회
                                      ↓
                    필요 표본만 Kiwoom CLI로 대조
                                      ↓
            Markdown + JSON 보고서 제출 → report_ready

[사용자가 Codex 실행]
  proposal 선택·승인 → Codex가 저장소/테스트로 재검증
                                      ↓
        codex_change_requests에 verified 결과 기록
                                      ↓
          사용자가 implemented / deferred / partially_implemented 결정
```

API의 상태 기록이 계정 간 업무 수락·결과 전달의 정본이다. Sam의 채팅 세션, 개인 파일,
알림 전달 성공은 보조 정보일 뿐 업무 수락이나 보고서 제출의 증명이 아니다.

Sam의 report 제출은 API transaction 안에서 `crawl_analysis_reports`를 저장하고 request를
`report_ready`로 전이한다. autobot은 Sam에게 webhook을 받지 않으며, 사용자 또는 Codex가
operator token으로 request 상태를 조회할 때 Markdown·JSON 보고서를 API에서 읽는다.

## 5. 책임 경계

| 주체 | 책임 | 금지 |
|---|---|---|
| autobot / RS Scanner | 품질 보고서 생성, API·DB 계약, 상태 전이, 권한, 배포, 테스트, legacy 경로 동결 | 배치 실패마다 Sam 호출, Kiwoom 가격 자동 반영 |
| Sam | 분석 수락, 오류 분류, 표본 선택, Kiwoom·DB 비교, Markdown/JSON 보고서 제출 | DB 직접 접속·수정, 전체 실패 종목 재조회, 자동 코드 수정 |
| Codex | 사용자가 승인한 proposal의 코드 변경·테스트·검증 결과 기록 | 자체 승인, 보고서 가설을 사실로 간주, 범위 확대 |
| 사용자 | 분석 요청, proposal 승인, Codex 실행, 최종 반영·보류 | 검토 없는 자동 운영 반영 |

Sam의 로컬 knowledge base 사본은 선택적 보관물이다. API에 제출된 `markdown_body`,
`report_json`, `report_hash`가 정본이며 API는 Sam 파일시스템의 해시를 독립적으로
검증할 수 없다는 점을 명시한다.

## 6. 데이터 모델과 상태

### 6.1 `crawl_quality_reports`

각 crawl job에 정확히 하나의 immutable 품질 보고서를 저장한다. 보고서 내용의 schema
변경은 `report_schema_version`으로 표현하며, 같은 job에 여러 버전을 쓰지 않는다.
재생성이 필요하면 기존 보고서를 변경하지 않고, 운영자가 별도 재생성 기록을 남긴 뒤
새 analysis request에서 그 사유를 명시한다.

주요 필드:

```text
id, crawl_job_id (UNIQUE), report_schema_version
trade_date, job_type, job_status
symbols_total, symbols_succeeded, symbols_failed, failure_event_count
success_rate, coverage_rate
error_distribution, repeated_failure_summary, anomaly_summary
sample_refs, source_snapshot, report_hash
created_at
```

- `sample_refs`에는 `crawl_failure.id`, `crawl_target_result.id` 등 상세 레코드 참조만 넣는다.
- failure 원문과 Kiwoom 원시 행을 무제한 JSON으로 복제하지 않는다.
- job이 예외로 실패했어도 가능한 범위에서 보고서를 생성한다. 보고서 작성 실패는
  `quality_report_write_error` metric과 재생성용 운영 기록으로 남기며, crawl job 결과를
  성공으로 바꾸지 않는다.

표준 오류 유형은 최소 `no_data_rows`, `invalid_ohlc`, `corporate_action`,
`network_error`, `parse_error`, `persistence_error`, `stale_job`, `unclassified`를
포함한다. 오류 유형별 event 수와 고유 종목 수를 함께 기록한다.

### 6.2 `crawl_analysis_requests`

사용자가 명시적으로 만든 분석 업무만 저장한다. 배치 완료 경로에는 이 테이블을
생성하는 코드가 없어야 한다.

```text
id, request_id (UNIQUE), idempotency_key (UNIQUE)
requested_by, request_kind (weekly | ad_hoc)
status, period_from, period_to, completed_job_ids
error_types, markets, sample_limit, reason
accepted_by, requested_at, accepted_at, report_id
last_error_code, last_error_message, created_at, updated_at
```

`completed_job_ids`는 품질 보고서 ID가 아니라 선택된 crawl job ID다. 요청을 생성할 때
서버가 각 job의 `crawl_quality_reports` 존재를 검증하고, 실제 보고서 참조는
`crawl_analysis_request_quality_reports` association table로 보관한다. 이로써 job ID와
quality report ID를 혼용하지 않는다.

기본 `sample_limit`은 주간 요청 전체 10종목, 오류 유형별 최대 3종목이다. 서버는 더 큰
값을 거부하며, 사용자 사유가 있는 `ad_hoc`도 이 상한을 넘을 수 없다.

### 6.3 `crawl_analysis_reports`

v1에서는 요청당 final report 하나만 허용한다. 수정이 필요하면 기존 보고서를 덮어쓰지
않고 이전 보고서를 참조한 새 `ad_hoc` analysis request를 만든다.

```text
id, request_id (UNIQUE), created_by
analysis_window, quality_report_refs
findings, kiwoom_evidence, recommendations, limitations
markdown_body, report_json, report_hash, created_at
```

`report_json`은 `schema_version: 1`을 포함하며, finding과 recommendation이 없을 때는
그 이유를 `limitations`에 명시해야 한다. API는 credential·token·계좌 정보 패턴을
검사하고, 제한을 넘는 body·evidence를 거부한다.

종료 상태(`implemented`, `partially_implemented`, `deferred`)의 요청·보고서·Codex audit
record는 1년간 보관한다. autobot 운영자는 기본 dry-run인
`scripts/prune_crawl_analysis_records.py`를 검토한 뒤에만 `--apply`로 삭제할 수 있다.
`requested`, `accepted`, `report_ready`, `codex_reviewed` 요청은 이 명령의 삭제 대상이 아니다.

### 6.4 `codex_change_requests`

보고서의 proposal 하나당 별도 change request를 둔다.

```text
id, change_request_id (UNIQUE), report_id, proposal_id
status, requested_by, approved_by
target_files, change_scope, risk_level, verification_plan
codex_run_id, commit_ref, test_results, review_notes
created_at, updated_at
```

proposal 상태는 `proposed → approved → running → verified → implemented` 또는
`deferred`/`failed`다. analysis request의 주 상태는 다음과 같다.

```text
requested → accepted → report_ready → codex_reviewed
                                            ├→ implemented
                                            ├→ partially_implemented
                                            └→ deferred
```

`partially_implemented`는 여러 proposal 중 일부만 최종 반영된 경우의 정직한 종료 상태다.
Codex는 `verified`까지만 쓸 수 있으며, 최종 상태는 사용자 권한으로 전이한다.

## 7. API 및 인증 계약

### 7.1 네트워크와 token

- API는 같은 호스트에서 `http://127.0.0.1:8000`으로 통신한다. 외부 노출과 공유 폴더를
  새 분석 경로에 사용하지 않는다.
- Docker Compose의 host port는 `127.0.0.1`에만 publish한다. Docker NAT 때문에 컨테이너가
  host 요청을 loopback IP로 보지 않을 수 있으므로, `AGENT_ALLOWED_IPS`는 실제
  container-visible source IP를 probe로 검증하기 전까지 비워 둔다. 내부 API 앞에 신뢰된
  reverse proxy를 두지 않으므로 caller가 보낸 `X-Forwarded-For`는 allowlist 판단에 사용하지 않는다.
- token은 역할별로 분리·회전하며 토큰 값은 문서, 보고서, 테스트 출력에 남기지 않는다.

| 주체 | 최소 scope |
|---|---|
| 사용자/운영자 CLI | `analysis:request`, `analysis:read`, `analysis:review` |
| Sam | `analysis:read`, `analysis:accept`, `analysis:submit` |
| Codex | `analysis:read`, `codex:request`, `codex:result` |

### 7.2 API 표면

민감한 failure 상세와 분석 업무는 모두 인증된 internal API로 제공한다.

```text
GET  /internal/v1/crawl-analysis/quality-reports
GET  /internal/v1/crawl-analysis/quality-reports/{report_id}
GET  /internal/v1/crawl-analysis/failures
GET  /internal/v1/crawl-analysis/target-results
GET  /internal/v1/crawl-analysis/stock-history/{symbol}

POST /internal/v1/crawl-analysis/requests
GET  /internal/v1/crawl-analysis/requests/{request_id}
POST /internal/v1/crawl-analysis/requests/{request_id}/accept
GET  /internal/v1/crawl-analysis/requests/{request_id}/quality-reports
POST /internal/v1/crawl-analysis/requests/{request_id}/report-hash
POST /internal/v1/crawl-analysis/requests/{request_id}/report

POST /internal/v1/codex-change-requests
GET  /internal/v1/codex-change-requests/{change_request_id}
POST /internal/v1/codex-change-requests/{change_request_id}/result
POST /internal/v1/codex-change-requests/{change_request_id}/review
```

일반 공개 crawl endpoint는 요약 정보만 유지할 수 있지만, Sam은 위 internal endpoint를
사용한다. 읽기 API는 페이지네이션, 최대 기간, 최대 행 수를 강제하고 source·trade date·
adjusted-price 여부·조회 범위를 반환한다.

`target-results`는 `job_id` 외에 정확 일치 `target_key`와 `step_name` 필터를 제공한다.
Sam은 전체 target 결과를 순회하지 않고, 선정된 증거 표본만 종목·단계별로 조회한다.

분석 요청은 `request_id`와 `idempotency_key`를 받아 중복 시 기존 요청을 반환한다.
`accept`는 단순 GET가 아니라 `requested → accepted` mutation이며 `accepted_by="sam"`
을 요구한다. 이 기록이 Sam이 업무를 수락했다는 운영상 증거다.

보고서 제출은 다음을 원자적으로 수행한다.

1. caller scope, `request_id`, 요청 상태 `accepted`를 검증한다.
2. Markdown, JSON schema, 표본 상한, evidence 범위, credential 차단을 검증한다.
3. 보고서와 SHA-256 `report_hash`를 저장한다.
4. 요청을 `report_ready`로 전이한다.

## 8. Sam 분석·Kiwoom evidence 정책

Sam은 오류 유형별로 분석 질문을 먼저 세우고 표본을 선택한다. 예시는 다음과 같다.

| 오류 유형 | Kiwoom 사용 | 표본 | 목적 |
|---|---|---|---|
| `no_data_rows` | 필요 시 | 반복 실패·최근 실패 각 1~3개 | 거래 이력 존재 여부와 Naver 공백 가설 확인 |
| `invalid_ohlc` | 필요 | 1~3개 | OHLC 관계, 0/음수, 조정주가 차이 검증 |
| `corporate_action` | 필요 | 1~3개 | 기준일·수정주가·가격 단절 가설 검증 |
| `network_error`, 429 | 기본 생략 | 로그·retry metadata | 공급자 장애와 데이터 오류 구분 |
| stale job·counter 불일치 | 생략 | job/checkpoint/report | 제어 흐름과 집계 진단 |

Kiwoom evidence에는 symbol, 오류 유형, 기간, Kiwoom 행 수·최신일·결과 hash,
RS Scanner API 조회 범위·행 수, 날짜/값 비교 요약, 결론만 보관한다. 빈 응답, 429,
시간 초과, API 오류, 표본 부족은 성공 evidence가 아니라 limitation 또는 failed evidence로
기록한다. 429 직후 임의 재시도와 전체 실패 종목 재조회는 금지한다.

## 9. autobot 구현 단계

### Phase A — 계약·운영 기반

- 현재 checkout, test DB, Alembic 실행 경로, container 배포 명령을 확인한다.
- operator/Sam/Codex token을 별도로 발급·주입하고, `AGENT_ALLOWED_IPS` loopback 정책을 검증한다.
- 사용자용 로컬 CLI `scripts/request_crawl_analysis.py`를 설계한다. CLI는 DB를 직접 쓰지 않고 internal API를 호출한다.
- 기존 repair request `id=1`을 삭제하지 않고 `legacy_hold`로 migration하며, claim·reaper·일반 metric에서 제외한다.

### Phase B — 품질 보고서

- `CrawlQualityReport` model, repository, builder, Alembic migration을 추가한다.
- batch `_finish_job()` 이후 별도 transaction으로 immutable report를 만든다. 정상·`completed_with_errors`·fatal failure 경로를 모두 다룬다.
- error taxonomy, 반복 실패, coverage, sample refs를 계산하고 `quality_report_write_error` metric 및 재생성 운영 명령을 추가한다.
- 운영자는 `scripts/backfill_crawl_quality_reports.py --job-id <id>` 또는 확인용
  `--latest-missing --limit 7 --dry-run`으로 누락된 완료 일일 job만 backfill할 수 있다. 이 명령은 기존
  보고서를 수정하지 않으며 analysis request·Sam·Kiwoom 호출을 만들지 않는다.
- 테스트: job당 하나, failure event/종목 수 분리, builder 실패가 batch 상태를 위조하지 않음, analysis request 0건, Sam/Kiwoom 호출 0건.

### Phase C — 읽기·분석 요청 API

- internal quality report/failure/history read API와 페이지네이션·범위 제한을 만든다.
- request model, state machine, idempotency, association table, `accept` endpoint를 만든다.
- 테스트: scope 분리, 잘못된 상태 409, 요청 중복, 최근 7개 완료 job 선택, sample limit 거부.

### Phase D — Sam 보고서 수신 API

- report model, JSON validator, credential redaction 검사, report hash를 구현한다.
- 보고서 저장과 `report_ready` 상태 전이를 한 transaction으로 처리한다.
- 테스트: 성공 제출, accepted 이전 제출 거부, schema 오류, secret 문자열, 표본 상한, Kiwoom 429 limitation, 중복 report 거부.

### Phase E — Codex 변경 기록과 legacy 경계

- proposal 단위 codex change request와 사용자 승인·최종 상태 API를 추가한다.
- Codex가 저장소 변경 전 scope와 target files를 기록하고, 실행 뒤 실제 테스트 결과·commit ref를 제출하도록 한다.
- 정상 batch에서 repair enqueue, Kiwoom fallback, file bridge 호출이 없음을 테스트한다.
- `KIWOOM_FALLBACK_ENABLED=false`를 기본 운영값으로 유지하고 legacy repair API/bridge는 명시적 legacy 설정에서만 노출한다.

### Phase F — staging 검증

- fake crawl로 quality report 하나와 분석 요청 0건을 확인한다.
- 사용자 CLI로 weekly request 하나를 만들고 Sam accept → read API → mock Kiwoom evidence → report_ready를 확인한다.
- 사용자 승인 proposal 하나로 Codex verified → 사용자 implemented/deferred 전이를 확인한다.
- 실제 Kiwoom은 단일 분석 요청의 제한 표본으로만 사용하며, 최소 3회의 주간 분석 후 legacy repair 완전 비활성화를 별도 검토한다.

## 10. 완료 기준

- 모든 새 crawl job에 품질 보고서 하나가 생성되고, 보고서 실패는 별도 관측된다.
- crawl 완료만으로 analysis request, Sam 호출, Kiwoom 호출이 생기지 않는다.
- 사용자가 만든 요청에서만 Sam `accepted`와 `report_ready`가 API로 추적된다.
- Sam은 DB 없이 읽기 API와 제한된 Kiwoom 표본만 사용한다.
- 보고서는 Markdown과 schema v1 JSON, evidence·가설·proposal·한계를 모두 가진다.
- Codex는 사용자 승인 없이 파일·최종 상태를 바꾸지 않으며 테스트 결과를 기록한다.
- 기존 repair 자료는 보존되고 `legacy_hold` 상태는 새 흐름·경보·지표를 오염시키지 않는다.

## 11. 리스크와 완화

| 리스크 | 완화 |
|---|---|
| 품질 보고서 write 실패 | batch transaction과 분리, write-error metric, 운영자 재생성 명령 |
| Sam의 로컬 문서와 API 보고서 불일치 | API 본문과 hash를 정본으로 정의; local copy는 비검증 보조본 |
| Kiwoom 표본의 대표성 부족 | 유형별 선택 근거·상한·limitations를 JSON에 강제 |
| Codex의 범위 확대 | proposal ID, target files, 사용자 승인, diff·test result 기록 |
| legacy repair가 새 흐름을 우회 | `legacy_hold`, feature flag, no-auto-repair integration test |
| 분석 API 인증 혼선 | 역할별 token·scope와 loopback IP allowlist |
