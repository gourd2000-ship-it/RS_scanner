"""크롤링 모니터링 API 엔드포인트."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.cache import cached_stats
from app.core.database import get_db_session
from app.models.crawl_failure import CrawlFailure
from app.models.crawl_job import CrawlJob
from app.schemas.response import PaginatedResponse

router = APIRouter()


# 응답 스키마 정의
from datetime import datetime
from pydantic import BaseModel, Field


class CrawlJobItem(BaseModel):
    """크롤링 작업 항목."""
    id: int = Field(description="작업 ID")
    job_type: str = Field(description="작업 유형")
    started_at: datetime = Field(description="시작 시각")
    finished_at: datetime | None = Field(default=None, description="종료 시각")
    status: str = Field(description="상태 (running/completed/failed)")
    symbols_total: int = Field(description="전체 종목 수")
    symbols_succeeded: int = Field(description="성공 종목 수")
    symbols_failed: int = Field(description="실패 종목 수")
    message: str | None = Field(default=None, description="메시지")
    duration_seconds: int | None = Field(default=None, description="실행 시간 (초)")
    success_rate: float | None = Field(default=None, description="성공률 (%)")


class CrawlFailureItem(BaseModel):
    """크롤링 실패 항목."""
    id: int = Field(description="실패 ID")
    job_id: int = Field(description="작업 ID")
    target_type: str = Field(description="대상 타입 (symbol/benchmark)")
    target_key: str = Field(description="대상 키 (종목코드 등)")
    url: str = Field(description="요청 URL")
    http_status: int | None = Field(default=None, description="HTTP 상태 코드")
    error_class: str = Field(description="에러 클래스")
    error_message: str = Field(description="에러 메시지")
    retry_count: int = Field(description="재시도 횟수")
    created_at: datetime = Field(description="발생 시각")


class CrawlStatsResponse(BaseModel):
    """크롤링 통계 응답."""
    total_jobs: int = Field(description="전체 작업 수")
    running_jobs: int = Field(description="실행 중인 작업 수")
    completed_jobs: int = Field(description="완료된 작업 수")
    failed_jobs: int = Field(description="실패한 작업 수")
    total_failures: int = Field(description="전체 실패 횟수")
    latest_job: CrawlJobItem | None = Field(default=None, description="최근 작업")


@router.get("/stats", response_model=CrawlStatsResponse)
@cached_stats
def get_crawl_stats(
    session: Session = Depends(get_db_session),
):
    """크롤링 통계 조회.

    전체 작업 수, 실행 중/완료/실패 작업 수, 최근 작업 정보를 반환합니다.

    캐시: 5분 (production 환경에서만 활성화)
    """
    # 전체 작업 수
    total_jobs = session.scalar(select(func.count()).select_from(CrawlJob)) or 0

    # 상태별 작업 수
    running_jobs = session.scalar(
        select(func.count()).select_from(CrawlJob).where(CrawlJob.status == "running")
    ) or 0

    completed_jobs = session.scalar(
        select(func.count()).select_from(CrawlJob).where(CrawlJob.status == "completed")
    ) or 0

    failed_jobs = session.scalar(
        select(func.count()).select_from(CrawlJob).where(CrawlJob.status == "failed")
    ) or 0

    # 전체 실패 횟수
    total_failures = session.scalar(select(func.count()).select_from(CrawlFailure)) or 0

    # 최근 작업
    latest_job_row = session.scalar(
        select(CrawlJob).order_by(desc(CrawlJob.started_at)).limit(1)
    )

    latest_job = None
    if latest_job_row:
        duration_seconds = None
        if latest_job_row.finished_at:
            duration_seconds = int((latest_job_row.finished_at - latest_job_row.started_at).total_seconds())

        success_rate = None
        if latest_job_row.symbols_total > 0:
            success_rate = (latest_job_row.symbols_succeeded / latest_job_row.symbols_total) * 100

        latest_job = CrawlJobItem(
            id=latest_job_row.id,
            job_type=latest_job_row.job_type,
            started_at=latest_job_row.started_at,
            finished_at=latest_job_row.finished_at,
            status=latest_job_row.status,
            symbols_total=latest_job_row.symbols_total,
            symbols_succeeded=latest_job_row.symbols_succeeded,
            symbols_failed=latest_job_row.symbols_failed,
            message=latest_job_row.message,
            duration_seconds=duration_seconds,
            success_rate=success_rate,
        )

    return CrawlStatsResponse(
        total_jobs=total_jobs,
        running_jobs=running_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs,
        total_failures=total_failures,
        latest_job=latest_job,
    )


@router.get("/jobs", response_model=PaginatedResponse[CrawlJobItem])
def list_crawl_jobs(
    page: int = Query(default=1, ge=1, description="페이지 번호"),
    size: int = Query(default=20, ge=1, le=100, description="페이지 크기"),
    status: str | None = Query(default=None, description="상태 필터 (running/completed/failed)"),
    session: Session = Depends(get_db_session),
):
    """크롤링 작업 목록 조회.

    페이지네이션을 지원하며, 최신 작업부터 반환합니다.
    """
    # 쿼리 빌드
    stmt = select(CrawlJob).order_by(desc(CrawlJob.started_at))
    if status:
        stmt = stmt.where(CrawlJob.status == status)

    # 전체 개수
    count_stmt = select(func.count()).select_from(CrawlJob)
    if status:
        count_stmt = count_stmt.where(CrawlJob.status == status)
    total_count = session.scalar(count_stmt) or 0

    # 페이지네이션
    offset = (page - 1) * size
    jobs = session.scalars(stmt.limit(size).offset(offset)).all()

    items = []
    for job in jobs:
        duration_seconds = None
        if job.finished_at:
            duration_seconds = int((job.finished_at - job.started_at).total_seconds())

        success_rate = None
        if job.symbols_total > 0:
            success_rate = (job.symbols_succeeded / job.symbols_total) * 100

        items.append(
            CrawlJobItem(
                id=job.id,
                job_type=job.job_type,
                started_at=job.started_at,
                finished_at=job.finished_at,
                status=job.status,
                symbols_total=job.symbols_total,
                symbols_succeeded=job.symbols_succeeded,
                symbols_failed=job.symbols_failed,
                message=job.message,
                duration_seconds=duration_seconds,
                success_rate=success_rate,
            )
        )

    return PaginatedResponse(
        total_count=total_count,
        page=page,
        size=size,
        items=items,
    )


@router.get("/jobs/{job_id}", response_model=CrawlJobItem)
def get_crawl_job(
    job_id: int,
    session: Session = Depends(get_db_session),
):
    """특정 크롤링 작업 상세 조회."""
    job = session.get(CrawlJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"작업을 찾을 수 없습니다: {job_id}")

    duration_seconds = None
    if job.finished_at:
        duration_seconds = int((job.finished_at - job.started_at).total_seconds())

    success_rate = None
    if job.symbols_total > 0:
        success_rate = (job.symbols_succeeded / job.symbols_total) * 100

    return CrawlJobItem(
        id=job.id,
        job_type=job.job_type,
        started_at=job.started_at,
        finished_at=job.finished_at,
        status=job.status,
        symbols_total=job.symbols_total,
        symbols_succeeded=job.symbols_succeeded,
        symbols_failed=job.symbols_failed,
        message=job.message,
        duration_seconds=duration_seconds,
        success_rate=success_rate,
    )


@router.get("/failures", response_model=PaginatedResponse[CrawlFailureItem])
def list_crawl_failures(
    page: int = Query(default=1, ge=1, description="페이지 번호"),
    size: int = Query(default=50, ge=1, le=200, description="페이지 크기"),
    job_id: int | None = Query(default=None, description="작업 ID 필터"),
    session: Session = Depends(get_db_session),
):
    """크롤링 실패 내역 조회.

    페이지네이션을 지원하며, 최근 실패부터 반환합니다.
    """
    # 쿼리 빌드
    stmt = select(CrawlFailure).order_by(desc(CrawlFailure.created_at))
    if job_id:
        stmt = stmt.where(CrawlFailure.job_id == job_id)

    # 전체 개수
    count_stmt = select(func.count()).select_from(CrawlFailure)
    if job_id:
        count_stmt = count_stmt.where(CrawlFailure.job_id == job_id)
    total_count = session.scalar(count_stmt) or 0

    # 페이지네이션
    offset = (page - 1) * size
    failures = session.scalars(stmt.limit(size).offset(offset)).all()

    items = [
        CrawlFailureItem(
            id=failure.id,
            job_id=failure.job_id,
            target_type=failure.target_type,
            target_key=failure.target_key,
            url=failure.url,
            http_status=failure.http_status,
            error_class=failure.error_class,
            error_message=failure.error_message,
            retry_count=failure.retry_count,
            created_at=failure.created_at,
        )
        for failure in failures
    ]

    return PaginatedResponse(
        total_count=total_count,
        page=page,
        size=size,
        items=items,
    )
