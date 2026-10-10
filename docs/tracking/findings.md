# 미해결 사항

| 항목 | 증거 | 영향 | 다음 조치 |
|---|---|---|---|
| 097870 장기 이력 미확보 | 2013~2023은 `provider_unsupported`, 결측 2,493행 | 해당 종목·연도는 dataset에서 제외 | 조정 기준이 검증된 허용 공급자를 확보할 때만 재평가 |
| 기업행위 근거 부족 | `CorporateAction` 0행, extreme return 검토 300행 | 265개 외 source 검토 행을 포함해 565행이 complete 불가 | 원자료·공식 이벤트 근거를 연결하거나 계속 제외 |
| 상장폐지 lifecycle 데이터 없음 | 확인된 상폐 lifecycle 1,508개 제외 | 생존편향 제거 완료 주장과 상폐 청산 backtest 불가 | 비용·이용 조건이 맞는 역사 데이터 계약 전까지 범위 밖 유지 |
| 수정 기준 차이 | canonical과 `kiwoom:1` 차이 362,887행 | 공급자 혼합 시 왜곡 가능 | 선택 정책을 고정하고 자동 보정 금지 |
| 사람 운영자 원격 인증 부재 | 운영자 권한은 운영 환경 접근에 의존 | 원격 관리 기능을 안전하게 공개할 수 없음 | 필요 시 별도 인증·감사 설계 |
| cron spool 쓰기 권한 없음 | 2026-10-10 `scripts/setup_crontab.sh` 실행에서 `/var/spool/cron/: mkstemp: Permission denied`, 이후 `crontab -l`도 `crontabs/autobot/: fopen: Permission denied`를 반환했다. | 코드와 운영 설정은 준비됐지만 이 호스트에는 일일 자동 실행 항목이 등록되지 않았다. | 호스트 운영자가 `autobot` 계정의 crontab 권한을 부여하거나, 같은 `scripts/run_daily_batch.sh`를 승인된 systemd timer·외부 scheduler에 KST 16:30(UTC 07:30)로 등록한다. |
| 2026-10-08 Kiwoom 일일 원본 overlap 불일치 | `reports/operations/indicator_source_apply_20261008.json`: 지표 series 2,175개 중 2,126개에 44,541행을 append했다. 앞선 5개 표본 105행을 포함하면 총 44,646행이다. 41개는 기존 2026-09-04 기준일 OHLCV와 새 Kiwoom 응답이 달랐고, 8개는 그 기준일이 응답에 없었다. | 해당 49개 종목은 대상일 Kiwoom 근거가 확인될 때까지 지표 증분 대상에서 제외한다. 2,126개 검증 종목의 EMA·거래량 MA50·ATR14는 독립적으로 증분 저장한다. | 각 종목의 기존 관측 payload hash·mapping 시점·새 응답을 읽기 전용으로 대조한다. 공급자 revision 또는 요청 범위 문제를 근거로 분리한 뒤에만 새 manifest로 재수집한다. 기존 관측을 수정하거나 값을 추측하지 않는다. |
| 2026-10-08 일일 수집 품질 gate 차단 | `reports/data_quality/job_137.json` (validation run 59, crawl job 137): 대상 4,341개, fetched 4,135개, failed 206개. 실패 206건 모두 `ValidationError`이며 양수 OHLC 위반 188건, OHLC 순서 모순 18건이다. HTTP status는 모두 null, retry는 모두 0. 총 437개 case가 모두 open이고 BLOCK 425건·REVIEW 12건: stale 201개(195 critical·6 warning, 1~59일 지연), missing row 24개, extreme return 5개, coverage warning 1개. fresh 4,116개, coverage 94.8169%, history 기준 RS 후보 3,945개 중 당일 fresh 3,745개, unique error symbols 219개. case 범주는 겹친다(예: invalid price와 stale 182개)이므로 원인 수량을 더해 고유 종목 수로 해석하지 않는다. 보고서 모드는 `report_only`지만 판정은 `blocked`다. 저장 보고서만 확인했고 운영 DB는 조회하지 않았다. | 이 판정으로 해당 일자의 가격·RS 품질을 성공으로 표시하거나 일일 Volume MA50·ATR14 계산을 수행할 수 없다. 206건의 ingest failure는 입력 검증에서 중단됐다. 보고서는 실패 target의 공급자·원문 payload를 노출하지 않으므로 원인을 특정 공급자 계약으로 귀속할 수 없다. | 다음 읽기 전용 검토에서 target·case와 원천 관측을 연결해 원인별 표본을 확인한다. 양수·OHLC 규칙을 낮추거나 가격을 보정하지 않는다. 공급자·계약 문제는 증거가 확인될 때만 별도 차단 사유로 남긴다. 운영자가 원인과 재수집 범위를 승인한 뒤 제한 표본 및 새 품질 검증을 거쳐 일일 전체 재평가 여부를 결정하고, 새 report가 통과하기 전까지 지표 계산과 dataset 발행을 보류한다. |

