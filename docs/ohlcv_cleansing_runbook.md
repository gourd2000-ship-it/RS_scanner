# OHLCV 클렌징 실행 기록

기준일: 2026-10-02. 대상: 2013-01-01~2026-09-04 KOSPI/KOSDAQ 보통주, 2026-10-01 기준 상폐가 확인된 lifecycle 제외. 관측 cutoff는 2026-10-02 08:40 UTC, 가격 선택은 `kiwoom:1`이다. 이는 기준일 생존 종목 중심의 연구 집합이며 과거 전체 시장을 대표하지 않는다.

## 실행 순서

~~~bash
APP_ENV=production .venv/bin/python scripts/audit_historical_ohlcv.py \
  --start 2013-01-01 --end 2026-09-04 \
  --selection-as-of 2026-10-01 \
  --observation-cutoff 2026-10-02T08:40:00Z \
  --adjustment-policy kiwoom:1 --exclude-delisted --read-only \
  --output reports/cleansing/baseline_v5_2013_20260904
~~~

1. `scripts/audit_historical_ohlcv.py`를 `--read-only --exclude-delisted`로 실행한다. PostgreSQL에서는 `REPEATABLE READ, READ ONLY` 트랜잭션을 쓴다. 출력 디렉터리의 `manifest.json`, `summary.json`, `symbol_year_coverage.csv`, `segment_assessment.csv`, `gaps.csv`, `anomalies.csv`, `source_conflicts.csv`, `excluded_universe.csv`, `unresolved_identity.csv`를 보존한다.
2. `summary.json`의 expected가 valid + missing + invalid + review_required와 같은지 확인한다. `assessment.json`의 complete는 그 종목·연도 기대 행이 모두 valid인 경우다. partial은 일부만 valid, unavailable은 유효 행이 없는 경우다.
3. `anomalies.csv`를 확인해 극단적 수익률은 기업행위·원자료와 대조한다. 30%는 검토 신호이며 법적 가격제한이 아니다. `source_conflicts.csv`의 canonical 차이는 공급자/수정주가 차이를 포함하므로 자동 보정하거나 오류로 확정하지 않는다.
4. 복구 후보는 `build_repair_plan(audit_dir, request_budget=0)`으로 먼저 계산한다. 기본 예산은 0이며 상폐 lifecycle에 재조회 요청을 보내지 않는다. 요청 수는 가장 오래된 결측일까지의 달력일을 600행 페이지로 나눈 보수적 추정치일 뿐, 실제 조회 계획이 아니다.
5. 격리 PostgreSQL에서 전체 migration과 `create_clean_backtest_dataset`의 같은 입력 재실행, 페이지 replay를 검증한다. 운영 DB schema 반영과 데이터셋 발행은 감사 수량·리소스와 보정 결정을 검토한 뒤 별도 단계로 수행한다. 발행 시 `scripts/create_clean_backtest_dataset.py --audit-dir ... --create`를 쓰며, 감사 규칙 버전과 상태별 수량이 일치하지 않으면 중단된다.

## 근거와 판정 제한

`PriceObservation`은 보존된 정규화 관측값이고 원 응답 전문은 저장되지 않았다. `source_verified` 수치는 지정 공급자·조정 유형의 보존 관측값이 있음을 뜻하며 원 응답 전문과의 독립 대조율을 뜻하지 않는다. Kiwoom 백필 관측은 `HistoricalBackfillRun.base_date=20260904`, `adjustment_type=1`에 연결돼 있다. 공급자의 수정주가·거래량 조정 의미와 기업행위별 일관성은 독립 확인이 더 필요하다.

현재 정지 이벤트 정보가 충분하지 않으면 `non_tradable=0`을 실제 정지 0건으로 해석하면 안 된다. identity 미확인과 결측은 별도로 유지한다. 승인된 보정·제외는 원본을 덮지 않고 새 데이터셋에만 반영한다. 유효 구간을 사후 선택하면 생존 편향에 더해 구간 선택 편향이 생길 수 있으므로 탈락·제외 목록을 함께 제시한다.

