"""Utility helpers for JD parsing and analysis."""

import asyncio
import logging
import os
import random
import tempfile

from fastapi.concurrency import run_in_threadpool
from groq import AsyncGroq
from llama_parse import LlamaParse

from src.config.settings import settings
from src.core.exceptions import (
    BadGatewayException,
    BadRequestException,
    InternalServerException,
)
from src.schemas.assessment import (
    FocusAreaOverride,
    InterviewPlan,
    InterviewSection,
    JDAnalysis,
    SkillPriority,
)

logger = logging.getLogger(__name__)


async def parse_pdf_jd(file_bytes: bytes, filename: str) -> str:
    """Parse PDF job description using LlamaParse in a background thread."""
    api_key = settings.LLAMA_CLOUD_API_KEY
    if not api_key:
        raise BadRequestException(
            "LlamaParse key not configured. Please paste the job description text instead."
        )

    suffix = os.path.splitext(filename)[1]
    tmp_path = ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        parser = LlamaParse(api_key=api_key, result_type="markdown")
        extra_info = {"file_name": filename}

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                documents = await asyncio.wait_for(
                    run_in_threadpool(
                        parser.load_data, tmp_path, extra_info=extra_info
                    ),
                    timeout=60,
                )
                return "\n".join(doc.text for doc in documents)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt == 0:
                    logger.warning(
                        "LlamaParse attempt 1 failed for %s, retrying once: %s",
                        filename,
                        exc,
                    )
                    continue
        raise last_exc  # type: ignore[misc]
    except Exception as exc:
        logger.exception("Failed to parse PDF JD using LlamaParse")
        raise InternalServerException(
            f"Error parsing job description file: {exc}"
        ) from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def generate_interview_plan(
    duration_mins: int,
    skills: list[SkillPriority],
    focus_areas: list[FocusAreaOverride] | None,
) -> InterviewPlan:
    """Create the base InterviewPlan with sections allocated proportionally based on priority weightings.

    The number of "primary" skills considered for proportional allocation
    scales with the available interview time — roughly one skill per
    AVG_MINUTES_PER_SKILL minutes of remaining time (e.g. ~8 skills for a
    45-minute interview), clamped to a sensible range.

    Skills beyond this primary set are not entirely discarded. If, after
    allocating time to the primary skills, any time is left over (most
    commonly because a low-weight primary skill's proportional share fell
    below MIN_SECTION_MINS and was dropped), that leftover time is offered
    to a single randomly-chosen "minor" skill as a short bonus section —
    enough for roughly one question. If there is no meaningful leftover,
    or there are no minor skills, no bonus section is added.
    """
    fixed_mins = 10.0
    if duration_mins <= fixed_mins:
        raise BadRequestException(
            f"Interview duration must be greater than {int(fixed_mins)} minutes to accommodate technical evaluation."
        )

    remaining_mins = float(duration_mins - fixed_mins)
    overrides = (
        {fa.skill: fa.weight_override for fa in focus_areas} if focus_areas else {}
    )

    # CHANGED: max primary skills now scales with available time instead of
    # a fixed value. AVG_MINUTES_PER_SKILL is calibrated so that a
    # 45-minute interview (remaining_mins = 35) yields 8 primary skills:
    # round(35 / 4.5) = 8.
    AVG_MINUTES_PER_SKILL = 4.5
    MIN_PRIMARY_SKILLS = 3
    MAX_PRIMARY_SKILLS = 10
    MIN_SECTION_MINS = 2.0
    BONUS_MIN_MINS = 1.0
    BONUS_SECTION_CAP_MINS = 5.0

    max_primary_skills = max(
        MIN_PRIMARY_SKILLS,
        min(MAX_PRIMARY_SKILLS, round(remaining_mins / AVG_MINUTES_PER_SKILL)),
    )

    # Sort all skills by priority once. The first max_primary_skills are
    # "primary" (proportional allocation); the rest are "minor" (eligible
    # only for the leftover-time bonus section).
    sorted_skills = sorted(skills, key=lambda s: s.priority_score, reverse=True)
    primary_skills = sorted_skills[:max_primary_skills]
    minor_skills = sorted_skills[max_primary_skills:]

    tech_skills = []
    for skill in primary_skills:
        weight = float(overrides.get(skill.skill, skill.priority_score))
        tech_skills.append((skill.skill, weight, skill.priority_score))

    total_weight = sum(weight for _, weight, _ in tech_skills)
    tech_sections = []
    allocated_total = 0.0

    if total_weight > 0:
        for skill_name, weight, original_priority in tech_skills:
            allocated = round(remaining_mins * (weight / total_weight), 1)

            if allocated < MIN_SECTION_MINS:
                logger.info(
                    "Skipping primary skill '%s' from interview plan — allocated %.1f min is below the %.1f min threshold",
                    skill_name,
                    allocated,
                    MIN_SECTION_MINS,
                )
                continue

            tech_sections.append(
                InterviewSection(
                    section_name=skill_name,
                    skill=skill_name,
                    allocated_mins=allocated,
                    priority_score=original_priority,
                )
            )
            allocated_total += allocated

    # CHANGED: any time not used by the kept primary sections (e.g. because
    # one or more low-weight primary skills were dropped, or due to rounding)
    # becomes "leftover" time that can be offered to a minor skill.
    leftover_mins = round(remaining_mins - allocated_total, 1)

    if minor_skills and leftover_mins >= BONUS_MIN_MINS:
        # Dynamic: randomly pick one minor skill each time the plan is
        # generated, so repeated runs for the same JD don't always favour
        # the same "extra" skill.
        bonus_skill = random.choice(minor_skills)
        bonus_allocated = min(leftover_mins, BONUS_SECTION_CAP_MINS)

        logger.info(
            "Allocating %.1f min bonus section to minor skill '%s' (1 question) from leftover time",
            bonus_allocated,
            bonus_skill.skill,
        )

        tech_sections.append(
            InterviewSection(
                section_name=f"bonus_{bonus_skill.skill}",
                skill=bonus_skill.skill,
                allocated_mins=bonus_allocated,
                priority_score=bonus_skill.priority_score,
            )
        )

    tech_sections.sort(key=lambda section: section.priority_score or 0.0, reverse=True)

    sections = [
        InterviewSection(
            section_name="self_intro",
            skill=None,
            allocated_mins=2.0,
            priority_score=None,
        )
    ]
    sections.extend(tech_sections)
    sections.extend(
        [
            InterviewSection(
                section_name="behavioural",
                skill=None,
                allocated_mins=4.0,
                priority_score=None,
            ),
            InterviewSection(
                section_name="cultural",
                skill=None,
                allocated_mins=4.0,
                priority_score=None,
            ),
        ]
    )

    return InterviewPlan(total_mins=duration_mins, sections=sections)


