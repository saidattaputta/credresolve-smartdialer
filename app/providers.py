import random
import time
import uuid
from dataclasses import dataclass

@dataclass
class InitiationResult:
    accepted: bool
    provider_call_id: str | None
    error: str | None = None

class TelecomProvider:
    name = "base"
    def initiate(self, call_id: int, phone: str) -> InitiationResult:
        raise NotImplementedError

class ProviderA(TelecomProvider):
    name = "provider_a"
    def initiate(self, call_id: int, phone: str) -> InitiationResult:
        return InitiationResult(True, f"A-{uuid.uuid4().hex[:12]}")

class ProviderB(TelecomProvider):
    name = "provider_b"
    def initiate(self, call_id: int, phone: str) -> InitiationResult:
        time.sleep(0.03)
        if random.random() < 0.12:
            return InitiationResult(False, None, "simulated_timeout")
        return InitiationResult(True, f"B-{uuid.uuid4().hex[:12]}")

PROVIDERS = {"provider_a": ProviderA(), "provider_b": ProviderB()}

class ProviderHealth:
    """Demo circuit breaker. Production multi-worker state belongs in shared storage."""
    def __init__(self):
        self.failures = 0
        self.successes = 0
        self.open = False

    def record(self, success: bool):
        if success:
            self.successes += 1
            if self.successes >= 2:
                self.open = False
                self.failures = 0
        else:
            self.failures += 1
            self.successes = 0
            if self.failures >= 3:
                self.open = True

    def healthy(self):
        return not self.open

HEALTH = {name: ProviderHealth() for name in PROVIDERS}
