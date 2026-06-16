"""벤치마크 재크롤링 + RS 재계산 스크립트.

벤치마크 데이터를 최신까지 크롤링하고 RS를 재계산한 뒤 텔레그램으로 결과를 전송한다.
"""

import logging
import sys
import time
from datetime import date, datetime

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    from app.core.database import session_scope
    from app.core.notification import get_notification_service
    from app.crawler.sources.naver import NaverPriceSource
    from app.services.batch.calculate_rs import calculate_rs
    from app.services.batch.context import build_db_batch_context
    from app.services.batch.sync_benchmarks import sync_benchmarks

    notification = get_notification_service()
    source = NaverPriceSource()
    started_at = datetime.utcnow()
    target_date = date.today()

    logger.info("벤치마크 재크롤링 시작")

    # Step 1: 벤치마크 크롤링
    logger.info("Step 1: 벤치마크 크롤링")
    t0 = time.time()
    with session_scope() as session:
        ctx = build_db_batch_context(session)
        benchmark_rows = sync_benchmarks(ctx, source)
    benchmark_elapsed = time.time() - t0

    bench_summary = {
        market: len(rows) for market, rows in benchmark_rows.items()
    }
    bench_latest = {
        market: rows[-1].trade_date if rows else None
        for market, rows in benchmark_rows.items()
    }
    logger.info(f"벤치마크 크롤링 완료: {bench_summary}, 최신날짜: {bench_latest}")

    # Step 2: RS 재계산
    logger.info(f"Step 2: RS 재계산 (target_date={target_date})")
    t1 = time.time()
    with session_scope() as session:
        ctx = build_db_batch_context(session)
        rs_results = calculate_rs(ctx, target_date=target_date)
    rs_elapsed = time.time() - t1

    rs_summary = {market: len(rows) for market, rows in rs_results.items()}
    logger.info(f"RS 재계산 완료: {rs_summary}")

    total_elapsed = (datetime.utcnow() - started_at).total_seconds()

    # Step 3: 텔레그램 완료 알림
    kospi_count = rs_summary.get("KOSPI", 0)
    kosdaq_count = rs_summary.get("KOSDAQ", 0)
    kospi_bench_date = bench_latest.get("KOSPI")
    kosdaq_bench_date = bench_latest.get("KOSDAQ")

    message = (
        f"✅ *벤치마크 재크롤링 완료*\n\n"
        f"*기준일*: {target_date}\n\n"
        f"*벤치마크 업데이트*\n"
        f"  KOSPI: {kospi_bench_date}\n"
        f"  KOSDAQ: {kosdaq_bench_date}\n\n"
        f"*RS 재계산 결과*\n"
        f"  KOSPI: {kospi_count:,}개\n"
        f"  KOSDAQ: {kosdaq_count:,}개\n\n"
        f"*소요 시간*\n"
        f"  벤치마크: {benchmark_elapsed:.0f}초\n"
        f"  RS 계산: {rs_elapsed:.0f}초\n"
        f"  합계: {total_elapsed:.0f}초"
    )

    import httpx
    from app.core.config import get_settings
    settings = get_settings()

    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json={
                    "chat_id": settings.telegram_chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                })
                resp.raise_for_status()
            logger.info("텔레그램 알림 전송 완료")
        except Exception as e:
            logger.error(f"텔레그램 알림 실패: {e}")
    else:
        logger.warning("텔레그램 미설정 — 알림 스킵")
        print("\n--- 전송할 메시지 ---")
        print(message)

    logger.info("전체 작업 완료")


if __name__ == "__main__":
    main()
