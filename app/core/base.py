"""SQLAlchemy DeclarativeBase 정의."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 ORM 모델의 베이스 클래스."""
    pass
