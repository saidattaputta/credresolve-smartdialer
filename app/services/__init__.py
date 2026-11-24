import math
from uuid import uuid4
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import Agent, Borrower, Call, ProviderEvent
from app.domain import TERMINAL_CALL_STATES, ALLOWED_CALL_TRANSITIONS
from app.providers import PROVIDERS, HEALTH
from app.services.safety_controller import SafetyController

class PacingEngine:
    """Pure decision logic: returns a recommendation and never calls providers."""
    def recommend(self, mode: str, available_agents: int, queued_borrowers: int,
                  ringing_calls: int, connected_calls: int, answer_rate: float,
                  avg_talk_seconds: int, max_batch: int) -> tuple[int, str]:
        if mode == "progressive":
            n = min(available_agents, queued_borrowers, max_batch)
            return n, "Progressive: one outbound attempt per currently available agent."
        # Conservative predictive policy: estimate attempts needed to fill a
        # target share of current agent capacity, then enforce the hard slot cap.
        # Longer calls lower the target to reduce queue pressure; ringing and
        # connected calls are included as already-occupied workload.
        observed_workload = connected_calls + ringing_calls
        estimated_pool = max(available_agents + observed_workload, 1)
        talk_time_factor = min(max(avg_talk_seconds, 30), 600) / 6000
        target_utilization = max(0.75, min(0.90, 0.90 - talk_time_factor))
        target_active = math.ceil(estimated_pool * target_utilization)
        target_new_answers = max(0, target_active - observed_workload)
        expected_answers_per_attempt = max(answer_rate, 0.01)
        demand_adjusted = math.ceil(target_new_answers / expected_answers_per_attempt)
        n = min(available_agents, queued_borrowers, max_batch, demand_adjusted)
        explanation = (
            f"Predictive estimate: answer_rate={answer_rate:.2f}, "
            f"avg_talk={avg_talk_seconds}s, ringing={ringing_calls}, "
            f"connected={connected_calls}, target_utilization={target_utilization:.0%}. "
            "The Safety Controller still caps every attempt at a reserved agent slot."
        )
        return n, explanation

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
        if db.scalar(select(Call.id).where(Call.idempotency_key == key)) is not None:
            return None

        for attempt in range(max_attempts):

            # Find an available agent.
            agent = db.scalar(
                select(Agent)
                .where(Agent.state == "AVAILABLE")
                .order_by(Agent.id)
                .limit(1)
            )

            # Find a queued borrower for this campaign.
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

            # Atomically claim the agent.
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

            # Atomically claim the borrower.
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

            # Both resources are successfully reserved.
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

        # No successful reservation within the retry limit.
        return None


class Dialer:
    def __init__(self):
        self.pacing = PacingEngine()
        self.safety = SafetyController()
        self.allocator = Allocator()

    def dial(self, db: Session, campaign_id: int, mode: str, provider_name: str,
             answer_rate: float = 0.5, avg_talk: int = 120, max_batch: int = 50,
             idempotency_key: str | None = None):
        available = db.scalar(select(func.count()).select_from(Agent).where(Agent.state == "AVAILABLE")) or 0
        queued = db.scalar(select(func.count()).select_from(Borrower).where(
            Borrower.campaign_id == campaign_id, Borrower.state == "QUEUED")) or 0
        ringing = db.scalar(select(func.count()).select_from(Call).where(Call.state == "RINGING")) or 0
        connected = db.scalar(select(func.count()).select_from(Call).where(Call.state == "CONNECTED")) or 0
        requested, explanation = self.pacing.recommend(
            mode, available, queued, ringing, connected, answer_rate, avg_talk, max_batch
        )
        decision = self.safety.approve(
            requested,
            available,
            queued,
            provider_healthy=HEALTH[provider_name].healthy(),
        )
        approved = decision.approved_count
        reason = decision.reason
        created = []
        batch_key = idempotency_key or uuid4().hex
        provider = PROVIDERS[provider_name]
        for i in range(approved):
            # Stable per-batch key prevents duplicate requests from creating duplicate calls.
            key = f"campaign-{campaign_id}-{batch_key}-{i}"
            call = self.allocator.reserve_one(db, campaign_id, provider_name, key)
            if call is None:
                break
            # Persist the boundary before the external side effect. If the worker
            # dies after this commit, recovery will not blindly retry the provider.
            call.provider_started = True
            db.commit()
            result = provider.initiate(call.id, db.get(Borrower, call.borrower_id).phone)
            HEALTH[provider_name].record(result.accepted)
            if result.accepted:
                call.provider_call_id = result.provider_call_id
                call.state = "INITIATED"
                db.get(Agent, call.agent_id).state = "DIALING"
            else:
                call.state = "FAILED"
                db.get(Agent, call.agent_id).state = "AVAILABLE"
                db.get(Agent, call.agent_id).current_call_id = None
                db.get(Borrower, call.borrower_id).state = "QUEUED"
            db.commit()
            created.append(call.id)
        return {
            "mode": mode, "requested": requested, "approved": approved,
            "idempotency_key": batch_key,
            "initiated_call_ids": created, "safety_decision": reason,
            "pacing_explanation": explanation, "provider_healthy": HEALTH[provider_name].healthy()
        }

