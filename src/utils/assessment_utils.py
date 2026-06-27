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
    BehaviouralCulturalSection,
    FocusAreaOverride,
    InterviewPlan,
    JDAnalysis,
    JDAnalysisAndInterviewPlan,
    SelfIntroSection,
    TechnicalInterviewSection,
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


BEHAVIOURAL_CULTURAL_SECTION_KEYS = {
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


def _technical_signal_map(plan: InterviewPlan) -> dict[str, list[str]]:
    signals: dict[str, list[str]] = {}
    for section in plan.sections:
        if not isinstance(section, TechnicalInterviewSection):
            continue
        key = _section_key(section.skill)
        signals[key] = [
            signal.strip()
            for signal in section.expected_signals
            if signal and signal.strip()
        ][:4]
    return signals


def _behavioural_signals(plan: InterviewPlan, jd_analysis: JDAnalysis) -> list[str]:
    generated: list[str] = []
    for section in plan.sections:
        if (
            isinstance(section, BehaviouralCulturalSection)
            or _section_key(section.section_name) in BEHAVIOURAL_CULTURAL_SECTION_KEYS
        ):
            generated.extend(getattr(section, "expected_signals", []))

    generated.extend(jd_analysis.behavioural_signals)
    generated.extend(
        [
            "Evidence-based collaboration and conflict resolution",
            "Ownership, adaptability, and clear communication",
            "Alignment with team culture and working norms",
        ]
    )

    unique: list[str] = []
    seen: set[str] = set()
    for signal in generated:
        cleaned = str(signal).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            unique.append(cleaned)
            seen.add(key)

    selected = unique[:4]
    has_culture_signal = any(
        marker in signal.casefold()
        for signal in selected
        for marker in ("culture", "team fit", "working norm")
    )
    if not has_culture_signal:
        culture_signal = "Alignment with team culture and working norms"
        if len(selected) >= 4:
            selected[-1] = culture_signal
        else:
            selected.append(culture_signal)
    return selected


def _technical_expected_signals(
    skill: str,
    signal_map: dict[str, list[str]],
) -> list[str]:
    generated = list(signal_map.get(_section_key(skill)) or [])
    generated.extend(
        [
            f"Understanding of core {skill} concepts",
            f"Ability to apply {skill} in practical role-relevant scenarios",
        ]
    )
    unique: list[str] = []
    seen: set[str] = set()
    for signal in generated:
        cleaned = str(signal).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            unique.append(cleaned)
            seen.add(key)
    return unique[:4]


def _focus_weights(
    focus_areas: list[FocusAreaOverride] | None,
) -> dict[str, float]:
    return {
        _section_key(item.skill): float(item.weight_override)
        for item in focus_areas or []
    }


def _allocate_technical_tenths(
    weights: list[float],
    total_tenths: int,
) -> list[int]:
    """Maximize covered skills, then distribute remaining time by weight."""

    minimum_tenths = 5
    allocations = [minimum_tenths for _ in weights]
    remaining = total_tenths - sum(allocations)
    if remaining <= 0:
        return allocations

    normalized_weights = [max(0.0, weight) for weight in weights]
    weight_total = sum(normalized_weights)
    if weight_total <= 0:
        normalized_weights = [1.0 for _ in weights]
        weight_total = float(len(weights))

    exact_shares = [remaining * weight / weight_total for weight in normalized_weights]
    whole_shares = [int(share) for share in exact_shares]
    allocations = [
        allocation + share
        for allocation, share in zip(allocations, whole_shares, strict=True)
    ]

    remainder = remaining - sum(whole_shares)
    ranked_remainders = sorted(
        range(len(weights)),
        key=lambda index: (
            exact_shares[index] - whole_shares[index],
            normalized_weights[index],
            -index,
        ),
        reverse=True,
    )
    for index in ranked_remainders[:remainder]:
        allocations[index] += 1
    return allocations


def _normalize_interview_plan(
    plan: InterviewPlan,
    duration_mins: int,
    jd_analysis: JDAnalysis,
    focus_areas: list[FocusAreaOverride] | None,
) -> InterviewPlan:
    """Build the final plan deterministically from JD priorities."""

    total_tenths = int(duration_mins * 10)
    intro_tenths = 10
    behavioural_tenths = int(duration_mins)
    technical_tenths = total_tenths - intro_tenths - behavioural_tenths
    if technical_tenths < 5:
        raise ValueError(
            "Interview duration leaves less than 30 seconds for technical assessment."
        )

    focus_weights = _focus_weights(focus_areas)
    signal_map = _technical_signal_map(plan)

    unique_skills: list[tuple[int, str, float]] = []
    seen_skills: set[str] = set()
    for index, item in enumerate(jd_analysis.skills):
        key = _section_key(item.skill)
        if key in seen_skills:
            continue
        seen_skills.add(key)
        effective_weight = focus_weights.get(key, float(item.priority_score))
        unique_skills.append((index, item.skill, effective_weight))

    if not unique_skills:
        raise ValueError("JD analysis returned no technical skills.")

    maximum_skill_count = max(1, technical_tenths // 5)
    selected_skills = sorted(
        unique_skills,
        key=lambda item: (-item[2], item[0]),
    )[:maximum_skill_count]
    allocations = _allocate_technical_tenths(
        [item[2] for item in selected_skills],
        technical_tenths,
    )

    technical_sections: list[TechnicalInterviewSection] = []
    for (_, skill, _), allocated_tenths in zip(
        selected_skills,
        allocations,
        strict=True,
    ):
        technical_sections.append(
            TechnicalInterviewSection(
                section_name=skill,
                skill=skill,
                allocated_mins=round(allocated_tenths / 10.0, 1),
                expected_signals=_technical_expected_signals(skill, signal_map),
            )
        )

    return InterviewPlan(
        total_mins=duration_mins,
        inferred_difficulty=jd_analysis.inferred_difficulty,
        sections=[
            SelfIntroSection(allocated_mins=1.0),
            *technical_sections,
            BehaviouralCulturalSection(
                allocated_mins=round(behavioural_tenths / 10.0, 1),
                expected_signals=_behavioural_signals(plan, jd_analysis),
            ),
        ],
    )


def _focus_areas_for_prompt(focus_areas: list[FocusAreaOverride] | None) -> str:
    if not focus_areas:
        return "[]"
    import json

    return json.dumps([item.model_dump() for item in focus_areas], ensure_ascii=True)


def _combined_analysis_system_prompt() -> str:
    return """
You are an expert technical recruiter and structured interview architect. Analyze
the supplied job description and return one JSON object containing `jd_analysis`
and `interview_plan`. The output is validated by a strict schema and stored
directly in a database, so never add undeclared fields.

REQUIRED WORK ORDER
1. Infer the role difficulty from the JD.
2. Extract distinct, interviewable technical skills and score their importance.
3. Extract behavioural and team-culture signals.
4. Copy the exact inferred difficulty into the interview plan.
5. Build a time plan that maximizes meaningful technical coverage.

INFERRED DIFFICULTY
Use exactly one of:
- "junior level"
- "mid-level"
- "senior level"

Years-of-experience rules:
- A role requiring 0-2 years is always "junior level".
- Intern, graduate, trainee, entry-level, junior, and associate roles are normally
  "junior level", unless the JD clearly contradicts the label.
- A role requiring roughly 3-6 years is normally "mid-level".
- Requirements such as 3+ years or 5+ years are "mid-level" by default when the
  person independently delivers features or services but does not own broad
  architecture or organizational technical direction.
- A role requiring 7+ years is normally "senior level".
- Senior, lead, staff, principal, architect, or engineering-manager roles are
  "senior level" when responsibilities include architecture, production strategy,
  cross-team ownership, mentoring, technical leadership, scaling, security, or
  high-impact design decisions.
- If an experience range crosses bands, use the responsibility level to decide.
  Example: 5-8 years with feature ownership is mid-level; 5-8 years with system
  architecture, mentoring, and cross-team leadership is senior-level.
- If years are absent, infer from the title and responsibilities. Do not inflate a
  role to senior merely because its technology is sophisticated.
- Prefer the explicit minimum required experience over optional/preferred
  experience. Do not use the candidate's experience; analyze only the JD.

JD SKILL EXTRACTION AND PRIORITY
- Include concrete technical skills that can be assessed in an interview:
  languages, frameworks, databases, cloud/platform tools, architecture domains,
  engineering practices, and directly relevant technical concepts.
- Consolidate aliases and duplicates into one clear skill name.
- Do not put communication, teamwork, leadership, ownership, or culture-fit traits
  in `skills`; place those in `behavioural_signals`.
- Keep relevant nice-to-have technical skills in `jd_analysis.skills`; the
  deterministic planner may omit only those that cannot receive 30 seconds.
- Score `priority_score` from 1.0 to 10.0:
  * 9.0-10.0: indispensable core competency repeatedly tied to primary duties.
  * 7.0-8.9: strongly required and regularly used in the role.
  * 5.0-6.9: relevant supporting competency or moderately emphasized requirement.
  * 3.0-4.9: useful secondary or preferred competency.
  * 1.0-2.9: weakly mentioned, optional, or peripheral competency.
- Raise priority for explicit must-have language, repetition, placement in core
  responsibilities, ownership, and direct coupling to daily work.
- Lower priority for "nice to have", "bonus", "exposure", broad stack lists, or
  incidental tooling.
- `reasoning` must briefly cite JD evidence and explain the score. Do not invent
  requirements.
- Do not output `depth_required`, `inferred_role_title`, `seniority_level`, or a
  separate `difficulty` field.

INTERVIEW PLAN — HARD RULES
- `total_mins` must exactly equal the supplied duration.
- `inferred_difficulty` must exactly equal `jd_analysis.inferred_difficulty`.
- Sections must be ordered as:
  1. `self_intro`
  2. technical skill sections in descending effective importance
  3. `behavioural_cultural`
- `self_intro` is always exactly 1.0 minute, has `skill: null`, and must NOT contain
  `expected_signals`.
- `behavioural_cultural` is always exactly 10 percent of total interview time.
  For 15 minutes it is exactly 1.5 minutes; for 30 minutes it is exactly 3.0.
- Allocate every remaining minute to technical skills.
- Technical time is weighted by the matching JD `priority_score`. When a matching
  `focus_areas.weight_override` exists, use it as that skill's effective weight.
- Include as many JD technical skills as possible. Every included technical skill
  must receive at least 0.5 minute. Drop a skill only when available technical
  time is too low to give it 0.5 minute; drop the lowest effective-weight skill
  first. Never impose an arbitrary skill-count cap.
- A technical section's `section_name` and `skill` must both exactly match the
  corresponding `jd_analysis.skills[].skill`.
- Technical and behavioural sections need 2-4 concise, observable
  `expected_signals`. Signals should describe evidence to listen for, not questions.
- Behavioural/cultural signals must cover both work behaviour (ownership,
  collaboration, conflict handling, adaptability, communication) and alignment
  with team culture or working norms.
- Do not include `priority_score` in interview-plan sections. Priority lives only
  in `jd_analysis`.
- Do not include question-count limits, follow-up limits, depth fields, role-title
  fields, or any other undeclared fields.
- Use one decimal place for section minutes. Allocations must sum exactly to
  `total_mins`.

ONE-SHOT EXAMPLE
Example input summary: 15-minute Python backend interview; JD asks for 0-2 years,
emphasizes Python, SQL, database foundations, Git, and a Python web framework.
Therefore the inferred difficulty is junior level. A valid output is:
{
  "jd_analysis": {
    "inferred_difficulty": "junior level",
    "skills": [
      {
        "skill": "Python",
        "priority_score": 9.5,
        "reasoning": "Python is the primary required language and is central to the listed backend responsibilities."
      },
      {
        "skill": "SQL",
        "priority_score": 8.0,
        "reasoning": "The JD explicitly requires writing SQL queries for application data access."
      },
      {
        "skill": "Database Foundations",
        "priority_score": 7.0,
        "reasoning": "Database concepts are required for schema and persistence work."
      },
      {
        "skill": "Git",
        "priority_score": 4.0,
        "reasoning": "Git is required as a supporting collaboration tool."
      },
      {
        "skill": "Python Web Framework",
        "priority_score": 4.0,
        "reasoning": "Framework familiarity is requested but no specific framework is emphasized."
      }
    ],
    "behavioural_signals": [
      "Collaborative mindset",
      "Strong problem-solving skills",
      "Motivation to learn"
    ]
  },
  "interview_plan": {
    "total_mins": 15,
    "inferred_difficulty": "junior level",
    "sections": [
      {
        "section_name": "self_intro",
        "skill": null,
        "allocated_mins": 1.0
      },
      {
        "section_name": "Python",
        "skill": "Python",
        "allocated_mins": 4.1,
        "expected_signals": [
          "Understanding of Python fundamentals",
          "Ability to write clean and readable code"
        ]
      },
      {
        "section_name": "SQL",
        "skill": "SQL",
        "allocated_mins": 3.5,
        "expected_signals": [
          "Understanding of SQL query fundamentals",
          "Ability to construct role-relevant queries"
        ]
      },
      {
        "section_name": "Database Foundations",
        "skill": "Database Foundations",
        "allocated_mins": 3.1,
        "expected_signals": [
          "Understanding of relational database concepts",
          "Ability to explain basic schema decisions"
        ]
      },
      {
        "section_name": "Git",
        "skill": "Git",
        "allocated_mins": 0.9,
        "expected_signals": [
          "Understanding of core Git concepts",
          "Ability to use Git in a collaborative workflow"
        ]
      },
      {
        "section_name": "Python Web Framework",
        "skill": "Python Web Framework",
        "allocated_mins": 0.9,
        "expected_signals": [
          "Understanding of web framework fundamentals",
          "Ability to apply a Python framework to a simple backend task"
        ]
      },
      {
        "section_name": "behavioural_cultural",
        "skill": null,
        "allocated_mins": 1.5,
        "expected_signals": [
          "Collaborative mindset",
          "Evidence-based problem solving",
          "Motivation to learn",
          "Alignment with team culture and working norms"
        ]
      }
    ]
  }
}

Return only raw JSON with no markdown, comments, analysis, or surrounding prose.
The exact permitted structure is:
{
  "jd_analysis": {
    "inferred_difficulty": "junior level",
    "skills": [
      {
        "skill": "string",
        "priority_score": 1.0,
        "reasoning": "string"
      }
    ],
    "behavioural_signals": ["string"]
  },
  "interview_plan": {
    "total_mins": 15,
    "inferred_difficulty": "junior level",
    "sections": [
      {
        "section_name": "self_intro",
        "skill": null,
        "allocated_mins": 1.0
      },
      {
        "section_name": "exact technical skill name",
        "skill": "exact technical skill name",
        "allocated_mins": 1.0,
        "expected_signals": ["string", "string"]
      },
      {
        "section_name": "behavioural_cultural",
        "skill": null,
        "allocated_mins": 1.5,
        "expected_signals": ["string", "string"]
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
                combined.jd_analysis,
                focus_areas,
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
