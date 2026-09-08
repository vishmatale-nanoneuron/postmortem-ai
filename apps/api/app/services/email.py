"""Transactional email via Resend (Vercel Marketplace integration --
provisioned against the real nanoneuron.ai sending domain, not a
placeholder). Kept as small, purpose-specific functions rather than a
generic "send_email" abstraction since each caller has exactly one real
template and no shared logic worth factoring out yet.
"""

import hashlib
import logging

from urllib.parse import quote, urlencode

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


def build_upi_payment_link(upi_id: str, payee_name: str, amount_inr: int) -> str:
    """An NPCI UPI deep link (`upi://pay?...`), built by hand from the spec.

    Deliberately zero-dependency: this is a URI scheme, not an API, so there
    is no SDK, no vendor, no fee and no account involved -- the money still
    moves bank-to-bank exactly as before. It only removes typing.

    Why it matters: before this, a client received a bare UPI ID and had to
    copy it, then type the amount themselves. A hand-typed amount is the one
    input most likely to be wrong, and a wrong amount is precisely what stops
    a payment matching its claim in bank_alerts.py -- which surfaces to the
    customer as a rejected claim after they have actually paid. Pre-filling
    payee and amount removes that failure mode at the source.

    Every value is percent-encoded: a payee name with a space or an "&"
    would otherwise silently truncate the query string and produce a link
    that opens a UPI app with the wrong (or missing) payee.
    """
    params = urlencode(
        {"pa": upi_id, "pn": payee_name, "am": str(amount_inr), "cu": "INR"},
        quote_via=quote,
    )
    return f"upi://pay?{params}"


def send_upi_payment_details_email(
    settings: Settings, to_email: str, request_id: str, upi_id: str, payee_name: str, amount_inr: int
) -> None:
    """Self-serve replacement for a client having to email the founder to
    receive the real UPI ID (see billing.py's POST /upi/email-details). The
    account details stay founder-only via GET /upi/info -- never returned
    from an API response a scraper or throwaway account could read -- but a
    genuine, already-authenticated client can now reach them without a
    manual round-trip. request_id is a fresh per-request nonce from the
    caller, not derived from the (static) account details themselves, so a
    deliberate second send after the rate-limit window still goes out --
    only a client-side retry of the exact same request collapses to one
    Resend send, same idempotency reasoning as send_password_reset_email."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    payment_link = build_upi_payment_link(upi_id, payee_name, amount_inr)

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "Your PostMortem AI UPI payment details",
            "html": (
                f"<p>Pay <strong>₹{amount_inr}/month</strong> via UPI.</p>"
                f'<p><a href="{payment_link}" style="display:inline-block;background:#1a1a1a;color:#f7f7f5;'
                f'padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600">'
                f"Pay ₹{amount_inr} with any UPI app</a></p>"
                "<p style=\"font-size:13px;color:#555\">Opens your UPI app with the payee and amount already "
                "filled in. Tap it on the phone your UPI app is installed on.</p>"
                f"<p style=\"font-size:13px;color:#555\">Prefer to enter it manually? UPI ID: <code>{upi_id}</code>"
                f"<br>Payee name: {payee_name} &middot; Amount: ₹{amount_inr}</p>"
                "<p>Once you've paid, go back to the UPI tab in your dashboard and submit the transaction "
                "reference / UTR number from your payment app -- your account is activated once that's reviewed.</p>"
            ),
        },
        {"idempotency_key": f"upi-details/{request_id}"},
    )
    logger.info("upi_payment_details_email_sent")


def send_wire_payment_details_email(
    settings: Settings,
    to_email: str,
    request_id: str,
    currency: str,
    amount: int,
    account_name: str,
    account_number: str,
    bank_name: str,
    swift_code: str,
    correspondent_bank: str,
    correspondent_swift: str,
    nostro_account: str,
    routing_reference: str,
) -> None:
    """Wire-transfer equivalent of send_upi_payment_details_email above --
    same reasoning, same idempotency shape."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": f"Your PostMortem AI wire payment details ({currency})",
            "html": (
                f"<p>Pay <strong>{currency} {amount}/month</strong> via SWIFT wire to:</p>"
                f"<p>Account name: {account_name}<br>Account number: <code>{account_number}</code><br>"
                f"Bank: {bank_name}<br>SWIFT/BIC: <code>{swift_code}</code></p>"
                f"<p>Correspondent bank: {correspondent_bank}<br>Correspondent SWIFT: "
                f"<code>{correspondent_swift}</code><br>Intermediary/nostro account: "
                f"<code>{nostro_account}</code><br>Routing reference (ABA/IBAN): <code>{routing_reference}</code></p>"
                # The single most important instruction in this email, and it
                # was missing entirely. Correspondent banks deduct their fees
                # from the transfer itself under SHA/BEN charge codes, so a
                # customer who sends the exact price has *less* than the price
                # arrive. bank_alerts.py matches on an exact amount
                # (amount != claim.amount_inr -> no auto-verification), which
                # means a short-landing wire silently fails to verify and has
                # to be reconciled by hand, every time. "OUR" makes the sender
                # bear those fees so the full amount lands and matching works.
                f'<p style="background:#fff8e1;border-left:3px solid #b8860b;padding:10px 14px">'
                f"<strong>Important:</strong> please send with charge code <code>OUR</code> "
                f"(sender pays all fees). Under <code>SHA</code> or <code>BEN</code>, intermediary "
                f"banks deduct their fees from the transfer, so less than {currency} {amount} arrives "
                "-- which delays activation while it's reconciled by hand.</p>"
                f"<p>Please also put your account email in the payment reference/message field, so the "
                "transfer can be matched to your account.</p>"
                "<p>Once you've sent it, go back to the Wire tab in your dashboard and submit the transaction "
                "reference from your MT103 -- your account is activated once that's reviewed.</p>"
            ),
        },
        {"idempotency_key": f"wire-details/{request_id}"},
    )
    logger.info("wire_payment_details_email_sent")


