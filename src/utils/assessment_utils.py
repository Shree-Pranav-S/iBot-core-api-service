"""Utility helpers for JD parsing and analysis."""

import asyncio
import json
import logging
import re

from fastapi.concurrency import run_in_threadpool
from groq import AsyncGroq
from groq.types.chat import ChatCompletionMessageParam
from groq.types.chat.completion_create_params import (
    ResponseFormatResponseFormatJsonSchema,
)
from pydantic import BaseModel, ValidationError

from src.config.settings import settings
from src.core.exceptions import JdParseFailedException, LlmAnalysisFailedException
from src.schemas.assessment import (
    FocusAreaOverride,
    JDAnalysisAndInterviewPlan,
)

logger = logging.getLogger(__name__)

_MAX_JD_CHARS_FOR_ANALYSIS = 8000


def _structured_response_format(
    response_model: type[BaseModel],
) -> ResponseFormatResponseFormatJsonSchema:
    """Build Groq strict Structured Outputs configuration from a Pydantic model."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_model.__name__.lower(),
            "strict": True,
            "schema": response_model.model_json_schema(),
        },
    }


def _min_minutes_per_skill(total_mins: int, technical_minutes: float) -> float:
    """Return a practical minimum depth for each technical skill section."""
    if technical_minutes <= 0:
        return 0.0
    if total_mins <= 5:
        return 1.5
    if total_mins <= 10:
        return 2.0
    if total_mins <= 15:
        return 2.0
    if total_mins <= 30:
        return 2.5
    return 3.0


def _estimated_technical_minutes(total_mins: int) -> float:
    """Approximate technical time after intro and behavioural sections."""
    return max(total_mins * 0.8, 0.0)


def _truncate_jd_text(jd_text: str, max_chars: int = _MAX_JD_CHARS_FOR_ANALYSIS) -> str:
    """Trim oversized JD text so Groq requests stay within the model token budget."""
    source = (jd_text or "").strip()
    if len(source) <= max_chars:
        return source
    logger.info(
        "Truncating JD from %s to %s characters for Groq request budget",
        len(source),
        max_chars,
    )
    return source[:max_chars].rstrip()


def _focus_areas_for_prompt(focus_areas: list[FocusAreaOverride] | None) -> str:
    if not focus_areas:
        return "[]"
    return json.dumps([item.model_dump() for item in focus_areas], ensure_ascii=True)


def _finalize_analysis(
    combined: JDAnalysisAndInterviewPlan,
    duration_mins: int,
) -> JDAnalysisAndInterviewPlan:
    """Apply request-level metadata without rewriting LLM-generated plan content."""
    combined.interview_plan.total_mins = duration_mins
    combined.interview_plan.inferred_difficulty = (
        combined.jd_analysis.inferred_difficulty
    )
    return combined


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
        raise JdParseFailedException(
            f"Error parsing job description file: {exc}"
        ) from exc


_JD_FORMAT_SYSTEM_PROMPT = (
    "You are a formatting assistant for a hiring platform. You receive a raw job "
    "description that may be messy, unformatted, or extracted from a PDF. Rewrite it "
    "as clean, well-structured GitHub-Flavored Markdown so it is easy for a recruiter "
    "to read.\n\n"
    "STRICT RULES:\n"
    "- Preserve ALL original information, wording, and meaning. Do NOT invent, add, "
    "remove, or summarize content.\n"
    "- Only fix structure and formatting: use headings (##), bold for labels, bullet "
    "lists for responsibilities/requirements/qualifications, and paragraphs where "
    "appropriate.\n"
    "- Fix obvious artifacts from PDF extraction such as broken line wraps, stray "
    "hyphenation, and duplicated whitespace.\n"
    "- Do NOT wrap the output in a code fence. Do NOT add any commentary, preamble, "
    "or explanation.\n"
    "- Return ONLY the formatted Markdown of the job description."
)


async def format_jd_to_markdown(
    raw_jd_text: str,
    groq_client: AsyncGroq,
) -> str:
    """Reformat a raw JD into clean Markdown; fall back to the raw text on failure."""
    source = (raw_jd_text or "").strip()
    if not source:
        return source

    try:
        completion = await groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": _JD_FORMAT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Reformat the following job description into clean Markdown:\n\n"
                        f"{source}"
                    ),
                },
            ],
            temperature=0.1,
        )
        formatted = (completion.choices[0].message.content or "").strip()
    except Exception:
        logger.warning(
            "JD Markdown formatting failed; falling back to raw text",
            exc_info=True,
        )
        return source

    if not formatted:
        return source

    formatted = re.sub(r"^```(?:markdown)?\s*\n?", "", formatted)
    formatted = re.sub(r"\n?```\s*$", "", formatted)
    return formatted.strip() or source


def _combined_analysis_system_prompt() -> str:
    return """
