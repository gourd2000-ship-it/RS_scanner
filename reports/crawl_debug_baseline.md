# DBG01 크롤링 장애 원인·데이터 기준선

조사: 2026-10-01 00:10~00:14 UTC / 09:10~09:14 KST.
완료된 거래일 기준: 2026-09-30. 장 시작 직후인 10/1은 일봉 결측 집계에서 제외했다.
적용: debugging-and-error-recovery. 최초 DBG01은 진단과 재현 경로 검증이었다.
이후 DBG02에서 네이버 지수 코드와 로컬 KRX 설정을 수정한 내용을 아래에 추가했다.
운영 상태·수량은 각 조사 시점의 관측이며 계획 개정 시 실시간으로 다시 조회한 값이 아니다.

## 결론

DBG01 조사 당시 배치의 직접 중단 원인은 **네이버 지수 조회 URL의 HTTP 410**이었다.
종목 가격 수집보다 지수 동기화가 먼저 실행되고 예외가 전체 배치로 전파되므로
개별 종목 일봉 API가 응답하더라도 가격 저장·검증·RS 계산에 도달하지 못한다.
이와 별개로 종목 목록 파싱, 이전 RS 강제 종료, API 이미지 버전 불일치가 존재한다.

| 장애 | 근거 | 확정 범위 |
|---|---|---|
| 지수 수집 | 두 시장 구 URL을 직접 GET하여 모두 410 재현; 작업 112~125 같은 실패 | 직접 중단 원인 확정. 후속 네이버 경로 구현은 DBG02, 추가 품질 검증은 DBG02B/C 참조 |
| 목록 수집 | 기존 URL 302→새 주소 200, 기존 파서 결과 0건; snapshot 72/73 실패 | 기존 HTML 계약 불일치 확정 |
| 상태 표시 | snapshot failed인데 symbols checkpoint completed/4,521건 | 실제 신규 수집이 아니라 기존 DB 목록 반환을 성공 단계로 표시 |
| RS 중단 | 작업 94/95/98/104/105/108/110/111의 rs=running, 대응 로그 exit 137 | 종료와 미정리 상태 확인; OOM인지 외부 종료인지는 미확정 |
| API | DB o8b9c0d1e2f3, 이미지에 해당 revision chain 없음 | 배포 코드와 DB 버전 불일치 확정 |

## DBG02: KRX 중단 및 네이버 지수 경로 복구

기존 네이버 웹 지수 URL은 KOSPI/KOSDAQ 모두 HTTP 410이었다. 초기 KRX 지수 API 읽기 조사에서는
두 시장 모두 HTTP 401을 확인했다. 이후 사용자 요청에 따라 KRX 경로 조사를 중단했으며
KRX 지수 source는 구현하지 않았다. 대신 네이버 모바일 증권의
일별 지수 JSON endpoint를 실시간 확인하고 source 경로를 전환했다:

- `https://m.stock.naver.com/api/json/sise/dailySiseIndexListJson.nhn?code=KOSPI&pageSize=100&page=1`
- 같은 요청의 `code=KOSDAQ`

2026-10-01 검증 시 양쪽 요청이 성공했고 각각 100행, 최신 거래일 2026-10-01을 반환했다.
응답의 `cd`, `dt`, `ncv`, `cr`, `ov`, `hv`, `lv`를 읽어 내부 지수 코드와
날짜·OHLC·변동률로 변환한다. 거래량은 응답에 없어 NULL로 둔다. 이 endpoint는 네이버
증권 화면의 내부 API로 보이며 공개 외부 API 명세를 확인하지 못했다. 따라서 응답 계약을
파서/source의 합성 JSON 테스트로 기본 계약을 고정하고, 비정상 JSON 및 실패 응답을 거부하도록 했다.
실제 응답을 보존한 fixture와 성공 형식의 빈 목록·날짜·전체 이력 검증은 추가해야 한다.

