"""Utility helpers for candidate invitation email generation and delivery."""

import logging

from brevo import AsyncBrevo
from brevo.transactional_emails import (
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
)

from src.config.settings import settings

logger = logging.getLogger(__name__)


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
  <title>Interview Invitation</title>
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
                    <a href="{invitation_link}" target="_blank"
                       style="display:inline-block;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:16px 48px;border-radius:50px;box-shadow:0 4px 16px rgba(79,70,229,0.4);letter-spacing:0.3px;">
                      Start Your Interview →
                    </a>
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


async def _send_invitation_email(
    candidate_name: str,
    recipient_email: str,
    assessment_title: str,
    role_name: str,
    invitation_link: str,
    interview_duration_mins: int,
) -> None:
    """Send an invitation email via Brevo."""
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
            candidate_name=candidate_name,
            assessment_title=assessment_title,
            role_name=role_name,
            invitation_link=invitation_link,
            interview_duration_mins=interview_duration_mins,
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
