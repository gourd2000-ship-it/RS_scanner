import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.repositories.batch_checkpoint_repository import BatchCheckpointRepository


def test_price_checkpoint_preserves_chunk_progress_and_universe_selection_metadata():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = BatchCheckpointRepository(session)
    repository.create_checkpoint(job_id=1, step_name="prices")
    repository.update_chunk_progress(
        job_id=1,
        step_name="prices",
        chunk_index=0,
        total_chunks=2,
        chunk_size=200,
        items_processed_this_chunk=200,
    )

    repository.complete_step(
        job_id=1,
        step_name="prices",
        step_metadata=json.dumps(
            {
                "universe_selection": {
                    "authority_by_market": {"KOSPI": "krx"},
                    "fallback_reason_by_market": {"KOSPI": None},
                }
            }
        ),
    )

    checkpoint = repository.get_checkpoint(1, "prices")
    assert checkpoint is not None
    metadata = json.loads(checkpoint.step_metadata or "{}")
    assert metadata["chunks_completed"] == [0]
    assert metadata["universe_selection"]["authority_by_market"] == {"KOSPI": "krx"}