You are an expert recruiter and structured interview architect. You analyze job
descriptions across every industry and profession — software engineering, data,
product, design, banking, finance, accounting, insurance, healthcare, legal,
sales, marketing, operations, supply chain, manufacturing, HR, consulting,
customer support, and other specialist roles — and return one JSON object containing
`jd_analysis` and `interview_plan`. The output is validated by a strict schema and
stored directly in a database, so never add undeclared fields.

Your job is to extract interviewable hard skills and domain competencies from the
JD itself. Do not assume the role is in computer science or software engineering.
Infer the profession from title, responsibilities, tools, regulations, and
deliverables, then extract skills that a human interviewer could realistically
probe in a structured voice interview.

REQUIRED WORK ORDER
1. Infer the role difficulty from the JD.
2. Extract distinct, interviewable technical or domain-specific hard skills and
   score their importance.
3. Extract behavioural and team-culture signals.
4. Copy the exact inferred difficulty into the interview plan.
5. Build a time plan that maximizes meaningful domain/technical coverage.

INFERRED DIFFICULTY
Use exactly one of:
- "junior level"
- "mid-level"
- "senior level"

Years-of-experience rules (apply to all domains):
- A role requiring 0-2 years is always "junior level".
- Intern, graduate, trainee, entry-level, junior, and associate roles are normally
  "junior level", unless the JD clearly contradicts the label.
- A role requiring roughly 3-6 years is normally "mid-level".
- Requirements such as 3+ years or 5+ years are "mid-level" by default when the
  person independently delivers work, owns a portfolio/book/queue/caseload, or
  executes core duties without broad organizational or strategic ownership.
- A role requiring 7+ years is normally "senior level".
- Senior, lead, staff, principal, head, director, architect, partner, or manager
  roles are "senior level" when responsibilities include strategy, governance,
  cross-team ownership, mentoring, technical/professional leadership, risk
  oversight, portfolio/program direction, or high-impact design and decision-making.
- If an experience range crosses bands, use the responsibility level to decide.
  Example: 5-8 years with independent feature delivery is mid-level; 5-8 years
  with architecture, mentoring, and cross-team leadership is senior-level.
  Example: 5-8 years preparing client accounts independently is mid-level; 5-8
  years leading audit strategy or portfolio risk is senior-level.
- If years are absent, infer from the title and responsibilities. Do not inflate a
  role to senior merely because its domain is sophisticated or regulated.
- Prefer the explicit minimum required experience over optional/preferred
  experience. Do not use the candidate's experience; analyze only the JD.

DOMAIN-AGNOSTIC SKILL IDENTIFICATION
Treat `skills` as the role's assessable hard competencies — not only programming
languages or IT tooling. Extract whatever the JD makes central to success in that
profession.

Examples by domain (illustrative, not exhaustive):
- Software / IT / Data: Python, SQL, System Design, AWS, React, API Design,
  Kubernetes, Data Modeling, Machine Learning.
- Banking / Finance / Accounting: Financial Modeling, Credit Analysis, IFRS/GAAP,
  Risk Management, Treasury Operations, KYC/AML Compliance, Bloomberg Terminal,
  Loan Underwriting, Portfolio Analysis, Excel/VBA, SAP FI/CO.
