# 현재 상태

## 완료

- KOSPI·KOSDAQ 종목 수집, 가격·RS 계산, FastAPI 조회, Next.js 화면, Alembic schema 이력이 구현돼 있다.
- 역사 종목 identity, listing event, 가격 관측 lineage, 품질 판정, materialized backtest dataset과 replay 경로가 구현돼 있다.
- 2026-10-02 읽기 전용 OHLCV 감사는 2013-01-01~2026-09-04의 생존 lifecycle 집합을 기준으로 수행됐다. 유효 5,080,047행, 결측 2,493행, 검토 565행이며, complete 21,831 종목·연도 구간이 확인됐다.
- 내부 자동화 읽기 API와 사람 운영자 쓰기 API는 token·IP allowlist 설정을 분리하며 repair·analysis 쓰기 API는 기본 비활성이다.

## 남은 일

1. `complete` 구간만 대상으로 실제 데이터셋을 발행하고, 발행된 dataset의 페이지 replay·coverage를 운영 환경에서 검증한다.
2. 097870의 공급자 미지원 이력과 565개 검토 행에 대해 허용된 근거·조정 정책을 확보하거나 계속 제외한다.
3. 상장폐지 lifecycle의 역사 가격·terminal event 데이터는 확보 계획이 없으므로 백테스트 범위에 포함하지 않는다.
4. 매매 체결, 수수료, 슬리피지, 포지션·상폐 청산을 모델링하는 시뮬레이터는 구현돼 있지 않다. 데이터셋 검증 뒤 별도 요구사항으로 설계한다.
5. 관리자용 원격 UI/API가 필요해지면 사람 운영자 인증과 쓰기 감사 체계를 별도로 설계한다.

## 차단 요인

역사 상폐 데이터와 기업행위 근거의 비용·이용 조건·coverage가 확정되지 않았다. 따라서 현재 결과는 상폐 제외 개인 연구 범위의 검증 완료 구간에 한정된다.