`.env`의 `KRX_SHADOW_INGESTION_ENABLED=false`, `UNIVERSE_AUTHORITY=naver_last_completed`,
빈 `UNIVERSE_CANARY_MARKETS`로 KRX shadow 수집과 KRX canary 대상을 비활성화했다.
현재 설정 읽기 결과도 KRX false / Naver authority / 빈 canary다. 예약 배치가 가져오는
`.env.production`에는 이 세 설정의 별도 override가 없어 `.env` 값이 적용된다.
배치 프로세스는 설정 변경 시점에 실행 중이지 않았다. 기존 KRX snapshot/키는 삭제하지 않았고
운영 데이터 재수집·전체 배치·배포도 실행하지 않았다.

테스트는 파서·양 시장 페이지 순회·증분 경계·오류 응답 거부·격리 SQLite 저장 및 재실행을
포함해 26개 통과했다. 개정 계획에서는 이 범위를 DBG02A 완료로 구분한다.
DBG02B/C 품질·날짜 검증과 예약 배치의 실제 저장 및 후속 단계 진입은 아직 미완료다.

## DBG03 후속 이슈: 네이버 종목 명부

종목 명부는 아직 별도 장애다. 구 `sise_market_sum.naver` URL은 HTTP 200까지 리다이렉트되지만
실제 목록 링크 없이 화면 shell을 반환하므로 기존 파서는 0건이다. 후보로 확인한 네이버
`/api/stocks/marketValue`는 `market=KOSPI`와 `market=KOSDAQ` 모두 응답 metadata가
`stockListCategoryType=KOSPI`, `totalCount=2482`로 같아 KOSDAQ 명부 계약으로 사용할 수 없었다.
따라서 DBG02 수정만으로 최신 전체 명부가 복구됐다고 보지 않는다. 현재는 마지막 저장된
네이버 명부 fallback에 의존할 수 있으며, 그 snapshot의 최신성·완전성은 보장되지 않는다.
DBG03에서 양 시장을 분리하는 확인된 네이버 목록 API와 페이지 완전성 계약을 더 찾아야 한다.

## 실행·배포 기준선

- 호스트 commit: `2c805e49de8b5e7cdb891ff5a9d9d17ec7697aef`.
- 작업 시작 시 tracked 수정 파일 24개. 백테스트 관련 코드·테스트, 기존 계획 문서 포함.
  `app/services/batch/orchestrator.py`, `run_daily_job.py`, `context.py`,
  `app/repositories/price_repository.py`에도 기존 미커밋 변경이 있다. 이번에 수정하지 않았다.
- TODO 상태 갱신 전 tracked diff SHA256:
  `f6ff5ffdbf1c6a6f9055bf5be00884d3c9ee3f797a0f426e37bdee198c3161c6`.
  이 해시는 untracked 파일을 포함하지 않는다. 아래 7개 migration은 기존 untracked 파일이다.
- 호스트에 존재하고 컨테이너에 없는 revision 파일:
  `h2b3c4d5e6f7`, `j3c4d5e6f7a8`, `k4d5e6f7a8b9`, `l5e6f7a8b9c0`,
  `m6f7a8b9c0d1`, `n7a8b9c0d1e2`, `o8b9c0d1e2f3`.
- 호스트 `alembic heads`와 DB `alembic_version`: 모두 `o8b9c0d1e2f3`.
- API image: `sha256:071196151c9b63290f73179eb6ab4b4a10d2f95dbd7977554c2572f5707dc091`.
  이미지 생성: 2026-09-05 15:27:31 UTC. 컨테이너 생성: 같은 날 15:27:41 UTC.
  관측 상태: restarting, exit 255, RestartCount 18,664. 로그는
  `Can't locate revision identified by 'o8b9c0d1e2f3'`를 반복한다.