def send_founder_claim_notification(
    settings: Settings, claim_id: str, method: str, currency: str, amount: int, reference: str, payer_email: str
) -> None:
    """The gap this closes: before this existed, a real customer could pay
    real money, submit a claim (POST /v1/billing/upi/claim or /wire/claim),
    and it would land as a 'pending' row in payment_claims with nothing
    telling the founder it exists -- discoverable only by opening the
    founder dashboard and noticing the pending_payment_claims count went
    up. Best-effort and non-blocking by design: raised inside a try/except
    at the call site (see billing.py's _insert_claim) so a Resend outage
    never turns a real, valid payment claim into a failed submission for
    the customer -- the claim itself is the record of truth; this email is
    only a faster way to notice it, not a required step in creating it."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    dashboard_url = f"{settings.frontend_url}/founder"
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [settings.founder_email],
            "subject": f"New {method.upper()} payment claim -- {currency} {amount}",
            "html": (
                f"<p>A new payment claim was just submitted: <strong>{currency} {amount}</strong> via "
                f"<strong>{method.upper()}</strong>, from <strong>{payer_email}</strong>.</p>"
                f"<p>Reference: <code>{reference}</code></p>"
                f'<p><a href="{dashboard_url}">Review and approve or reject it in the founder dashboard</a>. '
                "Nothing is granted automatically -- this claim stays pending until you act on it.</p>"
            ),
        },
        # Idempotent per claim, not per send -- a retry of the same claim
        # submission (if the route were ever retried) should never produce
        # a second notification for one real claim.
        {"idempotency_key": f"claim-notification/{claim_id}"},
    )
    logger.info("founder_claim_notification_sent", extra={"claim_id": claim_id, "method": method})


def send_client_claim_confirmation(
    settings: Settings, claim_id: str, to_email: str, method: str, currency: str, amount: int, reference: str
) -> None:
    """The client-side counterpart to send_founder_claim_notification above
    -- before this existed, submitting a claim only ever produced an inline
    UI message (see workspace.tsx's UpiPayment/WirePayment 'Submitted...'
    text); a client who closed the tab had no record anywhere that their
    claim was received, what reference they submitted, or what happens
    next. Same best-effort, non-blocking call site as the founder
    notification (see billing.py's _insert_claim) and the same per-claim
    idempotency reasoning -- the payment_claims row is the real record
    either way; this is only ever a courtesy copy of it."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "We've received your payment claim",
            "html": (
                f"<p>Your <strong>{method.upper()}</strong> payment claim for <strong>{currency} {amount}</strong> "
                f"has been received, with reference <code>{reference}</code>.</p>"
                "<p>The founder reviews every claim by hand before activating an account -- there's no automatic "
                "approval. You'll be able to see the outcome in your dashboard, typically within a day.</p>"
                "<p>If the reference above has a typo, you can correct it or withdraw the claim from the "
                "payment tab in your dashboard as long as it's still pending.</p>"
            ),
        },
        {"idempotency_key": f"claim-confirmation/{claim_id}"},
    )
    logger.info("client_claim_confirmation_sent", extra={"claim_id": claim_id, "method": method})


