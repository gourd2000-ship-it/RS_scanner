"""In-memory repair queue used by batch unit tests."""

from datetime import date, datetime


class MemoryCrawlRepairRequest:
    def __init__(self, *, id: int, **values) -> None:
        self.id = id
        for key, value in values.items():
            setattr(self, key, value)


class MemoryCrawlRepairRepository:
    def __init__(self) -> None:
        self._requests: dict[str, MemoryCrawlRepairRequest] = {}
        self._next_id = 1

    @staticmethod
    def build_dedupe_key(
        *,
        job_id: int | None,
        symbol: str,
        trade_date: date,
        error_type: str,
        adjusted_price: bool,
    ) -> str:
        return ":".join(
            (
                str(job_id) if job_id is not None else "manual",
                symbol.strip(),
                trade_date.isoformat(),
                error_type.strip(),
                "adjusted" if adjusted_price else "raw",
            )
        )

    def enqueue(self, *, symbol: str, trade_date: date, error_type: str, **kwargs):
        adjusted_price = bool(kwargs.get("adjusted_price", True))
        job_id = kwargs.get("job_id")
        dedupe_key = self.build_dedupe_key(
            job_id=job_id,
            symbol=symbol,
            trade_date=trade_date,
            error_type=error_type,
            adjusted_price=adjusted_price,
        )
        existing = self._requests.get(dedupe_key)
        if existing is not None:
            return existing, False
        now = kwargs.get("requested_at") or datetime.utcnow()
        request = MemoryCrawlRepairRequest(
            id=self._next_id,
            dedupe_key=dedupe_key,
            job_id=job_id,
            crawl_target_result_id=kwargs.get("crawl_target_result_id"),
            symbol=symbol,
            trade_date=trade_date,
            history_from=kwargs.get("history_from"),
            operation=kwargs.get("operation", "daily_chart"),
            error_type=error_type,
            provider=kwargs.get("provider", "kiwoom"),
            adjusted_price=adjusted_price,
            status="pending",
            application_status="not_applied",
            attempt_count=0,
            max_attempts=kwargs.get("max_attempts", 3),
            requested_at=now,
        )
        self._requests[dedupe_key] = request
        self._next_id += 1
        return request, True

    def list_all(self) -> list[MemoryCrawlRepairRequest]:
        return sorted(self._requests.values(), key=lambda item: item.id)
