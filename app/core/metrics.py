"""Small process-local metrics registry used by batch and API observability.

The registry intentionally stays dependency-free, but the metric names mirror
the production exporter contract.  A Prometheus/OpenTelemetry exporter can
read the snapshot later without changing crawler call sites.
"""

import re
from threading import Lock


class MetricsRegistry:
    """Thread-safe counters and gauges with no external service dependency."""

    def __init__(self) -> None:
        self._values: dict[str, float] = {}
        self._lock = Lock()

    def increment(self, name: str, amount: float = 1) -> None:
        with self._lock:
            self._values[name] = self._values.get(name, 0.0) + amount

    def set(self, name: str, value: float) -> None:
        with self._lock:
            self._values[name] = float(value)

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


metrics = MetricsRegistry()


def increment_metric(name: str, amount: float = 1) -> None:
    metrics.increment(name, amount)


def set_metric(name: str, value: float) -> None:
    metrics.set(name, value)


def _provider_key(provider: str | None) -> str:
    value = (provider or "unknown").strip().lower()
    return re.sub(r"[^a-z0-9_.-]+", "_", value) or "unknown"


def record_provider_request(
    provider: str | None,
    *,
    elapsed_seconds: float,
    success: bool,
    retry_count: int = 0,
) -> None:
    """Record one logical provider call and its latency.

    Generic names are useful for dashboards.  Provider-suffixed names make
    the same registry useful for budget and canary comparisons without
    introducing a labels dependency.
    """
    key = _provider_key(provider)
    increment_metric("crawl_provider_request_total")
    increment_metric(f"crawl_provider_request_total.{key}")
    increment_metric("crawl_provider_success_total" if success else "crawl_provider_error_total")
    increment_metric(f"crawl_provider_success_total.{key}" if success else f"crawl_provider_error_total.{key}")
    if retry_count:
        increment_metric("crawl_provider_retry_total", retry_count)
        increment_metric(f"crawl_provider_retry_total.{key}", retry_count)
    elapsed = max(0.0, float(elapsed_seconds))
    increment_metric("crawl_provider_latency_seconds", elapsed)
    increment_metric(f"crawl_provider_latency_seconds.{key}", elapsed)
    if "kiwoom" in key:
        increment_metric("kiwoom_latency_seconds", elapsed)


def record_batch_duration(elapsed_seconds: float) -> None:
    """Store the latest batch/price-stage duration in seconds."""
    set_metric("crawl_duration_seconds", max(0.0, float(elapsed_seconds)))


def record_price_sync_metrics(result: object) -> None:
    """Publish the latest price-stage totals from a PriceSyncResult-like object."""
    counts = {
        "crawl_eligible_total": getattr(result, "target_count", 0),
        "crawl_fetched_total": getattr(result, "fetched_count", 0),
        "crawl_no_new_data_total": getattr(result, "no_new_data_count", 0),
        "crawl_partial_total": getattr(result, "partial_count", 0),
        "crawl_failed_total": getattr(result, "failed_count", 0),
        "crawl_skipped_total": getattr(result, "skipped_count", 0),
    }
    for name, value in counts.items():
        set_metric(name, value)

    eligible = counts["crawl_eligible_total"]
    covered = (
        counts["crawl_fetched_total"]
        + counts["crawl_no_new_data_total"]
        + getattr(result, "skipped_count", 0)
    )
    set_metric("crawl_coverage_rate", covered / eligible if eligible else 0.0)