async def run_jd_analysis(jd_text: str, groq_client: AsyncGroq) -> JDAnalysis:
    """Call Groq to analyze JD text and return structured JD analysis."""
    import json

    system_prompt = (
        "You are an expert recruiter and talent agent. Analyze the provided Job Description (JD) "
        "and extract structured skills, seniority level, and traits.\n\n"
        "When assigning priority_score (1.0 to 10.0) for each skill, base it on these signals:\n"
        "- Positioning: skills mentioned early or in the role summary are higher priority than "
        "skills mentioned only in a bullet list near the bottom.\n"
        "- Frequency: a skill referenced multiple times across different sections (summary, "
        "responsibilities, requirements) is higher priority than one mentioned once.\n"
        "- Language strength: phrases like 'must have', 'required', 'strong expertise in', "
        "'deep understanding of' indicate high priority; phrases like 'familiarity with', "
        "'exposure to', 'nice to have', 'a plus' indicate low priority.\n"
        "- Responsibility coupling: if a core job responsibility is directly tied to a skill "
        "(e.g. 'you will design and own the database architecture' for SQL/Postgres), that "
        "skill should score higher than a skill only mentioned as part of the general tech stack.\n\n"
        "You MUST respond with a JSON object that strictly adheres to the following schema:\n"
        "{\n"
        '  "inferred_role_title": "string (name of the role, e.g. Backend Developer)",\n'
        '  "seniority_level": "string (Junior, Mid-level, or Senior)",\n'
        '  "difficulty": "string (Low, Medium, or High)",\n'
        '  "skills": [\n'
        "    {\n"
        '      "skill": "string (specific skill name, e.g. Python, React, SQL)",\n'
        '      "priority_score": float (relevance/priority score from 1.0 to 10.0 using the signals above)\n'
        '      "depth_required": "string (Awareness, Intermediate, or Expert)",\n'
        '      "reasoning": "string (cite which of the above signals support this score, with evidence from the JD)"\n'
        "    }\n"
        "  ],\n"
        '  "behavioural_signals": [\n'
        '    "string (key behavioural indicator or soft skill required, e.g. Mentorship, Autonomy)"\n'
        "  ]\n"
        "}\n"
        "Only return raw JSON. Do not include markdown code block formatting (such as ```json) or explanation."
    )

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            completion = await groq_client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Analyze this Job Description:\n{jd_text}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw_content = completion.choices[0].message.content or ""
            parsed_json = json.loads(raw_content)
            return JDAnalysis.model_validate(parsed_json)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == 0:
                logger.warning("JD analysis attempt 1 failed, retrying once: %s", exc)
                await asyncio.sleep(1.5)
                continue

    logger.exception("Groq JD analysis failed after retry")
    raise BadGatewayException(
        f"Failed to analyze job description: {last_exc}"
    ) from last_exc
