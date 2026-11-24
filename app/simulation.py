"""Deterministic aggregate pacing scenario estimates (not live call execution)."""
from itertools import product

ANSWER_RATES = (0.20, 0.50, 0.70)
TALK_TIMES_SECONDS = (120, 90, 180)
ATTEMPTS = 100
AGENT_COUNT = 20


def evaluate(answer_rate: float, average_talk_seconds: int) -> dict:
    expected_answers = ATTEMPTS * answer_rate
    # Approximate concurrent answered workload for a 60-second observation window.
    occupancy = min(1.0, expected_answers * average_talk_seconds / (AGENT_COUNT * 60))
    return {
        "answer_rate": answer_rate,
        "average_talk_seconds": average_talk_seconds,
        "attempts": ATTEMPTS,
        "expected_answers": round(expected_answers, 1),
        "estimated_agent_occupancy": round(occupancy, 3),
    }


def run_matrix() -> list[dict]:
    return [
        evaluate(rate, talk_time)
        for rate, talk_time in product(ANSWER_RATES, TALK_TIMES_SECONDS)
    ]


def main() -> None:
    print("answer_rate,talk_time_seconds,attempts,expected_answers,estimated_agent_occupancy")
    for row in run_matrix():
        print(
            f"{row['answer_rate']:.0%},{row['average_talk_seconds']},"
            f"{row['attempts']},{row['expected_answers']:.1f},"
            f"{row['estimated_agent_occupancy']:.3f}"
        )


if __name__ == "__main__":
    main()
