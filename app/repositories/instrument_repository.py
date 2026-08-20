"""Persistence operations for canonical KRX instruments."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instrument import Instrument, ProviderSymbol, UniverseExclusion
from app.models.symbol import Symbol


class InstrumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_instrument(
        self,
        *,
        krx_short_code: str,
        isin: str | None,
        name: str,
        market: str,
        security_type: str,
        listing_status: str,
        listed_at: date | None = None,
        delisted_at: date | None = None,
    ) -> Instrument:
        row = Instrument(
            krx_short_code=krx_short_code,
            isin=isin,
            name=name,
            market=market,
            security_type=security_type,
            listing_status=listing_status,
            listed_at=listed_at,
            delisted_at=delisted_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_krx_short_code(self, code: str) -> Instrument | None:
        return self.session.scalar(
            select(Instrument).where(Instrument.krx_short_code == code)
        )

    def add_provider_symbol(
        self,
        *,
        instrument_id: int,
        provider: str,
        provider_symbol: str,
        mapping_status: str,
        valid_from: date | None = None,
        valid_to: date | None = None,
        evidence_snapshot_id: int | None = None,
        evidence: str | None = None,
    ) -> ProviderSymbol:
        row = ProviderSymbol(
            instrument_id=instrument_id,
            provider=provider,
            provider_symbol=provider_symbol,
            mapping_status=mapping_status,
            valid_from=valid_from,
            valid_to=valid_to,
            evidence_snapshot_id=evidence_snapshot_id,
            evidence=evidence,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def add_exclusion(
        self,
        *,
        instrument_id: int,
        scope: str,
        reason_code: str,
        valid_from: date | None = None,
        valid_to: date | None = None,
        evidence_snapshot_id: int | None = None,
        evidence: str | None = None,
    ) -> UniverseExclusion:
        row = UniverseExclusion(
            instrument_id=instrument_id,
            scope=scope,
            reason_code=reason_code,
            valid_from=valid_from,
            valid_to=valid_to,
            evidence_snapshot_id=evidence_snapshot_id,
            evidence=evidence,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def link_legacy_symbol(self, *, symbol_id: int, instrument_id: int) -> Symbol:
        symbol = self.session.get(Symbol, symbol_id)
        if symbol is None:
            raise ValueError(f"symbol을 찾을 수 없습니다: {symbol_id}")
        if self.session.get(Instrument, instrument_id) is None:
            raise ValueError(f"instrument를 찾을 수 없습니다: {instrument_id}")
        symbol.instrument_id = instrument_id
        symbol.legacy_code = symbol.code
        self.session.flush()
        return symbol
