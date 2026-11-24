from dataclasses import dataclass


@dataclass(frozen=True)
class DialingDecision:
    approved_count: int
    requested_count: int
    reason: str


class SafetyController:
    """Mandatory gate between pacing decisions and call initiation.

    This first version contains the pure capacity rule. The next milestone will
    move the authoritative reservation into a PostgreSQL transaction so concurrent
    workers cannot over-allocate agents.
    """

    @staticmethod
    def approve(requested_count: int, available_agent_count: int,
                provider_healthy: bool = True) -> DialingDecision:
        if requested_count < 0 or available_agent_count < 0:
            raise ValueError("Counts cannot be negative")

        if not provider_healthy:
            return DialingDecision(0, requested_count, "provider_unhealthy")

        approved = min(requested_count, available_agent_count)
        reason = "approved" if approved == requested_count else "capped_by_agent_capacity"
        return DialingDecision(approved, requested_count, reason)
