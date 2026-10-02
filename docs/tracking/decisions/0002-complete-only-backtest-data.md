# 0002 검증 완료 구간만 백테스트 발행

OHLCV가 부분적이거나 검토 대상으로 남은 결과를 표시하지 않고, 모든 기대 행이 valid인 `complete` 종목·연도 구간만 backtest dataset에 발행한다.

이 결정은 결측·추정 가격을 조용히 사용한 연구 결과를 막는다. 범위가 줄어드는 비용은 acceptance coverage와 제외 목록으로 명시한다.
