from pydantic import BaseModel, Field
from typing import Literal

class AgentCreate(BaseModel):
    name: str

class BorrowerCreate(BaseModel):
    name: str
    phone: str

class CampaignCreate(BaseModel):
    name: str

class SeedRequest(BaseModel):
    agents: int = Field(default=5, ge=1, le=500)
    borrowers: int = Field(default=20, ge=1, le=5000)
    campaign_name: str = "Demo Collections Campaign"

class DialRequest(BaseModel):
    mode: Literal["progressive", "predictive"] = "progressive"
    provider: Literal["provider_a", "provider_b"] = "provider_a"
    answer_rate: float = Field(default=0.5, ge=0.01, le=0.99)
    average_talk_time_seconds: int = Field(default=120, ge=10, le=3600)
    max_batch: int = Field(default=50, ge=1, le=500)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)

class EventRequest(BaseModel):
    event_id: str
    event_type: Literal["RINGING", "ANSWERED", "CONNECTED", "COMPLETED", "FAILED", "CANCELLED"]
