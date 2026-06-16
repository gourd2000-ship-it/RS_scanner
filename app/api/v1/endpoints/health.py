from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.cache import get_cache_stats
from app.core.database import get_db_session
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.schemas.response import HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def healthcheck(session: Session = Depends(get_db_session)):
    """헬스체크 + 캐시 상태 + 배치 실행 정보 조회."""
    try:
        # DB 연결 확인
        session.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        db_connected = False

    cache_stats = get_cache_stats()

    # 최근 배치 작업 정보 조회
    latest_job = CrawlJobRepository(session).get_latest()
    last_batch_at = latest_job.started_at if latest_job else None
    last_batch_status = latest_job.status if latest_job else None

    return HealthResponse(
        status="ok" if db_connected else "degraded",
        db_connected=db_connected,
        cache=cache_stats,
        last_batch_at=last_batch_at,
        last_batch_status=last_batch_status,
    )
