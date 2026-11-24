
import pytest
from uuid import uuid4
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import make_url

from app.config import DATABASE_URL
from app.db import SessionLocal
from app.models import Agent, Borrower, Call, Campaign, ProviderEvent
from app.services import process_provider_event


# Use only the dedicated PostgreSQL test database.
_db_url = make_url(DATABASE_URL)

pytestmark = pytest.mark.skipif(
    _db_url.get_backend_name() != "postgresql"
    or _db_url.database != "credresolve_test",
    reason="Requires the dedicated PostgreSQL credresolve_test database",
)


@pytest.fixture
def call_records():
    with SessionLocal() as db:
        campaign = Campaign(name="Provider Event Test Campaign")
        db.add(campaign)
        db.flush()

        agent = Agent(
            name="Provider Event Test Agent",
            state="DIALING",
        )

        borrower = Borrower(
            campaign_id=campaign.id,
            name="Provider Event Test Borrower",
            phone="+919000000099",
            state="RESERVED",
            attempts=1,
        )

        db.add_all([agent, borrower])
        db.flush()

        call = Call(
            campaign_id=campaign.id,
            agent_id=agent.id,
            borrower_id=borrower.id,
            provider="provider_a",
            state="INITIATED",
            idempotency_key=f"provider-event-test-{campaign.id}",
        )

        db.add(call)
        db.flush()

        agent.current_call_id = call.id
        db.commit()

        campaign_id = campaign.id
        agent_id = agent.id
        borrower_id = borrower.id
        call_id = call.id

    yield campaign_id, agent_id, borrower_id, call_id

    # Clean up only this fixture's records.
    with SessionLocal() as db:
        db.execute(
            update(Agent)
            .where(Agent.id == agent_id)
            .values(current_call_id=None)
        )

        db.execute(
            delete(ProviderEvent).where(
                ProviderEvent.call_id == call_id
            )
        )

        db.execute(delete(Call).where(Call.id == call_id))
        db.execute(delete(Borrower).where(Borrower.id == borrower_id))
        db.execute(delete(Agent).where(Agent.id == agent_id))
        db.execute(delete(Campaign).where(Campaign.id == campaign_id))

        db.commit()


def test_duplicate_provider_event_is_processed_only_once(call_records):
    _, _, _, call_id = call_records
    event_prefix = uuid4().hex

    with SessionLocal() as db:
        first = process_provider_event(
            db, call_id, "provider_a", f"{event_prefix}-duplicate-event-1", "RINGING"
        )

        second = process_provider_event(
            db, call_id, "provider_a", f"{event_prefix}-duplicate-event-1", "RINGING"
        )

        assert first["duplicate"] is False
        assert second["duplicate"] is True
        assert second["state"] == "RINGING"

        event_count = db.scalar(
            select(func.count(ProviderEvent.id)).where(
                ProviderEvent.call_id == call_id
            )
        )

        assert event_count == 1


def test_stale_event_cannot_resurrect_completed_call(call_records):
    _, agent_id, borrower_id, call_id = call_records
    event_prefix = uuid4().hex

    with SessionLocal() as db:
        for event_type in ["RINGING", "ANSWERED", "CONNECTED", "COMPLETED"]:
            process_provider_event(
                db,
                call_id,
                "provider_a",
                f"{event_prefix}-lifecycle-{event_type}",
                event_type,
            )

        result = process_provider_event(
            db, call_id, "provider_a", f"{event_prefix}-late-ringing-event", "RINGING"
        )

        assert result["ignored_stale"] is True
        assert result["state"] == "COMPLETED"

        agent = db.get(Agent, agent_id)
        borrower = db.get(Borrower, borrower_id)
        call = db.get(Call, call_id)

        assert call.state == "COMPLETED"
        assert agent.state == "AVAILABLE"
        assert agent.current_call_id is None
        assert borrower.state == "CONTACTED"


def test_failed_call_releases_agent_and_requeues_borrower(call_records):
    _, agent_id, borrower_id, call_id = call_records
    event_prefix = uuid4().hex

    with SessionLocal() as db:
        result = process_provider_event(
            db, call_id, "provider_a", f"{event_prefix}-failed-event-1", "FAILED"
        )

        assert result["state"] == "FAILED"

        agent = db.get(Agent, agent_id)
        borrower = db.get(Borrower, borrower_id)
        call = db.get(Call, call_id)

        assert call.state == "FAILED"
        assert agent.state == "AVAILABLE"
        assert agent.current_call_id is None
        assert borrower.state == "QUEUED"


def test_completed_call_releases_agent_and_contacts_borrower(call_records):
    _, agent_id, borrower_id, call_id = call_records
    event_prefix = uuid4().hex

    with SessionLocal() as db:
        for event_type in ["RINGING", "ANSWERED", "CONNECTED", "COMPLETED"]:
            result = process_provider_event(
                db,
                call_id,
                "provider_a",
                f"{event_prefix}-completed-{event_type}",
                event_type,
            )

        agent = db.get(Agent, agent_id)
        borrower = db.get(Borrower, borrower_id)
        call = db.get(Call, call_id)

        assert result["state"] == "COMPLETED"
        assert call.state == "COMPLETED"
        assert agent.state == "AVAILABLE"
        assert agent.current_call_id is None
        assert borrower.state == "CONTACTED"


def test_unknown_call_id_is_handled_safely():
    with SessionLocal() as db:
        result = process_provider_event(
            db, 999999999, "provider_a", "unknown-call-event", "RINGING"
        )

        assert result is None