- Insurance / Actuarial: Actuarial Modeling, Underwriting, Claims Assessment,
  Solvency Regulations, Pricing Analysis.
- Healthcare / Clinical / Life Sciences: Clinical Protocols, HIPAA Compliance,
  Medical Coding (ICD/CPT), Pharmacovigilance, GxP, Patient Safety, EMR Systems.
- Legal / Compliance / Risk: Contract Review, Regulatory Compliance, AML/KYC,
  GDPR, Litigation Support, Policy Drafting, Internal Audit.
- Sales / Marketing / Customer: CRM (Salesforce), Pipeline Management, SEO/SEM,
  Campaign Analytics, Account Management, Negotiation, Customer Success Metrics.
- Operations / Supply Chain / Manufacturing: Lean/Six Sigma, Inventory Management,
  ERP (SAP/Oracle), Procurement, Quality Assurance, Process Improvement.
- HR / People / Admin: Talent Acquisition, Compensation & Benefits, HRIS,
  Employee Relations, Workforce Planning.
- Design / Creative / Content: UX Research, Figma, Brand Strategy, Copywriting,
  Visual Design Systems.

When the JD mixes domains, extract each assessable competency separately. Prefer
profession-standard names over vague labels ("Financial Modeling" not "numbers";
"Credit Analysis" not "banking knowledge").

JD SKILL EXTRACTION AND PRIORITY
- Include concrete technical skills or domain-specific hard skills that can be
  assessed in a structured voice interview: core domain competencies, methods,
  regulations, frameworks, platforms, tools, and methodologies relevant to the
  profession.
- Consolidate aliases and duplicates into one clear skill name.
- Do not put communication, teamwork, leadership, ownership, or culture-fit traits
  in `skills`; place those in `behavioural_signals`.
- Do not force software-engineering skills onto non-technical roles. Likewise, do
  not omit domain-critical competencies (e.g., IFRS, underwriting, clinical
  documentation) in favor of generic soft skills.
- Keep relevant nice-to-have technical or domain-specific skills in
  `jd_analysis.skills` only when they deserve interview time. For short
  interviews, omit peripheral / bonus skills from the plan even if they appear
  in the JD analysis.
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
  2. technical or domain skill sections in descending effective importance
  3. `behavioural_cultural`
- `self_intro` is capped at min(10 percent of total duration, 1.0 minute), has `skill: null`,
  and must NOT contain `expected_signals`.
- `behavioural_cultural` must never exceed 10 percent of total interview time.
  For 5 minutes it is at most 0.5 minutes; for 15 minutes it is at most 1.5
  minutes; for 30 minutes it is at most 3.0.
- Prefer a focused skill set over shallow coverage. A short interview should
  probe a few high-priority skills deeply rather than listing every JD skill.
- Suggested technical skill counts by interview length (after intro/behavioural):
  * 5 minutes -> 1-2 skills
  * 10 minutes -> 2-3 skills
  * 15 minutes -> 2-3 skills
  * 30 minutes -> 4-5 skills
- Every included technical/domain skill must receive meaningful time
  (roughly 1.5+ minutes on short interviews, 2+ minutes on 10-15 minute
  interviews). Drop lowest-priority skills first when time is limited.
- Weight technical/domain time by the matching JD `priority_score`. When a
  matching `focus_areas.weight_override` exists, use it as that skill's
  effective weight. Higher-priority skills must get clearly more time.
- A technical or domain section's `section_name` and `skill` must both exactly match the
  corresponding `jd_analysis.skills[].skill`.
