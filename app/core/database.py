from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.base import Base
from app.core.config import get_settings
import app.models  # noqa: F401


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """데이터베이스 초기화.

    개발 환경(local, dev, test)에서는 create_all()로 테이블을 생성합니다.
    운영 환경(production, prod)에서는 Alembic 마이그레이션을 사용해야 하므로
    create_all()을 호출하지 않습니다.
    """
    env = settings.app_env.lower()
    if env in ("production", "prod"):
        # 운영 환경에서는 `alembic upgrade head` 명령으로 마이그레이션을 실행해야 합니다
        pass
    else:
        # 개발 환경에서는 편의를 위해 자동으로 테이블 생성
        Base.metadata.create_all(bind=engine)
        # ``create_all`` does not create SQL views.  Keep local/dev databases
        # aligned with the Alembic clean-layer views as well.
        from app.services.validation.clean_layer import ensure_validated_views

        with SessionLocal() as session:
            ensure_validated_views(session)
            session.commit()
