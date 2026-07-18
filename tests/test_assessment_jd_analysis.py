"""JD-analysis request compatibility tests."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.schemas.assessment import JDAnalysisAndInterviewPlan
from src.utils.assessment_utils import (
    _finalize_analysis,
    run_jd_analysis_and_interview_plan,
)


def _valid_analysis_payload() -> dict[str, object]:
    return {
        "jd_analysis": {
            "inferred_difficulty": "mid-level",
            "skills": [
                {
                    "skill": "Python",
                    "priority_score": 9.0,
                    "reasoning": "Python is central to the role.",
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
                {
                    "section_name": "Python",
                    "skill": "Python",
                    "allocated_mins": 8.0,
                    "expected_signals": [
                        "Explains Python mechanisms clearly",
                        "Applies Python to backend reliability",
                    ],
                    "question_brief": {
                        "expected_signals": [
                            "Explains Python mechanisms clearly",
                            "Applies Python to backend reliability",
                        ],
                        "role_responsibility": "Build reliable Python services.",
                        "operating_environment": "Production backend services.",
                        "important_tools": ["Python"],
                        "constraints": ["Reliability"],
                        "seniority_depth": "Use mid-level production reasoning.",
                        "out_of_scope_topics": [],
                    },
                },
                {
                    "section_name": "behavioural_cultural",
                    "skill": None,
                    "allocated_mins": 1.0,
                    "expected_signals": ["Ownership"],
                },
            ],
        },
    }


async def test_jd_analysis_uses_json_object_response_mode() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(_valid_analysis_payload())
                    )
                )
            ]
        )
    )
    groq_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    generated = await run_jd_analysis_and_interview_plan(
        "We need a Python backend engineer who owns reliable services.",
        10,
        None,
        groq_client,
    )

    assert generated.jd_analysis.inferred_difficulty == "mid-level"
    assert create.await_args.kwargs["response_format"] == {"type": "json_object"}
    system_prompt = create.await_args.kwargs["messages"][0]["content"]
    assert "Match this JSON Schema" in system_prompt


def test_five_minute_plan_has_fixed_non_technical_timing() -> None:
    payload = _valid_analysis_payload()
    jd_analysis = payload["jd_analysis"]
    interview_plan = payload["interview_plan"]
    assert isinstance(jd_analysis, dict)
    assert isinstance(interview_plan, dict)

    jd_analysis["skills"] = [
        {
            "skill": "Python",
            "priority_score": 9.0,
            "reasoning": "Python is central to the role.",
        },
        {
            "skill": "FastAPI Fundamentals",
            "priority_score": 8.0,
            "reasoning": "FastAPI is required for API delivery.",
        },
        {
            "skill": "Solid Database Foundations",
            "priority_score": 5.0,
            "reasoning": "Database knowledge supports the role.",
        },
    ]
    interview_plan["total_mins"] = 5
    sections = interview_plan["sections"]
    assert isinstance(sections, list)
    sections[0]["allocated_mins"] = 1.0
    sections[1]["allocated_mins"] = 1.5
    sections.insert(
        2,
        {
            "section_name": "FastAPI Fundamentals",
            "skill": "FastAPI Fundamentals",
            "allocated_mins": 1.5,
            "expected_signals": [
                "Understands FastAPI fundamentals",
                "Can build functional API endpoints",
            ],
            "question_brief": {
                "expected_signals": [
                    "Understands FastAPI fundamentals",
                    "Can build functional API endpoints",
                ],
                "role_responsibility": "Build reliable FastAPI endpoints.",
                "operating_environment": "Production API services.",
                "important_tools": ["FastAPI"],
                "constraints": ["Reliability"],
                "seniority_depth": "Probe role-appropriate API reasoning.",
                "out_of_scope_topics": [],
            },
        },
    )
    sections.insert(
        3,
        {
            "section_name": "Solid Database Foundations",
            "skill": "Solid Database Foundations",
            "allocated_mins": 1.0,
            "expected_signals": [
                "Understands data relationships",
                "Can explain database normalization",
            ],
            "question_brief": {
                "expected_signals": [
                    "Understands data relationships",
                    "Can explain database normalization",
                ],
                "role_responsibility": "Maintain application data models.",
                "operating_environment": "Relational application databases.",
                "important_tools": ["SQL"],
                "constraints": ["Data integrity"],
                "seniority_depth": "Probe foundational database reasoning.",
                "out_of_scope_topics": [],
            },
        },
    )
    sections[-1]["allocated_mins"] = 0.5

    generated = _finalize_analysis(
        JDAnalysisAndInterviewPlan.model_validate(payload),
        5,
        None,
    )

    normalized = generated.interview_plan.sections
    assert [section.section_name for section in normalized] == [
        "self_intro",
        "Python",
        "FastAPI Fundamentals",
        "behavioural_cultural",
    ]
    assert normalized[0].allocated_mins == 0.5
    assert normalized[-1].allocated_mins == 0.5
    assert sum(section.allocated_mins for section in normalized) == 5.0
    assert normalized[1].allocated_mins > normalized[2].allocated_mins


def test_long_interview_caps_self_intro_at_one_and_a_half_minutes() -> None:
    generated = _finalize_analysis(
        JDAnalysisAndInterviewPlan.model_validate(_valid_analysis_payload()),
        30,
        None,
    )

    sections = generated.interview_plan.sections
    assert sections[0].allocated_mins == 1.5
    assert sections[-1].allocated_mins == 3.0
    assert sum(section.allocated_mins for section in sections) == 30.0