def process_provider_event(db: Session, call_id: int, provider: str, event_id: str, event_type: str):
    existing = db.scalar(select(ProviderEvent).where(
        ProviderEvent.provider == provider, ProviderEvent.event_id == event_id
    ))
    if existing:
        return {"accepted": True, "duplicate": True, "state": db.get(Call, call_id).state}
    call = db.get(Call, call_id)
    if not call:
        return None
    db.add(ProviderEvent(provider=provider, event_id=event_id, call_id=call_id, event_type=event_type))
    current = call.state
    if current in TERMINAL_CALL_STATES:
        db.commit()
        return {"accepted": True, "duplicate": False, "ignored_stale": True, "state": current}
    # Ignore stale/out-of-order events that cannot legally move the state forward.
    allowed = ALLOWED_CALL_TRANSITIONS.get(current, set())
    if event_type not in allowed:
        db.commit()
        return {"accepted": True, "duplicate": False, "ignored_stale": True, "state": current}
    call.state = event_type
    agent = db.get(Agent, call.agent_id)
    borrower = db.get(Borrower, call.borrower_id)
    if event_type == "RINGING":
        agent.state = "DIALING"
    elif event_type in {"ANSWERED", "CONNECTED"}:
        agent.state = "CONNECTED"
    elif event_type in {"COMPLETED", "FAILED", "CANCELLED"}:
        agent.state = "WRAP_UP" if event_type == "COMPLETED" else "AVAILABLE"
        agent.current_call_id = None
        borrower.state = "CONTACTED" if event_type == "COMPLETED" else "QUEUED"
        if event_type == "COMPLETED":
            agent.state = "AVAILABLE"
    db.commit()
    return {"accepted": True, "duplicate": False, "state": call.state}



def recover_stale_reservations(db: Session, stale_after_seconds: int = 120) -> dict:
    """Release reservations left by a worker that died before provider initiation.

    Only RESERVED calls are automatically recovered. INITIATED calls are ambiguous
    after a crash and must be reconciled with the provider before retrying.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
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
        # Conditional state check prevents overwriting a concurrent transition.
        changed = db.execute(
            update(Call)
            .where(Call.id == call.id, Call.state == "RESERVED")
            .values(state="FAILED")
        )
        if changed.rowcount != 1:
            continue
        db.execute(
            update(Agent)
            .where(Agent.id == agent.id, Agent.current_call_id == call.id)
            .values(state="AVAILABLE", current_call_id=None)
        )
        db.execute(
            update(Borrower)
            .where(Borrower.id == borrower.id, Borrower.state == "RESERVED")
            .values(state="QUEUED")
        )
        recovered += 1
    db.commit()
    return {"recovered": recovered, "cutoff": cutoff.isoformat()}
