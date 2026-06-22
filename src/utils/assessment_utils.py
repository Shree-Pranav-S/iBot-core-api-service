"""Utility helpers for JD parsing and analysis."""

import asyncio
import logging

from fastapi.concurrency import run_in_threadpool
from groq import AsyncGroq

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


def generate_interview_plan(
    duration_mins: int,
    skills: list[SkillPriority],
    focus_areas: list[FocusAreaOverride] | None,
) -> InterviewPlan:
    """Create the base InterviewPlan with sections allocated proportionally based on priority weightings.

    The plan guarantees that the sum of allocated durations exactly matches
    the total interview duration.

    Non-technical sections (self-introduction, behavioral, cultural) scale
    dynamically with the total interview duration to keep the balance natural:
    - self_intro: 1.0 min for short sessions, else ~5% of duration (capped at 5 mins)
    - behavioral: ~10% of duration (between 2 and 15 mins)
    - cultural: ~10% of duration (between 2 and 15 mins)

    Technical skills are filtered and allocated iteratively to ensure no active
    technical section falls below a minimum threshold (e.g. 3.0 mins), preventing
    highly fragmented interviews. Any leftover time is offered to the highest-priority
    minor skill as a bonus section, with any final discrepancy resolved by normalization.
    """
    if duration_mins == 5:
        sorted_skills = sorted(skills, key=lambda s: s.priority_score, reverse=True)
        tech_skill = sorted_skills[0].skill if sorted_skills else "Technical"
        tech_priority = sorted_skills[0].priority_score if sorted_skills else 10.0
        return InterviewPlan(
            total_mins=5,
            sections=[
                InterviewSection(
                    section_name="self_intro",
                    skill=None,
                    allocated_mins=1.0,
                    priority_score=None,
                ),
                InterviewSection(
                    section_name=tech_skill,
                    skill=tech_skill,
                    allocated_mins=2.0,
                    priority_score=tech_priority,
                ),
                InterviewSection(
                    section_name="behavioural",
                    skill=None,
                    allocated_mins=1.0,
                    priority_score=None,
                ),
                InterviewSection(
                    section_name="cultural",
                    skill=None,
                    allocated_mins=1.0,
                    priority_score=None,
                ),
            ],
        )

    fixed_mins = 5.0
    if duration_mins < fixed_mins:
        raise BadRequestException(
            f"Interview duration must be at least {int(fixed_mins)} minutes."
        )

    # 1. Dynamic Scaling of Non-Technical Sections
    # self_intro: 1.0 min for < 15 mins, otherwise ~5% of total time, max 5.0 mins
    if duration_mins < 15:
        intro_mins = 1.0
    else:
        intro_mins = max(1.0, min(5.0, round(duration_mins * 0.05, 1)))

    # behavioural & cultural: ~10% each, min 2.0 mins, max 15.0 mins
    behavioral_mins = max(2.0, min(15.0, round(duration_mins * 0.10, 1)))
    cultural_mins = max(2.0, min(15.0, round(duration_mins * 0.10, 1)))

    non_tech_mins = round(intro_mins + behavioral_mins + cultural_mins, 1)
    remaining_mins = max(0.0, round(duration_mins - non_tech_mins, 1))

    # Focus area overrides mapping
    overrides = (
        {fa.skill: fa.weight_override for fa in focus_areas} if focus_areas else {}
    )

    # 2. Dynamic Primary Skills Cap to avoid fragmentation
    # Target 5 minutes per primary technical skill.
    TARGET_MINS_PER_SKILL = 5.0
    MIN_PRIMARY_SKILLS = 2
    MAX_PRIMARY_SKILLS = 15
    MIN_TECH_SECTION_MINS = 3.0

    max_primary_skills = max(
        MIN_PRIMARY_SKILLS,
        min(
            MAX_PRIMARY_SKILLS,
            int(remaining_mins // TARGET_MINS_PER_SKILL) if remaining_mins > 0 else 0,
        ),
    )

    # Sort all skills by priority score descending
    sorted_skills = sorted(skills, key=lambda s: s.priority_score, reverse=True)
    primary_skills = sorted_skills[:max_primary_skills]
    minor_skills = sorted_skills[max_primary_skills:]

    # Iterative allocation to filter out sub-threshold sections and redistribute time
    active_primary = list(primary_skills)
    tech_allocations: list[tuple[str, float, float]] = []

    while active_primary:
        # Build active skills weights
        tech_skills_weights = []
        for skill in active_primary:
            raw_weight = overrides.get(skill.skill, skill.priority_score)
            weight = float(raw_weight) if raw_weight is not None else 5.0
            tech_skills_weights.append((skill.skill, weight, skill.priority_score))

        total_weight = sum(w for _, w, _ in tech_skills_weights)
        if total_weight <= 0:
            break

        # Calculate proportional allocations
        temp_allocations = []
        has_sub_threshold = False
        lowest_sub_skill_idx = -1
        lowest_sub_priority = float("inf")

        for i, (skill_name, weight, priority) in enumerate(tech_skills_weights):
            allocated = round(remaining_mins * (weight / total_weight), 1)
            temp_allocations.append((skill_name, allocated, priority))

            # Track the lowest priority skill that falls below the threshold
            if allocated < MIN_TECH_SECTION_MINS:
                has_sub_threshold = True
                if priority < lowest_sub_priority:
                    lowest_sub_priority = priority
                    lowest_sub_skill_idx = i

        if not has_sub_threshold:
            # All active sections satisfy the minimum threshold
            tech_allocations = temp_allocations
            break
        else:
            # Remove the lowest-priority sub-threshold skill from primary set,
            # push it to minor skills, and re-allocate in the next iteration
            removed_skill = active_primary.pop(lowest_sub_skill_idx)
            minor_skills.append(removed_skill)
            # Sort minor skills by priority again
            minor_skills.sort(key=lambda s: s.priority_score, reverse=True)

    # Build primary technical sections
    tech_sections: list[InterviewSection] = []
    allocated_total = 0.0
    for skill_name, allocated, priority in tech_allocations:
        tech_sections.append(
            InterviewSection(
                section_name=skill_name,
                skill=skill_name,
                allocated_mins=allocated,
                priority_score=priority,
            )
        )
        allocated_total += allocated

    # 3. Priority-Based Leftover Allocation to Minor Skills
    leftover_mins = round(remaining_mins - allocated_total, 1)
    BONUS_MIN_MINS = 3.0
    BONUS_SECTION_CAP_MINS = 5.0

    if minor_skills and leftover_mins >= BONUS_MIN_MINS:
        # Pick the highest-priority minor skill instead of random
        bonus_skill = minor_skills[0]
        bonus_allocated = min(leftover_mins, BONUS_SECTION_CAP_MINS)

        logger.info(
            "Allocating %.1f min bonus section to highest-priority minor skill '%s' from leftover time",
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
        allocated_total += bonus_allocated

    # Sort tech sections by priority descending (bonus sections have priority scores too)
    tech_sections.sort(key=lambda s: s.priority_score or 0.0, reverse=True)

    # Build final sections list
    sections = [
        InterviewSection(
            section_name="self_intro",
            skill=None,
            allocated_mins=intro_mins,
            priority_score=None,
        )
    ]
    sections.extend(tech_sections)
    sections.extend(
        [
            InterviewSection(
                section_name="behavioural",
                skill=None,
                allocated_mins=behavioral_mins,
                priority_score=None,
            ),
            InterviewSection(
                section_name="cultural",
                skill=None,
                allocated_mins=cultural_mins,
                priority_score=None,
            ),
        ]
    )

    # 4. Zero-Waste Time Normalization
    # Ensure the sum of all sections matches duration_mins exactly
    total_allocated = round(sum(s.allocated_mins for s in sections), 1)
    discrepancy = round(duration_mins - total_allocated, 1)

    if discrepancy != 0.0:
        # Find the largest tech section to adjust
        tech_indices = [
            i
            for i, s in enumerate(sections)
            if s.skill is not None and not s.section_name.startswith("bonus_")
        ]
        if tech_indices:
            # Sort tech indices by allocated mins descending, pick the largest
            tech_indices.sort(
                key=lambda idx: sections[idx].allocated_mins, reverse=True
            )
            target_idx = tech_indices[0]
            new_allocated = round(sections[target_idx].allocated_mins + discrepancy, 1)
            # Ensure it doesn't fall below absolute min
            sections[target_idx].allocated_mins = max(
                MIN_TECH_SECTION_MINS, new_allocated
            )
        else:
            # Fallback to adjusting behavioural section if no tech sections exist
            for i, s in enumerate(sections):
                if s.section_name == "behavioural":
                    sections[i].allocated_mins = round(
                        s.allocated_mins + discrepancy, 1
                    )
                    break

    # Re-verify and final check
    for s in sections:
        s.allocated_mins = round(s.allocated_mins, 1)

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
