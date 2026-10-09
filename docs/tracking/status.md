# 현재 상태

## 완료

- KOSPI·KOSDAQ 종목 수집, 가격·RS 계산, FastAPI 조회, Next.js 화면, Alembic schema 이력이 구현돼 있다.
- 역사 종목 identity, listing event, 가격 관측 lineage, 품질 판정, materialized backtest dataset과 replay 경로가 구현돼 있다.
- 백테스트 계산 기능은 구현 완료됐다. 전략·버전 저장, 실행 요청·상태/결과 조회 API, 고정 dataset·RS 입력 선택, 종가 신호/다음 거래일 시가 체결 시뮬레이터, 수수료·슬리피지·포지션·종료일 청산 계산과 결과 저장이 코드 및 테스트에 있다. `/backtests` 화면은 전략 입력·실행 요청·실행 상태를 제공한다.
- 2026-10-02 읽기 전용 OHLCV 감사는 2013-01-01~2026-09-04의 생존 lifecycle 집합을 기준으로 수행됐다. 유효 5,080,047행, 결측 2,493행, 검토 565행이며, complete 21,831 종목·연도 구간이 확인됐다.
- 내부 자동화 읽기 API와 사람 운영자 쓰기 API는 token·IP allowlist 설정을 분리하며 repair·analysis 쓰기 API는 기본 비활성이다.

## 남은 일

1. 2026-10-08 일일 품질 gate의 수집 실패·stale 입력을 원인별로 복구하고, 새 보고서에서 coverage·freshness 통과를 확인한다.
2. 통과한 일일 배치에서 거래량 MA50·ATR14 증분 계산을 각각 소규모로 검증한 뒤 활성화 여부를 운영 결정한다. 역사 백필 완료만으로 일일 계산이나 공개 API를 켜지 않는다.
3. `complete` 구간만 대상으로 실제 데이터셋을 발행하고, 발행된 dataset의 페이지 replay·coverage를 운영 환경에서 검증한다.
4. 백테스트 실행 서비스를 호출하는 별도 워커의 운영 진입점·배포를 연결하고, 검증 완료 dataset으로 요청→실행→결과 저장·조회까지 운영 검증한다. 현재 화면에는 실행 기록만 있으며 결과 상세 화면은 없다.
5. 거래량 MA50·ATR14를 백테스트 조건이나 공개 화면에 사용할 경우, 고정 dataset과 지표 generation·입력 hash를 연결하는 계약과 검증을 먼저 추가한다.
6. 097870의 공급자 미지원 이력과 565개 검토 행에 대해 허용된 근거·조정 정책을 확보하거나 계속 제외한다. 상장폐지 lifecycle은 역사 가격·terminal event 데이터가 없어 백테스트 범위에 포함하지 않는다. 따라서 상폐 청산 모델과 생존편향 제거는 완료 범위에 포함되지 않는다.
7. 관리자용 원격 UI/API가 필요해지면 사람 운영자 인증과 쓰기 감사 체계를 별도로 설계한다.

## 차단 요인

역사 상폐 데이터와 기업행위 근거의 비용·이용 조건·coverage가 확정되지 않았다. 따라서 현재 결과는 상폐 제외 개인 연구 범위의 검증 완료 구간에 한정된다.

- 거래량 MA50: 공용 불변 input evidence, 저장 service, 계획·재개 백필 도구, 기본 비활성 일일 증분을 구현했다. 승인 manifest `957cac…b0b70`의 2,175개 대상 역사 백필은 2026-10-07 완료됐으며 apply report는 신규 1,623개·재사용 552개·실패 0건을 기록한다. DB의 completed run 2,175개와 series 2,175개, value 7,303,650개를 대조했다. 일일 증분·공개 활성화는 최신 quality gate 통과 후 별도 운영 결정이 필요하다.
- ATR14: 공용 OHLC evidence와 별도 series를 사용하는 영속 계산 service, 계획·재개 백필 도구, 기본 비활성 일일 증분을 구현했다. 운영 migration과 승인 manifest `191847c…7e68cdb15`의 역사 DB 백필은 2026-10-08 완료됐다. 원래 apply report의 동시 writer 충돌 17건은 DB의 승인된 완료 run과 저장값을 전수 검증한 뒤 checkpoint에서만 복구했다. 최종 reconciliation report는 2,175개 대상과 input/result 각 7,303,650행, 상태별 수량·result hash의 일치를 확인했으며 DB의 ATR series·completed run도 각각 2,175개다. 감시 컨테이너는 정상 종료했다. 일일 증분·공개 활성화는 최신 quality gate 통과 후 별도 운영 결정이 필요하다.
- 최신 일일 품질 보고서 `reports/data_quality/job_137.json`(2026-10-08)은 coverage 94.8169%, stale 201개로 `blocked`다. RS·ATR14·거래량 MA50의 후속 활성화는 보류한다.
