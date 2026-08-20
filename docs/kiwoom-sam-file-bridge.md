# Kiwoom CLI 파일 브리지 운영 계약 (Legacy)

- 상태: Legacy 전환 계약 (PostgreSQL repair queue 목표 구조로 대체 예정)
- 대상: RS Scanner와 Hermes Agent Sam
- 목적: `rs_scanner`가 직접 `kiwoomcli`를 실행할 수 없는 환경에서 Sam을 Kiwoom 일봉 조회 실행자로 사용
- 원칙: Naver 주 공급자, Kiwoom은 실패 종목 전용 읽기 전용 폴백

> 이 문서는 공유 폴더를 사용할 수밖에 없는 전환 전 진단·회귀 환경의 계약이다.
> 신규 운영 경로는 [크롤링 분석 후속 PRD](prd-crawl-analysis-followup.md)의 PostgreSQL
> repair queue와 제한된 Repair API이며, `KIWOOM_FALLBACK_TRANSPORT=file`은 기본 경로가 아니다.

## 1. Sam에게 전달할 업무 요청 규칙

Sam에게는 상시 실행 모드나 별도 상주 역할을 요구하지 않는다. rs_scanner가
DB 무결성 검증을 위해 구체적인 업무 요청을 전달할 때만 아래 규칙을 적용한다.

> 이 요청은 RS Scanner DB 무결성 검증을 위한 읽기 전용 데이터 수집 업무다.
> 요청 JSON의 `operation=daily_chart`와 고정된 종목·기간·수정주가 조건을 확인하고,
> 허용된 `kiwoomcli domestic candles daily` 명령으로 결과를 수집하라.
> 주문·계좌·잔고 조회, DB 직접 접근·수정, 임의 명령 실행은 하지 말라.
>
> `request_id`와 `idempotency_key`로 중복 실행을 방지하고, 처리 중인 요청은
> `processing/`으로 원자적으로 이동하라. 결과를 공통 JSON 형식으로 정규화한 뒤
> `results/<request_id>.result.json`으로 원자적으로 기록하라. JSON이 기계 처리의
> 기준이며 Markdown은 사람이 읽는 요약이 필요할 때만 추가한다.
>
> 앱키·시크릿·토큰은 요청·결과·Markdown·로그에 기록하지 않는다. 잘못된 JSON,
> 만료된 요청, 알 수 없는 작업, 중복 요청, 일부 종목 실패와 전체 요청 실패를
> 각각 구분해 결과에 기록하라. 실행 결과가 없거나 불확실하면 성공으로 표시하지 말라.

Sam은 위 업무 요청을 임의의 CLI 명령 문자열을 실행하는 방식으로 해석해서는 안 된다.
`operation` 값과 CLI 인자 사이의 매핑은 Sam 내부의 고정된 allowlist로 관리한다.

### 업무 요청 템플릿

```text
목적: RS Scanner DB 무결성 검증
대상: <6자리 종목 코드 목록>
작업: 수정주가 기준 daily_chart 조회
기준일: <YYYY-MM-DD>
결과: 공유 폴더 results/<request_id>.result.json에 기록
제약: DB 직접 수정 금지, 주문·계좌 API 금지, 인증정보 기록 금지
완료 보고: 종목별 행 수·최신 거래일·수정주가 여부·오류·재시도 횟수
```

Sam이 결과 파일을 작성하는 것은 검증 자료를 반환하는 단계다. DB 저장·교체·RS
입력 승격은 rs_scanner가 결과를 읽은 뒤 OHLCV·최신성·중복·출처 충돌 검증을
통과시킨 경우에만 수행한다.

## 2. 공유 폴더와 역할

기본 경로는 `/srv/rs_scanner-share/kiwoom`으로 한다. 실제 배포 경로가 다르면
양쪽 프로세스가 동일한 설정값을 사용해야 한다. `rs_scanner-share`와
`rs_scanner_share`를 혼용하지 않는다.

```text
/srv/rs_scanner-share/kiwoom/
  requests/       # rs_scanner가 완성된 요청을 생성
  processing/     # Sam이 소유권을 가져간 요청
  results/        # Sam이 생성한 최종 결과
  payload/        # 결과가 클 때 사용하는 JSONL/압축 데이터
  archive/        # 완료 결과와 원본 요청의 보관
  failed/         # 형식 오류 또는 처리 불가 요청
```

역할은 다음과 같다.

| 주체 | 읽기 | 쓰기 |
|---|---|---|
| rs_scanner | `results/`, 필요 시 `failed/` | `requests/`, `archive/` |
| Sam | `requests/`, 필요 시 `processing/` | `processing/`, `results/`, `payload/`, `failed/`, `archive/` |

공유 폴더의 권한은 두 프로세스가 실제로 사용하는 계정 또는 공용 그룹에만
부여한다. 자격증명은 파일 브리지의 권한으로 대체하지 않으며, Secret Manager나
Sam 실행 환경에만 둔다.

## 3. 파일 수명 주기

파일 내용이 완성되기 전에는 Sam이 발견할 수 있는 확장자를 사용하지 않는다.

