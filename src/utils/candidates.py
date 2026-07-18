"""Utility helpers for candidate operations (parsing, email generation)."""

import json
import logging
import re
import uuid
from html import escape
from pathlib import Path
from typing import Any, Literal

import fitz
import httpx
from brevo import AsyncBrevo
from brevo.transactional_emails import (
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
)
from fastapi.concurrency import run_in_threadpool
from groq import AsyncGroq

from src.config.settings import settings
from src.core.exceptions import (
    ResumeDownloadFailedException,
    ResumeParseFailedException,
)

logger = logging.getLogger(__name__)


async def generate_candidate_decision_feedback(
    *,
    decision: Literal["APPROVED", "REJECTED"],
    candidate_name: str,
    role_name: str,
    assessment_title: str,
    overall_summary: str,
    recommendation_reasoning: str,
    strengths: list[str],
    concerns: list[str],
) -> str:
    """Generate concise, candidate-facing copy for a final hiring decision."""
    first_name = (
        candidate_name.strip().split()[0] if candidate_name.strip() else "there"
    )
    primary_strength = (
        strengths[0].strip()
        if strengths
        else "the time and preparation you brought to the interview"
    )
    primary_concern = (
        concerns[0].strip()
        if concerns
        else "showing more specific evidence and depth in future interview responses"
    )
    if decision == "APPROVED":
        fallback = (
            f"Thank you for the time and thought you put into the {role_name} interview, "
            f"{first_name}. We were especially impressed by "
            f"{primary_strength.rstrip('.').lower()}. We are pleased to move forward "
            "with your application and look forward to continuing the conversation. "
            "Our recruiting team will contact you with the next steps and any additional "
            "details you need. We appreciate your interest in the opportunity and the "
            "preparation you brought to the interview."
        )
        system_prompt = (
            "You are an expert recruiting communications assistant. Write a warm, "
            "specific, candidate-facing approval message using only the provided "
            "interview evidence. Keep it between 70 and 120 words. Mention one or two "
            "genuine strengths, confirm that the candidate is moving forward, and say "
            "that the recruiting team will contact them with next steps. Do not mention "
            "scores, AI, models, internal recommendations, policy, integrity flags, or "
            "hidden evaluation criteria. Do not promise an offer, compensation, dates, "
            "or a guaranteed outcome. Return only the message with no heading, bullets, "
            "or quotation marks."
        )
    else:
        fallback = (
            f"Thank you for the time and thought you put into the {role_name} interview, "
            f"{first_name}. We appreciated {primary_strength.rstrip('.').lower()}. "
            "After reviewing the interview evidence, we have decided not to move forward "
            "with your application at this stage. For future opportunities, we encourage "
            f"you to focus on {primary_concern.rstrip('.').lower()}. "
            "We appreciate your interest and wish you the best in your search."
        )
        system_prompt = (
            "You are an expert recruiting communications assistant. Write a warm, "
            "specific, candidate-facing rejection feedback paragraph using only the "
            "provided interview evidence. Keep it between 70 and 120 words. Mention one "
            "genuine strength and one or two constructive development areas. Do not mention "
            "scores, AI, models, internal recommendations, policy, integrity flags, or hidden "
            "evaluation criteria. Do not make promises or invite debate. Return only the "
            "feedback paragraph with no heading, bullets, or quotation marks."
        )

    if not settings.GROQ_API_KEY and not settings.FALLBACK_GROQ_API_KEY:
        return fallback[:2000]

    user_prompt = (
        f"Decision: {decision}\n"
        f"Candidate: {candidate_name}\n"
        f"Role: {role_name}\n"
        f"Assessment: {assessment_title}\n"
        f"Overall summary: {overall_summary}\n"
        f"Recommendation reasoning: {recommendation_reasoning}\n"
        f"Strengths: {'; '.join(strengths[:4]) or 'Not specified'}\n"
        f"Development areas: {'; '.join(concerns[:4]) or 'Not specified'}"
    )

    api_keys = [settings.GROQ_API_KEY, settings.FALLBACK_GROQ_API_KEY]
    for api_key in dict.fromkeys(key for key in api_keys if key):
        try:
            client = AsyncGroq(api_key=api_key)
            completion = await client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.35,
                max_tokens=240,
            )
            draft = (completion.choices[0].message.content or "").strip()
            if draft:
                return draft[:2000]
        except Exception:
            logger.exception("AI hiring decision feedback generation failed")

    return fallback[:2000]


