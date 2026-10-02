"""The only service entry point a backend worker uses to claim simulations."""

from sqlalchemy.orm import Session

from app.repositories.backtest_repository import BacktestRepository


class BacktestQueueWorker:
    """Claim exactly one FIFO run; HTTP routes never call this worker method."""

    def __init__(self, session: Session) -> None:
        self.repository = BacktestRepository(session)

    def claim_next(self):
        return self.repository.claim_next_run()
