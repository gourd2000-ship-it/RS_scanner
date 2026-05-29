"""쿼리 성능 테스트 및 인덱스 검증 스크립트."""

import time
from datetime import date

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.models.daily_price import DailyPrice
from app.models.rs_score import RsScore
from app.models.symbol import Symbol


def explain_query(session: Session, stmt, description: str):
    """EXPLAIN ANALYZE로 쿼리 플랜 출력."""
    print(f"\n{'=' * 80}")
    print(f"Query: {description}")
    print(f"{'=' * 80}")

    # 쿼리 문자열로 변환
    compiled = stmt.compile(compile_kwargs={"literal_binds": True})
    query_str = str(compiled)

    # EXPLAIN ANALYZE 실행
    explain_stmt = text(f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE) {query_str}")
    result = session.execute(explain_stmt)

    print("\nQuery Plan:")
    for row in result:
        print(row[0])
    print()


def measure_query_time(session: Session, stmt, description: str, iterations: int = 5):
    """쿼리 실행 시간 측정."""
    print(f"\n{'=' * 80}")
    print(f"Performance Test: {description}")
    print(f"{'=' * 80}")

    times = []
    for i in range(iterations):
        start = time.time()
        session.execute(stmt).all()
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"  Iteration {i + 1}: {elapsed * 1000:.2f}ms")

    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)

    print(f"\n  Average: {avg_time * 1000:.2f}ms")
    print(f"  Min: {min_time * 1000:.2f}ms")
    print(f"  Max: {max_time * 1000:.2f}ms")
    print()

    return avg_time


def test_rankings_query(session: Session):
    """Rankings API 쿼리 테스트."""
    print("\n" + "=" * 80)
    print("TEST 1: Rankings Query (with JOIN)")
    print("=" * 80)

    market = "KOSPI"

    # 최신 거래일 찾기
    target_trade_date = session.scalar(
        select(func.max(RsScore.trade_date)).where(RsScore.market == market)
    )

    if target_trade_date is None:
        print("No data available for rankings query")
        return

    # 최신 가격 서브쿼리
    latest_price_subq = (
        select(
            DailyPrice.symbol_id,
            DailyPrice.close,
            DailyPrice.change_rate,
            func.row_number()
            .over(partition_by=DailyPrice.symbol_id, order_by=DailyPrice.trade_date.desc())
            .label("rn"),
        )
        .subquery()
    )

    # 메인 쿼리
    stmt = (
        select(
            RsScore,
            Symbol.code,
            Symbol.name,
            latest_price_subq.c.close,
            latest_price_subq.c.change_rate,
        )
        .join(Symbol, Symbol.id == RsScore.symbol_id)
        .outerjoin(
            latest_price_subq,
            (latest_price_subq.c.symbol_id == RsScore.symbol_id) & (latest_price_subq.c.rn == 1),
        )
        .where(RsScore.market == market, RsScore.trade_date == target_trade_date)
        .order_by(RsScore.rank_in_market)
        .limit(100)
    )

    # EXPLAIN ANALYZE
    explain_query(session, stmt, "Rankings with prices (100 items)")

    # 성능 측정
    measure_query_time(session, stmt, "Rankings with prices (100 items)")


