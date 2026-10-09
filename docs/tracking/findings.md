# 미해결 사항

| 항목 | 증거 | 영향 | 다음 조치 |
|---|---|---|---|
| 프런트엔드 기존 lint 오류 | 2026-10-03 `npm run lint`: operations의 render/effect 규칙, 주가 차트와 공통 API client의 `any` 등 12 errors·5 warnings | 전체 lint 실패, 백테스트 조건 화면의 범위 lint와 production build는 통과 | 해당 화면·공통 client 개선 시 별도 정리 |
| 097870 장기 이력 미확보 | 2013~2023은 `provider_unsupported`, 결측 2,493행 | 해당 종목·연도는 dataset에서 제외 | 조정 기준이 검증된 허용 공급자를 확보할 때만 재평가 |
| 기업행위 근거 부족 | `CorporateAction` 0행, extreme return 검토 300행 | 265개 외 source 검토 행을 포함해 565행이 complete 불가 | 원자료·공식 이벤트 근거를 연결하거나 계속 제외 |
| 상장폐지 lifecycle 데이터 없음 | 확인된 상폐 lifecycle 1,508개 제외 | 생존편향 제거 완료 주장과 상폐 청산 backtest 불가 | 비용·이용 조건이 맞는 역사 데이터 계약 전까지 범위 밖 유지 |
| 수정 기준 차이 | canonical과 `kiwoom:1` 차이 362,887행 | 공급자 혼합 시 왜곡 가능 | 선택 정책을 고정하고 자동 보정 금지 |
| 사람 운영자 원격 인증 부재 | 운영자 권한은 운영 환경 접근에 의존 | 원격 관리 기능을 안전하게 공개할 수 없음 | 필요 시 별도 인증·감사 설계 |
| 2026-10-08 일일 수집 품질 gate 차단 | `reports/data_quality/job_137.json`: 4,341개 대상 중 fresh 4,116개, coverage 94.8169%, stale 201개, `validation_status=blocked` | 당일 RS 입력·후속 RS 계산 및 지표 일일 활성화를 검증 완료로 승격할 수 없음 | ingest 실패와 stale input을 원인별로 분류·복구한 뒤 새 quality report에서 coverage 및 freshness gate를 재검증 |
| ATR14 외 전체 테스트의 재현 가능한 실패 2건 | 2026-10-09 `pytest -m 'not integration and not api'` 재실행에서 711개 통과·기존 2개 실패. `test_incremental_sync_e2e`는 재실행 가격 수량 0을 260으로 기대했고, `test_clean_snapshot_on_postgres_is_reproducible_and_rolls_back`는 새 coverage 형식·품질 gate 대신 이전 형식을 기대했다. 두 테스트는 2026-10-08에도 같은 사유로 실패했다 | ATR14 관련 22개 테스트는 통과했으나 저장소 전체 테스트 gate는 통과하지 못함 | 해당 배치·clean snapshot 계약과 테스트 기대값을 별도 범위에서 대조·수정 |

## 해결한 문제

| 항목 | 증거 | 영향 | 조치 |
|---|---|---|---|
| 관측 정렬의 UTC 시각 혼합 | 2026-10-05 ATR PostgreSQL rebuild와 `test_selector_orders_fresh_and_reloaded_observations_with_consistent_utc`에서 새 aware 관측과 DB에서 읽은 naive 관측 비교가 `TypeError`로 실패 | 같은 세션에서 관측 추가 후 EMA·Volume·ATR 선택이 실패할 수 있음 | 두 관측 정렬 경로에 기존 UTC 정규화 함수를 적용하고 단위·PostgreSQL 회귀 검증 |
| ATR14 역사 백필 동시 writer와 체크포인트/DB 불일치 | 격리 셸에서 보이지 않던 호스트 writer가 실행 중인 상태에서 Docker writer를 추가 기동해 checkpoint에 `IntegrityError` 17건이 기록됐다. `reports/atr14/reconciliation_20130102_20260904.json`은 승인 manifest에 대해 2,175개 완료 run과 input/result 각 7,303,650행의 저장값 hash·상태 수량을 검증했다 | 원래 apply report의 실패 17건은 DB 저장 실패가 아니었으며 결과나 lineage 손실은 확인되지 않았다 | 중복 writer를 중지하고 원래 writer 완료 후 DB와 일치하는 17개 checkpoint 표기만 복구했다. 재개 시 호스트 PID namespace와 DB 연결을 함께 확인한다 |

## 추적 중인 운영 개선

| 항목 | 증거 | 영향 | 다음 조치 |
|---|---|---|---|
| 전체 역사 지표 계획 보고서의 긴 실행 시간 | 2026-10-05의 2013-01-02~2026-09-04 전체 범위 Volume MA50·ATR14 읽기 전용 manifest가 각각 약 22분 소요 | DB를 변경하지는 않지만 운영자가 완료 시점과 진행률을 즉시 알기 어렵다 | 대상 처리 수·경과 시간·예상 잔여를 출력하는 progress reporting과 selector/query profile을 별도 개선으로 검토 |
