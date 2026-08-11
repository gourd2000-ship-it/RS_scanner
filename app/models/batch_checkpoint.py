from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class BatchCheckpoint(Base):
    """배치 작업 체크포인트 - 단계별 진행 상황 추적"""

    __tablename__ = "batch_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)  # 'symbols', 'benchmarks', 'prices', 'rs'
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )  # 'pending', 'running', 'completed', 'completed_with_errors', 'failed'
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    items_total: Mapped[int] = mapped_column(Integer, default=0)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("job_id", "step_name", name="uq_job_step"),
    )