- DB 컨테이너: healthy, 운영 포트 127.0.0.1:5432.
- cron: 평일 UTC 02:30/07:30, KST 11:30/16:30에
  `scripts/run_daily_batch.sh` 실행. 호스트 `.venv`에서 `python -m app.main_batch`를 실행한다.
  따라서 API 컨테이너 장애가 호스트 배치의 410을 유발한 것은 아니다.
- 조사 시점 크롤링 Python 프로세스 없음. 다음 정규 실행은 10/1 02:30 UTC.

## 장애 시점

| 기간/작업 | 결과 |
|---|---|
| 9/4 오후, 작업 93 | 마지막 완료 배치. completed_with_errors, 4,136 성공/174 실패 |
| 9/7~9/17, 작업 94~111 | RS 중 exit 137 8회, 지수 단계 DNS 실패 10회 |
| 9/9 오전, snapshot 46 | 마지막 completed 네이버 명부 snapshot, 4,305건 |
| 9/14 오전 이후 | 네트워크가 응답한 실행에서도 명부 0건 실패가 기록됨 |
| 9/18~9/30, 작업 112~125 | 14회 모두 지수 단계 HTTP 410 |
| 9/24~9/25 | 휴장일 건너뛰기. 종료 코드 0을 수집 성공으로 세지 않음 |

작업 124/125 공통 상태: krx_shadow completed(2,765), symbols completed(4,521),
benchmarks failed, prices/validation/rs pending.
명부 snapshot 72/73은 symbols_seen=0, symbols_valid=0, status=failed이며
`KOSDAQ:below_minimum:0<913;KOSPI:below_minimum:0<1245`를 기록한다.

## 실시간 읽기 전용 재현

| 요청 | 결과 |
|---|---|
| `finance.naver.com/sise/sise_index_day.naver?code=KOSPI&page=1` | HTTP 410 |
| 같은 주소의 `code=KOSDAQ` | HTTP 410 |
| `finance.naver.com/sise/sise_market_sum.naver?sosok=0&page=1` | 302→`stock.naver.com/market/stock/kr/stocklist/capitalization`, HTTP 200, parse_symbols 0건 |
| fchart 일봉, 005930, 9/28~9/30 | HTTP 200, 9/28·29·30 세 행 파싱 |

소스 연결: `app/crawler/sources/naver.py:149` → `sync_benchmarks.py` →
`app/services/batch/orchestrator.py:108`; 가격 단계는 같은 파일 115행 이후다.
`app/crawler/parsers/symbols.py:38`은 예전 `item/main.naver` 링크만 찾는다.
`sync_symbols.py:263`은 빈 목록 snapshot을 failed로 정하지만 289행에서 기존 목록을 반환한다.
HTTP 410은 현재 retry 정책상 일시적 오류가 아니므로 재시도 대상이 아니다.

## 데이터별 마지막 날짜·관측 공백

전체 등록 종목 4,521개, 현재 활성 4,315개(주식 2,771 / ETF 1,169 / ETN 375).
현재 active는 오래된 명부에 기반하므로 실제 거래소의 최신 적격 집합을 보장하지 않는다.
본 집계는 현재 등록 집합의 **미저장 관측**이며 상장 전·거래정지·RS 부적격까지
모두 크롤러 누락으로 단정하지 않는다. 활성 종목의 `listed_at`은 전부 NULL이어서
이 테이블만으로 상장 전 공백을 정확히 제외할 수 없다.

| 대상 | 마지막 날짜/분포 | 9월 관측 공백 |
|---|---|---|
| 활성 종목 가격 4,315개 | 9/17: 4,126개; 이전 날짜: 164개; 전혀 없음: 25개 | 모두 9/18·21·22·23·28·29·30 없음 |
| KOSPI_INDEX / KOSDAQ_INDEX | 각각 9/17, 저장 이력 각각 830행 | 각각 위 7거래일 없음 |
| 활성 주식 RS 2,771개 | 9/4: 2,597개; 이전 날짜: 69개; 전혀 없음: 105개 | 모두 9/7 이후 16거래일 없음 |

