import pytest

from app.services.safety_controller import SafetyController


def test_never_approves_more_calls_than_available_agents():
    decision = SafetyController.approve(15, 10)
    assert decision.approved_count == 10
    assert decision.reason == "capped_by_agent_capacity"


def test_approves_request_within_capacity():
    decision = SafetyController.approve(4, 10)
    assert decision.approved_count == 4


def test_rejects_all_calls_when_provider_unhealthy():
    decision = SafetyController.approve(5, 10, provider_healthy=False)
    assert decision.approved_count == 0
    assert decision.reason == "provider_unhealthy"


def test_negative_counts_are_rejected():
    with pytest.raises(ValueError):
        SafetyController.approve(-1, 10)

def test_never_approves_more_calls_than_queued_borrowers():
    decision = SafetyController.approve(10, 8, 3)
    assert decision.approved_count == 3
    assert decision.reason == "capped_by_borrower_capacity"