def test_stock_detail_query(session: Session):
    """Stock detail API 쿼리 테스트."""
    print("\n" + "=" * 80)
    print("TEST 2: Stock Detail Query (optimized with window functions)")
    print("=" * 80)

    # 첫 번째 종목 코드 가져오기
    code = session.scalar(select(Symbol.code).limit(1))
    if code is None:
        print("No symbols available")
        return

    # 최신 가격 서브쿼리
    latest_price_subq = (
        select(
            DailyPrice.symbol_id,
            DailyPrice.trade_date.label("price_trade_date"),
            DailyPrice.open,
            DailyPrice.high,
            DailyPrice.low,
            DailyPrice.close,
            DailyPrice.volume,
            DailyPrice.change_rate,
            func.row_number().over(
                partition_by=DailyPrice.symbol_id, order_by=DailyPrice.trade_date.desc()
            ).label("price_rn"),
        )
        .subquery()
    )

    # 최신 RS 서브쿼리
    latest_rs_subq = (
        select(
            RsScore.symbol_id,
            RsScore.trade_date.label("rs_trade_date"),
            RsScore.rs_rating,
            RsScore.rank_in_market,
            RsScore.return_3m,
            RsScore.return_6m,
            RsScore.return_9m,
            RsScore.return_12m,
            RsScore.relative_return_score,
            RsScore.rs_percentile,
            func.row_number().over(
                partition_by=RsScore.symbol_id, order_by=RsScore.trade_date.desc()
            ).label("rs_rn"),
        )
        .subquery()
    )

    # 메인 쿼리
    stmt = (
        select(
            Symbol,
            latest_price_subq.c.price_trade_date,
            latest_price_subq.c.open,
            latest_price_subq.c.close,
            latest_rs_subq.c.rs_trade_date,
            latest_rs_subq.c.rs_rating,
        )
        .outerjoin(
            latest_price_subq,
            (latest_price_subq.c.symbol_id == Symbol.id) & (latest_price_subq.c.price_rn == 1),
        )
        .outerjoin(
            latest_rs_subq,
            (latest_rs_subq.c.symbol_id == Symbol.id) & (latest_rs_subq.c.rs_rn == 1),
        )
        .where(Symbol.code == code)
    )

    # EXPLAIN ANALYZE
    explain_query(session, stmt, f"Stock detail for {code}")

    # 성능 측정
    measure_query_time(session, stmt, f"Stock detail for {code}")


def test_index_usage(session: Session):
    """인덱스 사용률 확인."""
    print("\n" + "=" * 80)
    print("TEST 3: Index Usage Statistics")
    print("=" * 80)

    # PostgreSQL 인덱스 통계 조회
    stmt = text("""
        SELECT
            schemaname,
            relname as tablename,
            indexrelname as indexname,
            idx_scan as index_scans,
            idx_tup_read as tuples_read,
            idx_tup_fetch as tuples_fetched
        FROM pg_stat_user_indexes
        WHERE schemaname = 'public'
          AND relname IN ('symbols', 'rs_scores', 'daily_prices')
        ORDER BY relname, indexrelname;
    """)

    result = session.execute(stmt)

    print("\nIndex Usage:")
    print(f"{'Table':<20} {'Index':<40} {'Scans':<10} {'Tuples Read':<15} {'Tuples Fetched':<15}")
    print("-" * 100)

    for row in result:
        print(
            f"{row.tablename:<20} {row.indexname:<40} {row.index_scans:<10} "
            f"{row.tuples_read:<15} {row.tuples_fetched:<15}"
        )

    print()


def test_table_stats(session: Session):
    """테이블 통계 조회."""
    print("\n" + "=" * 80)
    print("TEST 4: Table Statistics")
    print("=" * 80)

    stmt = text("""
        SELECT
            schemaname,
            relname as tablename,
            n_tup_ins as inserts,
            n_tup_upd as updates,
            n_tup_del as deletes,
            n_live_tup as live_tuples,
            n_dead_tup as dead_tuples,
            last_vacuum,
            last_autovacuum,
            last_analyze,
            last_autoanalyze
        FROM pg_stat_user_tables
        WHERE schemaname = 'public'
          AND relname IN ('symbols', 'rs_scores', 'daily_prices', 'benchmarks')
        ORDER BY relname;
    """)

    result = session.execute(stmt)

    print("\nTable Statistics:")
    print(f"{'Table':<20} {'Live Tuples':<15} {'Dead Tuples':<15} {'Inserts':<10} {'Updates':<10}")
    print("-" * 80)

    for row in result:
        print(
            f"{row.tablename:<20} {row.live_tuples:<15} {row.dead_tuples:<15} "
            f"{row.inserts:<10} {row.updates:<10}"
        )

    print()


def main():
    """메인 함수."""
    print("\n" + "=" * 80)
    print("Query Performance Test & Index Verification")
    print("=" * 80)

    with next(get_db_session()) as session:
        # 1. Rankings 쿼리 테스트
        test_rankings_query(session)

        # 2. Stock detail 쿼리 테스트
        test_stock_detail_query(session)

        # 3. 인덱스 사용률 확인
        test_index_usage(session)

        # 4. 테이블 통계
        test_table_stats(session)

    print("\n" + "=" * 80)
    print("Test completed!")
    print("=" * 80)


if __name__ == "__main__":
    main()