- 가격 공백: 9월 20거래일×활성 집합 비교 시 32,027 종목·일.
  이 중 공통 7거래일 공백은 30,205 종목·일이며, 나머지는 이전 공백이다.
- RS 공백: 같은 기간 활성 주식 기준 45,040 종목·일. 이는 RS 생성 적격성을 판정하기 전 수치다.
- 9/17까지 가격이 있는 4,126개 중 4,122개는 9/1~17의 13거래일 가격이 모두 있다.
  나머지 4개는 기간 앞부분에도 공백이 있어 마지막 날짜만으로 완전성을 판단할 수 없다.
- 삼성전자·SK하이닉스·NAVER·에코프로비엠의 저장 가격은 모두 9/17까지다.
- DB에는 가격 이력이 없는 별도 benchmark_code `KOSPI` 행도 있다.
  현재 수집 코드의 대상은 `KOSPI_INDEX`/`KOSDAQ_INDEX`이므로 해당 빈 행을 이번 중단 증거로 사용하지 않았다.

종목별 원자료: [전체 4,521개 종목 CSV](crawl_debug_symbol_coverage_20260930.csv).
`last_price`/`last_rs`는 전체 저장 이력의 최대 날짜다. 공백 필드는 2026년 9월의
일자를 `|`로 구분한다. 예: `18|21`은 9/18·9/21. 빈 마지막 날짜는 이력 없음이다.
`is_active`, `symbol_type`, `listed_at`, `delisted_at`을 함께 보존했다.
재현 SQL: [읽기 전용 coverage SQL](crawl_debug_coverage.sql).
달력은 저장소 `krx_market_day_status`와 `.env.production`의 휴장일 override 부재를 확인해 고정했다.
9월 이전의 전체 역사 결측 분류는 이번 조사 범위에 포함하지 않는다.

## RS 원인 확정의 한계

8개 작업은 모두 가격/검증까지 진행한 뒤 RS에서 종료됐고 finished_at이 없다.
예외 처리로 정리할 기회가 없는 강제 종료와 일치하지만, exit 137만으로 OOM을 단정하지 않는다.
시스템 kernel journal은 현재 계정에 열람 권한이 없어 과거 OOM 근거를 확보하지 못했다.
현재 호스트 메모리 가용량 약 13.5GB는 과거 종료 시점 메모리 상태의 증거가 아니다.
API 컨테이너의 OOMKilled=false 역시 호스트 RS 프로세스의 OOM 여부와 무관하다.
DBG04에서 종료 근거와 고정 입력 규모별 메모리/SQL/기업행위 재수집 비용을 확인해야 한다.

## 격리 재현 경로 검증

다음 기존 테스트를 APP_ENV=test, DATABASE_URL=sqlite://,
NOTIFICATION_ENABLED=false, TELEGRAM_ENABLED=false,
KRX_SHADOW_INGESTION_ENABLED=false로 실행했다.
Python socket connect/connect_ex를 예외 발생 함수로 대체해 외부 연결을 차단했으며
pytest cache와 Python bytecode 생성을 비활성화했다.

- `tests/unit/test_parsers.py`
- `tests/unit/test_naver_universe_source.py`
- `tests/unit/test_universe_snapshot.py`
- `tests/integration/test_replay_source.py`
- `tests/integration/test_batch_harness.py`

결과: **22 passed, 72 warnings, 1.19s**. 경고는 기존 datetime.utcnow 사용 관련이다.
SQLite 메모리 DB와 fake/replay source 경로가 동작한다는 기준선이며,
최신 네이버 페이지와 운영 규모 RS 문제가 해결됐다는 의미는 아니다.
기존 fixture 테스트가 통과하면서 실사이트 요청은 실패하므로 DBG02/03에서
이번 응답 계약 변화를 포착하는 회귀 사례를 추가해야 한다.

