from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.repositories.batch_checkpoint_repository import BatchCheckpointRepository
from app.repositories.benchmark_repository import BenchmarkRepository
from app.repositories.crawl_failure_repository import CrawlFailureRepository
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.crawl_target_result_repository import CrawlTargetResultRepository
from app.repositories.memory_batch_checkpoint_repository import MemoryBatchCheckpointRepository
from app.repositories.memory_benchmark_repository import MemoryBenchmarkRepository
from app.repositories.memory_crawl_failure_repository import MemoryCrawlFailureRepository
from app.repositories.memory_crawl_job_repository import MemoryCrawlJobRepository
from app.repositories.memory_crawl_target_result_repository import MemoryCrawlTargetResultRepository
from app.repositories.memory_price_repository import MemoryPriceRepository
from app.repositories.memory_rs_repository import MemoryRsRepository
from app.repositories.memory_symbol_repository import MemorySymbolRepository
from app.repositories.memory_symbol_universe_snapshot_repository import MemorySymbolUniverseSnapshotRepository
from app.repositories.price_repository import PriceRepository
from app.repositories.rs_repository import RsRepository
from app.repositories.symbol_repository import SymbolRepository
from app.repositories.symbol_universe_snapshot_repository import SymbolUniverseSnapshotRepository


@dataclass
class BatchContext:
    symbol_repository: object
    benchmark_repository: object
    price_repository: object
    rs_repository: object
    crawl_job_repository: object | None = None
    crawl_failure_repository: object | None = None
    crawl_target_result_repository: object | None = None
    checkpoint_repository: object | None = None
    session: Session | None = None
    price_source: object | None = None
    universe_snapshot_repository: object | None = None
    universe_snapshot_id: int | None = None
    universe_snapshot_status: str | None = None
    job_id: int | None = None


def build_db_batch_context(session: Session) -> BatchContext:
    return BatchContext(
        symbol_repository=SymbolRepository(session),
        benchmark_repository=BenchmarkRepository(session),
        price_repository=PriceRepository(session),
        rs_repository=RsRepository(session),
        crawl_job_repository=CrawlJobRepository(session),
        crawl_failure_repository=CrawlFailureRepository(session),
        crawl_target_result_repository=CrawlTargetResultRepository(session),
        checkpoint_repository=BatchCheckpointRepository(session),
        universe_snapshot_repository=SymbolUniverseSnapshotRepository(session),
        session=session,
    )


def build_memory_batch_context() -> BatchContext:
    return BatchContext(
        symbol_repository=MemorySymbolRepository(),
        benchmark_repository=MemoryBenchmarkRepository(),
        price_repository=MemoryPriceRepository(),
        rs_repository=MemoryRsRepository(),
        crawl_job_repository=MemoryCrawlJobRepository(),
        crawl_failure_repository=MemoryCrawlFailureRepository(),
        crawl_target_result_repository=MemoryCrawlTargetResultRepository(),
        checkpoint_repository=MemoryBatchCheckpointRepository(),
        universe_snapshot_repository=MemorySymbolUniverseSnapshotRepository(),
    )
