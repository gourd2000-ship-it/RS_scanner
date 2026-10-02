-- DBG01 읽기 전용 진단. 2026-09-01~09-30, 저장소 거래일 달력 기준.
-- 미저장일은 거래정지/상장 전/RS 부적격을 분류하기 전의 관측 공백이다.
-- 운영 데이터나 임시 테이블을 변경하지 않는다.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '30s';
WITH days AS (
  SELECT day::date AS d FROM generate_series('2026-09-01'::date, '2026-09-30'::date, '1 day') day
  WHERE extract(isodow FROM day) < 6 AND day::date NOT IN ('2026-09-24', '2026-09-25')
), targets AS (
  SELECT s.id, s.code, s.market, s.symbol_type, s.is_active, s.listed_at, s.delisted_at,
    (SELECT max(trade_date) FROM daily_prices p WHERE p.symbol_id=s.id) AS last_price,
    (SELECT max(trade_date) FROM rs_scores r WHERE r.symbol_id=s.id) AS last_rs
  FROM symbols s
), coverage AS (
  SELECT t.*, array_agg(d.d ORDER BY d.d) FILTER (WHERE p.symbol_id IS NULL) AS absent_price_dates,
    array_agg(d.d ORDER BY d.d) FILTER (WHERE r.symbol_id IS NULL) AS absent_rs_dates
  FROM targets t CROSS JOIN days d
  LEFT JOIN daily_prices p ON p.symbol_id=t.id AND p.trade_date=d.d
  LEFT JOIN rs_scores r ON r.symbol_id=t.id AND r.trade_date=d.d
  GROUP BY t.id,t.code,t.market,t.symbol_type,t.is_active,t.listed_at,t.delisted_at,t.last_price,t.last_rs
)
SELECT row_to_json(c) FROM coverage c ORDER BY code;
ROLLBACK;
