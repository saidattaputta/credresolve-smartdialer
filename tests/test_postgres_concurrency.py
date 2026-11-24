
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.engine import make_url

from app.config import DATABASE_URL
from app.db import SessionLocal
from app.models import Agent, Borrower, Call, Campaign
from app.services import Allocator


# Run these integration tests only against the dedicated PostgreSQL test DB.
_db_url = make_url(DATABASE_URL)

pytestmark = pytest.mark.skipif(
    _db_url.get_backend_name() != "postgresql"
    or _db_url.database != "credresolve_test",
    reason="Requires the dedicated PostgreSQL credresolve_test database",
)


def test_two_workers_cannot_reserve_the_same_agent_and_borrower():
    allocator = Allocator()
    barrier = Barrier(2)

    # Temporarily isolate this test from other available agents.
    with SessionLocal() as db:
        previously_available_agent_ids = list(
            db.scalars(
                select(Agent.id).where(Agent.state == "AVAILABLE")
            ).all()
        )

        db.execute(
            update(Agent)
            .where(Agent.state == "AVAILABLE")
            .values(state="PAUSED")
        )

        campaign = Campaign(name="Concurrency Test Campaign")
        db.add(campaign)
        db.flush()

        agent = Agent(name="Concurrency Test Agent")
        borrower = Borrower(
            campaign_id=campaign.id,
            name="Concurrency Test Borrower",
            phone="+910000000001",
        )

        db.add_all([agent, borrower])
        db.commit()

        campaign_id = campaign.id
        agent_id = agent.id
        borrower_id = borrower.id

    def worker(worker_number):
        with SessionLocal() as db:
            barrier.wait(timeout=10)

            return allocator.reserve_one(
                db,
                campaign_id,
                "provider_a",
                f"concurrency-test-{campaign_id}-{worker_number}",
            )

    try:
        # Each thread gets its own SQLAlchemy session.
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(worker, 1),
                executor.submit(worker, 2),
            ]
            results = [future.result(timeout=20) for future in futures]

        successful = [result for result in results if result is not None]

        # Only one worker may successfully reserve the same records.
        assert len(successful) == 1

        with SessionLocal() as db:
            calls = db.scalars(
                select(Call).where(Call.campaign_id == campaign_id)
            ).all()

            saved_agent = db.get(Agent, agent_id)
            saved_borrower = db.get(Borrower, borrower_id)

            assert len(calls) == 1
            assert calls[0].agent_id == agent_id
            assert calls[0].borrower_id == borrower_id

            assert saved_agent.state == "RESERVED"
            assert saved_agent.current_call_id == calls[0].id

            assert saved_borrower.state == "RESERVED"
            assert saved_borrower.attempts == 1

    finally:
        with SessionLocal() as db:
            test_call_ids = select(Call.id).where(
                Call.campaign_id == campaign_id
            )

            # Clear all agent references to calls created by this test.
            db.execute(
                update(Agent)
                .where(Agent.current_call_id.in_(test_call_ids))
                .values(current_call_id=None)
            )

            db.execute(
                delete(Call).where(Call.campaign_id == campaign_id)
            )

            db.execute(
                delete(Borrower).where(Borrower.id == borrower_id)
            )

            db.execute(
                delete(Agent).where(Agent.id == agent_id)
            )

            db.execute(
                delete(Campaign).where(Campaign.id == campaign_id)
            )

            # Restore agents that were available before the test.
            if previously_available_agent_ids:
                db.execute(
                    update(Agent)
                    .where(Agent.id.in_(previously_available_agent_ids))
                    .values(state="AVAILABLE")
                )

            db.commit()


def test_ten_workers_cannot_duplicate_five_agents_and_borrowers():
    allocator = Allocator()
    worker_count = 10
    resource_count = 5
    barrier = Barrier(worker_count)

    # Temporarily isolate this test from other available agents.
    with SessionLocal() as db:
        previously_available_agent_ids = list(
            db.scalars(
                select(Agent.id).where(Agent.state == "AVAILABLE")
            ).all()
        )

        db.execute(
            update(Agent)
            .where(Agent.state == "AVAILABLE")
            .values(state="PAUSED")
        )

        campaign = Campaign(name="Multi Worker Concurrency Test")
        db.add(campaign)
        db.flush()

        agents = [
            Agent(name=f"Multi Worker Agent {i}")
            for i in range(resource_count)
        ]

        borrowers = [
            Borrower(
                campaign_id=campaign.id,
                name=f"Multi Worker Borrower {i}",
                phone=f"+9190000000{i:02d}",
            )
            for i in range(resource_count)
        ]

        db.add_all(agents + borrowers)
        db.commit()

        campaign_id = campaign.id
        agent_ids = [agent.id for agent in agents]
        borrower_ids = [borrower.id for borrower in borrowers]

    def worker(worker_number):
        with SessionLocal() as db:
            barrier.wait(timeout=15)

            return allocator.reserve_one(
                db,
                campaign_id,
                "provider_a",
                f"multi-concurrency-{campaign_id}-{worker_number}",
            )

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(worker, i)
                for i in range(worker_count)
            ]

            results = [future.result(timeout=30) for future in futures]

        successful = [result for result in results if result is not None]

        with SessionLocal() as db:
            calls = db.scalars(
                select(Call).where(Call.campaign_id == campaign_id)
            ).all()

            assert len(calls) == len(successful)
            assert 1 <= len(calls) <= resource_count

            used_agent_ids = [call.agent_id for call in calls]
            used_borrower_ids = [call.borrower_id for call in calls]

            # No agent or borrower can be reserved more than once.
            assert len(used_agent_ids) == len(set(used_agent_ids))
            assert len(used_borrower_ids) == len(set(used_borrower_ids))

            # Only agents and borrowers created by this test may be used.
            assert set(used_agent_ids).issubset(set(agent_ids))
            assert set(used_borrower_ids).issubset(set(borrower_ids))

            for call in calls:
                agent = db.get(Agent, call.agent_id)
                borrower = db.get(Borrower, call.borrower_id)

                assert agent.state == "RESERVED"
                assert agent.current_call_id == call.id

                assert borrower.state == "RESERVED"
                assert borrower.attempts == 1

    finally:
        with SessionLocal() as db:
            test_call_ids = select(Call.id).where(
                Call.campaign_id == campaign_id
            )

            # Clear all agent references to calls created by this test.
            db.execute(
                update(Agent)
                .where(Agent.current_call_id.in_(test_call_ids))
                .values(current_call_id=None)
            )

            db.execute(
                delete(Call).where(Call.campaign_id == campaign_id)
            )

            db.execute(
                delete(Borrower).where(Borrower.id.in_(borrower_ids))
            )

            db.execute(
                delete(Agent).where(Agent.id.in_(agent_ids))
            )

            db.execute(
                delete(Campaign).where(Campaign.id == campaign_id)
            )

            # Restore agents that were available before the test.
            if previously_available_agent_ids:
                db.execute(
                    update(Agent)
                    .where(Agent.id.in_(previously_available_agent_ids))
                    .values(state="AVAILABLE")
                )

            db.commit()
