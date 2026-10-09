# 현재 상태

## 완료

- KOSPI·KOSDAQ 종목 수집, 가격·RS 계산, FastAPI 조회, Next.js 화면, Alembic schema 이력이 구현돼 있다.
- 역사 종목 identity, listing event, 가격 관측 lineage, 품질 판정, materialized backtest dataset과 replay 경로가 구현돼 있다.
- 백테스트 계산 기능은 구현 완료됐다. 전략·버전 저장, 실행 전 검증·요청, 고정 dataset·RS 입력 선택, 종가 신호/다음 거래일 시가 체결 시뮬레이터, 수수료·슬리피지·포지션·종료일 청산 계산, 결과 저장·조회 API와 명시적 워커 CLI가 코드 및 테스트에 있다.
- 거래량 MA50·ATR14 전략 비교 조건, dataset과 lineage가 일치하는 불변 지표 snapshot, 실행별 snapshot ID/hash 고정, 운영자 전용 현재 generation 조회 API와 `/backtests` 화면이 구현돼 있다. 지표를 쓰는 실행은 사전 점검에서 필요한 날짜별 값이 모두 사용 가능해야 queue에 들어간다.
- 2026-10-02 읽기 전용 OHLCV 감사는 2013-01-01~2026-09-04의 생존 lifecycle 집합을 기준으로 수행됐다. 유효 5,080,047행, 결측 2,493행, 검토 565행이며, complete 21,831 종목·연도 구간이 확인됐다.
- 내부 자동화 읽기 API와 사람 운영자 쓰기 API는 token·IP allowlist 설정을 분리하며 repair·analysis 쓰기 API는 기본 비활성이다.

## 남은 일

1. 최신으로 확인한 보관 일일 품질 보고서 `job_137`은 `blocked`다. 실패·stale 입력을 원인별로 조사하고 새 보고서에서 coverage·freshness 통과를 확인한다.
2. 새 품질 gate가 통과하고 운영 결정이 내려진 뒤에만 기본 비활성인 일일 MA50·ATR14 증분 계산을 제한 검증한다.
3. `complete` 구간만 대상으로 운영 dataset을 발행하고, 실제 발행본의 페이지 replay·coverage를 운영 환경에서 검증한다.
4. 별도 워커 CLI를 승인된 배치 환경에 배포하고, 검증된 발행 dataset으로 요청→실행→결과 저장·조회 운영 검증을 수행한다. 코드는 준비됐으나 운영 연결은 확인되지 않았다.
5. 097870의 공급자 미지원 이력과 565개 검토 행에 허용 근거·조정 정책을 확보하거나 계속 제외한다. 상장폐지 lifecycle은 역사 가격·terminal event 데이터가 없어 백테스트 범위에 포함하지 않는다. 상폐 청산 모델과 생존편향 제거는 완료 범위가 아니다.
6. 관리자용 원격 UI/API가 필요해지면 사람 운영자 인증과 쓰기 감사 체계를 별도로 설계한다.

## 차단 요인

역사 상폐 데이터와 기업행위 근거의 비용·이용 조건·coverage가 확정되지 않았다. 따라서 현재 결과는 상폐 제외 개인 연구 범위의 검증 완료 구간에 한정된다.

- 거래량 MA50: 공용 불변 input evidence, 저장 service, 계획·재개 백필 도구, 기본 비활성 일일 증분을 구현했다. 승인 manifest `957cac…b0b70`의 2,175개 대상 역사 백필은 2026-10-07 완료됐으며 apply report는 신규 1,623개·재사용 552개·실패 0건을 기록한다. DB의 completed run 2,175개와 series 2,175개, value 7,303,650개를 대조했다. 일일 증분·공개 활성화는 최신 quality gate 통과 후 별도 운영 결정이 필요하다.
- ATR14: 공용 OHLC evidence와 별도 series를 사용하는 영속 계산 service, 계획·재개 백필 도구, 기본 비활성 일일 증분을 구현했다. 운영 migration과 승인 manifest `191847c…7e68cdb15`의 역사 DB 백필은 2026-10-08 완료됐다. 원래 apply report의 동시 writer 충돌 17건은 DB의 승인된 완료 run과 저장값을 전수 검증한 뒤 checkpoint에서만 복구했다. 최종 reconciliation report는 2,175개 대상과 input/result 각 7,303,650행, 상태별 수량·result hash의 일치를 확인했으며 DB의 ATR series·completed run도 각각 2,175개다. 감시 컨테이너는 정상 종료했다. 일일 증분·공개 활성화는 최신 quality gate 통과 후 별도 운영 결정이 필요하다.
- 최신으로 확인한 보관 일일 품질 보고서 `reports/data_quality/job_137.json`(2026-10-08)은 coverage 94.8169%, stale 201개로 `blocked`다. 저장된 보고서만 확인했으며 운영 DB의 실시간 상태는 조회하지 않았다. RS·ATR14·거래량 MA50의 후속 활성화와 dataset 발행은 새 품질 gate가 통과할 때까지 보류한다.
- 일일 지표는 기본 비활성이고 워커는 자동 시작되지 않는다. 준비 보고서와 격리 DB 테스트는 운영 배포·dataset 발행·replay 검증을 대체하지 않는다.
- T8 실행 준비 판정과 검증·중단·재개·되돌림 절차: [backtest MA50·ATR14 준비 보고서](../../reports/operations/backtest_ma50_atr14_readiness_20261009.md).