1. `rs_scanner`가 `<request_id>.request.json.tmp`를 생성한다.
2. JSON을 검증하고 flush한 뒤 같은 디렉터리 안에서
   `<request_id>.request.json`으로 원자적 rename한다.
3. Sam은 `*.request.json`만 발견하고, 처리 시작 시 `processing/`으로 원자적 이동한다.
4. Sam은 결과를 `<request_id>.result.json.tmp`로 작성한 뒤 `results/`로 원자적 rename한다.
5. `rs_scanner`는 `request_id`가 일치하고 결과가 유효할 때만 결과를 소비한다.
6. 보관 정책에 따라 요청·결과·payload를 `archive/`로 이동한다.

파일을 직접 덮어쓰거나, 처리 중인 파일의 JSON 상태를 부분적으로 수정하지 않는다.
상태는 디렉터리와 최종 결과 JSON의 `status`를 함께 사용한다.

### 상태 값

```text
queued     -> processing -> succeeded
                         -> partial
                         -> failed
                         -> expired
queued     -> rejected
```

- `queued`: 요청이 생성되었지만 아직 Sam이 가져가지 않음
- `processing`: Sam이 소유권을 가져가 실행 중
- `succeeded`: 요청한 모든 종목이 정상 결과를 가짐
- `partial`: 일부 종목만 성공
- `failed`: 요청 전체를 실행할 수 없음
- `rejected`: 스키마·작업·보안 정책 위반
- `expired`: `expires_at` 이후 발견되었거나 처리 deadline을 넘김

결과 파일이 없거나 JSON이 손상된 경우 `succeeded`로 추정하지 않는다.
rs_scanner는 polling timeout 이후 해당 종목을 복구되지 않은 Naver 실패로 남긴다.

## 4. 요청 JSON 계약

파일명은 `[A-Za-z0-9._-]`로 제한된 `request_id`를 사용한다.

```json
{
  "schema_version": 1,
  "request_id": "rs-20260813-001",
  "idempotency_key": "rs-20260813-001",
  "operation": "daily_chart",
  "provider": "kiwoom",
  "symbols": ["005930", "000660"],
  "target_date": "2026-08-13",
  "history_from": "2020-01-01",
  "adjusted_price": true,
  "max_rows_per_symbol": 6000,
  "created_at": "2026-08-13T10:00:00Z",
  "expires_at": "2026-08-13T10:10:00Z",
  "requested_by": "rs_scanner"
}
```

필수 필드는 `schema_version`, `request_id`, `idempotency_key`, `operation`,
`symbols`, `created_at`, `expires_at`이다.

- `operation`은 현재 `daily_chart`만 허용한다.
- `symbols`는 국내 주식 6자리 코드의 중복 없는 목록이어야 한다.
- 한 요청의 종목 수는 초기 canary에서 5~10개, 정식 canary에서 100~300개로 제한한다.
- `adjusted_price=true` 여부를 결과에 그대로 반영한다.
- `target_date`와 `history_from`은 ISO 날짜로 기록하며 Sam이 Kiwoom CLI 형식으로 변환한다.
- `expires_at`이 지난 요청은 API를 호출하지 않고 `expired`로 반환한다.

요청에 앱키, 시크릿, bearer token, 임의의 shell command, shell option을 넣지 않는다.

## 5. 결과 JSON 계약

작은 결과는 아래처럼 `rows`를 직접 포함할 수 있다. 결과가 커지면 `data_file`을
사용하고 `sha256`과 `row_count`를 반드시 기록한다.

```json
{
  "schema_version": 1,
  "request_id": "rs-20260813-001",
  "status": "partial",
  "provider": "kiwoom_rest",
  "executor": "sam",
  "tool": "kiwoomcli",
  "started_at": "2026-08-13T10:00:02Z",
  "finished_at": "2026-08-13T10:00:18Z",
  "items": [
    {
      "symbol": "005930",
      "status": "succeeded",
      "adjusted_price": true,
      "row_count": 1200,
      "latest_date": "2026-08-13",
      "rows": [
        {
          "date": "2026-08-13",
          "open": 70000,
          "high": 71000,
          "low": 69500,
          "close": 70500,
          "volume": 12345678,
          "change_rate": 1.2
        }
      ]
    },
    {
      "symbol": "000660",
      "status": "failed",
      "error_code": "RATE_LIMIT",
      "error_message": "rate limit exceeded",
      "retry_count": 2
    }
  ],
  "metrics": {
    "requests_sent": 2,
    "rate_limit_errors": 1
  }
}
```

종목별 `status`는 `succeeded`, `failed`, `skipped`, `expired` 중 하나를 사용한다.
`error_message`에는 토큰·앱키·시크릿·개인정보를 포함하지 않는다.

`rows`의 날짜는 오름차순 또는 내림차순 중 하나로 일관되게 유지하고, 숫자 필드는
문자열이 아닌 JSON 숫자로 정규화한다. `close <= 0`, OHLC 불일치, 날짜 중복,
조정주가 정책 불일치는 성공 결과로 내보내지 않는다.