감사 기준 시점의 `CorporateAction` 테이블은 0행이다. 따라서 급격한 수익률 검토 대상 중 분할·병합 등을 자동 확인할 수 없으며, 이 행들을 근거 없이 유효로 승격하지 않는다.

종목 097870(효성오앤비)은 `kiwoom:1` 관측이 2024-03-19부터만 저장돼 있다. 기존 백필 대상 상태는 `provider_unsupported`다. 이 종목의 앞 구간은 단순 누락 재요청으로 복구 가능하다고 분류해서는 안 되며, 다른 허용 공급자의 조정 정책을 별도로 검증하기 전까지 미확보로 둔다.

## 운영 감사 결과

4거래일 표본 [canary_v5 보고서](../reports/cleansing/canary_v5_20260901_20260904/summary.json): 기대 8,700행, 관측 8,700행, 유효 8,699행, 검토 1행, 결측 0행. 확인된 상폐 lifecycle 1,508개를 제외했고 identity 미확인 594개는 별도 집계했다. 검토 1행은 2026-09-03의 121850으로, 기업행위 근거가 없는 큰 종가 변화다. 이는 조사 대상으로만 표시했다.

첫 전수 기준선 `baseline_v3`는 상폐일이 `Instrument`에만 있고 `ListingEvent`에 종료 이벤트가 없는 42개 lifecycle을 누락해 기대 행과 결측을 과다 계산했다. 해당 보고서는 판정에 사용하지 않는다. 이 오류를 고치고 회귀 테스트를 추가했다.

확정 전 기간 보고서: [baseline_v5 요약](../reports/cleansing/baseline_v5_2013_20260904/summary.json), [종목·연도 판정](../reports/cleansing/baseline_v5_2013_20260904/assessment.json). 읽기 전용 감사의 메모리 RSS는 관측 중 약 1.2GB였다.

| 항목 | 수량 |
|---|---:|
| 확인된 상폐 lifecycle 제외 | 1,508 |
| identity 미확인, 별도 분류 | 594 |
| 기대 거래행 | 5,083,105 |
| 관측행 | 5,080,612 |
| 유효행 | 5,080,047 |
| 결측행 | 2,493 |
| 검토 필요 | 565 |
| 구조상 invalid / 확인된 정지 | 0 / 0 |

검토 565행은 근거 없는 큰 가격 변동 300행과 선택한 `kiwoom:1` 관측이 없어 canonical의 다른 공급자 가격만 확인된 265행이다. 후자는 097870의 2023~2024 구간이다. 결측 2,493행도 모두 097870에 속한다. 종목·연도 구간은 complete 21,831개, partial 275개, unavailable 11개다. unavailable은 097870의 2013~2023 각 연도다. 다른 종목·연도의 partial은 큰 변동 검토행이 포함된 구간이다.

`source_conflicts.csv`에는 canonical과 선택 관측값의 OHLCV 차이 362,887행이 있다. 예를 들어 001840의 2023-02-15 canonical은 Naver, 선택 관측은 Kiwoom 수정주가로 가격·거래량이 다르다. 선택 공급자를 명시했으므로 이 차이를 모두 오류로 보지 않는다. 서로 다른 조정 기준의 숫자를 이어 붙이거나 무근거로 보정하지 않는다.

현재 복구 계획은 네트워크 예산 0, 대상 후보 1개(097870), 실행 요청 0개다. 그 후보도 기존 공급자 상태가 `provider_unsupported`이므로 자동 재조회 대상으로 승인되지 않았다. 일별 가격의 경제적 조정 의미·정지 이벤트·기업행위 근거가 보완되기 전까지 전체 OHLCV를 검증 완료로 선언하지 않는다.

검증은 격리 PostgreSQL에서 신규 migration까지 `alembic upgrade head`를 적용하고 롤백하는 데이터셋 통합 테스트, 단위·통합 360개 테스트, `git diff --check`와 Python 컴파일 검사로 수행했다. 테스트 DB 컨테이너는 검증 후 내렸다. 운영 DB migration·보정 적용·데이터셋 발행은 수행하지 않았다.