async def generate_rejection_feedback(**kwargs: Any) -> str:
    """Generate a rejection draft while preserving the existing call surface."""
    return await generate_candidate_decision_feedback(decision="REJECTED", **kwargs)


async def generate_approval_feedback(**kwargs: Any) -> str:
    """Generate an approval draft from persisted interview evidence."""
    return await generate_candidate_decision_feedback(decision="APPROVED", **kwargs)


def temporary_resume_path(candidate_assessment_id: uuid.UUID) -> Path:
    """Return the configured runtime path for a temporary resume."""
    return Path(settings.TEMP_RESUME_DIR) / f"{candidate_assessment_id}.pdf"


async def write_temporary_resume(
    candidate_assessment_id: uuid.UUID,
    content: bytes,
) -> Path:
    """Persist resume bytes in the writable runtime temporary directory."""
    path = temporary_resume_path(candidate_assessment_id)

    def write_file() -> None:
        """Write uploaded resume bytes to the temporary path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    await run_in_threadpool(write_file)
    return path


async def parse_resume_from_file(temp_file_path: str) -> dict:
    """Core logic to extract text from PDF and call Groq to return parsed JSON dict."""

    def extract_text() -> str:
        """Extract text from the temporary resume PDF file."""
        text = ""
        with fitz.open(temp_file_path) as doc:
            for page in doc:
                text += page.get_text() + "\n"
        return text

    resume_text = await run_in_threadpool(extract_text)
    if not resume_text.strip():
        raise ResumeParseFailedException("Parsed resume text is empty")

    system_prompt = (
        "You are an expert resume parser and technical recruiter. "
        "Analyze the provided resume markdown text and extract structured candidate data.\n\n"
        "You MUST respond with a JSON object that strictly adheres to the following schema:\n"
        "{\n"
        '  "summary": "string (a concise 2-3 sentence technical summary of the candidate\'s background and strengths)",\n'
        '  "skills": ["string (key technical skills/tools/languages the candidate has experience with)"],\n'
        '  "experience_years": float (estimated total years of professional/technical work experience based on the resume timeline. Be realistic. If it is not clear, have it a zero)\n'
        "}\n"
        "Only return raw JSON. Do not include markdown code block formatting (such as ```json) or explanation."
    )

    messages: Any = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Analyze this Candidate Resume:\n{resume_text}",
        },
    ]

    try:
        groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        completion = await groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
        )
    except Exception as e:
        logger.warning(
            "Groq API call failed with primary key: %s. Retrying with fallback key...",
            e,
        )
        groq_client = AsyncGroq(api_key=settings.FALLBACK_GROQ_API_KEY)
        completion = await groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
        )

    raw_content = completion.choices[0].message.content or ""
    return json.loads(raw_content)


async def download_resume(resume_url: str, temp_file_path: str) -> None:
    """Download a resume from a URL to a local temporary file path."""

    def get_direct_download_url(url: str) -> str:
        """Convert Google Drive sharing URLs into direct download URLs."""
        gd_match = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", url)
        if gd_match:
            file_id = gd_match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        gd_match_query = re.search(r"drive\.google\.com/.*id=([a-zA-Z0-9_-]+)", url)
        if gd_match_query:
            file_id = gd_match_query.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        return url

    if not resume_url.startswith("http"):
        raise ResumeDownloadFailedException(
            f"Invalid resume URL (not HTTP/HTTPS): {resume_url}"
        )

    download_url = get_direct_download_url(resume_url)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(download_url, timeout=30.0)
        response.raise_for_status()
        path = Path(temp_file_path)

        def write_file() -> None:
            """Write downloaded resume bytes to the temporary path."""
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)

        await run_in_threadpool(write_file)


async def send_invitation_email(
    candidate_name: str,
    recipient_email: str,
    assessment_title: str,
    role_name: str,
    invitation_link: str,
    interview_duration_mins: int,
) -> None:
    """Send an invitation email via Brevo."""

    def _build_invitation_html(
        candidate_name: str,
        assessment_title: str,
        role_name: str,
        invitation_link: str,
        interview_duration_mins: int,
    ) -> str:
        """Build a rich HTML email for the candidate interview invitation."""
        return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <meta name="color-scheme" content="light only" />
      <meta name="supported-color-schemes" content="light only" />
      <title>Interview Invitation</title>
      <style>
        :root {{
          color-scheme: light only;
          supported-color-schemes: light only;
        }}
        @media (prefers-color-scheme: dark) {{
          .interview-cta-cell {{
            background-color: #4f46e5 !important;
            background-image: linear-gradient(135deg, #4f46e5, #7c3aed) !important;
            border-color: #312e81 !important;
          }}
          .interview-cta-link,
          .interview-cta-link span {{
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
          }}
        }}
        [data-ogsc] .interview-cta-cell,
        [data-ogsb] .interview-cta-cell {{
          background-color: #4f46e5 !important;
          background-image: linear-gradient(135deg, #4f46e5, #7c3aed) !important;
          border-color: #312e81 !important;
        }}
        [data-ogsc] .interview-cta-link,
        [data-ogsc] .interview-cta-link span,
        [data-ogsb] .interview-cta-link,
        [data-ogsb] .interview-cta-link span {{
          color: #ffffff !important;
          -webkit-text-fill-color: #ffffff !important;
        }}
      </style>
    </head>
    <body style="margin:0;padding:0;background-color:#f4f6fa;font-family:'Segoe UI',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fa;padding:40px 0;">
        <tr>
          <td align="center">
            <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
              <!-- Header -->
              <tr>
                <td style="background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%);padding:36px 40px;text-align:center;">
                  <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.5px;">iBot AI Interview</h1>
                  <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">Intelligent Hiring Platform</p>
                </td>
              </tr>
              <!-- Body -->
              <tr>
                <td style="padding:40px;">
                  <p style="margin:0 0 8px;color:#6366f1;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Interview Invitation</p>
                  <h2 style="margin:0 0 20px;color:#1e1b4b;font-size:22px;font-weight:700;">Hello, {candidate_name}!</h2>
                  <p style="margin:0 0 24px;color:#4b5563;font-size:15px;line-height:1.7;">
                    You have been invited to complete an AI-powered interview for the
                    <strong style="color:#1e1b4b;">{role_name}</strong> position as part of the
                    <strong style="color:#1e1b4b;">{assessment_title}</strong> assessment.
                  </p>

                  <!-- Info card -->
                  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f3ff;border:1px solid #ddd6fe;border-radius:12px;margin:0 0 28px;">
                    <tr>
                      <td style="padding:20px 24px;">
                        <table width="100%" cellpadding="0" cellspacing="0">
                          <tr>
                            <td style="padding:6px 0;">
                              <span style="color:#6b7280;font-size:13px;">📋 Role</span>
                              <span style="float:right;color:#1e1b4b;font-size:13px;font-weight:600;">{role_name}</span>
                            </td>
                          </tr>
                          <tr>
                            <td style="padding:6px 0;border-top:1px solid #ede9fe;">
                              <span style="color:#6b7280;font-size:13px;">⏱️ Duration</span>
                              <span style="float:right;color:#1e1b4b;font-size:13px;font-weight:600;">{interview_duration_mins} minutes</span>
                            </td>
                          </tr>
                          <tr>
                            <td style="padding:6px 0;border-top:1px solid #ede9fe;">
                              <span style="color:#6b7280;font-size:13px;">🤖 Format</span>
                              <span style="float:right;color:#1e1b4b;font-size:13px;font-weight:600;">AI-powered conversation</span>
                            </td>
                          </tr>
                        </table>
                      </td>
                    </tr>
                  </table>

                  <!-- CTA Button -->
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td align="center" style="padding:8px 0 28px;">
                        <!--[if mso]>
                        <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml"
                                     xmlns:w="urn:schemas-microsoft-com:office:word"
                                     href="{invitation_link}"
                                     style="height:54px;v-text-anchor:middle;width:326px;"
                                     arcsize="50%" strokecolor="#312e81" fillcolor="#4f46e5">
                          <w:anchorlock/>
                          <center style="color:#ffffff;font-family:'Segoe UI',Arial,sans-serif;font-size:15px;font-weight:700;">
                            Start Your Interview &#8594;
                          </center>
                        </v:roundrect>
                        <![endif]-->
                        <!--[if !mso]><!-->
                        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                          <tr>
                            <td class="interview-cta-cell" align="center" bgcolor="#4f46e5"
                                style="background-color:#4f46e5 !important;background-image:linear-gradient(135deg,#4f46e5,#7c3aed);border:2px solid #312e81;border-radius:50px;box-shadow:0 4px 16px rgba(79,70,229,0.4);">
                              <a class="interview-cta-link" href="{invitation_link}" target="_blank" role="button"
                                 style="display:block;min-width:230px;padding:15px 46px;color:#ffffff !important;-webkit-text-fill-color:#ffffff !important;text-decoration:none;font-family:'Segoe UI',Arial,sans-serif;font-size:15px;font-weight:700;line-height:20px;letter-spacing:0.3px;text-align:center;text-shadow:0 1px 1px rgba(0,0,0,0.25);">
                                <span style="color:#ffffff !important;-webkit-text-fill-color:#ffffff !important;">Start Your Interview &#8594;</span>
                              </a>
                            </td>
                          </tr>
                        </table>
                        <!--<![endif]-->
                      </td>
                    </tr>
                  </table>

                  <p style="margin:0 0 8px;color:#6b7280;font-size:13px;line-height:1.6;">
                    If the button above doesn't work, copy and paste this link into your browser:
                  </p>
                  <p style="margin:0 0 28px;word-break:break-all;">
                    <a href="{invitation_link}" style="color:#6366f1;font-size:12px;">{invitation_link}</a>
                  </p>

                  <div style="background:#fef3c7;border:1px solid #fde68a;border-radius:10px;padding:14px 18px;margin-bottom:28px;">
                    <p style="margin:0;color:#92400e;font-size:13px;line-height:1.6;">
                      <strong>⚠️ Important:</strong> Please ensure you are in a quiet environment with a stable internet connection before starting.
                      The interview cannot be paused once begun.
                    </p>
                  </div>
                </td>
              </tr>
              <!-- Footer -->
              <tr>
                <td style="background:#f9fafb;border-top:1px solid #f3f4f6;padding:24px 40px;text-align:center;">
                  <p style="margin:0;color:#9ca3af;font-size:12px;">
                    This invitation was sent by the iBot AI Interview Platform.<br/>
                    If you were not expecting this email, please ignore it.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    client = AsyncBrevo(api_key=settings.BREVO_API_KEY)
    sender = SendTransacEmailRequestSender(
        email=settings.BREVO_SENDER_EMAIL,
        name="iBot AI Interview Platform",
    )
    recipient = SendTransacEmailRequestToItem(
        email=recipient_email,
        name=candidate_name,
    )
    result = await client.transactional_emails.send_transac_email(
        html_content=_build_invitation_html(
            candidate_name,
            assessment_title,
            role_name,
            invitation_link,
            interview_duration_mins,
        ),
        sender=sender,
        subject=f"Interview Invitation: {role_name} — {assessment_title}",
        to=[recipient],
    )
    logger.info(
        "Invitation email sent via Brevo",
        extra={
            "recipient": recipient_email,
            "assessment_title": assessment_title,
            "brevo_response": str(result),
        },
    )


async def send_cancellation_email(
    candidate_name: str,
    recipient_email: str,
    assessment_title: str,
    role_name: str,
) -> None:
    """Send a cancellation email via Brevo."""

    def _build_cancellation_html(
        candidate_name: str,
        assessment_title: str,
        role_name: str,
    ) -> str:
        """Build a rich HTML email for the candidate interview cancellation."""
        return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>Interview Cancelled</title>
    </head>
    <body style="margin:0;padding:0;background-color:#f4f6fa;font-family:'Segoe UI',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fa;padding:40px 0;">
        <tr>
          <td align="center">
            <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
              <!-- Header -->
              <tr>
                <td style="background:linear-gradient(135deg,#ef4444 0%,#b91c1c 100%);padding:36px 40px;text-align:center;">
                  <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.5px;">iBot AI Interview</h1>
                  <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">Assessment Update</p>
                </td>
              </tr>
              <!-- Body -->
              <tr>
                <td style="padding:40px;">
                  <p style="margin:0 0 8px;color:#ef4444;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Interview Cancelled</p>
                  <h2 style="margin:0 0 20px;color:#1e1b4b;font-size:22px;font-weight:700;">Hello, {candidate_name},</h2>
                  <p style="margin:0 0 24px;color:#4b5563;font-size:15px;line-height:1.7;">
                    We are writing to inform you that the <strong style="color:#1e1b4b;">{role_name}</strong> assessment
                    (<strong style="color:#1e1b4b;">{assessment_title}</strong>) has been <strong style="color:#ef4444;">cancelled</strong> until further notice.
                  </p>
                  <p style="margin:0 0 24px;color:#4b5563;font-size:15px;line-height:1.7;">
                    If you have already completed the interview, no further action is required. If you haven't started yet, please note that your invitation link is no longer active.
                  </p>
                  <p style="margin:0 0 8px;color:#4b5563;font-size:15px;line-height:1.7;">
                    Thank you for your understanding.
                  </p>
                </td>
              </tr>
              <!-- Footer -->
              <tr>
                <td style="background:#f9fafb;border-top:1px solid #f3f4f6;padding:24px 40px;text-align:center;">
                  <p style="margin:0;color:#9ca3af;font-size:12px;">
                    This notification was sent by the iBot AI Interview Platform.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    client = AsyncBrevo(api_key=settings.BREVO_API_KEY)
    sender = SendTransacEmailRequestSender(
        email=settings.BREVO_SENDER_EMAIL,
        name="iBot AI Interview Platform",
    )
    recipient = SendTransacEmailRequestToItem(
        email=recipient_email,
        name=candidate_name,
    )
    result = await client.transactional_emails.send_transac_email(
        html_content=_build_cancellation_html(
            candidate_name, assessment_title, role_name
        ),
        sender=sender,
        subject=f"Update on Interview: {role_name} — {assessment_title}",
        to=[recipient],
    )
    logger.info(
        "Cancellation email sent via Brevo",
        extra={
            "recipient": recipient_email,
            "assessment_title": assessment_title,
            "brevo_response": str(result),
        },
    )


async def send_hiring_decision_email(
    *,
    candidate_name: str,
    recipient_email: str,
    assessment_title: str,
    role_name: str,
    decision: str,
    feedback: str | None = None,
) -> None:
    """Send the recruiter's final hiring decision email via Brevo."""

    normalized_decision = decision.upper()
    safe_candidate_name = escape(candidate_name)
    safe_assessment_title = escape(assessment_title)
    safe_role_name = escape(role_name)
    safe_feedback = escape(feedback.strip()) if feedback and feedback.strip() else None
    is_approved = normalized_decision == "APPROVED"
    accent = "#059669" if is_approved else "#dc2626"
    soft_bg = "#ecfdf5" if is_approved else "#fef2f2"
    border = "#a7f3d0" if is_approved else "#fecaca"
    label = (
        "Hiring Update - Shortlisted" if is_approved else "Hiring Update - Not Selected"
    )
    subject_status = "Shortlisted" if is_approved else "Application Update"
    body = (
        "Congratulations. After reviewing your AI interview evaluation, "
        "the recruiting team has decided to move forward with your candidature."
        if is_approved
        else (
            "Thank you for completing the AI interview. After reviewing your "
            "evaluation, the recruiting team has decided not to move forward "
            "with your candidature for this assessment."
        )
    )
    next_step = (
        "The team may contact you with next steps or additional coordination details."
        if is_approved
        else "We appreciate your time and encourage you to apply again for future roles that match your experience."
    )
    feedback_html = ""
    if safe_feedback:
        feedback_html = f"""
                  <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 18px;margin-top:22px;">
                    <p style="margin:0 0 6px;color:#0f172a;font-size:13px;font-weight:700;">Recruiter feedback</p>
                    <p style="margin:0;color:#475569;font-size:13px;line-height:1.6;">{safe_feedback}</p>
                  </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>Hiring Decision</title>
    </head>
    <body style="margin:0;padding:0;background-color:#f4f6fa;font-family:'Segoe UI',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fa;padding:40px 0;">
        <tr>
          <td align="center">
            <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
              <tr>
                <td style="background:{accent};padding:34px 40px;text-align:center;">
                  <h1 style="margin:0;color:#ffffff;font-size:26px;font-weight:700;">iBot AI Interview</h1>
                  <p style="margin:8px 0 0;color:rgba(255,255,255,0.86);font-size:14px;">Final hiring decision</p>
                </td>
              </tr>
              <tr>
                <td style="padding:40px;">
                  <p style="margin:0 0 8px;color:{accent};font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">{label}</p>
                  <h2 style="margin:0 0 20px;color:#0f172a;font-size:22px;font-weight:700;">Hello, {safe_candidate_name}</h2>
                  <p style="margin:0 0 22px;color:#475569;font-size:15px;line-height:1.7;">{body}</p>
                  <table width="100%" cellpadding="0" cellspacing="0" style="background:{soft_bg};border:1px solid {border};border-radius:12px;margin:0 0 22px;">
                    <tr>
                      <td style="padding:18px 22px;">
                        <p style="margin:0;color:#64748b;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;">Assessment</p>
                        <p style="margin:6px 0 0;color:#0f172a;font-size:15px;font-weight:700;">{safe_assessment_title}</p>
                        <p style="margin:6px 0 0;color:#475569;font-size:13px;">Role: {safe_role_name}</p>
                      </td>
                    </tr>
                  </table>
                  <p style="margin:0;color:#475569;font-size:14px;line-height:1.7;">{next_step}</p>
                  {feedback_html}
                </td>
              </tr>
              <tr>
                <td style="background:#f8fafc;border-top:1px solid #f1f5f9;padding:22px 40px;text-align:center;">
                  <p style="margin:0;color:#94a3b8;font-size:12px;">This message was sent by the iBot AI Interview Platform.</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    client = AsyncBrevo(api_key=settings.BREVO_API_KEY)
    sender = SendTransacEmailRequestSender(
        email=settings.BREVO_SENDER_EMAIL,
        name="iBot AI Interview Platform",
    )
    recipient = SendTransacEmailRequestToItem(
        email=recipient_email,
        name=candidate_name,
    )
    result = await client.transactional_emails.send_transac_email(
        html_content=html_content,
        sender=sender,
        subject=f"{subject_status}: {role_name} - {assessment_title}",
        to=[recipient],
    )
    logger.info(
        "Hiring decision email sent via Brevo",
        extra={
            "recipient": recipient_email,
            "assessment_title": assessment_title,
            "decision": normalized_decision,
            "brevo_response": str(result),
        },
    )


async def send_otp_email(recipient_email: str, otp: str) -> None:
    """Send a password-reset OTP email via Brevo."""

    def _build_otp_html(otp: str) -> str:
        """Build a rich HTML email for the OTP verification."""
        digits = list(otp)
        digit_cells = "".join(
            f'<td style="width:56px;height:64px;background:#f5f3ff;border:2px solid #ddd6fe;border-radius:12px;text-align:center;vertical-align:middle;font-size:28px;font-weight:800;color:#1e1b4b;letter-spacing:2px;">{d}</td>'
            for d in digits
        )
        return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>Password Reset OTP</title>
    </head>
    <body style="margin:0;padding:0;background-color:#f4f6fa;font-family:'Segoe UI',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fa;padding:40px 0;">
        <tr>
          <td align="center">
            <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
              <!-- Header -->
              <tr>
                <td style="background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%);padding:36px 40px;text-align:center;">
                  <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.5px;">iBot AI Interview</h1>
                  <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">Password Reset Verification</p>
                </td>
              </tr>
              <!-- Body -->
              <tr>
                <td style="padding:40px;">
                  <p style="margin:0 0 8px;color:#6366f1;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Security Code</p>
                  <h2 style="margin:0 0 20px;color:#1e1b4b;font-size:22px;font-weight:700;">Password Reset Request</h2>
                  <p style="margin:0 0 28px;color:#4b5563;font-size:15px;line-height:1.7;">
                    Use the verification code below to complete your password reset.
                    This code will expire in <strong style="color:#1e1b4b;">60 seconds</strong>.
                  </p>

                  <!-- OTP Code -->
                  <table cellpadding="0" cellspacing="8" style="margin:0 auto 28px;">
                    <tr>
                      {digit_cells}
                    </tr>
                  </table>

                  <div style="background:#fef3c7;border:1px solid #fde68a;border-radius:10px;padding:14px 18px;margin-bottom:28px;">
                    <p style="margin:0;color:#92400e;font-size:13px;line-height:1.6;">
                      <strong>⚠️ Important:</strong> If you did not request a password reset, please ignore this email.
                      Your account remains secure.
                    </p>
                  </div>
                </td>
              </tr>
              <!-- Footer -->
              <tr>
                <td style="background:#f9fafb;border-top:1px solid #f3f4f6;padding:24px 40px;text-align:center;">
                  <p style="margin:0;color:#9ca3af;font-size:12px;">
                    This email was sent by the iBot AI Interview Platform.<br/>
                    Do not share this code with anyone.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    client = AsyncBrevo(api_key=settings.BREVO_API_KEY)
    sender = SendTransacEmailRequestSender(
        email=settings.BREVO_SENDER_EMAIL,
        name="iBot AI Interview Platform",
    )
    recipient = SendTransacEmailRequestToItem(
        email=recipient_email,
        name=recipient_email,
    )
    result = await client.transactional_emails.send_transac_email(
        html_content=_build_otp_html(otp),
        sender=sender,
        subject="Password Reset OTP — iBot AI Interview",
        to=[recipient],
    )
    logger.info(
        "OTP email sent via Brevo",
        extra={
            "recipient": recipient_email,
            "brevo_response": str(result),
        },
    )


async def send_report_ready_email(
    *,
    recruiter_email: str,
    recruiter_name: str,
    candidate_name: str,
    assessment_title: str,
    role_name: str,
    overall_score: float | int | None,
    hiring_recommendation: str | None,
    report_link: str,
) -> None:
    """Notify a recruiter via Brevo that an evaluation report is ready."""
    safe_recruiter_name = escape((recruiter_name or "there").strip() or "there")
    safe_candidate_name = escape((candidate_name or "The candidate").strip())
    safe_assessment_title = escape((assessment_title or "Assessment").strip())
    safe_role_name = escape((role_name or "the role").strip())
    safe_report_link = escape(report_link)

    score_display = "—"
    if overall_score is not None:
        try:
            score_display = f"{float(overall_score):.1f}"
        except (TypeError, ValueError):
            score_display = escape(str(overall_score))

    recommendation_display = escape(
        (hiring_recommendation or "Not specified").replace("_", " ").strip().title()
    )

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>Evaluation Report Ready</title>
    </head>
    <body style="margin:0;padding:0;background-color:#f4f6fa;font-family:'Segoe UI',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fa;padding:40px 0;">
        <tr>
          <td align="center">
            <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
              <tr>
                <td style="background:linear-gradient(135deg,#0f766e 0%,#059669 100%);padding:36px 40px;text-align:center;">
                  <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.5px;">iBot AI Interview</h1>
                  <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">Evaluation report ready</p>
                </td>
              </tr>
              <tr>
                <td style="padding:40px;">
                  <p style="margin:0 0 8px;color:#0f766e;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Report Ready</p>
                  <h2 style="margin:0 0 20px;color:#0f172a;font-size:22px;font-weight:700;">Hello, {safe_recruiter_name}</h2>
                  <p style="margin:0 0 24px;color:#4b5563;font-size:15px;line-height:1.7;">
                    The interview evaluation for <strong style="color:#0f172a;">{safe_candidate_name}</strong>
                    is now ready to review.
                  </p>
                  <table width="100%" cellpadding="0" cellspacing="0" style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;margin:0 0 26px;">
                    <tr>
                      <td style="padding:18px 22px;">
                        <p style="margin:0;color:#64748b;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;">Assessment</p>
                        <p style="margin:6px 0 0;color:#0f172a;font-size:15px;font-weight:700;">{safe_assessment_title}</p>
                        <p style="margin:6px 0 0;color:#475569;font-size:13px;">Role: {safe_role_name}</p>
                        <p style="margin:12px 0 0;color:#0f172a;font-size:13px;">
                          <strong>Overall score:</strong> {score_display} &nbsp;·&nbsp;
                          <strong>Recommendation:</strong> {recommendation_display}
                        </p>
                      </td>
                    </tr>
                  </table>
                  <table cellpadding="0" cellspacing="0" style="margin:0 0 8px;">
                    <tr>
                      <td style="border-radius:10px;background:#059669;">
                        <a href="{safe_report_link}" target="_blank"
                          style="display:inline-block;padding:14px 30px;color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;border-radius:10px;">
                          View evaluation report
                        </a>
                      </td>
                    </tr>
                  </table>
                  <p style="margin:18px 0 0;color:#94a3b8;font-size:12px;line-height:1.6;word-break:break-all;">
                    If the button does not work, copy and paste this link into your browser:<br/>
                    {safe_report_link}
                  </p>
                </td>
              </tr>
              <tr>
                <td style="background:#f8fafc;border-top:1px solid #f1f5f9;padding:22px 40px;text-align:center;">
                  <p style="margin:0;color:#94a3b8;font-size:12px;">This message was sent by the iBot AI Interview Platform.</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    client = AsyncBrevo(api_key=settings.BREVO_API_KEY)
    sender = SendTransacEmailRequestSender(
        email=settings.BREVO_SENDER_EMAIL,
        name="iBot AI Interview Platform",
    )
    recipient = SendTransacEmailRequestToItem(
        email=recruiter_email,
        name=recruiter_name or recruiter_email,
    )
    result = await client.transactional_emails.send_transac_email(
        html_content=html_content,
        sender=sender,
        subject=f"Evaluation ready: {candidate_name} — {role_name}",
        to=[recipient],
    )
    logger.info(
        "Report-ready email sent via Brevo",
        extra={
            "recipient": recruiter_email,
            "assessment_title": assessment_title,
            "candidate_name": candidate_name,
            "brevo_response": str(result),
        },
    )