## 6. 중복·오류·재시도 규칙

- 같은 `idempotency_key`가 이미 처리되었으면 기존 결과를 재사용하고 Kiwoom을 다시
  호출하지 않는다.
- JSON 파싱 실패, 알 수 없는 `operation`, 잘못된 종목 코드, 경로 탈출 시도는
  `rejected`로 기록한다.
- Kiwoom 일시 오류와 rate limit은 Sam의 제한된 retry/backoff 정책 안에서만 재시도한다.
- 인증 오류, 계약 위반, 데이터 품질 오류는 무한 재시도하지 않는다.
- 한 종목 실패가 전체 요청의 성공 종목을 무효화하지 않도록 종목별 결과를 남긴다.
- rs_scanner의 polling timeout이나 Sam 중단으로 결과가 없으면 Naver 실패 상태를
  유지한다. 결과가 없다는 이유로 성공 처리하지 않는다.
- Naver에 이미 저장된 값과 Kiwoom 결과가 충돌하면 Sam은 덮어쓰지 않는다. 결과를
  `failed` 또는 `review_required`로 남기고 rs_scanner의 provider conflict 검증에 맡긴다.

## 7. canary 실행 순서

### 단계 0: 단일 종목 무결성 검증

1. Naver 실패 종목 중 1개를 선정한다.
2. `KIWOOM_FALLBACK_CODES`에 그 코드만 설정한다.
3. DB 저장 전 검증 목적의 `daily_chart` 요청 1건을 만든다.
4. 요청 이동, `kiwoomcli` 실행, 결과 생성, rs_scanner 파싱을 확인한다.
5. 요청·결과·로그에 인증정보가 없는지 확인한다.

### 단계 1: 제한 canary

1. Naver 실패 종목 100~300개를 allowlist로 고정한다.
2. Kiwoom 복구율, 최신 거래일, 조정주가 여부, coverage, 저장 건수,
   충돌률, rate-limit 오류율, 지연시간을 기록한다.
3. coverage 99.5% 이상, 가격 단계 30분 이내, rate-limit 오류가 운영 한도 이내인지
   확인한다.
4. 동일 조건을 3회 연속 관측한 뒤에만 범위를 확대한다.

초기 canary에서 `KIWOOM_FALLBACK_CODES`를 비워 두지 않는다. 비어 있으면 eligible한
Naver 실패 대상 전체가 선택될 수 있다. 문제 발생 시 `KIWOOM_FALLBACK_ENABLED=false`로
전환하고, 진행 중 요청은 새 요청을 만들지 않고 timeout 또는 명시적 중단으로 처리한다.

## 8. Sam 작업 완료 체크리스트

- [ ] 공유 폴더의 실제 경로와 읽기·쓰기 권한 확인
- [ ] `requests/`, `processing/`, `results/`, `payload/`, `failed/`, `archive/` 생성
- [ ] `daily_chart` 외 operation 거부
- [ ] `request_id`·`idempotency_key` 중복 방지
- [ ] 임시 파일 후 atomic rename 적용
- [ ] Kiwoom CLI는 읽기 전용 일봉 조회만 실행
- [ ] 결과 JSON의 종목별 상태·최신일·행 수·retry 수 기록
- [ ] 결과·로그·Markdown에 인증정보 미기록
- [ ] 단일 종목 무결성 검증 통과
- [ ] rs_scanner가 결과를 읽고 품질 검증까지 통과

## 9. 구현 경계 (전환 전 한정)

이 문서는 전환 전 Sam과 rs_scanner 사이의 파일 계약이다. rs_scanner의
`KiwoomFileBridgePriceSource`가 이 계약을 구현하며, 결과는 기존
`PriceFetchResult`와 동일한 품질·충돌 검증을 통과해야 한다. 파일 브리지는 Naver를
대체하지 않고, 기존 직접 REST client와 교체 가능한 실행 경로로 취급한다.

PostgreSQL queue/Repair API가 canary를 통과하면 이 파일 브리지와 공유 폴더 의존성은
비활성화하고, 이 문서는 과거 요청의 해석·감사 참고용으로만 유지한다.

rs_scanner 설정:

```text
KIWOOM_FALLBACK_ENABLED=true
KIWOOM_FALLBACK_TRANSPORT=file
KIWOOM_BRIDGE_DIR=/srv/rs_scanner-share/kiwoom
KIWOOM_BRIDGE_TIMEOUT=120
KIWOOM_BRIDGE_POLL_INTERVAL=1
```

`KIWOOM_CLI_PROFILE`은 Sam 환경에서 별도 프로필이 필요한 경우에만 설정한다.
현재 Sam이 확인한 실행 파일은
`/home/gourd/.hermes/profiles/sam/home/.local/bin/kiwoomcli`이며, rs_scanner가
직접 실행하지 않고 요청 JSON만 생성한다.

관련 문서:

- [크롤링 분석 후속 PRD](prd-crawl-analysis-followup.md)
- [운영 전환·rollback runbook](operations_rollout.md)
- [배포 가이드](deployment.md)
