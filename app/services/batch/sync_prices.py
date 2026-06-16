"""가격 데이터 동기화 - 청크 기반 처리"""

import logging
from typing import Any

from app.core.config import get_settings
from app.core.database import session_scope
from app.core.notification import get_notification_service
from app.crawler.sources.base import PriceSource
from app.services.batch.context import BatchContext, build_db_batch_context
from app.services.validation.market_data import validate_prices

logger = logging.getLogger(__name__)
settings = get_settings()
notification_service = get_notification_service()


def chunk_list(items: list, chunk_size: int) -> list[list]:
    """리스트를 청크로 분할"""
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def sync_prices(context: BatchContext, source: PriceSource) -> dict[str, Any]:
    """가격 데이터 동기화 - 청크 기반 처리

    Args:
        context: 배치 컨텍스트 (job_id 포함)
        source: 가격 데이터 소스

    Returns:
        dict: 종목코드별 저장된 가격 데이터
    """
    # 전체 종목 목록 조회
    all_symbols = context.symbol_repository.list_all()
    total_symbols = len(all_symbols)
    logger.info(f"sync_prices: {total_symbols} symbols to process")

    if not all_symbols:
        logger.warning("no symbols found, skipping price sync")
        return {}

    # 청크로 분할
    chunks = chunk_list(all_symbols, settings.batch_chunk_size)
    total_chunks = len(chunks)
    logger.info(f"sync_prices: {total_symbols} symbols in {total_chunks} chunks (size={settings.batch_chunk_size})")

    # 완료된 청크 조회 (재시작 시나리오)
    completed_chunks = _get_completed_chunks(context)
    if completed_chunks:
        logger.info(f"resuming from checkpoint: {len(completed_chunks)} chunks already completed")

    # 청크별 처리
    synced = {}
    for chunk_idx, symbol_chunk in enumerate(chunks):
        if chunk_idx in completed_chunks:
            logger.info(f"skipping already completed chunk {chunk_idx}/{total_chunks - 1}")
            continue

        logger.info(f"processing chunk {chunk_idx}/{total_chunks - 1}: {len(symbol_chunk)} symbols")

        # 청크 처리 (별도 트랜잭션)
        chunk_result = _process_chunk(
            chunk_idx=chunk_idx,
            total_chunks=total_chunks,
            symbol_chunk=symbol_chunk,
            source=source,
            job_id=context.job_id,
        )

        synced.update(chunk_result)
        logger.info(f"chunk {chunk_idx}/{total_chunks - 1} completed: {len(chunk_result)} symbols processed")

    logger.info(f"sync_prices completed: {len(synced)} total symbols processed")
    return synced


def _get_completed_chunks(context: BatchContext) -> set[int]:
    """완료된 청크 인덱스 조회"""
    if not context.job_id or not context.checkpoint_repository:
        return set()

    return context.checkpoint_repository.get_completed_chunks(context.job_id, "prices")


