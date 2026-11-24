from dataclasses import dataclass


@dataclass(frozen=True)
class DialingDecision:
    approved_count: int
    requested_count: int
    reason: str


class SafetyController:
    """Final capacity and provider-health gate before call allocation."""

    @staticmethod
    def approve(
        requested_count: int,
        available_agent_count: int,
        queued_borrower_count: int | None = None,
        provider_healthy: bool = True,
    ) -> DialingDecision:

        counts = [requested_count, available_agent_count]
        if queued_borrower_count is not None:
            counts.append(queued_borrower_count)

        if any(count < 0 for count in counts):
            raise ValueError("Counts cannot be negative")

        if not provider_healthy:
            return DialingDecision(
                0, requested_count, "provider_unhealthy"
            )

        capacities = [requested_count, available_agent_count]

        if queued_borrower_count is not None:
            capacities.append(queued_borrower_count)

        approved = min(capacities)

        if approved == requested_count:
            reason = "approved"
        elif (
            queued_borrower_count is not None
            and queued_borrower_count < available_agent_count
            and queued_borrower_count < requested_count
        ):
            reason = "capped_by_borrower_capacity"
        else:
            reason = "capped_by_agent_capacity"

        return DialingDecision(approved, requested_count, reason)
