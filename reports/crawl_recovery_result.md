# 크롤링 복구 실행 결과

실행일: 2026-10-01 UTC  
대상 작업: 운영 DB `daily_full` job 128  
결론: 네이버 명부·지수·가격 수집은 실제 운영 DB에서 재개되어 2026-10-01까지 저장됐다. 후속 작업에서 API 기동도 복구했다. 가격·검증 오류와 RS 갱신 문제가 남아 전체 서비스 복구 완료로 보지는 않는다.

## 원인과 수정

- 과거 예약 배치는 폐기된 `finance.naver.com/sise/sise_index_day.naver` 경로에서 HTTP 410으로 실패해 가격 단계와 RS 단계로 진행하지 못했다.
- 현 Naver stock-security 목록 API와 ETF/ETN feed, 모바일 지수 JSON API를 연결하고 페이지·날짜·OHLC 완전성 검증을 적용했다.
- 가격 결과가 종목별 전체 저장 이력(평균 약 1,500행)을 배치 결과에 계속 보관해 RSS가 선형 증가했다. 이를 이번 fetch에서 받은 행만 보관하도록 수정했다. 1차 시도는 5/22 청크에서 약 4GB RSS로 중단했다. 수정 뒤 22청크 가격 수집 동안 RSS는 약 140–190MB였다.
- 단일 실행 `flock`을 host batch wrapper에 추가해 예약/수동 실행의 중복을 막았다.
- HTTPX의 INFO 요청 로그가 Telegram bot token이 포함된 URL을 남기는 점을 발견했다. HTTPX 요청 로그를 WARNING 이상으로 제한하고 알림 예외는 예외 클래스만 기록하도록 바꿨다. 기존 batch 로그의 Telegram URL은 마스킹했다. 이미 로그 밖으로 노출된 bot token은 회전이 필요하다.

## 격리 canary

실제 Naver 응답을 disposable in-memory SQLite에 저장했다. KOSPI/KOSDAQ 지수와 KOSPI·KOSDAQ 주식, ETF, ETN, 영숫자 코드 5종목을 두 번 실행했다. 두 번 모두 가격 5/5 성공, 지수·종목 최신일 2026-09-30, 가격/지수 행 수 변화 없음(각 8행)이었다. 운영 DB 쓰기는 없었다.

## 운영 DB 반영

| 항목 | job 시작 전 | job 128 이후 |
|---|---:|---:|
| Naver universe snapshot | 마지막 완료 4,305종목(9/9) | 4,306종목, 30/30 pages completed |
| 활성 종목 | 4,315 | 4,340 |
| benchmark 최신일 | 2026-09-17 | 2026-10-01 |
| benchmark 행 수 | 1,660 | 1,676 |
| daily price 최신일 | 2026-09-17 | 2026-10-01 |
| daily price 행 수 | 6,483,022 | 6,516,075 (+33,053) |
| RS 최신일 | 2026-09-04 | 2026-09-04 |

job 128의 prices checkpoint는 `completed_with_errors`: 4,340 targets, 4,146 fetched, 194 failed. 실패는 OHLC 양수/일관성 검증에서 차단됐고 저장되지 않았다. validation은 `completed_with_errors`/`blocked`로 기록됐다(4,340 expected, 4,127 fresh, 189 stale, 218 errors, 188 critical). Naver snapshot에는 현재 명부에서 사라진 34개 코드가 deactivation candidate로 기록됐으나 자동 비활성화는 하지 않았다. 따라서 활성 명부 4,340개와 최신 snapshot 4,306개의 차이는 아직 개별 분류가 필요하다.

KRX shadow 설정은 false였고 job 128의 `krx_shadow` checkpoint는 pending이므로 이 실행에서 KRX 수집은 호출되지 않았다.

## 미완료·안전 정지

- RS 계산 중 RSS가 약 9.4GB까지 상승했다. 이때 전체 이력 RS 경로가 메모리 병목임을 관측해 OOM 전에 중단했다. 직접적인 exit 137 원인은 확인하지 못했다. job 128과 RS checkpoint는 실패로 정확히 정리했고 RS 데이터는 갱신되지 않았다.
- RS 계산 입력을 12개월(254행)로 제한하는 수정과 회귀 테스트를 추가했다. calculator는 252일 창과 인접일 검사에 필요한 최대 254행만 받도록 했으며, 전체 이력 corporate-action 검출은 기존 범위를 유지한다. 격리 RS/batch 테스트는 통과했으나 이 수정으로 운영 전체 RS를 재계산하지는 않았다.
- API 컨테이너 `rs_scanner_api`는 후속 작업에서 누락된 migration 7개를 포함한 복구 이미지로 배포했다. DB/이미지 revision 일치, health·종목·랭킹 HTTP 200을 확인했다. 자세한 내용은 `reports/api_migration_recovery_20261001.md`에 기록했다.
- job 126·127은 각각 비밀 URL 로깅 차단과 메모리 수정 때문에 중단된 작업이며, 가격 단계는 커밋되지 않았다. 최종 크롤러 데이터는 job 128의 별도 단계 커밋이다.
- API는 기동됐으나 RS 갱신과 가격 실패/명부 차이가 남아 있으므로 D3/D4 및 전체 서비스 복구는 미완료다.

## 검증

- 실제 Naver 전체 universe: 30/30 pages, 4,306 unique symbols.
- 실제 Naver canary: SQLite 저장·재실행 idempotency, 종목 5/5, 두 지수, 최신일 상한 통과.
- 최종 집중 회귀 테스트: 71 passed. `compileall`, `git diff --check` 통과.
- 기존 `datetime.utcnow()` deprecation 경고 98건은 남아 있다.

다음 작업은 RS 254행 메모리 수정의 운영 규모 측정/재계산, 194 가격 실패와 34 명부 후보의 분류다. Telegram bot token을 회전한 후 다음 예약 실행도 확인해야 한다.