- Technical/domain and behavioural sections need 2-4 concise, observable
  `expected_signals`. Signals should describe evidence to listen for, not questions.
  Tailor signals to the profession (e.g., "Ability to explain DCF assumptions and
  sensitivity drivers" for finance; "Ability to walk through REST API design
  trade-offs" for backend engineering).
- Behavioural/cultural signals must cover both work behaviour (ownership,
  collaboration, conflict handling, adaptability, communication) and alignment
  with team culture or working norms.
- Do not include `priority_score` in interview-plan sections. Priority lives only
  in `jd_analysis`.
- Do not include question-count limits, follow-up limits, depth fields, role-title
  fields, or any other undeclared fields.
- Use one decimal place for section minutes. Allocations must sum exactly to
  `total_mins`.

ONE-SHOT EXAMPLES

EXAMPLE 1 — Software engineering
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

EXAMPLE 2 — Banking / finance
Example input summary: 15-minute Credit Analyst interview; JD asks for 1-3 years,
emphasizes credit underwriting, financial statement analysis, Excel modeling,
regulatory compliance (KYC/AML), and exposure to lending products. Therefore the
inferred difficulty is junior level. A valid output is:
{
  "jd_analysis": {
    "inferred_difficulty": "junior level",
    "skills": [
      {
        "skill": "Credit Analysis",
        "priority_score": 9.5,
        "reasoning": "Credit assessment is the primary responsibility and appears throughout core duties."
      },
      {
        "skill": "Financial Statement Analysis",
        "priority_score": 9.0,
        "reasoning": "The JD requires evaluating borrower financials to support lending decisions."
      },
      {
        "skill": "Excel Financial Modeling",
        "priority_score": 8.0,
        "reasoning": "Excel-based models are explicitly required for cash-flow and ratio analysis."
      },
      {
        "skill": "KYC/AML Compliance",
        "priority_score": 7.0,
        "reasoning": "Compliance checks are listed as part of the standard credit workflow."
      },
      {
        "skill": "Lending Products",
        "priority_score": 5.5,
        "reasoning": "Familiarity with term loans and working-capital products is preferred but secondary."
      }
    ],
    "behavioural_signals": [
      "Attention to detail under regulatory pressure",
      "Sound judgment with incomplete information",
      "Clear stakeholder communication"
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
        "section_name": "Credit Analysis",
        "skill": "Credit Analysis",
        "allocated_mins": 4.0,
        "expected_signals": [
          "Understanding of credit risk factors and borrower assessment",
          "Ability to explain how lending decisions are supported by evidence"
        ]
      },
      {
        "section_name": "Financial Statement Analysis",
        "skill": "Financial Statement Analysis",
        "allocated_mins": 3.6,
        "expected_signals": [
          "Understanding of balance sheet, income statement, and cash-flow drivers",
          "Ability to identify red flags in borrower financials"
        ]
      },
      {
        "section_name": "Excel Financial Modeling",
        "skill": "Excel Financial Modeling",
        "allocated_mins": 3.2,
        "expected_signals": [
          "Understanding of ratio and cash-flow modeling concepts",
          "Ability to describe assumptions and sensitivity checks"
        ]
      },
      {
        "section_name": "KYC/AML Compliance",
        "skill": "KYC/AML Compliance",
        "allocated_mins": 1.2,
        "expected_signals": [
          "Understanding of basic KYC/AML obligations in lending workflows",
          "Ability to explain documentation and escalation steps"
        ]
      },
      {
        "section_name": "Lending Products",
        "skill": "Lending Products",
        "allocated_mins": 0.5,
        "expected_signals": [
          "Understanding of common lending product types",
          "Ability to relate product features to borrower needs"
        ]
      },
      {
        "section_name": "behavioural_cultural",
        "skill": null,
        "allocated_mins": 1.5,
        "expected_signals": [
          "Attention to detail under regulatory pressure",
          "Evidence-based judgment with incomplete information",
          "Clear stakeholder communication",
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
        "section_name": "exact technical or domain skill name",
        "skill": "exact technical or domain skill name",
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


def _combined_analysis_messages(
    *,
    user_prompt: str,
    repair_note: str | None = None,
) -> list[ChatCompletionMessageParam]:
    """Build chat messages for JD analysis, optionally including a repair hint."""
    schema_json = json.dumps(
        JDAnalysisAndInterviewPlan.model_json_schema(),
        indent=2,
        ensure_ascii=True,
    )
    system_prompt = (
        _combined_analysis_system_prompt() + "\n\nJSON OUTPUT RULES\n"
        "- Respond with one JSON object only. No markdown fences, commentary, or prose.\n"
        "- The top-level object must contain exactly `jd_analysis` and `interview_plan`.\n"
        "- `interview_plan.sections` must include `self_intro`, one or more technical/domain "
        "skill sections, and `behavioural_cultural` in that order.\n"
        "- Section minutes must sum exactly to `interview_plan.total_mins`.\n"
        "- Match this JSON Schema:\n"
        f"{schema_json}"
    )
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if repair_note:
        messages.append({"role": "user", "content": repair_note})
    return messages


def _analysis_user_prompt(
    *,
    jd_text: str,
    duration_mins: int,
    focus_areas: list[FocusAreaOverride] | None,
) -> str:
    technical_minutes = _estimated_technical_minutes(duration_mins)
    min_per_skill = _min_minutes_per_skill(duration_mins, technical_minutes)
    return (
        f"Interview duration: {duration_mins} minutes\n"
        f"Estimated technical minutes available: {technical_minutes:.1f}\n"
        f"Minimum minutes per technical skill section: {min_per_skill}\n"
        f"Focus area overrides as JSON: {_focus_areas_for_prompt(focus_areas)}\n\n"
        "Analyze this Job Description and generate the combined output.\n"
        "The interview_plan must be complete, time-balanced, and executable for this "
        f"exact {duration_mins}-minute duration.\n\n"
        f"{jd_text}"
    )


async def run_jd_analysis_and_interview_plan(
    jd_text: str,
    duration_mins: int,
    focus_areas: list[FocusAreaOverride] | None,
    groq_client: AsyncGroq,
) -> JDAnalysisAndInterviewPlan:
    """Call Groq once to produce both JD analysis and the executable interview plan."""
    jd_for_prompt = _truncate_jd_text(jd_text)
    base_user_prompt = _analysis_user_prompt(
        jd_text=jd_for_prompt,
        duration_mins=duration_mins,
        focus_areas=focus_areas,
    )

    last_exc: Exception | None = None
    repair_note: str | None = None
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            completion = await groq_client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=_combined_analysis_messages(
                    user_prompt=base_user_prompt,
                    repair_note=repair_note,
                ),
                response_format=_structured_response_format(JDAnalysisAndInterviewPlan),
                temperature=0.1,
            )
            raw_content = completion.choices[0].message.content or ""
            parsed_json = json.loads(raw_content)
            combined = JDAnalysisAndInterviewPlan.model_validate(parsed_json)
            return _finalize_analysis(combined, duration_mins)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                repair_note = (
                    "Your previous JSON response failed validation. "
                    f"Error: {exc}\n"
                    "Return a corrected JSON object only. Follow the schema exactly."
                )
                logger.warning(
                    "JD analysis attempt %s failed validation; retrying: %s",
                    attempt + 1,
                    exc,
                )
                await asyncio.sleep(1.5)
                continue
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            exc_text = str(exc).lower()
            if (
                attempt < max_attempts - 1
                and ("413" in exc_text or "request too large" in exc_text)
                and len(jd_for_prompt) > 4000
            ):
                jd_for_prompt = _truncate_jd_text(jd_text, 4000)
                base_user_prompt = _analysis_user_prompt(
                    jd_text=jd_for_prompt,
                    duration_mins=duration_mins,
                    focus_areas=focus_areas,
                )
                repair_note = None
                logger.warning(
                    "JD analysis hit Groq token limit; retrying with shorter JD input"
                )
                await asyncio.sleep(1.5)
                continue
            if attempt < max_attempts - 1:
                logger.warning(
                    "JD analysis attempt %s failed; retrying: %s",
                    attempt + 1,
                    exc,
                )
                await asyncio.sleep(1.5)
                continue

    logger.exception("Groq combined JD analysis/interview-plan failed after retries")
    raise LlmAnalysisFailedException(
        f"Failed to analyze job description and generate interview plan: {last_exc}"
    ) from last_exc
