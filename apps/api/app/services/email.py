"""Transactional email via Resend (Vercel Marketplace integration --
provisioned against the real nanoneuron.ai sending domain, not a
placeholder). Kept as small, purpose-specific functions rather than a
generic "send_email" abstraction since each caller has exactly one real
template and no shared logic worth factoring out yet.
"""

import hashlib
import logging

import resend

from ..settings import Settings

logger = logging.getLogger("postmortem_ai")


class EmailNotConfiguredError(RuntimeError):
    """Raised when RESEND_API_KEY/RESEND_EMAIL_DOMAIN aren't set -- callers
    turn this into a 503, same "unconfigured means off" stance as Stripe's
    billing._client() and every other optional integration in this app."""


def send_password_reset_email(settings: Settings, to_email: str, reset_url: str) -> None:
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    # idempotency_key ties retries of the *same* logical request to one
    # send -- without it, a client-side retry after a slow/ambiguous
    # response could send the same link twice. Hashed (not the raw URL,
    # which embeds a JWT and can exceed Resend's 256-char key limit);
    # scoped to the URL itself since a new request always mints a new
    # token/URL, so this never suppresses a genuinely new reset request.
    url_fingerprint = hashlib.sha256(reset_url.encode()).hexdigest()
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "Reset your PostMortem AI password",
            "html": (
                "<p>Someone requested a password reset for this account. "
                f'If that was you, <a href="{reset_url}">click here to choose a new password</a> '
                "-- this link expires in 30 minutes and can only be used once.</p>"
                "<p>If you didn't request this, no action is needed -- your password hasn't changed.</p>"
            ),
        },
        {"idempotency_key": f"password-reset/{url_fingerprint}"},
    )
    logger.info("password_reset_email_sent")


def send_free_incident_nudge_email(settings: Settings, to_email: str, incident_title: str, user_id: str) -> None:
    """The one automated nudge this app sends toward a purchase decision --
    deliberately just a reminder that the account exists and what it drew
    on real evidence, with a plain link to pricing. Never a fabricated
    urgency claim ("only 2 spots left", a countdown, a discount that isn't
    real) -- this app's own core invariant against inventing anything not
    literally true extends to how it asks for money, not just what it
    drafts."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    pricing_url = f"{settings.frontend_url}/pricing"
    # Idempotency key is scoped to the user, not a per-send fingerprint --
    # this email is meant to go out at most once ever per account (enforced
    # by free_incident_reminder_sent_at at the call site), so any retry of
    # the same logical send should always collapse to the same Resend send,
    # never produce a second one.
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "Your free postmortem is ready -- here's what's next",
            "html": (
                f'<p>Your free postmortem for "<strong>{incident_title}</strong>" is drafted and grounded in the '
                "evidence you recorded. You can keep reading it and refining the evidence anytime.</p>"
                "<p>To publish it as a permanent, citable record, or to start a second incident, you'll need a "
                f'subscription -- see <a href="{pricing_url}">pricing</a> for the options.</p>'
                "<p>If you have questions before deciding, just reply to this email.</p>"
            ),
        },
        {"idempotency_key": f"free-incident-nudge/{user_id}"},
    )
    logger.info("free_incident_nudge_email_sent")
