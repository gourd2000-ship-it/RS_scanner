from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.symbol import Symbol
from app.schemas.market_data import SymbolPayload
from app.schemas.response import SymbolItem


class SymbolRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(
        self,
        symbols: Iterable[SymbolPayload],
        *,
        snapshot_id: int | None = None,
        seen_at: datetime | None = None,
    ) -> list[SymbolPayload]:
        incoming = list(symbols)
        if not incoming:
            return []

        seen_at = seen_at or datetime.utcnow()
        codes = [symbol.code for symbol in incoming]
        existing = {
            row.code: row
            for row in self.session.scalars(select(Symbol).where(Symbol.code.in_(codes))).all()
        }

        for payload in incoming:
            row = existing.get(payload.code)
            if row is None:
                row = Symbol(
                    code=payload.code,
                    name=payload.name,
                    market=payload.market,
                    symbol_type=payload.symbol_type,
                    last_seen_at=seen_at if snapshot_id is not None else None,
                    last_snapshot_id=snapshot_id,
                )
                self.session.add(row)
                existing[payload.code] = row
            else:
                row.name = payload.name
                row.market = payload.market
                row.symbol_type = payload.symbol_type
                row.is_active = True
                if snapshot_id is not None:
                    row.last_seen_at = seen_at
                    row.last_snapshot_id = snapshot_id

        self.session.flush()
        return self.list_all()

    def reconcile_missing(
        self,
        incoming_codes: set[str],
        *,
        delisted_at: date | None = None,
    ) -> list[str]:
        """완료된 universe에서 사라진 active 종목만 비활성화한다."""
        rows = self.session.scalars(select(Symbol).where(Symbol.is_active.is_(True))).all()
        missing_codes: list[str] = []
        delisted_at = delisted_at or datetime.utcnow().date()
        for row in rows:
            if row.code in incoming_codes:
                continue
            row.is_active = False
            row.delisted_at = delisted_at
            missing_codes.append(row.code)
        self.session.flush()
        return missing_codes

    def list_all(self) -> list[SymbolPayload]:
        rows = self.session.scalars(select(Symbol).order_by(Symbol.market, Symbol.code)).all()
        return [SymbolPayload(code=row.code, name=row.name, market=row.market, symbol_type=row.symbol_type) for row in rows]

    def list_price_targets(self) -> list[SymbolPayload]:
        """가격 수집 대상: 활성 상태인 모든 분류의 종목을 반환한다.

        ETF/ETN도 가격 이력은 보존해야 하므로 크롤링 대상에는 포함한다.
        RS 계산처럼 일반 주식만 필요한 소비자는 ``list_stocks_only``를
        사용한다.
        """
        rows = self.session.scalars(
            select(Symbol)
            .where(Symbol.is_active.is_(True))
            .order_by(Symbol.market, Symbol.code)
        ).all()
        return [SymbolPayload(code=row.code, name=row.name, market=row.market, symbol_type=row.symbol_type) for row in rows]

    def list_stocks_only(self) -> list[SymbolPayload]:
        """RS 계산 등 일반 주식만 필요한 작업의 대상."""
        rows = self.session.scalars(
            select(Symbol)
            .where(Symbol.is_active.is_(True), Symbol.symbol_type == "stock")
            .order_by(Symbol.market, Symbol.code)
        ).all()
        return [SymbolPayload(code=row.code, name=row.name, market=row.market, symbol_type=row.symbol_type) for row in rows]

    def get_by_code(self, code: str) -> SymbolPayload | None:
        row = self.session.scalar(select(Symbol).where(Symbol.code == code))
        if row is None:
            return None
        return SymbolPayload(code=row.code, name=row.name, market=row.market, symbol_type=row.symbol_type)

    def get_code_to_id_map(self) -> dict[str, int]:
        rows = self.session.scalars(select(Symbol)).all()
        return {row.code: row.id for row in rows}

    def list_filtered(
        self,
        market: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        page: int = 1,
        size: int = 100,
    ) -> tuple[list[SymbolItem], int]:
        """필터링된 종목 목록 조회.

        Args:
            market: 시장 구분 (KOSPI/KOSDAQ)
            is_active: 상장 여부
            search: 종목명 또는 종목코드 검색어
            page: 페이지 번호 (1부터 시작)
            size: 페이지 크기

        Returns:
            (items, total_count)
        """
        # 필터 조건 구성
        filters = []
        if market is not None:
            filters.append(Symbol.market == market)
        if is_active is not None:
            filters.append(Symbol.is_active == is_active)
        if search is not None:
            search_pattern = f"%{search}%"
            filters.append((Symbol.name.ilike(search_pattern)) | (Symbol.code.ilike(search_pattern)))

        # 전체 개수 조회
        total_count = self.session.scalar(
            select(func.count()).select_from(Symbol).where(*filters)
        ) or 0

        # 페이지네이션 조회
        offset = (page - 1) * size
        rows = self.session.scalars(
            select(Symbol)
            .where(*filters)
            .order_by(Symbol.market, Symbol.code)
            .limit(size)
            .offset(offset)
        ).all()

        # SymbolItem으로 변환
        items = [
            SymbolItem(
                code=row.code,
                name=row.name,
                market=row.market,
                sector=row.sector,
                industry=row.industry,
                is_active=row.is_active,
                listed_at=row.listed_at,
            )
            for row in rows
        ]

        return items, total_count
