from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import APP_NAME
from app.db import get_db, init_db
from app.models import Agent, Borrower, Call, Campaign
from app.schemas import (
    AgentCreate,
    BorrowerCreate,
    CampaignCreate,
    DialRequest,
    EventRequest,
    SeedRequest,
)
from app.services import (
    Dialer,
    process_provider_event,
    recover_stale_reservations,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables when the application starts."""
    init_db()
    yield


app = FastAPI(
    title=APP_NAME,
    version="1.0.0",
    description=(
        "SmartDialer prototype with progressive/predictive pacing "
        "and a mandatory safety gate."
    ),
    lifespan=lifespan,
)

dialer = Dialer()


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "credresolve-smartdialer"}


@app.post("/api/v1/demo/seed", tags=["demo"])
def seed(payload: SeedRequest, db: Session = Depends(get_db)):
    campaign = Campaign(name=payload.campaign_name)
    db.add(campaign)
    db.flush()

    agents = [Agent(name=f"Agent {index + 1}") for index in range(payload.agents)]
    borrowers = [
        Borrower(
            campaign_id=campaign.id,
            name=f"Borrower {index + 1}",
            phone=f"+9100000{index:04d}",
        )
        for index in range(payload.borrowers)
    ]
    db.add_all([*agents, *borrowers])
    db.commit()

    return {
        "campaign_id": campaign.id,
        "agents_created": payload.agents,
        "borrowers_created": payload.borrowers,
    }


@app.post("/api/v1/campaigns", tags=["campaigns"])
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    campaign = Campaign(name=payload.name)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
    }


@app.post("/api/v1/agents", tags=["agents"])
def create_agent(payload: AgentCreate, db: Session = Depends(get_db)):
    agent = Agent(name=payload.name)
    db.add(agent)
    db.commit()
    db.refresh(agent)

    return {"id": agent.id, "name": agent.name, "state": agent.state}


@app.post("/api/v1/campaigns/{campaign_id}/borrowers", tags=["campaigns"])
def add_borrower(
    campaign_id: int,
    payload: BorrowerCreate,
    db: Session = Depends(get_db),
):
    if not db.get(Campaign, campaign_id):
        raise HTTPException(404, "Campaign not found")

    borrower = Borrower(
        campaign_id=campaign_id,
        name=payload.name,
        phone=payload.phone,
    )
    db.add(borrower)
    db.commit()
    db.refresh(borrower)

    return {"id": borrower.id, "state": borrower.state}


@app.post("/api/v1/campaigns/{campaign_id}/dial", tags=["dialing"])
def dial_campaign(
    campaign_id: int,
    payload: DialRequest,
    db: Session = Depends(get_db),
):
    if not db.get(Campaign, campaign_id):
        raise HTTPException(404, "Campaign not found")

    return dialer.dial(
        db,
        campaign_id,
        payload.mode,
        payload.provider,
        payload.answer_rate,
        payload.average_talk_time_seconds,
        payload.max_batch,
        payload.idempotency_key,
    )


@app.get("/api/v1/campaigns/{campaign_id}/calls", tags=["calls"])
def list_calls(campaign_id: int, db: Session = Depends(get_db)):
    calls = db.scalars(
        select(Call)
        .where(Call.campaign_id == campaign_id)
        .order_by(Call.id)
    ).all()

    return [
        {
            "id": call.id,
            "agent_id": call.agent_id,
            "borrower_id": call.borrower_id,
            "provider": call.provider,
            "provider_call_id": call.provider_call_id,
            "state": call.state,
        }
        for call in calls
    ]


@app.post("/api/v1/calls/{call_id}/events", tags=["provider events"])
def provider_event(
    call_id: int,
    payload: EventRequest,
    db: Session = Depends(get_db),
):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Call not found")

    return process_provider_event(
        db,
        call_id,
        call.provider,
        payload.event_id,
        payload.event_type,
    )


@app.post(
    "/api/v1/maintenance/recover-stale-reservations",
    tags=["maintenance"],
)
def recover_reservations(
    stale_after_seconds: int = 120,
    db: Session = Depends(get_db),
):
    if stale_after_seconds < 1:
        raise HTTPException(422, "stale_after_seconds must be positive")
    return recover_stale_reservations(db, stale_after_seconds)


@app.get("/api/v1/metrics", tags=["monitoring"])
def metrics(db: Session = Depends(get_db)):
    def count(model, field=None, value=None):
        statement = select(func.count()).select_from(model)
        if field is not None:
            statement = statement.where(field == value)
        return db.scalar(statement) or 0

    agent_states = (
        "AVAILABLE",
        "RESERVED",
        "DIALING",
        "CONNECTED",
        "OFFLINE",
        "PAUSED",
    )
    call_states = (
        "INITIATED",
        "RINGING",
        "ANSWERED",
        "CONNECTED",
        "COMPLETED",
        "FAILED",
    )

    return {
        "agents": {
            state: count(Agent, Agent.state, state) for state in agent_states
        },
        "calls": {
            state: count(Call, Call.state, state) for state in call_states
        },
        "borrowers_queued": count(Borrower, Borrower.state, "QUEUED"),
    }


@app.post("/api/v1/simulation/run", tags=["simulation"])
def run_simulation(db: Session = Depends(get_db)):
    campaign = Campaign(name="Simulation Campaign")
    db.add(campaign)
    db.flush()

    agents = [Agent(name=f"Sim Agent {index}") for index in range(10)]
    borrowers = [
        Borrower(
            campaign_id=campaign.id,
            name=f"Sim Borrower {index}",
            phone=f"+919999{index:05d}",
        )
        for index in range(100)
    ]
    db.add_all([*agents, *borrowers])
    db.commit()

    result = dialer.dial(
        db,
        campaign.id,
        "predictive",
        "provider_a",
        0.5,
        120,
        50,
    )

    return {
        "scenario": {
            "agents": 10,
            "borrowers": 100,
            "answer_rate": 0.5,
            "average_talk_time_seconds": 120,
        },
        "result": result,
        "interpretation": (
            "The safety controller ensures initiated attempts "
            "never exceed currently available agent slots."
        ),
    }
