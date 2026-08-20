"""Safe authority selection for staged KRX target canaries."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseAuthorityDecision:
    authority: str
    fallback_reason: str | None


def choose_universe_authority(
    settings,
    *,
    market: str,
    krx_snapshot_status: str | None,
    mapping_rate: float | None,
) -> UniverseAuthorityDecision:
    """Allow KRX only for explicitly canaried markets with healthy evidence."""
    if str(getattr(settings, "universe_authority", "naver_last_completed")).lower() != "krx":
        return UniverseAuthorityDecision("naver_last_completed", "authority_not_enabled")
    canary_markets = {
        item.strip().upper()
        for item in str(getattr(settings, "universe_canary_markets", "")).split(",")
        if item.strip()
    }
    if market.upper() not in canary_markets:
        return UniverseAuthorityDecision("naver_last_completed", "market_not_in_canary")
    if krx_snapshot_status != "completed":
        return UniverseAuthorityDecision(
            "naver_last_completed", f"krx_snapshot_{krx_snapshot_status or 'missing'}"
        )
    threshold = float(getattr(settings, "universe_mapping_rate_threshold", 0.995))
    if mapping_rate is None or mapping_rate < threshold:
        return UniverseAuthorityDecision("naver_last_completed", "krx_mapping_rate_below_threshold")
    return UniverseAuthorityDecision("krx", None)
