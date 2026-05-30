import logging

from app.core.database import init_db
from app.core.logging import configure_logging
from app.crawler.sources.naver import NaverPriceSource
from app.services.batch.orchestrator import BatchOrchestrator


logger = logging.getLogger(__name__)


def main() -> None:
    """배치 메인 엔트리포인트 - 체크포인트 시스템 사용"""
    configure_logging()
    init_db()

    source = NaverPriceSource()
    orchestrator = BatchOrchestrator(source)
    result = orchestrator.run_daily_job()

    logger.info("batch summary: %s", result)


if __name__ == "__main__":
    main()
