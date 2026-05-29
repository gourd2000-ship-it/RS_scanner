import logging

from app.core.database import init_db, session_scope
from app.core.logging import configure_logging
from app.crawler.sources.naver import NaverPriceSource
from app.services.batch.context import build_db_batch_context
from app.services.batch.run_daily_job import run_daily_job


logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    init_db()
    source = NaverPriceSource()
    with session_scope() as session:
        context = build_db_batch_context(session)
        result = run_daily_job(context, source)
        logger.info("batch summary: %s", result)


if __name__ == "__main__":
    main()
