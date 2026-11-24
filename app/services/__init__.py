import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import ALLOWED_CALL_TRANSITIONS, TERMINAL_CALL_STATES
from app.models import Agent, Borrower, Call, ProviderEvent
from app.providers import HEALTH, PROVIDERS
from app.services.safety_controller import SafetyController


class PacingEngine:
    """Recommend a batch size without initiating calls or changing state."""

    def recommend(
        self,
        mode: str,
        available_agents: int,
        queued_borrowers: int,
        ringing_calls: int,
        connected_calls: int,
        answer_rate: float,
        avg_talk_seconds: int,
        max_batch: int,
    ) -> tuple[int, str]:
        if mode == "progressive":
            count = min(available_agents, queued_borrowers, max_batch)
            return (
                count,
                "Progressive: one outbound attempt per currently available agent.",
            )

        # Estimate attempts needed to fill a target share of agent capacity.
        # The hard agent-slot limit is enforced again by the Safety Controller.
        observed_workload = connected_calls + ringing_calls
        estimated_pool = max(available_agents + observed_workload, 1)
        talk_time_factor = min(max(avg_talk_seconds, 30), 600) / 6000
        target_utilization = max(0.75, min(0.90, 0.90 - talk_time_factor))
        target_active = math.ceil(estimated_pool * target_utilization)
        target_new_answers = max(0, target_active - observed_workload)
        expected_answers_per_attempt = max(answer_rate, 0.01)
        demand_adjusted = math.ceil(
            target_new_answers / expected_answers_per_attempt
        )
        count = min(
            available_agents,
            queued_borrowers,
            max_batch,
            demand_adjusted,
        )

        explanation = (
            "Conservative safety policy. Predictive estimate: "
            f"answer_rate={answer_rate:.2f}, "
            f"avg_talk={avg_talk_seconds}s, ringing={ringing_calls}, "
            f"connected={connected_calls}, "
            f"target_utilization={target_utilization:.0%}. "
            "The Safety Controller still caps every attempt at a reserved agent slot."
        )
        return count, explanation


class Allocator:
    def reserve_one(
        self,
        db: Session,
        campaign_id: int,
        provider_name: str,
        key: str,
        max_attempts: int = 10,
    ):
        # A repeated client key must never allocate a second call.
        existing_call = db.scalar(
            select(Call.id).where(Call.idempotency_key == key)
        )
        if existing_call is not None:
            return None

        for _ in range(max_attempts):
            agent = db.scalar(
                select(Agent)
                .where(Agent.state == "AVAILABLE")
                .order_by(Agent.id)
                .limit(1)
            )
            borrower = db.scalar(
                select(Borrower)
                .where(
                    Borrower.campaign_id == campaign_id,
                    Borrower.state == "QUEUED",
                )
                .order_by(Borrower.id)
                .limit(1)
            )

            if not agent or not borrower:
                return None

            agent_claim = db.execute(
                update(Agent)
                .where(
                    Agent.id == agent.id,
                    Agent.state == "AVAILABLE",
                )
                .values(state="RESERVED")
            )
            if agent_claim.rowcount != 1:
                db.rollback()
                continue

            borrower_claim = db.execute(
                update(Borrower)
                .where(
                    Borrower.id == borrower.id,
                    Borrower.state == "QUEUED",
                )
                .values(
                    state="RESERVED",
                    attempts=Borrower.attempts + 1,
                )
            )
            if borrower_claim.rowcount != 1:
                db.rollback()
                continue

            call = Call(
                campaign_id=campaign_id,
                agent_id=agent.id,
                borrower_id=borrower.id,
                provider=provider_name,
                state="RESERVED",
                idempotency_key=key,
            )
            db.add(call)

            try:
                db.flush()
                agent.current_call_id = call.id
                db.commit()
                db.refresh(call)
                return call
            except IntegrityError:
                # Another worker may have won the unique idempotency-key race.
                db.rollback()
                return None

        return None


