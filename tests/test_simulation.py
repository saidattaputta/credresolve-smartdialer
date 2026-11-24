from app.simulation import run_matrix


def test_scenario_matrix_covers_required_rates_and_talk_times():
    rows = run_matrix()
    assert len(rows) == 9
    assert {row["answer_rate"] for row in rows} == {0.2, 0.5, 0.7}
    assert {row["average_talk_seconds"] for row in rows} == {90, 120, 180}
    assert all(row["attempts"] == 100 for row in rows)
    assert all(0 <= row["estimated_agent_occupancy"] <= 1 for row in rows)
