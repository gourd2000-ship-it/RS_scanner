from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.symbol import Symbol
from app.schemas.market_data import SymbolPayload


class SymbolRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, symbols: Iterable[SymbolPayload]) -> list[SymbolPayload]:
        incoming = list(symbols)
        if not incoming:
            return []

        codes = [symbol.code for symbol in incoming]
        existing = {
            row.code: row
            for row in self.session.scalars(select(Symbol).where(Symbol.code.in_(codes))).all()
        }

        for payload in incoming:
            row = existing.get(payload.code)
            if row is None:
                row = Symbol(code=payload.code, name=payload.name, market=payload.market)
                self.session.add(row)
                existing[payload.code] = row
            else:
                row.name = payload.name
                row.market = payload.market
                row.is_active = True

        self.session.flush()
        return self.list_all()

    def list_all(self) -> list[SymbolPayload]:
        rows = self.session.scalars(select(Symbol).order_by(Symbol.market, Symbol.code)).all()
        return [SymbolPayload(code=row.code, name=row.name, market=row.market) for row in rows]

    def get_code_to_id_map(self) -> dict[str, int]:
        rows = self.session.scalars(select(Symbol)).all()
        return {row.code: row.id for row in rows}
