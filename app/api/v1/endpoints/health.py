from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.cache import get_cache_stats
from app.core.database import get_db_session


router = APIRouter()


@router.get("/health")
def healthcheck(session: Session = Depends(get_db_session)):
    """헬스체크 + 캐시 상태 조회."""
    try:
        # DB 연결 확인
        session.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        db_connected = False

    cache_stats = get_cache_stats()

    return {
        "status": "ok" if db_connected else "degraded",
        "db_connected": db_connected,
        "cache": cache_stats,
    }