def _process_chunk(
    chunk_idx: int,
    total_chunks: int,
    symbol_chunk: list,
    source: PriceSource,
    job_id: int | None,
) -> dict[str, Any]:
    """단일 청크 처리 (별도 트랜잭션)

    Args:
        chunk_idx: 청크 인덱스
        total_chunks: 전체 청크 수
        symbol_chunk: 처리할 종목 목록
        source: 가격 데이터 소스
        job_id: 배치 작업 ID

    Returns:
        dict: 종목코드별 저장된 가격 데이터
    """
    chunk_synced = {}
    chunk_failed = 0

    with session_scope() as session:
        # 새 컨텍스트 생성 (독립된 세션)
        chunk_context = build_db_batch_context(session)
        chunk_context.job_id = job_id

        # 청크 내 각 종목 처리
        for symbol in symbol_chunk:
            try:
                # 최신 거래일 조회
                latest_trade_date = chunk_context.price_repository.get_latest_symbol_trade_date(symbol.code)

                # 증분 수집 (since_date 이후 데이터만)
                prices = source.fetch_daily_prices(symbol.code, since_date=latest_trade_date)

                if prices:
                    # 검증
                    validate_prices(prices)

                    # 세이브포인트로 종목 단위 격리 — flush 실패 시 세션 전체가 오염되는 것을 방지
                    with chunk_context.session.begin_nested():
                        saved_prices = chunk_context.price_repository.save_symbol_prices(symbol.code, prices)
                    chunk_synced[symbol.code] = saved_prices
                else:
                    # 신규 데이터 없음 - 기존 데이터 로드
                    existing_prices = chunk_context.price_repository.get_symbol_prices(symbol.code)
                    chunk_synced[symbol.code] = existing_prices

            except Exception as e:
                # 종목별 실패 처리 — 세이브포인트 덕분에 세션은 계속 유효
                chunk_failed += 1
                logger.warning(f"failed to sync prices for {symbol.code}: {e}")

                # 실패 기록
                if chunk_context.crawl_failure_repository and job_id:
                    try:
                        chunk_context.crawl_failure_repository.record_failure(
                            job_id=job_id,
                            target_type="daily_price",
                            target_key=symbol.code,
                            error_class=type(e).__name__,
                            error_message=str(e),
                        )
                    except Exception as record_err:
                        logger.error(f"failed to record failure for {symbol.code}: {record_err}")

        # 커밋 전 검증
        _validate_chunk(chunk_idx, total_chunks, len(symbol_chunk), len(chunk_synced), chunk_failed)

        # 청크 진행률 기록 (커밋 전)
        if chunk_context.checkpoint_repository and job_id:
            chunk_context.checkpoint_repository.update_chunk_progress(
                job_id=job_id,
                step_name="prices",
                chunk_index=chunk_idx,
                total_chunks=total_chunks,
                chunk_size=len(symbol_chunk),
                items_processed_this_chunk=len(chunk_synced),
            )

    # 커밋 후 검증 (별도 세션)
    _post_commit_validate_chunk(chunk_idx, symbol_chunk, job_id)

    # 청크 완료 알림 전송
    try:
        notification_service.send_chunk_completed_sync(
            step_name="prices",
            chunk_index=chunk_idx,
            total_chunks=total_chunks,
            items_synced=len(chunk_synced),
            items_failed=chunk_failed,
        )
    except Exception as e:
        logger.error(f"Failed to send chunk completion notification for chunk {chunk_idx}: {e}")

    return chunk_synced


def _validate_chunk(
    chunk_idx: int, total_chunks: int, chunk_size: int, synced_count: int, failed_count: int
) -> None:
    """커밋 전 청크 검증

    Args:
        chunk_idx: 청크 인덱스
        total_chunks: 전체 청크 수
        chunk_size: 청크 크기
        synced_count: 동기화 성공 건수
        failed_count: 실패 건수

    Raises:
        ValueError: 검증 실패 시
    """
    # 카운트 검증
    total_processed = synced_count + failed_count
    if total_processed != chunk_size:
        raise ValueError(
            f"chunk {chunk_idx}/{total_chunks - 1} count mismatch: "
            f"processed={total_processed}, expected={chunk_size}"
        )

    logger.debug(f"chunk {chunk_idx}/{total_chunks - 1} validation passed: {synced_count} synced, {failed_count} failed")


def _post_commit_validate_chunk(chunk_idx: int, symbol_chunk: list, job_id: int | None) -> None:
    """커밋 후 청크 검증 - 영속성 확인

    Args:
        chunk_idx: 청크 인덱스
        symbol_chunk: 처리한 종목 목록
        job_id: 배치 작업 ID
    """
    if not job_id or not symbol_chunk:
        return

    # 샘플 검증: 첫 번째 종목의 데이터를 새 세션에서 조회
    sample_symbol_code = symbol_chunk[0].code

    with session_scope() as session:
        validation_context = build_db_batch_context(session)

        # DB에서 조회
        prices = validation_context.price_repository.get_symbol_prices(sample_symbol_code)

        if not prices:
            logger.warning(
                f"post-commit validation: chunk {chunk_idx} sample symbol {sample_symbol_code} has no prices in DB"
            )
        else:
            logger.debug(
                f"post-commit validation passed: chunk {chunk_idx} sample symbol {sample_symbol_code} has {len(prices)} prices"
            )
