from types import SimpleNamespace

from app.services.universe_authority import choose_universe_authority


def settings(**overrides):
    values = {
        "universe_authority": "naver_last_completed",
        "universe_canary_markets": "",
        "universe_mapping_rate_threshold": 0.995,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_authority_defaults_to_naver_last_completed():
    decision = choose_universe_authority(
        settings(), market="KOSPI", krx_snapshot_status="completed", mapping_rate=1.0
    )

    assert decision.authority == "naver_last_completed"
    assert decision.fallback_reason == "authority_not_enabled"


def test_krx_authority_is_limited_to_approved_canary_market_with_healthy_snapshot():
    decision = choose_universe_authority(
        settings(universe_authority="krx", universe_canary_markets="KOSPI"),
        market="KOSPI",
        krx_snapshot_status="completed",
        mapping_rate=0.999,
    )

    assert decision.authority == "krx"
    assert decision.fallback_reason is None


def test_partial_or_low_mapping_krx_snapshot_falls_back_without_changing_targets():
    partial = choose_universe_authority(
        settings(universe_authority="krx", universe_canary_markets="KOSPI"),
        market="KOSPI",
        krx_snapshot_status="partial",
        mapping_rate=1.0,
    )
    low_mapping = choose_universe_authority(
        settings(universe_authority="krx", universe_canary_markets="KOSPI"),
        market="KOSPI",
        krx_snapshot_status="completed",
        mapping_rate=0.90,
    )

    assert partial.authority == "naver_last_completed"
    assert partial.fallback_reason == "krx_snapshot_partial"
    assert low_mapping.authority == "naver_last_completed"
    assert low_mapping.fallback_reason == "krx_mapping_rate_below_threshold"
