"""Validated price read model.

The SQL views are created by Alembic for production.  This repository uses the
same exclusion predicates through SQLAlchemy so development/test databases
created with ``Base.metadata.create_all`` behave identically even when views
were not created by a migration.
"""

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

from app.models.data_quality import OhlcCorrection, OhlcExclusion, ValidationCase
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol
from app.schemas.market_data import DailyPricePayload


def ensure_validated_views(session: Session) -> None:
    """Create read-only clean views for local/dev databases."""

    session.execute(
        text(
            """
            CREATE OR REPLACE VIEW v_daily_prices_validated AS
            SELECT dp.id, dp.symbol_id, s.code, s.market, dp.trade_date,
                   COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                          THEN oc.corrected_value ->> 'value'
                                          ELSE oc.corrected_value #>> '{}'
                                     END)::numeric(18,4)
                             FROM ohlc_corrections oc
                             WHERE oc.symbol_id = dp.symbol_id
                               AND oc.trade_date = dp.trade_date
                               AND oc.field_name = 'open'
                               AND oc.status = 'APPROVED'
                             ORDER BY oc.id DESC LIMIT 1), dp.open) AS open,
                   COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                          THEN oc.corrected_value ->> 'value'
                                          ELSE oc.corrected_value #>> '{}'
                                     END)::numeric(18,4)
                             FROM ohlc_corrections oc
                             WHERE oc.symbol_id = dp.symbol_id
                               AND oc.trade_date = dp.trade_date
                               AND oc.field_name = 'high'
                               AND oc.status = 'APPROVED'
                             ORDER BY oc.id DESC LIMIT 1), dp.high) AS high,
                   COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                          THEN oc.corrected_value ->> 'value'
                                          ELSE oc.corrected_value #>> '{}'
                                     END)::numeric(18,4)
                             FROM ohlc_corrections oc
                             WHERE oc.symbol_id = dp.symbol_id
                               AND oc.trade_date = dp.trade_date
                               AND oc.field_name = 'low'
                               AND oc.status = 'APPROVED'
                             ORDER BY oc.id DESC LIMIT 1), dp.low) AS low,
                   COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                          THEN oc.corrected_value ->> 'value'
                                          ELSE oc.corrected_value #>> '{}'
                                     END)::numeric(18,4)
                             FROM ohlc_corrections oc
                             WHERE oc.symbol_id = dp.symbol_id
                               AND oc.trade_date = dp.trade_date
                               AND oc.field_name = 'close'
                               AND oc.status = 'APPROVED'
                             ORDER BY oc.id DESC LIMIT 1), dp.close) AS close,
                   COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                          THEN oc.corrected_value ->> 'value'
                                          ELSE oc.corrected_value #>> '{}'
                                     END)::bigint
                             FROM ohlc_corrections oc
                             WHERE oc.symbol_id = dp.symbol_id
                               AND oc.trade_date = dp.trade_date
                               AND oc.field_name = 'volume'
                               AND oc.status = 'APPROVED'
                             ORDER BY oc.id DESC LIMIT 1), dp.volume) AS volume,
                   COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                          THEN oc.corrected_value ->> 'value'
                                          ELSE oc.corrected_value #>> '{}'
                                     END)::numeric(10,4)
                             FROM ohlc_corrections oc
                             WHERE oc.symbol_id = dp.symbol_id
                               AND oc.trade_date = dp.trade_date
                               AND oc.field_name = 'change_rate'
                               AND oc.status = 'APPROVED'
                             ORDER BY oc.id DESC LIMIT 1), dp.change_rate) AS change_rate,
                   dp.source, dp.created_at
            FROM daily_prices dp
            JOIN symbols s ON s.id = dp.symbol_id
            WHERE NOT EXISTS (
                SELECT 1 FROM ohlc_exclusions oe
                WHERE oe.symbol_id = dp.symbol_id
                  AND oe.trade_date = dp.trade_date
                  AND oe.status = 'APPROVED'
            )
            AND NOT EXISTS (
                SELECT 1 FROM validation_cases vc
                WHERE vc.subject_type = 'daily_price'
                  AND vc.symbol_id = dp.symbol_id
                  AND vc.trade_date = dp.trade_date
                  AND vc.decision = 'EXCLUDE'
                  AND vc.case_status IN ('auto_resolved', 'approved')
            )
            """
        )
    )
    session.execute(
        text(
            """
            CREATE OR REPLACE VIEW v_rs_input_prices AS
            SELECT * FROM v_daily_prices_validated
            """
        )
    )


class ValidatedPriceRepository:
    """Read-only price repository applying approved clean-layer policy."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_symbol_prices(self, code: str) -> list[DailyPricePayload]:
        excluded = select(OhlcExclusion.id).where(
            OhlcExclusion.symbol_id == DailyPrice.symbol_id,
            OhlcExclusion.trade_date == DailyPrice.trade_date,
            OhlcExclusion.status == "APPROVED",
        )
        invalid_case = select(ValidationCase.id).where(
            ValidationCase.subject_type == "daily_price",
            ValidationCase.symbol_id == DailyPrice.symbol_id,
            ValidationCase.trade_date == DailyPrice.trade_date,
            ValidationCase.decision == "EXCLUDE",
            ValidationCase.case_status.in_(("auto_resolved", "approved")),
        )
        rows = self.session.scalars(
            select(DailyPrice)
            .join(Symbol, Symbol.id == DailyPrice.symbol_id)
            .where(
                Symbol.code == code,
                ~exists(excluded),
                ~exists(invalid_case),
            )
            .order_by(DailyPrice.trade_date)
        ).all()
        corrections = self.session.scalars(
            select(OhlcCorrection)
            .where(
                OhlcCorrection.symbol_id.in_({row.symbol_id for row in rows}),
                OhlcCorrection.trade_date.in_({row.trade_date for row in rows}),
                OhlcCorrection.status == "APPROVED",
            )
            .order_by(OhlcCorrection.id)
        ).all() if rows else []
        correction_by_key = {
            (correction.symbol_id, correction.trade_date, correction.field_name): correction
            for correction in corrections
        }

        def corrected(row: DailyPrice, field_name: str, default: object) -> object:
            correction = correction_by_key.get(
                (row.symbol_id, row.trade_date, field_name)
            )
            if correction is None:
                return default
            value = correction.corrected_value
            if isinstance(value, dict) and "value" in value:
                value = value["value"]
            if field_name == "volume":
                return int(value)
            if field_name in {"open", "high", "low", "close", "change_rate"}:
                return Decimal(str(value))
            return value

        return [
            DailyPricePayload(
                trade_date=row.trade_date,
                open=corrected(row, "open", row.open),
                high=corrected(row, "high", row.high),
                low=corrected(row, "low", row.low),
                close=corrected(row, "close", row.close),
                volume=corrected(row, "volume", row.volume),
                change_rate=corrected(row, "change_rate", row.change_rate),
            )
            for row in rows
        ]

    def get_latest_symbol_trade_date(self, code: str):
        rows = self.get_symbol_prices(code)
        return rows[-1].trade_date if rows else None


def hash_price_rows(rows: Iterable[DailyPricePayload]) -> str:
    """Stable hash used for RS input lineage snapshots."""

    import hashlib
    import json

    values = [
        {
            "date": row.trade_date.isoformat(),
            "open": str(row.open),
            "high": str(row.high),
            "low": str(row.low),
            "close": str(row.close),
            "volume": row.volume,
            "change_rate": str(row.change_rate),
        }
        for row in rows
    ]
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