class Dialer:
    def __init__(self):
        self.pacing = PacingEngine()
        self.safety = SafetyController()
        self.allocator = Allocator()

    def dial(
        self,
        db: Session,
        campaign_id: int,
        mode: str,
        provider_name: str,
        answer_rate: float = 0.5,
        avg_talk: int = 120,
        max_batch: int = 50,
        idempotency_key: str | None = None,
    ):
        available = db.scalar(
            select(func.count())
            .select_from(Agent)
            .where(Agent.state == "AVAILABLE")
        ) or 0
        queued = db.scalar(
            select(func.count())
            .select_from(Borrower)
            .where(
                Borrower.campaign_id == campaign_id,
                Borrower.state == "QUEUED",
            )
        ) or 0
        ringing = db.scalar(
            select(func.count())
            .select_from(Call)
            .where(Call.state == "RINGING")
        ) or 0
        connected = db.scalar(
            select(func.count())
            .select_from(Call)
            .where(Call.state == "CONNECTED")
        ) or 0

        requested, explanation = self.pacing.recommend(
            mode,
            available,
            queued,
            ringing,
            connected,
            answer_rate,
            avg_talk,
            max_batch,
        )
        decision = self.safety.approve(
            requested,
            available,
            queued,
            provider_healthy=HEALTH[provider_name].healthy(),
        )

        created = []
        batch_key = idempotency_key or uuid4().hex
        provider = PROVIDERS[provider_name]

        for index in range(decision.approved_count):
            # Stable per-batch keys prevent duplicate requests from creating calls.
            key = f"campaign-{campaign_id}-{batch_key}-{index}"
            call = self.allocator.reserve_one(
                db,
                campaign_id,
                provider_name,
                key,
            )
            if call is None:
                break

            # Persist the boundary before the external provider side effect.
            started = db.execute(
                update(Call)
                .where(
                    Call.id == call.id,
                    Call.state == "RESERVED",
                    Call.provider_started.is_(False),
                )
                .values(provider_started=True)
            )
            if started.rowcount != 1:
                db.rollback()
                continue

            db.commit()
            borrower = db.get(Borrower, call.borrower_id)
            result = provider.initiate(call.id, borrower.phone)
            HEALTH[provider_name].record(result.accepted)

            agent = db.get(Agent, call.agent_id)
            if result.accepted:
                call.provider_call_id = result.provider_call_id
                call.state = "INITIATED"
                agent.state = "DIALING"
            else:
                call.state = "FAILED"
                agent.state = "AVAILABLE"
                agent.current_call_id = None
                borrower.state = "QUEUED"

            db.commit()
            created.append(call.id)

        return {
            "mode": mode,
            "requested": requested,
            "approved": decision.approved_count,
            "idempotency_key": batch_key,
            "initiated_call_ids": created,
            "safety_decision": decision.reason,
            "pacing_explanation": explanation,
            "provider_healthy": HEALTH[provider_name].healthy(),
        }


def process_provider_event(
    db: Session,
    call_id: int,
    provider: str,
    event_id: str,
    event_type: str,
):
    existing = db.scalar(
        select(ProviderEvent).where(
            ProviderEvent.provider == provider,
            ProviderEvent.event_id == event_id,
        )
    )
    if existing:
        call = db.get(Call, call_id)
        return {
            "accepted": True,
            "duplicate": True,
            "state": call.state if call else None,
        }

    call = db.get(Call, call_id)
    if not call:
        return None

    db.add(
        ProviderEvent(
            provider=provider,
            event_id=event_id,
            call_id=call_id,
            event_type=event_type,
        )
    )

    current = call.state
    if current in TERMINAL_CALL_STATES:
        db.commit()
        return {
            "accepted": True,
            "duplicate": False,
            "ignored_stale": True,
            "state": current,
        }

    # Ignore events that cannot legally move the call state forward.
    allowed = ALLOWED_CALL_TRANSITIONS.get(current, set())
    if event_type not in allowed:
        db.commit()
        return {
            "accepted": True,
            "duplicate": False,
            "ignored_stale": True,
            "state": current,
        }

    call.state = event_type
    agent = db.get(Agent, call.agent_id)
    borrower = db.get(Borrower, call.borrower_id)

    if event_type == "RINGING":
        agent.state = "DIALING"
    elif event_type in {"ANSWERED", "CONNECTED"}:
        agent.state = "CONNECTED"
    elif event_type in {"COMPLETED", "FAILED", "CANCELLED"}:
        agent.state = "AVAILABLE"
        agent.current_call_id = None
        borrower.state = (
            "CONTACTED" if event_type == "COMPLETED" else "QUEUED"
        )

    db.commit()
    return {
        "accepted": True,
        "duplicate": False,
        "state": call.state,
    }


def recover_stale_reservations(
    db: Session,
    stale_after_seconds: int = 120,
) -> dict:
    """Release reservations abandoned before provider initiation.

    Initiated calls are ambiguous after a crash and require provider
    reconciliation before they can safely be retried.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=stale_after_seconds
    )
    stale_calls = db.scalars(
        select(Call).where(
            Call.state == "RESERVED",
            Call.provider_started.is_(False),
            Call.updated_at < cutoff,
        )
    ).all()

    recovered = 0
    for call in stale_calls:
        agent = db.get(Agent, call.agent_id)
        borrower = db.get(Borrower, call.borrower_id)
        if not agent or not borrower:
            continue

        # The conditional update avoids overwriting a concurrent transition.
        changed = db.execute(
            update(Call)
            .where(
                Call.id == call.id,
                Call.state == "RESERVED",
                Call.provider_started.is_(False),
                Call.updated_at < cutoff,
            )
            .values(state="FAILED")
        )
        if changed.rowcount != 1:
            continue

        db.execute(
            update(Agent)
            .where(
                Agent.id == agent.id,
                Agent.current_call_id == call.id,
            )
            .values(state="AVAILABLE", current_call_id=None)
        )
        db.execute(
            update(Borrower)
            .where(
                Borrower.id == borrower.id,
                Borrower.state == "RESERVED",
            )
            .values(state="QUEUED")
        )
        recovered += 1

    db.commit()
    return {"recovered": recovered, "cutoff": cutoff.isoformat()}
