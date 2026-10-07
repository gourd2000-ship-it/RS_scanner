# 미해결 사항

| 항목 | 증거 | 영향 | 다음 조치 |
|---|---|---|---|
| 프런트엔드 기존 lint 오류 | 2026-10-03 `npm run lint`: operations의 render/effect 규칙, 주가 차트와 공통 API client의 `any` 등 12 errors·5 warnings | 전체 lint 실패, 백테스트 조건 화면의 범위 lint와 production build는 통과 | 해당 화면·공통 client 개선 시 별도 정리 |
| 097870 장기 이력 미확보 | 2013~2023은 `provider_unsupported`, 결측 2,493행 | 해당 종목·연도는 dataset에서 제외 | 조정 기준이 검증된 허용 공급자를 확보할 때만 재평가 |
| 기업행위 근거 부족 | `CorporateAction` 0행, extreme return 검토 300행 | 265개 외 source 검토 행을 포함해 565행이 complete 불가 | 원자료·공식 이벤트 근거를 연결하거나 계속 제외 |
| 상장폐지 lifecycle 데이터 없음 | 확인된 상폐 lifecycle 1,508개 제외 | 생존편향 제거 완료 주장과 상폐 청산 backtest 불가 | 비용·이용 조건이 맞는 역사 데이터 계약 전까지 범위 밖 유지 |
| 수정 기준 차이 | canonical과 `kiwoom:1` 차이 362,887행 | 공급자 혼합 시 왜곡 가능 | 선택 정책을 고정하고 자동 보정 금지 |
| 사람 운영자 원격 인증 부재 | 운영자 권한은 운영 환경 접근에 의존 | 원격 관리 기능을 안전하게 공개할 수 없음 | 필요 시 별도 인증·감사 설계 |
| 2026-10-06 일일 수집 품질 gate 차단 | `reports/data_quality/job_132.json`, `job_133.json`: 4,340개 대상 중 4,140개 fetch·200개 실패, coverage 94.9539%, stale 195개, `validation_status=blocked` | 당일 RS 입력·후속 RS 계산을 검증 완료로 승격할 수 없음; health endpoint의 마지막 batch도 `completed_with_errors` | 200개 ingest 실패와 195개 stale input을 원인별로 분류·복구한 뒤 새 quality report에서 coverage 및 freshness gate를 재검증 |

## 해결한 문제

| 항목 | 증거 | 영향 | 조치 |
|---|---|---|---|
| 관측 정렬의 UTC 시각 혼합 | 2026-10-05 ATR PostgreSQL rebuild와 `test_selector_orders_fresh_and_reloaded_observations_with_consistent_utc`에서 새 aware 관측과 DB에서 읽은 naive 관측 비교가 `TypeError`로 실패 | 같은 세션에서 관측 추가 후 EMA·Volume·ATR 선택이 실패할 수 있음 | 두 관측 정렬 경로에 기존 UTC 정규화 함수를 적용하고 단위·PostgreSQL 회귀 검증 |

## 추적 중인 운영 개선

| 항목 | 증거 | 영향 | 다음 조치 |
|---|---|---|---|
| 전체 역사 지표 계획 보고서의 긴 실행 시간 | 2026-10-05의 2013-01-02~2026-09-04 전체 범위 Volume MA50·ATR14 읽기 전용 manifest가 각각 약 22분 소요 | DB를 변경하지는 않지만 운영자가 완료 시점과 진행률을 즉시 알기 어렵다 | 대상 처리 수·경과 시간·예상 잔여를 출력하는 progress reporting과 selector/query profile을 별도 개선으로 검토 |
