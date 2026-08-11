"""Persisted decision helper for the EOD provider canary rollout."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class CanaryObservation:
    coverage_rate: float
    duration_seconds: float
    freshness_ok: bool = True
    provider_healthy: bool = True

    @property
    def passed(self) -> bool:
        return (
            self.provider_healthy
            and self.freshness_ok
            and self.coverage_rate >= 0.995
            and self.duration_seconds <= 30 * 60
        )


@dataclass(frozen=True)
class CanaryState:
    provider: str
    consecutive_successes: int = 0
    expanded: bool = False
    enabled: bool = True
    last_observation: CanaryObservation | None = None


class EodCanaryController:
    """Require three consecutive passing observations before expansion."""

    def __init__(
        self,
        path: str | Path,
        *,
        provider: str,
        required_successes: int = 3,
    ) -> None:
        if required_successes < 1:
            raise ValueError("required_successes must be positive")
        self.path = Path(path)
        self.provider = provider
        self.required_successes = required_successes

    def load(self) -> CanaryState:
        if not self.path.exists():
            return CanaryState(provider=self.provider)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        observation = payload.get("last_observation")
        return CanaryState(
            provider=payload.get("provider", self.provider),
            consecutive_successes=int(payload.get("consecutive_successes", 0)),
            expanded=bool(payload.get("expanded", False)),
            enabled=bool(payload.get("enabled", True)),
            last_observation=(
                CanaryObservation(**observation) if isinstance(observation, dict) else None
            ),
        )

    def record(self, observation: CanaryObservation) -> CanaryState:
        current = self.load()
        consecutive = current.consecutive_successes + 1 if observation.passed else 0
        state = CanaryState(
            provider=self.provider,
            consecutive_successes=consecutive,
            expanded=current.expanded or consecutive >= self.required_successes,
            enabled=current.enabled,
            last_observation=observation,
        )
        self._write(state)
        return state

    def rollback(self) -> CanaryState:
        current = self.load()
        state = CanaryState(
            provider=self.provider,
            consecutive_successes=0,
            expanded=False,
            enabled=False,
            last_observation=current.last_observation,
        )
        self._write(state)
        return state

    def enable(self) -> CanaryState:
        current = self.load()
        state = CanaryState(
            provider=self.provider,
            consecutive_successes=current.consecutive_successes,
            expanded=current.expanded,
            enabled=True,
            last_observation=current.last_observation,
        )
        self._write(state)
        return state

    def _write(self, state: CanaryState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)