## 해결한 문제

| 항목 | 증거 | 영향 | 조치 |
|---|---|---|---|
| 프런트엔드 lint 기준선 | 기존 operations 화면의 render/effect 규칙과 주가 차트·공통 API client에서 12 errors·5 warnings가 확인됐다. | 전체 lint 명령이 실패했다. | 영향 경로를 정리했고 `npm run lint` 및 production build 통과를 확인했다. |
| 기본 pytest selector의 DB/E2E 혼입 | 경로 기반 marker가 없어 `pytest -m 'not integration and not api'`가 통합/E2E suite도 수집 대상에 포함했다. | 기본 검증이 의도보다 넓게 실행될 수 있었다. | `integration`, `api`, `e2e` marker를 경로·파일명에서 자동 적용했다. Collection-only에서 통합·E2E 파일이 제외됨을 확인하고 기본 suite 562 passed, 205 deselected로 검증했다. |
| API 통합 fixture의 기존 test DB 의존 | `pytest tests/integration/api -q`가 `crawl_jobs` 테이블이 없는 `rs_scanner_test`에서 실패했고, session commit이 테스트 간 샘플 행을 남겨 3개 assertion도 충돌했다. | 새 전용 PostgreSQL test DB에서 기존 API suite를 실행할 수 없었다. | 전용 localhost test DB에 임시 schema를 만들고 metadata를 준비한 뒤 삭제한다. 각 test session은 외부 transaction 안에서 savepoint를 쓰고, app import 때 기본 DB 초기화를 막는다. 격리 suite 60 passed로 검증했다. |
| 관측 정렬의 UTC 시각 혼합 | 2026-10-05 ATR PostgreSQL rebuild와 `test_selector_orders_fresh_and_reloaded_observations_with_consistent_utc`에서 새 aware 관측과 DB에서 읽은 naive 관측 비교가 `TypeError`로 실패 | 같은 세션에서 관측 추가 후 EMA·Volume·ATR 선택이 실패할 수 있음 | 두 관측 정렬 경로에 기존 UTC 정규화 함수를 적용하고 단위·PostgreSQL 회귀 검증 |
| ATR14 역사 백필 동시 writer와 체크포인트/DB 불일치 | 격리 셸에서 보이지 않던 호스트 writer가 실행 중인 상태에서 Docker writer를 추가 기동해 checkpoint에 `IntegrityError` 17건이 기록됐다. `reports/atr14/reconciliation_20130102_20260904.json`은 승인 manifest에 대해 2,175개 완료 run과 input/result 각 7,303,650행의 저장값 hash·상태 수량을 검증했다 | 원래 apply report의 실패 17건은 DB 저장 실패가 아니었으며 결과나 lineage 손실은 확인되지 않았다 | 중복 writer를 중지하고 원래 writer 완료 후 DB와 일치하는 17개 checkpoint 표기만 복구했다. 재개 시 호스트 PID namespace와 DB 연결을 함께 확인한다 |
| Daily Volume MA50·ATR14의 report-only 차단 누락 | 회귀 테스트에서 `validation_status=blocked`, `mode=report_only`여도 두 배치 진입점이 지표 계산을 호출함을 재현했다. 판정 상태와 mode를 분리해 검사하도록 고쳤고, 두 진입점 모두 지표를 `validation_gate_blocked`로 skip하며 체크포인트를 `completed_with_errors`로 기록한다. report-only의 RS 동작은 유지한다. | 차단된 가격 입력으로 지표가 계산되거나 정상 완료로 보일 수 있었다 | 직접 배치와 checkpoint 오케스트레이터의 회귀 테스트를 통과시켰다. |
| 백테스트 품질 테스트의 오래된 기대값 | `test_incremental_sync_e2e`는 신규 행이 없는 재실행에도 전체 저장 이력 260개를 가격 단계 반환값으로 기대했으나, 현재 계약은 이번 실행에서 수신한 행만 반환한다. `test_clean_snapshot_on_postgres_is_reproducible_and_rolls_back`는 과거 coverage 형식과 불완전 연도 가격 발행을 기대했으나, 현재 계약은 `audited_coverage`와 complete segment만 발행한다. | 오래된 assertion 두 건이 현재 동기화·데이터셋 계약과 맞지 않았다 | 테스트 기대값을 현재 계약에 맞췄다. |

## 추적 중인 운영 개선

| 항목 | 증거 | 영향 | 다음 조치 |
|---|---|---|---|
| 전체 역사 지표 계획 보고서의 긴 실행 시간 | 2026-10-05의 2013-01-02~2026-09-04 전체 범위 Volume MA50·ATR14 읽기 전용 manifest가 각각 약 22분 소요 | DB를 변경하지는 않지만 운영자가 완료 시점과 진행률을 즉시 알기 어렵다 | 대상 처리 수·경과 시간·예상 잔여를 출력하는 progress reporting과 selector/query profile을 별도 개선으로 검토 |
