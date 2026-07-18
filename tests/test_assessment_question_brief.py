"""JD-specific live-question brief schema contracts."""

import pytest
from pydantic import ValidationError

from src.schemas.assessment import InterviewPlan, JDAnalysisAndInterviewPlan


def _payload(*, include_brief: bool) -> dict[str, object]:
    technical: dict[str, object] = {
        "section_name": "Python",
        "skill": "Python",
        "allocated_mins": 8.0,
        "expected_signals": [
            "Explains Python mechanisms clearly",
            "Applies Python to backend reliability",
        ],
    }
    if include_brief:
        technical["question_brief"] = {
            "expected_signals": ["stale value", "another stale value"],
            "role_responsibility": "Build reliable Python backend services.",
            "operating_environment": "FastAPI services running in production.",
            "important_tools": ["Python", "FastAPI"],
            "constraints": ["Reliability", "Latency"],
            "seniority_depth": "Use mid-level production reasoning.",
            "out_of_scope_topics": ["Desktop GUI development"],
        }
    return {
        "jd_analysis": {
            "inferred_difficulty": "mid-level",
            "skills": [
                {
                    "skill": "Python",
                    "priority_score": 9.0,
                    "reasoning": "Python is central to backend delivery.",
                }
            ],
            "behavioural_signals": ["Ownership"],
        },
        "interview_plan": {
            "total_mins": 10,
            "inferred_difficulty": "mid-level",
            "sections": [
                {
                    "section_name": "self_intro",
                    "skill": None,
                    "allocated_mins": 1.0,
                },
                technical,
                {
                    "section_name": "behavioural_cultural",
                    "skill": None,
                    "allocated_mins": 1.0,
                    "expected_signals": ["Ownership", "Collaboration"],
                },
            ],
        },
    }


def test_new_combined_plan_requires_and_synchronizes_question_brief() -> None:
    generated = JDAnalysisAndInterviewPlan.model_validate(_payload(include_brief=True))
    technical = generated.interview_plan.sections[1]

    assert technical.question_brief is not None
    assert technical.question_brief.expected_signals == technical.expected_signals

    with pytest.raises(ValidationError, match="requires question_brief"):
        JDAnalysisAndInterviewPlan.model_validate(_payload(include_brief=False))


def test_legacy_stored_interview_plan_remains_readable_without_brief() -> None:
    payload = _payload(include_brief=False)["interview_plan"]

    plan = InterviewPlan.model_validate(payload)

    assert plan.sections[1].question_brief is None
