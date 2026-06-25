"""Utility helpers for JD parsing and analysis."""

import asyncio
import logging
import re

from fastapi.concurrency import run_in_threadpool
from groq import AsyncGroq

from src.config.settings import settings
from src.core.exceptions import (
    BadGatewayException,
    InternalServerException,
)
from src.schemas.assessment import (
    FocusAreaOverride,
    InterviewPlan,
    InterviewSection,
    JDAnalysisAndInterviewPlan,
)

logger = logging.getLogger(__name__)


async def parse_pdf_jd(file_bytes: bytes, filename: str) -> str:
    """Parse PDF job description using PyMuPDF in a background thread."""
    import fitz

    def extract_text() -> str:
        text = ""
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text() + "\n"
        return text

    try:
        return await run_in_threadpool(extract_text)
    except Exception as exc:
        logger.exception("Failed to parse PDF JD using PyMuPDF")
        raise InternalServerException(
            f"Error parsing job description file: {exc}"
        ) from exc


NON_TECH_SECTION_KEYS = {
    "self_intro",
    "intro",
    "introduction",
    "behavioural",
    "behavioral",
    "cultural",
    "culture",
    "behavioural_cultural",
    "behavioral_cultural",
}


def _section_key(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return key or "section"


def _is_technical_section(section: InterviewSection) -> bool:
    return (
        bool(section.skill)
        and _section_key(section.section_name) not in NON_TECH_SECTION_KEYS
    )


def _section_importance(section: InterviewSection) -> float:
    if _is_technical_section(section):
        return 100.0 + float(section.priority_score or 5.0)
    key = _section_key(section.section_name)
    if key in {"self_intro", "intro", "introduction"}:
        return 20.0
    if key in {
        "behavioural_cultural",
        "behavioral_cultural",
        "behavioural",
        "behavioral",
        "cultural",
        "culture",
    }:
        return 15.0
    return 5.0


def _drop_overflow_sections(
    sections: list[InterviewSection], total_tenths: int
) -> list[InterviewSection]:
    retained = list(sections)
    while len(retained) > total_tenths and len(retained) > 1:
        tech_count = sum(1 for section in retained if _is_technical_section(section))
        drop_index = min(
            range(len(retained)),
            key=lambda idx: (
                _section_importance(retained[idx])
                + (
                    1000.0
                    if _is_technical_section(retained[idx]) and tech_count == 1
                    else 0.0
                ),
                float(retained[idx].priority_score or 0.0),
            ),
        )
        retained.pop(drop_index)
    return retained


def _adjust_tenths_to_total(
    sections: list[InterviewSection], tenths: list[int], total_tenths: int
) -> list[int]:
    while sum(tenths) < total_tenths:
        target = max(
            range(len(sections)),
            key=lambda idx: (_section_importance(sections[idx]), tenths[idx]),
        )
        tenths[target] += 1

    while sum(tenths) > total_tenths:
        reducible = [idx for idx, value in enumerate(tenths) if value > 1]
        if not reducible:
            break
        target = min(
            reducible,
            key=lambda idx: (_section_importance(sections[idx]), -tenths[idx]),
        )
        tenths[target] -= 1

    return tenths


def _enforce_technical_priority(
    sections: list[InterviewSection], tenths: list[int]
) -> list[int]:
    tech_indices = [
        idx for idx, section in enumerate(sections) if _is_technical_section(section)
    ]
    non_tech_indices = [idx for idx in range(len(sections)) if idx not in tech_indices]
    if not tech_indices or not non_tech_indices:
        return tenths

    def can_shift() -> bool:
        return any(tenths[idx] > 1 for idx in non_tech_indices)

    while (
        sum(tenths[idx] for idx in tech_indices)
        <= sum(tenths[idx] for idx in non_tech_indices)
        and can_shift()
    ):
        donor = max(non_tech_indices, key=lambda idx: tenths[idx])
        receiver = max(
            tech_indices,
            key=lambda idx: (float(sections[idx].priority_score or 0.0), tenths[idx]),
        )
        tenths[donor] -= 1
        tenths[receiver] += 1

    while (
        max(tenths[idx] for idx in tech_indices)
        <= max(tenths[idx] for idx in non_tech_indices)
        and can_shift()
    ):
        donor = max(non_tech_indices, key=lambda idx: tenths[idx])
        receiver = max(
            tech_indices,
            key=lambda idx: (float(sections[idx].priority_score or 0.0), tenths[idx]),
        )
        tenths[donor] -= 1
        tenths[receiver] += 1

    return tenths


def _dedupe_section_names(sections: list[InterviewSection]) -> list[InterviewSection]:
    used: dict[str, int] = {}
    for index, section in enumerate(sections):
        base_name = section.section_name or section.skill or f"section_{index + 1}"
        key = _section_key(base_name)
        count = used.get(key, 0)
        used[key] = count + 1
        if count:
            section.section_name = f"{base_name}_{count + 1}"
        else:
            section.section_name = base_name
    return sections


def _combined_behavioural_cultural_section(
    sections: list[InterviewSection],
) -> tuple[list[InterviewSection], InterviewSection]:
    retained: list[InterviewSection] = []
    combined: InterviewSection | None = None
    expected_signals: list[str] = []
    allocated_mins = 0.0

    for section in sections:
        key = _section_key(section.section_name)
        if key not in {
            "behavioural_cultural",
            "behavioral_cultural",
            "behavioural",
            "behavioral",
            "cultural",
            "culture",
        }:
            retained.append(section)
            continue

        allocated_mins += max(0.0, float(section.allocated_mins or 0))
        for signal in section.expected_signals or []:
            if signal not in expected_signals:
                expected_signals.append(signal)
        combined = InterviewSection(
            section_name="behavioural_cultural",
            skill=None,
            allocated_mins=allocated_mins,
            priority_score=None,
            expected_signals=expected_signals,
        )

    if combined is None:
        combined = InterviewSection(
            section_name="behavioural_cultural",
            skill=None,
            allocated_mins=0.3,
            priority_score=None,
            expected_signals=[
                "behavioural example",
                "team collaboration",
                "culture fit",
            ],
        )

    if not combined.expected_signals:
        combined.expected_signals = [
            "behavioural example",
            "team collaboration",
            "culture fit",
        ]

    return retained, combined


def _normalize_required_section_shape(
    sections: list[InterviewSection],
) -> list[InterviewSection]:
    retained, behavioural_cultural = _combined_behavioural_cultural_section(sections)
    intro_sections: list[InterviewSection] = []
    technical_sections: list[InterviewSection] = []
    other_sections: list[InterviewSection] = []

    for section in retained:
        key = _section_key(section.section_name)
        if key in {"self_intro", "intro", "introduction"}:
            intro_sections.append(
                InterviewSection(
                    section_name="self_intro",
                    skill=None,
                    allocated_mins=section.allocated_mins,
                    priority_score=None,
                    expected_signals=section.expected_signals,
                )
            )
        elif _is_technical_section(section):
            technical_sections.append(section)
        else:
            other_sections.append(section)

    if not intro_sections:
        intro_sections.append(
            InterviewSection(
                section_name="self_intro",
                skill=None,
                allocated_mins=0.3,
                priority_score=None,
                expected_signals=["concise background", "role fit"],
            )
        )

    return [
        intro_sections[0],
        *technical_sections,
        *other_sections,
        behavioural_cultural,
    ]


def _normalize_interview_plan(
    plan: InterviewPlan,
    duration_mins: int,
) -> InterviewPlan:
    total_tenths = max(1, int(duration_mins * 10))
    sections = [section for section in plan.sections if section.allocated_mins > 0]
    if not sections:
        raise ValueError(
            "LLM returned an interview plan with no positive-duration sections."
        )

    sections = _normalize_required_section_shape(sections)
    sections = _drop_overflow_sections(sections, total_tenths)
    raw_tenths = [
        max(1, int(round(section.allocated_mins * 10))) for section in sections
    ]
    raw_total = sum(raw_tenths)
    if raw_total <= 0:
        raw_tenths = [1 for _ in sections]
        raw_total = sum(raw_tenths)

    tenths = [
        max(1, int(round(value * total_tenths / raw_total))) for value in raw_tenths
    ]
    tenths = _adjust_tenths_to_total(sections, tenths, total_tenths)
    tenths = _enforce_technical_priority(sections, tenths)
    tenths = _adjust_tenths_to_total(sections, tenths, total_tenths)

    normalized_sections: list[InterviewSection] = []
    for section, value in zip(sections, tenths, strict=True):
        normalized_sections.append(
            InterviewSection(
                section_name=section.section_name,
                skill=section.skill,
                allocated_mins=round(value / 10.0, 1),
                priority_score=section.priority_score,
                expected_signals=section.expected_signals,
            )
        )

    normalized_sections = _dedupe_section_names(normalized_sections)
    return InterviewPlan(
        total_mins=duration_mins,
        sections=normalized_sections,
    )


def _focus_areas_for_prompt(focus_areas: list[FocusAreaOverride] | None) -> str:
    if not focus_areas:
        return "[]"
    import json

    return json.dumps([item.model_dump() for item in focus_areas], ensure_ascii=True)


def _combined_analysis_system_prompt() -> str:
    return """
You are an expert technical recruiter, interview architect, and structured assessment designer.

Your task is to analyze a Job Description (JD) and produce TWO objects in ONE JSON response:
1. jd_analysis: the structured JD analysis.
2. interview_plan: a concrete section-by-section plan that the interview bot will execute and the recruiter UI will display.

Work in this order internally:
1. Extract the JD analysis first.
2. Use that exact JD analysis, especially skill priority_score and depth_required, to design the interview plan.

JD analysis scoring rules for priority_score from 1.0 to 10.0:
- Positioning: skills in the title, summary, responsibilities, or early requirements rank higher.
- Frequency: repeated skills across sections rank higher.
- Language strength: required, must-have, strong expertise, owns, designs, leads, or deep understanding are high-priority signals. Familiarity, exposure, nice-to-have, bonus, or plus are low-priority signals.
- Responsibility coupling: skills tied directly to core work rank higher than skills listed only in a broad stack.
- Seniority/depth: senior ownership, architecture, mentoring, production operations, scaling, or security responsibilities raise depth_required.

Interview-plan design technique:
- The input duration can be any integer from 2 to 180 minutes. Always honor it exactly.
- The interview_plan must contain exactly these section types in this natural order:
  1. self_intro
  2. one or more technical sections, where each technical section is named after a skill
  3. behavioural_cultural
- behavioural and cultural must be combined into one final section named exactly "behavioural_cultural".
- Always include the behavioural_cultural section, even for very short interviews.
- The behavioural_cultural section must always receive enough time for the bot to ask at least one meaningful behavioural or cultural-fit question.
- For extremely short interviews, allocate a very small but non-zero amount of time to behavioural_cultural, such as 0.2 to 0.5 minutes, so the section is still represented and can be executed.
- The self_intro section should be short and should not consume time that is needed for technical assessment.
- First reserve the minimum useful non-technical time for self_intro and behavioural_cultural.
- After reserving minimum non-technical time, allocate the remaining time to technical sections.
- Technical sections must receive more total time than self_intro and behavioural_cultural combined whenever the interview duration makes this possible.
- For technical roles, the total technical time should normally be the majority of the interview.
- Allocate technical time proportionally by priority_score, adjusted by focus_areas weight_override when provided.
- Do not drop important technical skills unnecessarily.
- Prefer covering more relevant JD skills when each can still receive enough time for at least one meaningful technical question.
- Only drop a skill from interview_plan.sections when it is clearly lower-priority, nice-to-have, weakly mentioned, or impossible to assess meaningfully within the available time.
- Skills with high priority_score, strong JD evidence, or Expert depth_required should be preserved whenever possible.
- If time is constrained, reduce allocation to lower-priority skills before completely dropping them.
- If time is too small for all skills, drop lower-priority or nice-to-have skills from interview_plan.sections, but keep them in jd_analysis.skills.
- For 2-4 minute interviews: include self_intro, behavioural_cultural, and at least one top technical skill. If possible, include a second high-priority technical skill only if both technical skills can still be meaningfully assessed.
- For 5-9 minute interviews: include self_intro, behavioural_cultural, and cover the top 2-3 technical skills when possible.
- For 10-19 minute interviews: include self_intro, behavioural_cultural, and cover the top 3-5 technical skills when possible.
- For 20-45 minute interviews: include self_intro, behavioural_cultural, and cover the top 4-7 technical skills when possible.
- For longer interviews: include additional relevant skills when each receives enough time to be meaningfully assessed.
- Avoid unnecessary fragmentation, but do not over-prune skills. A skill should only be omitted if its allocated time would be too small to support a real answer.
- Section order should be natural: short self_intro first, technical sections by importance, then behavioural_cultural.
- allocated_mins can use one decimal place. The sum of allocated_mins MUST equal total_mins exactly.
- For self_intro and behavioural_cultural sections, skill MUST be null.
- For technical sections, skill MUST be the exact skill name from jd_analysis.skills.
- For technical sections, section_name MUST be the exact same value as skill.
- For self_intro and behavioural_cultural sections, priority_score MUST be null.
- For technical sections, priority_score MUST match the corresponding skill's priority_score from jd_analysis.skills.
- expected_signals should list 2-4 concise signals the bot should listen for in that section.
- For behavioural_cultural, expected_signals must include both behavioural signals and cultural/team-fit signals.
- Do not include max_questions, max_questions_per_section, max_followups_per_question, or any other question-count control fields. The interview bot will dynamically decide question count and follow-ups during execution.

Return only raw JSON. No markdown, comments, or prose outside JSON.
The JSON must strictly match this schema:
{
  "jd_analysis": {
    "inferred_role_title": "string",
    "seniority_level": "Junior | Mid-level | Senior",
    "difficulty": "Low | Medium | High",
    "skills": [
      {
        "skill": "string",
        "priority_score": 1.0,
        "depth_required": "Awareness | Intermediate | Expert",
        "reasoning": "string with JD evidence for the score"
      }
    ],
    "behavioural_signals": ["string"]
  },
  "interview_plan": {
    "total_mins": 30,
    "sections": [
      {
        "section_name": "self_intro | exact technical skill name | behavioural_cultural",
        "skill": null,
        "allocated_mins": 1.0,
        "priority_score": null,
        "expected_signals": ["string"]
      }
    ]
  }
}
""".strip()


async def run_jd_analysis_and_interview_plan(
    jd_text: str,
    duration_mins: int,
    focus_areas: list[FocusAreaOverride] | None,
    groq_client: AsyncGroq,
) -> JDAnalysisAndInterviewPlan:
    """Call Groq once to produce both JD analysis and the executable interview plan."""
    import json

    user_prompt = (
        f"Interview duration: {duration_mins} minutes\n"
        f"Focus area overrides as JSON: {_focus_areas_for_prompt(focus_areas)}\n\n"
        "Analyze this Job Description and generate the combined output:\n"
        f"{jd_text}"
    )

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            completion = await groq_client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": _combined_analysis_system_prompt()},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw_content = completion.choices[0].message.content or ""
            parsed_json = json.loads(raw_content)
            combined = JDAnalysisAndInterviewPlan.model_validate(parsed_json)
            normalized_plan = _normalize_interview_plan(
                combined.interview_plan,
                duration_mins,
            )
            return JDAnalysisAndInterviewPlan(
                jd_analysis=combined.jd_analysis,
                interview_plan=normalized_plan,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == 0:
                logger.warning(
                    "Combined JD analysis/interview-plan attempt 1 failed, retrying once: %s",
                    exc,
                )
                await asyncio.sleep(1.5)
                continue

    logger.exception("Groq combined JD analysis/interview-plan failed after retry")
    raise BadGatewayException(
        f"Failed to analyze job description and generate interview plan: {last_exc}"
    ) from last_exc
