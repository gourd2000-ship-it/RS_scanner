from app.crawler.sources.eod import EodCanaryPolicy
from app.services.monitoring.eod_canary import CanaryObservation, EodCanaryController


def test_canary_requires_three_consecutive_passing_runs(tmp_path):
    controller = EodCanaryController(tmp_path / "canary.json", provider="fixture")
    passing = CanaryObservation(coverage_rate=0.999, duration_seconds=120)

    assert controller.record(passing).expanded is False
    assert controller.record(passing).expanded is False
    state = controller.record(passing)
    assert state.expanded is True
    assert state.consecutive_successes == 3

    failed = controller.record(CanaryObservation(coverage_rate=0.9, duration_seconds=120))
    assert failed.consecutive_successes == 0
    assert failed.expanded is True

    rolled_back = controller.rollback()
    assert rolled_back.enabled is False
    assert rolled_back.expanded is False


def test_canary_policy_limits_markets_and_codes():
    policy = EodCanaryPolicy(
        markets=frozenset({"KOSPI"}),
        codes=frozenset({"A"}),
    )
    assert policy.allows(market="KOSPI", code="A")
    assert not policy.allows(market="KOSPI", code="B")
    assert not policy.allows(market="KOSDAQ", code="A")
