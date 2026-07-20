"""Public recruiter-report schema for deterministic proctoring details."""

from src.schemas.evaluation import ViolationSummary


def test_violation_summary_accepts_exact_policy_category_details() -> None:
    summary = ViolationSummary.model_validate(
        {
            "has_violation": True,
            "validated_violation_count": 2,
            "severity_counts": {
                "low": 1,
                "medium": 0,
                "high": 1,
                "critical": 0,
            },
            "summary": "One tab category and one face category were recorded.",
            "penalty_applied": 0.25,
            "hard_gate_reasons": [],
            "category_details": [
                {
                    "violation_type": "tab_switch",
                    "severity": "low",
                    "scored_occurrence_count": 1,
                    "occurrence_count": 5,
                    "timestamp": "2026-07-19T10:00:00Z",
                    "termination_triggered": True,
                    "termination_reason": "tab_switch_limit",
                    "tab_switch_count": 5,
                    "metadata": {"termination_threshold_count": 5},
                },
                {
                    "violation_type": "face_absent",
                    "severity": "high",
                    "scored_occurrence_count": 1,
                    "occurrence_count": 1,
                    "timestamp": "2026-07-19T10:01:00Z",
                    "termination_triggered": True,
                    "termination_reason": ("face_absent_continuous_duration_exceeded"),
                    "observed_duration_ms": 30_000,
                    "observed_durations_ms": [30_000],
                    "max_observed_duration_ms": 30_000,
                    "total_observed_duration_ms": 30_000,
                    "termination_duration_ms": 30_000,
                    "max_face_count": 0,
                    "metadata": {"source": "browser_face_proctoring"},
                },
            ],
        }
    )

    assert summary.category_details[0].tab_switch_count == 5
    assert summary.category_details[1].termination_triggered is True
    assert summary.category_details[1].observed_durations_ms == [30_000]