PostgreSQL E2E 경로는 `docker-compose.test.yml`의 localhost:5433,
DB/user `rs_scanner_test`다. 테스트 컨테이너는 현재 Exited, 5433 listener 없음.
이번에 기동하거나 schema를 초기화하지 않았다.
후속 E2E 실행에는 DATABASE_URL/TEST_DATABASE_URL/E2E_DATABASE_URL 모두 이 격리 DB를 지정해야 한다.
`app.main_api`는 import 시 init_db를 호출하고, E2E fixture는 DROP SCHEMA를 수행한다.
또한 migration 실패 시 create_all로 대체하므로 E2E 통과만으로 migration 정합성을 인정하면 안 된다.

## 완료·다음 작업

DBG01의 코드/배포/DB 기준선, 대상별 마지막 날짜와 9월 공백, 안전한 fixture 재현 경로를 확보했다.
후속 DBG02A에서 네이버 지수 코드와 로컬 KRX 중단 설정을 적용했다. 운영 DB 재수집·수동 전체
배치·컨테이너 배포는 실행하지 않았다. 호스트 cron은 작업 트리의 수정 코드를 읽을 수 있으므로
실행 전 최신 프로세스·예약 상태와 저장 결과를 다시 확인해야 한다.

## 2026-10-01 후속 코드 수정 및 검증

사용자 요청에 따라 운영 데이터 변경 없이 호스트 코드와 격리 테스트를 수정했다.

- 네이버 지수 parser에서 8자리 날짜, 응답 종목 코드, 유한/양수 값과 일관된 OHLC를 검증한다.
- 지수 이력의 빈 첫 페이지, 역순, 반복/진행 없는 페이지, 설정 페이지 상한 도달을 실패로 처리한다.
- 네이버 지수 및 종목 가격은 저장된 최신 날짜를 다시 요청해 장중 값을 마감 값으로 갱신하고,
  batch target_date 뒤의 응답 행을 저장하지 않는다.
- orchestrator가 benchmark 단계에 target_date를 전달하도록 했다.
- 네이버 명부 첫 페이지 0건은 정상 빈 목록이 아니라 incomplete 실패로 처리한다.
- 명부 snapshot partial/failed 상태를 symbols checkpoint의 completed_with_errors와 metadata에
  반영해 재개 시 완료 단계로 건너뛰지 않게 했다.

재검증: 지수 첫 페이지는 두 시장 모두 100행이며 엄격 parser를 통과했다. SPA 배포 JS에서
확인한 KRX 주식 목록 API를 28페이지 끝까지 읽은 결과 `totalCount=2768`, 고유 주식 2,768
(KOSPI 944/KOSDAQ 1,824)였다. 별도 Naver ETF/ETN 목록은 각각 1,171/367건이었다. 전체
4,306종목을 임시 메모리 SQLite에 적재한 결과 snapshot completed, symbols_seen/valid 각각
4,306, 오류 없음이었다. 기존 등록 active 4,315종목과의 9건 차이는 대상별 대조가 남았다.

관련 parser/source/snapshot/price sync/benchmark sync/replay/batch harness/checkpoint 테스트
**59 passed, 158 warnings**. 경고는 기존 `datetime.utcnow()` deprecation이다. `ruff` 실행파일은
가상환경에 없어 lint는 실행하지 못했다. 운영 DB 배치·대량 저장·배포는 수행하지 않았다.

남은 작업은 DBG06A의 기존 명부 provenance/최종 상태 일치, DBG07A의 지수·종목가격·검증까지
실응답 canary, 기존 9건 명부 차이 설명 및 KST 장중/마감 기준 고정이다. RS 종료 137 원인,
API 이미지/migration chain, 운영 결측 복구 및 다음 예약 실행 역시 미검증이다. 최신 순서와
완료 기준은 [개정 계획](../tasks/plan.md)과 [실행 체크리스트](../tasks/todo.md)를 따른다.