def send_client_claim_approved_email(settings: Settings, claim_id: str, to_email: str, method: str) -> None:
    """The missing end of the manual-payment conversation. A client could
    submit a claim and receive send_client_claim_confirmation above -- which
    literally tells them "you'll be able to see the outcome in your
    dashboard" -- and then never hear anything again. On a rail where
    approval is manual and asynchronous (the founder reviews by hand,
    possibly hours later, see founder.py's approve_payment_claim), that left
    a paying customer with no way to learn their access had turned on except
    repeatedly logging in to check.

    Deliberately says nothing about amounts or references: this fires after
    the subscription is already active, so the useful content is "it's on,
    here's what to do next," not a restatement of the receipt they already
    got."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "Your payment is approved -- your account is active",
            "html": (
                f"<p>Your <strong>{method.upper()}</strong> payment has been reviewed and approved. "
                "Your subscription is active now -- nothing else to do.</p>"
                "<p>You can record an incident, add evidence, and generate a grounded postmortem draft "
                "straight away. Every claim in a draft cites a real evidence entry you recorded; anything "
                "the evidence doesn't support is marked unsupported rather than invented, and publishing "
                "always records you as the named approver.</p>"
                "<p>If anything looks wrong with your account, reply to this email.</p>"
            ),
        },
        {"idempotency_key": f"claim-approved/{claim_id}"},
    )
    logger.info("client_claim_approved_sent", extra={"claim_id": claim_id, "method": method})


def send_client_claim_rejected_email(settings: Settings, claim_id: str, to_email: str, method: str) -> None:
    """Counterpart to send_client_claim_approved_email above, for the other
    outcome. Worse to omit than the approval, not better: a client whose
    claim is rejected has usually either paid and had the reference fail to
    match, or mistyped it -- both cases where silence reads as "my money
    vanished."

    Deliberately non-accusatory and gives a real next step. It never asserts
    the customer didn't pay -- the founder rejects a claim when it can't be
    matched, which is not the same thing."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "We couldn't match your payment claim",
            "html": (
                f"<p>Your <strong>{method.upper()}</strong> payment claim was reviewed but couldn't be "
                "matched to a payment we've received, so it hasn't activated an account.</p>"
                "<p>This is usually a mistyped transaction reference, or a transfer still in flight -- "
                "international wires in particular can take a few working days to land.</p>"
                "<p><strong>If you have paid:</strong> reply to this email with the transaction reference "
                "and the date, and it'll be sorted out by hand. You have not lost your payment.</p>"
                "<p>You can also submit a fresh claim from the payment tab in your dashboard.</p>"
            ),
        },
        {"idempotency_key": f"claim-rejected/{claim_id}"},
    )
    logger.info("client_claim_rejected_sent", extra={"claim_id": claim_id, "method": method})
