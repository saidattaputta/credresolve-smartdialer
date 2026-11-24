from app.services import PacingEngine, SafetyController
from app.domain import ALLOWED_CALL_TRANSITIONS

def test_progressive_is_one_call_per_available_agent():
    n, _ = PacingEngine().recommend("progressive", 4, 20, 0, 0, .5, 120, 50)
    assert n == 4

def test_progressive_respects_borrower_queue():
    n, _ = PacingEngine().recommend("progressive", 10, 2, 0, 0, .5, 120, 50)
    assert n == 2

def test_predictive_never_recommends_more_than_agents():
    n, explanation = PacingEngine().recommend("predictive", 5, 100, 0, 0, .2, 120, 50)
    assert n <= 5
    assert "Conservative safety policy" in explanation

def test_safety_controller_hard_caps():
    decision = SafetyController().approve(20, 3, 100, True)

    assert decision.approved_count == 3
    assert decision.requested_count == 20
    assert decision.reason == "capped_by_agent_capacity"

def test_call_state_machine_has_no_terminal_resurrection():
    assert "RINGING" not in ALLOWED_CALL_TRANSITIONS["COMPLETED"]
