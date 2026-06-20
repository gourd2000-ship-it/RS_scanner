"""RS 재계산 스크립트 (ETF/ETN 제외 + 기업이벤트 필터링 적용).

기존 DB 가격 데이터를 기반으로 RS를 재계산한다.
Phase A 필터링(ETF/ETN 제외, 기업이벤트 감지)이 적용된 결과를 확인할 수 있다.
"""

import logging
import sys

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    from app.core.database import session_scope
    from app.services.batch.calculate_rs import calculate_rs
    from app.services.batch.context import build_db_batch_context

    logger.info("RS 재계산 시작 (ETF/ETN 제외 + 기업이벤트 필터링)")

    with session_scope() as session:
        context = build_db_batch_context(session)
        results = calculate_rs(context)

        for market, count in results.items():
            logger.info("market=%s: %d종목 RS 계산 완료", market, count)

        logger.info("상위 10종목 확인:")
        from sqlalchemy import text
        for market in ["KOSPI", "KOSDAQ"]:
            rows = session.execute(text("""
                SELECT s.code, s.name, rs.rs_rating, rs.rank_in_market,
                       rs.return_3m, rs.return_6m, rs.return_9m, rs.return_12m
                FROM rs_scores rs
                JOIN symbols s ON s.id = rs.symbol_id
                WHERE rs.market = :market
                ORDER BY rs.trade_date DESC, rs.rank_in_market ASC
                LIMIT 10
            """), {"market": market}).fetchall()

            logger.info("=== %s 상위 10 ===", market)
            for r in rows:
                logger.info(
                    "  %s %s: RS=%d rank=%d 3m=%.0f%% 6m=%.0f%% 9m=%.0f%% 12m=%.0f%%",
                    r[0], r[1], r[2], r[3],
                    float(r[4]) * 100, float(r[5]) * 100, float(r[6]) * 100, float(r[7]) * 100,
                )

    logger.info("RS 재계산 완료")


if __name__ == "__main__":
    main()
