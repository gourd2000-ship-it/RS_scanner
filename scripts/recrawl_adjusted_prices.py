"""수정주가 전체 재크롤링 스크립트.

fchart API를 사용하여 모든 종목의 가격 데이터를 수정주가로 교체한다.
기존 raw 가격 데이터는 UPSERT로 덮어쓴다.

예상 소요: ~2,813종목 × ~2초/종목 ≈ 94분

사용법:
    python scripts/recrawl_adjusted_prices.py [--start-from CODE] [--dry-run]
"""

import argparse
import logging
import sys
import time

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="수정주가 전체 재크롤링")
    parser.add_argument("--start-from", type=str, default=None, help="이 종목 코드부터 재개")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 크롤링만 테스트")
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.core.database import session_scope
    from app.crawler.sources.naver import NaverPriceSource
    from app.services.batch.context import build_db_batch_context
    from app.services.batch.calculate_rs import calculate_rs
    from app.services.validation.market_data import validate_prices

    settings = get_settings()
    source = NaverPriceSource()
    chunk_size = settings.batch_chunk_size

    # 전 종목 목록 조회
    with session_scope() as session:
        context = build_db_batch_context(session)
        all_symbols = context.symbol_repository.list_all()

    all_symbols.sort(key=lambda s: s.code)
    total = len(all_symbols)
    logger.info("수정주가 재크롤링 시작: %d종목 (chunk_size=%d)", total, chunk_size)

    if args.start_from:
        skip_idx = next((i for i, s in enumerate(all_symbols) if s.code >= args.start_from), 0)
        logger.info("--start-from %s: %d종목 건너뜀", args.start_from, skip_idx)
        all_symbols = all_symbols[skip_idx:]

    started_at = time.time()
    success_count = 0
    fail_count = 0
    failed_codes: list[str] = []

    # 청크 단위 처리
    for chunk_start in range(0, len(all_symbols), chunk_size):
        chunk = all_symbols[chunk_start:chunk_start + chunk_size]
        chunk_success = 0

        with session_scope() as session:
            ctx = build_db_batch_context(session)

            for sym in chunk:
                try:
                    prices = source.fetch_daily_prices(sym.code, since_date=None)

                    if prices and not args.dry_run:
                        validate_prices(prices)
                        with session.begin_nested():
                            ctx.price_repository.save_symbol_prices(sym.code, prices)

                    chunk_success += 1
                    success_count += 1

                except Exception as e:
                    fail_count += 1
                    failed_codes.append(sym.code)
                    logger.warning("실패 %s: %s", sym.code, e)

                # 진행률 로그 (50개마다)
                done = chunk_start + chunk_success + fail_count - (fail_count if chunk_start == 0 else 0)
                processed = success_count + fail_count
                if processed % 50 == 0 and processed > 0:
                    elapsed = time.time() - started_at
                    rate = processed / elapsed
                    remaining = (total - processed) / rate if rate > 0 else 0
                    logger.info(
                        "진행: %d/%d (%.1f%%) — %.0f초 경과, 예상 남은 시간: %.0f분",
                        processed, total, processed / total * 100,
                        elapsed, remaining / 60,
                    )

        logger.info(
            "청크 완료: %d~%d (%d성공, %d실패)",
            chunk_start, chunk_start + len(chunk) - 1, chunk_success, len(chunk) - chunk_success,
        )

    elapsed = time.time() - started_at
    logger.info(
        "재크롤링 완료: %d성공, %d실패, %.0f분 소요",
        success_count, fail_count, elapsed / 60,
    )

    if failed_codes:
        logger.warning("실패 종목: %s", ", ".join(failed_codes[:20]))

    if args.dry_run:
        logger.info("--dry-run 모드: DB 저장 건너뜀, RS 재계산 생략")
        return

    # RS 재계산
    logger.info("RS 재계산 시작...")
    with session_scope() as session:
        ctx = build_db_batch_context(session)
        results = calculate_rs(ctx)
        for market, count in results.items():
            logger.info("market=%s: %d종목 RS 계산 완료", market, count)

    logger.info("전체 작업 완료")


if __name__ == "__main__":
    main()
